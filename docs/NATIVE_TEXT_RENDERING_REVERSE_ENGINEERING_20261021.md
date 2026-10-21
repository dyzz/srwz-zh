# 原生文本渲染与控制逻辑：持续反编译记录

> 当前维护总览见[标签、控制符与排版交接](TEXT_CONTROL_AND_LAYOUT_HANDOFF_20261021.md)。本文按阶段保留历史发现；开头的“本阶段”及覆盖表指第一阶段，最新字号和三版证据见第二十二阶段。完整反编译目标仍未完成。

目标：完整反编译和理解原游戏的文本渲染及控制逻辑，包含三版对应关系、调用者、字形解析、控制符、测宽／换行、绘制和状态生命周期。本文件不是完成声明；下表中的未完成项仍属于目标范围。

2026-10-21。本阶段只读原盘可执行文件，以锁定 SHA-256 校验身份；未改生产补丁、语料或 ISO。运行证据为隔离的整数指令路径对照；未启动图形模拟器。

## 第一阶段覆盖与剩余工作（历史快照）

| 范围 | 当前证据 | 状态／仍需完成 |
| --- | --- | --- |
| 字体显式／分类状态及 setter | 已有尺寸调查；本阶段 C 结构的关键偏移静态断言 | 补全其他属性、缓冲区和所有 setter |
| 原生测宽 `139B00` | 重建 C 模型、三版原生指令对照 | 已还原主算法；负值／溢出、损坏串与所有分类边界仍需扩大检查 |
| 绘制分类选择 `13A630..13A79C` | C 模型；每版 32 个开关组合 × 35 个边界／邻点 | 已完成分类核心边界矩阵；与各实际 descriptor 的使用绑定仍需继续 |
| 控制分派 `13A390..13A5E8` | 三版跳表、完整解析 C 模型、300 组全状态／记录对照 | 参数到记录的效果已还原；替换缓冲区来源及上游格式化仍未完成 |
| 字符代码到 glyph `13A7A0..13A990` | C 模型与每版全部 65,536 个码值原生执行逐项一致 | 此函数的整数映射已还原；实际字体读取、上传和异常索引后果仍需继续 |
| 字形列表记录与缓存分配 `13A990..13AC88` | 完整 C 解析／分配模型；300 组全状态、整记录区、上传列表对照 | 整数记录构造及容量边界已还原；后续上传处理与跨帧生命周期待完成 |
| 绘制包 `13ACA0..13BD60` | C 模型；270 组完整输出缓冲区逐字节对照；303 组与解析器连通的立即绘制对照 | 包生成整数逻辑已还原；GS 执行仍不属于该指令测试 |
| 后续数字／符号 helper `13BD60..13C5C0` | 字段用途、调用与汇编 | 尚需逐函数模型及执行对照 |
| 字体资源初始化 `139F00..13A290` | 重建 C 模型、三版 native 初始化对照；文件／分配／GS 服务使用明确替代契约 | 字体模块内部数据／状态路径已还原；外部服务及其失败传播不能由这些替代调用证明 |
| 字形拷贝 `13C5C0` | 147 组整 atlas 对照；真实原盘字体解压 102 组；重置函数 468 组 | CPU 内存路径已还原；DMA／GS 执行时序仍待核对 |
| 上层调用、格式化与替换、测宽结果用途 | SHF_EXECINSTR 段的直接 JAL 引用清单 | Original / Best 各 125 个测宽调用，SP 185 个；需逐一归属调用者、检查间接调用和预处理 |
| 图鉴／剧情换行与 descriptor 包装 | 既有图鉴调用绑定、尺寸调查 | 完整拆行语义、换页／滚动和其他文本显示面仍需追踪 |
| 三版语义对应 | 原盘身份校验、独立签名、跳表、执行对照 | 不能以统一地址偏移代替逐函数对应；尚未完成全部路径的语义差异审计 |
| LRPS2 验证 | 两个人物修复截图；新增三版原盘冷启动字体及保留 atlas 读回 | 冷启动资源状态已核对；测宽、异常退出等具体调用场景影响验证仍未完成 |

## 本阶段确认的三版入口

| 版本 | 状态基址 F | 初始化入口 | 测宽入口 | 绘制入口 | 控制跳表 |
| --- | --- | --- | --- | --- | --- |
| Original | 0x46E330 | 0x139930 | 0x139B00 | 0x13A290 | 0x433E50 |
| Best | 0x46EB30 | 0x139930 | 0x139B00 | 0x13A290 | 见 inventory.json |
| SP | 0x4ED5B0 | 0x13A3A0 | 0x13A5A0 | 0x13AD30 | 见 inventory.json |

SP 初始化相对 Original 为 +0xA70，但测宽／绘制相对为 +0xAA0。差异已经通过独立入口签名和执行校验发现并处理；不能把某一区段的偏移应用到整个字体模块。

关键状态偏移：`F+14/16` 显式字宽／字高，`F+18/1A` 显式横／纵推进，`F+38..3E` 分类 A，`F+40..46` 分类 B，`F+48` 分类开关，`F+4B..4F` 五个分类允许标志。尺寸均按带符号 halfword 读取；控制参数按无符号 byte 读取。

## 测宽与绘制不是同一个解析器

原生测宽只识别 `31 xx`（跳过）、`32 xx`（字宽）、`34 xx`（横向推进）。width/space 同时清零分类开关，修改共享状态且函数退出不恢复。其他非零首字节按双字节字符处理；不能为它擅自补上 height、换行或字符串替换语义。返回值的第二参数非零时为累计推进，为零时为负的半宽（向零取整），这与居中用途相符，但具体调用目的还需逐调用者确认。

下表为三版一致的实际执行结果。测试状态 A 推进 21、B 推进 12，显式推进 21；这组受控参数用于暴露分支，不代表所有原生页面都使用不同 A/B 尺寸。

| 输入 | 原生测宽 | 绘制游标／记录 | 结论 |
| --- | --- | --- | --- |
| `889F 889F` | 42 | x=42，2 字形 | 基准 |
| `33 0E 889F 889F` | 63 | x=42，2 字形 | height 被测宽当成一个额外字符 |
| `35 0F 889F 889F` | 63 | x=42，2 字形 | 纵向推进控制也不被测宽识别 |
| `889F 0A 889F` | 63 | x=21、y=14，2 字形 | 测宽没有换行语义，并可能使后续双字节读取错位 |
| 紧缩 G + 字高控制 + 中文恢复 | 66 | x=33，2 字形 | 安全的 height 参数仍不等于测宽兼容 |
| 大写开关关、broad 开关开，字符 `8260` | 21 | x=12，1 字形 | 两个分类器在重叠范围内的优先级不同 |

前一阶段生成的正文 height 闭合段属于表中的兼容性风险：目标人物 LRPS2 截图已经通过，但这不能证明其他依赖原生测宽的居中、截断、滚动或容量判断正确。**必须继续归属调用者、验证影响后再决定补丁方案。** 本阶段没有默默修改已经构建的 ISO 来掩盖此差异。

分类测宽按大写→小写→平假名→片假名→broad 的互斥区间判断；命中具体区间但该标志关闭后，直接选 A，不再尝试 broad。绘制则先检查 broad 的 `[8140,829F)`，再检查片假名、大写、平假名、小写。因此禁止将二者抽象为同一个分类 predicate。

## 绘制器控制分派

Original 地址；其他版本的实际目标见跳表 JSON。首字节实际 NUL 会转换为内部 `2F`，LF (`0A`) 转换为内部 `2E`。下表同时包括内部及原始字节分派，不能将裸 ASCII 标点与可显示文本混用。

| 字节 | 入口 | 已确认的直接动作 |
| --- | --- | --- |
| 2E / LF | 13A420 | 将临时 x 设为显式初始 x，临时 y 增加临时纵向推进 |
| 2F / NUL | 13A3E8 | 若正在替换串则恢复原串指针，否则置结束标志 |
| 30 | 13A450 | 调用字体初始化，并额外消费一个字节；不会重新同步全部临时 scratch 尺寸；已在 reset-after-compact 用例检查 |
| 31 | 13A460 | 参数写入 `F+1C`，进入主字形记录的 TEX0 高字节选择字段 |
| 32 | 13A470 | 字宽写入 `F+14` 和 scratch `+34`，分类清零 |
| 33 | 13A490 | 字高写入 `F+16` 和 scratch `+36`，分类清零 |
| 34 | 13A4B0 | 横推进写入 `F+18` 和 scratch `+38`，分类清零 |
| 35 | 13A4D0 | 纵推进写入 `F+1A` 和 scratch `+3A`，分类清零 |
| 36 | 13A4F0 | 参数写入 `F+32`，供数字／符号记录的 TEX0 高字节选择字段使用 |
| 37 | 13A500 | 参数写入 `F+2C`，供数字记录字宽使用 |
| 38 | 13A510 | 参数写入 `F+2E`，供数字／符号记录字高使用 |
| 39 | 13A520 | 参数写入 `F+30`，供数字记录横向推进／右对齐使用 |
| 3A | 13A530 | 保存原串指针，进入 `558573` 的替换缓冲区 |
| 3B | 13A560 | 同上，缓冲区 `55857E` |
| 3C | 13A590 | 同上，缓冲区 `55858F` |
| 3D | 13A5C0 | 同上，缓冲区 `5585B6` |

替换缓冲区的角色、格式化层的 `%...`、`$n/$F`、图标与参数标记不能仅凭现有工具的标签名称认定与原生某个字节一一对应，仍需读入这些缓冲区的写入者及上游预处理。

## 正常返回与提前退出必须分开

正常退出到 `13AC58` 恢复入口分类开关。缓存分配路径在临时 atlas y≥480 时，会从 `13AA60` 直接到 `13AC68`，绕过分类恢复。受控执行中，入口分类=1，height 控制后为 0；正常终止后恢复 1，但 atlas 耗尽退出后仍为 0。这个发现限定的是该提前退出分支，不代表所有退出路径或实际页面已触发它。

## 证据与复跑

- [三版区域、跳表、分支及直接调用清单](issue-assets/native-text-rendering-20261021/inventory.json)
- [Original 汇编](issue-assets/native-text-rendering-20261021/original.asm)、[Best 汇编](issue-assets/native-text-rendering-20261021/best.asm)、[SP 汇编](issue-assets/native-text-rendering-20261021/sp.asm)
- [直接 JAL 调用位置](issue-assets/native-text-rendering-20261021/callers.json)，只计可执行 section，不含间接调用；调用者语义仍待归属。
- [测宽／绘制分类 C 模型](issue-assets/native-text-rendering-20261021/core_model.c)，只覆盖文件明确声明的语义，不冒充完整渲染器。
- [30 组原生路径与 C 模型对照](issue-assets/native-text-rendering-20261021/execution.json)、[运行日志](issue-assets/native-text-rendering-20261021/execution.log)

```sh
python3 docs/issue-assets/native-text-rendering-20261021/inventory.py --dependency-path /tmp/srwz-font-audit-deps
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/execute.py
clang -std=c11 -Wall -Wextra -Werror -fsyntax-only docs/issue-assets/native-text-rendering-20261021/core_model.c
```

inventory 依赖当前本地 Capstone 目录（具体版本记在 JSON 中）和之前从原盘提取的 `work/analysis/library-font-fix-20261021/{original,best,sp}.elf`；每次读取都校验仓库原盘 ELF 身份锁。原始二进制不随报告提交。

本次修正通用 MIPS 反汇编将 EE 的 LQ/SQ 错读成 DSP/MSA 指令的问题，并补出带 rd 的 EE MULT。零未识别指令只是这些区域的助记符覆盖，不代表已经完成语义反编译。

Unicorn 不直接执行所需 EE LQ/SQ，执行脚本将覆盖函数中的这些字替为 NOP，由 hook 维护完整 128 位载入／存储（高 64 位单独保存），保留分支延迟槽行为。解析核心只使用低 64 位整数；包生成器需要完整 128 位模板／描边复制。此适配不覆盖 EE 的其他 packed 运算，不是 LRPS2 或真实像素绘制证明，也与早前只执行受支持指令片段的测试属于不同证据范围。

## 图鉴路径的进一步归属

[三版图鉴包装函数审计](issue-assets/native-text-rendering-20261021/library-path.json) 从各自原盘验证了物理行调用链。Original：`221130` 拆行 → `221220` 调用 `220DB0` → `220E3C` 调用 `225290` → `2253A8 / 2253C4` 调用 `13A290`。Best 与 SP 分别使用它们实际的调用地址。

上述已列包装函数范围内没有直接调用 `139B00` 测宽，这与当前目标页面的 height 闭合段仍能正常显示相符。这个有限的调用链结果不能扩展为“图鉴系统没有任何测宽”，也不能替代全部下游、上游及间接调用检查。新增测宽差异的优先排查对象是 callers.json 中真实调用测宽的显示路径。

三版逐指令包装函数清单：`original-library.asm`、`best-library.asm`、`sp-library.asm`。复跑：`python3 docs/issue-assets/native-text-rendering-20261021/library_path.py`。

## 第二阶段：完整整数路径与绘制包模型

新增的 [parse_model.c](issue-assets/native-text-rendering-20261021/parse_model.c) 还原 `13A290` 的队列式解析、控制分派、替换、字形索引、atlas 分配和记录构造；[packet_model.c](issue-assets/native-text-rendering-20261021/packet_model.c) 还原 `13ACA0` 的两个记录队列到绘制包的转换。[core_model.c](issue-assets/native-text-rendering-20261021/core_model.c) 已补齐字形解析。它们是重建模型，不是原开发者源码。

### 字形解析的穷举结果

三版均逐项比较全部 65,536 个 16 位输入，合计 196,608 次：结果完全一致，输出序列 SHA-256 为 `c765c85a18bf230c4f5c89041e6f5c79850b0c94b1d73fc0403236a944c17ba1`。三版扩展表均为 229 个原始记录，内容相同；不能将“原始表记录数”与已知文本表实际引用的扩展字符数混为一谈。

标准分支不校验尾字节是否 ≥0x40，也不对最终索引作字库边界检查；低位 halfword 存储会截断运算结果。扩展表命中后索引是 `signed_row*224+packed_position`，缺失项返回 glyph 0。本次全域输入中每版有 33,119 个结果越过 4,480 字槽范围；其中包含大量不合法文本码。这证明工具层的合法槽检查是附加安全约束，不能误称原程序已有此检查。该原生分支不是通用单字节 ASCII 解析器。

分类矩阵另检查每版 32 个开关组合 × 35 个区间边界／邻点，共 3,360 次，渲染宽高和横纵推进均与模型一致。

### 分配、记录及立即绘制

- atlas 按固定 24×24 源格分配。x 增加 24，达到 504 后回到 0、y 增加 24；y≥480 提前退出。21 列 × 20 行可分配 420 个源格。
- y<240 的记录用页选择 0x24；y≥240 的记录将源 y 减去 240，用页选择 0x2C。图形包再把页选择放进对应纹理状态字段。
- 普通流程对每次出现的动态字形都追加一次待上传索引；不能仅因称为缓存，就假定这里会自动查重。
- 数字 `824F..8258` 和全角空格 `8140` 在 `F+88==0` 时使用已有 UV，不消耗动态 atlas；`F+88!=0` 时强制走动态分配。SP 待上传计数的 GP 相对位置独立读取原指令，不使用 Original 的偏移。
- 主记录计数增加到 0x13F 时会退回 0x13E 并回退记录指针。因此连续超量文本会反复覆盖最后一个槽；计数、游标推进和上传请求并非同步截断。425 字的受控例中，记录计数为 318，已追加 420 个上传索引，随后 atlas 耗尽退出。
- `a1==0` 时积累记录。`a1!=0` 时只对本次新建的主记录调用包生成器，暂时屏蔽数字队列，再恢复入口主／次记录计数与队列指针；游标、尺寸和待上传列表的变化保留。正常立即绘制不是简单“把新增记录永久追加到全局队列”。
- atlas 耗尽的提前退出绕过包生成和正常分类恢复，直接返回原输入包指针。即使本次已生成部分记录，也不能假定它们已经通过立即绘制输出。

300 组队列解析对照检查完整状态区、整个记录缓冲区、上传索引列表和指针，包括确定种子的混合控制串。另有 303 组从原生主渲染函数入口一直执行到返回的立即绘制对照，将解析 C 模型和包 C 模型组合后，检查状态、队列回退、上传列表、返回指针与完整包缓冲区。

### 两种记录格式与实际字段

| 状态／记录字段 | 已还原用途 |
| --- | --- |
| `F+20` / 主记录 +08 | 写入 XYZ 的 Z 深度字；不是 RGBA |
| `F+24` / 记录 +14 | 正文字形 RGBA 字 |
| `F+28` / 记录 +18 | 描边 RGBA 字 |
| `F+1C` / 主记录 +10 | TEX0 高字节选择值（由 `31 xx` 设置） |
| `F+4A` / 主记录 +12 | 非零时用四顶点路径，数值对顶边施加水平偏移 |
| `F+50` / 记录 +1C | 非零时生成八邻域描边副本 |
| 次记录 +0C/+0D | byte 宽／高；主记录的宽／高则为 +0C/+0E 的 signed halfword |
| 次记录 +0E/+0F/+10 | TEX0 高字节选择、页选择、顶边水平偏移 |

这使控制符 `36..39` 的数据流明确：它们修改数字／符号绘制使用的另一组参数，不应自动当作普通正文的第二套 width/height/space。

### 绘制包结构

`13ACA0` 对主、次记录使用同一套几何构造，但字段宽度与偏移不同。无顶边偏移时每字形使用 80 字节的双顶点包；非零偏移时使用 112 字节四顶点包。源 UV 从 `(u+1,v+1)` 到 `(u+24,v+24)`，目标尺寸来自各记录的宽／高。

描边使用副本颜色，在中心包前复制八份；X 偏移为 -16/0/+16，Y 偏移为 -8/0/+8（均为包内坐标低字段单位），排除中心点。最后按原模板填充到严格的下一处 64 字节边界，再返回带 0x30000000 别名位的指针。空队列直接返回原指针、不写包。270 组独立包对照检查全部已写及未写缓冲区字节，包括两种格式、倾斜、描边、chain 参数、输入别名和对齐。

以上是包字节及整数几何的还原，未执行 GS，不能把包模型通过称为像素验证。

### 替换和 reset 的细节

替换控制保存的是单个返回指针，并非调用栈；替换串的第一个字节直接进入双字节字形路径，绕过普通控制分派。空替换串也可能先生成一个 code 0000 的记录再返回原串，不能按高级语言的空字符串替换语义简化。其余上游是否保证缓冲区非空、如何写入姓名等，仍需确认。

`30 xx` 会调用原生字体 reset 并消费参数字节；它重置共享状态，但不重建全部临时 scratch。reset 之前的显式临时字宽／字高与 reset 后从共享状态重载的推进可能同时参与后续字形。模型保留该行为，未替原程序“修正”成统一重置。

### 新增证据与复跑

- [全域 glyph／分类矩阵](issue-assets/native-text-rendering-20261021/resolver-execution.json)
- [完整队列解析](issue-assets/native-text-rendering-20261021/parse-execution.json)
- [独立绘制包](issue-assets/native-text-rendering-20261021/packet-execution.json)
- [完整立即绘制调用](issue-assets/native-text-rendering-20261021/immediate-execution.json)

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_resolver.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_parse.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_packets.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_immediate.py
```

完整目标仍未完成：资源加载／上传／跨帧重置、其余数字／符号 helper、上游格式化与替换缓冲区来源、所有调用者和故事／图鉴分页控制，以及实际调用场景的 LRPS2 影响检查均继续保留。

最终复跑的四组检查均通过。三版同名用例的整记录缓冲区、独立包缓冲区及完整立即绘制输出亦逐组一致；见 [带模型与报告哈希的总验证收据](issue-assets/native-text-rendering-20261021/verification-receipt.json)。该收据明确保留完整目标未完成的状态。

## 第三阶段：资源初始化、字形拷贝和批次生命周期

### 实际资源与解压器

资源初始化入口不假设三版资源编号相同：Original / Best 的主字体取 VT1 `[2,3)`，辅助数字纹理取 `[7,8)`；SP 分别取 `[3,4)`、`[8,9)`。这些编号从各版原生初始化所读 halfword 表获取，而非从另一版平移。

[font_decode_model.c](issue-assets/native-text-rendering-20261021/font_decode_model.c) 还原原生解压包装器及 LZ 主体。三版共 102 组执行对照，包含原盘实际主字体、辅助纹理、固定字面量／回溯流及明确的异常流；有效输出同时与现有工具解码器比较。主字体解码后为 0x13B000 字节；辅助资源为 32,832 字节（前 64 字节调色数据，后 32,768 字节纹理数据）。

不能将原生解码器当作严格校验器：非法回溯的测试中，内部返回错误 1、实际只写 1 字节，但外层仍返回声明长度 5；另一测试声明长度 1，字面量块实际写入 2 字节，外层仍返回 1。严格工具拒绝这些输入是额外约束，不能改成复现原程序的容错缺陷。空输出包装器也会在读取声明长度后直接返回，而不是继续读取其余头部。

### 初始化的外部契约与内部执行

[resource_model.c](issue-assets/native-text-rendering-20261021/resource_model.c) 重建字体模块的初始化数据／状态效果。[三版初始化对照](issue-assets/native-text-rendering-20261021/resource-init-execution.json) 执行各自原生初始化、实际解压、文字解析和 scatter；文件读取、分配、GS descriptor／上传、同步叶函数则由记录参数的替代服务提供。**这不是实际文件 I/O、分配器错误处理或 GS 上传执行的证明。**

核对的分配尺寸依次是：主记录 0x2800、次记录 0x2000、暂存 atlas 0x1E000、主字库 0x13B000。临时辅助资源分配为 65,536 字节。三次外部上传源契约为：

| 源数据 | TBP | TBW | 格式值 | 尺寸 | 源字节数 |
| --- | --- | --- | --- | --- | --- |
| 辅助资源首部 | 0x2CA9 | 1 | 0x02 | 16×2 | 64 |
| 辅助资源 +0x40 | 0x2CAA | 4 | 0x14 | 256×256 | 32,768 |
| 原生内嵌调色表 | 0x2680 | 1 | 0x00 | 16×16 | 1,024 |

字体解析器强制动态模式 `F+88=1`，处理原生种子串后执行 scatter，再清零强制模式。种子串共 42 字形：全角空格、10 个数字、26 个大写字母及 5 个符号。它恰占 21 列的两行，初始化末端 `(x,y)=(0,48)` 保存到 `F+0C/0E`。初始化末端仍有 42 个待上传索引，scatter 不负责清空这个计数。

### 420 总格数与 378 动态格数

前文从空 atlas 验证的 420 格是**总容量**。原生初始化后保留前两行，因此从正常保留区末端开始只有 378 个动态格。须区分空 atlas 的受控测试与正常游戏初始化后的容量，不能直接把 420 当作正常动态正文预算。

[upload_model.c](issue-assets/native-text-rendering-20261021/upload_model.c) 还原 CPU scatter：每个索引对应 `glyph*288`；每字形 24 行，每行复制 12 字节，到 `atlas + y*256 + (x>>1)`，目标行距 256 字节。横向推进 24，达到 504 后换行。它从 `F+0C/0E` 开始，不修改全局位置、记录计数、待上传计数或写指针。三版共 147 组整 atlas 比较，包含跨行、分页、满动态区、空请求和末格；状态与计数不变亦逐项核对。

### 重置函数不能混为一谈

[lifecycle 对照](issue-assets/native-text-rendering-20261021/lifecycle-execution.json) 共 468 组，覆盖三版三类函数和参数低位边界：

- `13A260`：仅把保留区标记 `F+0C/0E` 复制到当前 atlas `F+08/0A`。
- `13C390`：参数低 8 位非零时才清两个记录计数，恢复 atlas 保留区起点，清待上传计数，并将索引写指针恢复到原生静态数组。参数 256 是 no-op，257 则执行重置。
- `13C3E0`：重置字体参数，再以参数 0 调用上一函数；因此它本身不会清记录／请求队列，也不会恢复 atlas 位置。

这些重置函数可用于批次或帧边界；是否每帧调用、先后顺序及多层 UI 场景必须由调用者证明，不能由函数命名推定。

### 三版独立地址

| 入口 | Original / Best | SP |
| --- | --- | --- |
| 资源初始化 | 0x139F60 | 0x13AA00 |
| atlas 标记恢复 | 0x13A260 | 0x13AD00 |
| 有条件批次重置 | 0x13C390 | 0x13CE40 |
| 字体参数 reset 包装 | 0x13C3E0 | 0x13CE90 |
| CPU scatter | 0x13C5C0 | 0x13D070 |

SP 的 scatter 相对偏移是 +0xAB0，与前面渲染器的 +0xAA0 又不同；由独立指令签名定位后，三版均执行验证。原生解压入口分别是 Original 0x1C6C40、Best 0x1C7000、SP 0x1CA120。

### 上传请求与 CPU 拷贝是不同阶段

[三版上传请求清单与汇编](issue-assets/native-text-rendering-20261021/transfer-inventory.json) 在每版找到了两处 `F+70` dirty 标志控制的 atlas 上传块。它们清 dirty 标志，安排两个 512×240 半区，BITBLTBUF 的 DBP=0x1180、DBW=8，格式分别为 0x24 与 0x2C，第二块源地址为第一块 +0xF000，每块 0xF00 个 quadword（61,440 字节）。

Original 的请求构造函数为 `136330`，其辅助 `136090` 生成链引用。构造函数把源地址写入 REF 类型项，不在此处逐像素复制 atlas。主路径的请求构造块从 `1431C4` 开始，而 CPU scatter 调用在 `143440`；因此不能把“请求已经构造”直接当作“数据已经被 GS 读走”。实际 DMA 提交及缓存同步的完整时序仍需继续审计。这一段目前是原生静态证据，不冒充已做逐字节模型对照或 GS 运行验证。

### LRPS2 原盘读回

新增 [三版原盘 LRPS2 资源读回](issue-assets/native-text-rendering-20261021/lrps2-resource-verification.json)：各版原盘独立冷启动到标题界面，使用 Software (SW)、独立记忆卡目录。会话只发按键、截图和内存读取命令，没有发送 `poke` 或代码替换命令；原记忆卡前后哈希一致，会话已退出。

三版运行中主字体的 SHA-256 均为 `e68a24df2daaf16f472e55e0ba9b2282752bb70225aedc0bbb8aeef7713662bd`，与各自原生解码真实资源的结果一致。运行中保留区标记均为 `(0,48)`，前 48 行的 42 个种子字形及剩余填充字节与原盘字体按已验证 scatter 布局构造的结果逐字节一致。

此读回验证的是冷启动标题状态下的字库与保留区，不是所有调用者、所有帧、动态测宽问题或 DMA／GS 边界行为的全覆盖证明。原始内存转储保留在忽略的 work 目录，报告只保存哈希、命令收据与标题截图。

### 第三阶段复跑

```sh
python3 docs/issue-assets/native-text-rendering-20261021/resource_inventory.py
python3 docs/issue-assets/native-text-rendering-20261021/transfer_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_font_decode.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_upload.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_lifecycle.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_resource_init.py
```

新增指令、模型与运行证据分层保存。完整目标继续保留：实际 DMA 提交时序、剩余数字／符号与格式化、替换缓冲区写入者、测宽调用者和分页控制仍未完成。

## 第四阶段：数字、符号记录生成器

新增 [独立入口清单](issue-assets/native-text-rendering-20261021/numeric-inventory.json)、[C 重建](issue-assets/native-text-rendering-20261021/numeric_model.c) 及 [423 组原始指令对照](issue-assets/native-text-rendering-20261021/numeric-execution.json)。每版 141 组，比较整个 0x90 字节状态和 400 槽记录缓冲区，包含十进制位数边界、INT32 上下边界、右对齐、坐标有符号截断、属性低字节截断、记录计数边界、42 个原生种子符号和空串。指令执行仅对 EE LQ/SQ 和带目标寄存器的 MULT 作明确适配，不是 LRPS2 图形验证。

| 函数 | Original / Best | SP | 本阶段验证范围 |
| --- | --- | --- | --- |
| 数字记录生成 | 0x13BD60 | 0x13C800 | 队列模式的完整状态、记录 |
| 有符号数字包装 | 0x13C000 | 0x13CAA0 | 已定位、反汇编；执行对照待补 |
| 种子符号记录生成 | 0x13C190 | 0x13CC30 | 队列模式、合法种子键、返回值 |
| 记录组初始化 | 0x13C410 | 0x13CEC0 | 5 个组索引，含全部未写字段保持 |
| 设置坐标后调用正文解析器 | 0x13C5A0 | 0x13D050 | 已定位、反汇编；组合执行待补 |

### 与英数字高问题的直接关系

数字专用函数按 `F+2C` 字宽、`F+2E` 字高、`F+30` 横向推进生成 secondary 记录；字宽、字高、调色参数以低 8 位存入记录。它把调用者传入的 Y 原样按 16 位存入记录，不计算中文基线或字形笔画包围盒。右对齐起点是 `x - (字宽 + (位数-1)*推进)`，而结束位置保存的是最后一字之后的推进位置，二者不能混用。

符号函数使用调用参数 advance 同时作为记录字宽和横向推进，字高仍来自 `F+2E`；同样不自动调整 Y。它逐键扫描预置字形表，不处理正文控制符。这一专用路径不同于正文解析器遇到文本数字的路径；正文解析器及其 fast-digit UV 选择已由前面的 parser 对照覆盖，不能把修改 `F+2E` 当成修复所有正文数字的措施。

因此，可见高度与纵向对齐需要分开设计。专用数字函数的高度独立性不能推出所有 UI 都调用它，也不能据此把统一补偿补丁直接放进公共 GIF 输出器；实际调用者归属仍需追踪。

### 边界与版本差异

- 数字队列计数增加到 255 时退回 254，后续数字覆盖该末槽；符号队列没有对应钳制。本阶段以足够大的分析缓冲区验证计数 254 后继续生成，不将其直接定性为实际游戏越界。
- 负数直接传给底层数字函数仍只生成一个数字槽，UV 来自有符号商；正常负数应经有符号包装函数处理。底层接受 int32 并不表示它负责绘制负号。
- 符号函数队列模式：Original / Best 保留入口 V0，本阶段以 `0x13572468` 验证；SP 明确返回 0。这里只证明返回行为差异，调用者是否使用它尚未证明。
- 记录组初始化以 `index*66` 为起点，选择性初始化 66 个主记录槽，Y=-200、宽高=1、palette=128，其余字段保持原值。索引 4 在扩大的分析缓冲区中验证；不能由此推断游戏会把该索引传入默认 320 槽缓冲区。
- 未命中种子键时，原生符号函数没有模型中的安全上限。C 模型的容量与扫描失败返回值是分析保护，不能当作原生行为。

本阶段未完成：有符号包装的负号混合路径、数字／符号即时 GIF 输出的组合对照、符号未知键的调用者约束、全部直接和间接调用归属。复跑：

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/numeric_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_numeric.py
```

## 第五阶段：数字／符号即时输出与负号组合

[即时输出对照](issue-assets/native-text-rendering-20261021/numeric-immediate-execution.json) 新增三版共 **222 组**。实际执行原生数字／符号函数及其调用的 GIF 构造函数，以 C 记录生成器和 packet 模型组合结果为对照，比较返回指针、完整状态、完整 secondary 记录、旧 primary 记录不变，以及包含未写区域的 128 KiB packet 缓冲区。覆盖已有队列、数字计数 253／254、两类链标志、四种 16 字节对齐、地址别名、shear、outline、空符号串。即时路径临时屏蔽旧 primary 与 secondary 队列，只输出新增 secondary 区间，再恢复原计数和记录指针；数值格式参数和横向起止位置不回滚。计数钳制导致新增计数为零时，末槽可能已经被覆盖，但即时函数不因此把该槽输出成新记录。

[负号组合对照](issue-assets/native-text-rendering-20261021/signed-numeric-execution.json) 新增三版共 **264 组**。独立 [C 调度及坐标模型](issue-assets/native-text-rendering-20261021/signed_numeric_plan.c) 生成计划；分别执行完整原生 signed 包装函数，以及按该计划组合的真实原生下层函数，比较实际下层调用顺序、参数、返回值、字体状态、两类记录、完整 packet 缓冲区、上传索引／计数／指针。没有替换下层函数体；下层解析器、数字生成器和 packet 构造器另有前述 C 字节模型对照。本项是包装函数的组合证明，不冒充一份独立的全 C signed renderer。覆盖正负数、十进制位数边界、INT32_MIN、左右对齐、队列／即时、坐标回绕、atlas 已满、两种动态数字标志。

### signed 包装的真实分工

- 非负值直接调用数字生成器。
- 负值先把原生负号串交给“设置坐标并调用正文解析器”的 bridge，随后把 32 位取负结果交给专用数字生成器。
- 左对齐时负号位置为 `(x,y)`，数字起点为 `x + F+30`；它不会根据负号实际绘制宽度决定下一位置。
- 右对齐时负号位置为 `x - 位数*F+30 - F+44`，其中 `F+44` 是 B 类横向推进。数字自身仍以输入 x 为右边界进行其独立宽度计算。
- 负号那次正文调用的链参数固定为 0；数字那次才使用调用者的链参数。即时模式下数字接收负号绘制返回的 packet 指针。
- `INT32_MIN` 的取负仍为负值：包装函数用于负号布局的除十循环计出 10 位，而下层数字函数把负值当成单槽处理。因此这里不存在完整正确的 `-2147483648` 十进制格式化。测试证明了原生行为，未证明实际调用者会输入此值。

负号使用普通文字尺寸，数字使用 `F+2C/2E/30` 尺寸，两者的 Y 来自同一输入，却不自动统一字高或可见笔画位置。修改公共 packet 输出器会同时影响两种记录和所有调用者，不能仅凭“它们最终都进入 GIF”就认定这是安全补丁位置。仍需结合面板初始化和调用者实际用途决定补偿归属。

### 本阶段边界与复跑

这是原盘整数指令及模型证据，没有执行 GS 或 DMA，没有新增 LRPS2 图形验收。未知种子键、调用者输入范围、全部上游格式化／替换缓冲区写入、测宽消费与分页控制仍待完成。可复跑：

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_numeric_immediate.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_signed_numeric.py
```

## 第六阶段：上层调用清单与缓存符号分支

[三版静态引用清单](issue-assets/native-text-rendering-20261021/caller-inventory.json) 扫描 ELF executable sections 内的直接 J/JAL，保存每处前后指令，并另列字体状态的相邻 LUI/访问模式及原始函数地址字候选。该清单是候选索引：可执行区中可能嵌有数据；相邻地址模式不能代替完整数据流；未找到函数地址字不能证明不存在间接调用。

| 目标入口 | Original | Best | SP |
| --- | ---: | ---: | ---: |
| 主解析器（J 与 JAL 合计） | 7 | 7 | 7 |
| 设置坐标后转入主解析器 | 850 | 850 | 961 |
| 专用数字生成器 | 90 | 90 | 88 |
| signed 数字包装 | 7 | 7 | 5 |
| 种子符号生成器 | 2 | 2 | 2 |
| 测宽函数 | 125 | 125 | 185 |
| 新定位的缓存重复绘制包装 | 58 | 58 | 58 |

符号生成器的两处直接调用都位于同一个缓存初始化函数内：Original `3A9830`、Best `3AA000`、SP `3D4D00`。它们将 `815B 0000` 和 `817C 0000` 两串分别转为即时 packet，复制到两个缓存，初始化期间暂时关闭 shear／outline，末尾恢复。两处调用的输出指针均非零，不属于前面 SP 与 Original/Best 返回值有差异的队列调用。不能因此断言所有间接使用均已排除。

### 绕过主解析器的 `@N` 分支

[独立定位清单及汇编](issue-assets/native-text-rendering-20261021/cache-inventory.json) 确认三版有相同结构的包装函数：Original `3A99D0`、Best `3AA1A0`、SP `3D4EA0`。首字节不是 `@` 时调用普通文字 bridge；是 `@` 时调用十进制转换函数，将正向计数上限限制为 32767，然后直接拼接缓存符号包。

该路径输出 144 字节前缀，加 `max(count,0)*64` 字节重复单元。字体参数来自 B 类 `F+40` 字宽、`F+42` 字高、`F+44` 横向推进；palette 和 RGBA 来自主文字参数，Z 使用调用参数。它不调用普通文字测宽或逐字解析，不修改字体 pen，也不生成新字形上传请求。每次复制当前单元后才把缓存中的 X 更新到下一位置；即使 count<=0，也会修改缓存的 count、palette、RGBA、初始坐标和 Z。

新增 [repeat_model.c](issue-assets/native-text-rendering-20261021/repeat_model.c) 及 [60 组对照](issue-assets/native-text-rendering-20261021/repeat-execution.json)，覆盖负计数、0、8 次展开循环边界、32767／32768 和坐标回绕，比较全输出缓冲区、完整 208 字节缓存、字体状态不变及返回指针。每版 20 组。

**证据边界：本项明确截获十进制转换调用，提供声明的 int32 返回值。** 尝试执行原生转换器时进入 C 运行库的 EE MMI 算术（Original 首个未支持位置 `12B550`），当前适配器未覆盖。测试中即使保留 `@` 文本输入，也不证明该文本转换为指定整数的过程；它只证明收到该整数后的原生缓存几何输出。缓存 lazy 标志置为已完成，故本项也不证明初始化函数的完整执行。C 模型容量保护不是原生边界检查。

### 字高影响与仍待追踪项

这里存在另一条直接读取 B 类字高、完全绕过主解析器的几何生成路径。仅在主解析器里改英数字形尺寸，不能据此声称覆盖了这类缓存绘制；同样不能在未识别使用界面前，把该重复符号机械地套用英文字高补偿。

替换缓冲区的相邻静态地址引用目前只定位到一组上层复制候选，尚未穷尽写入者；原生第一缓冲区地址构造本身就有间隔指令，已超出本轮相邻模式的覆盖范围。后续必须扩展局部数据流、GP 相对访问和基址加偏移追踪。调用者的界面归属、全部间接调用、测宽结果消费、分页和完整 DMA 时序继续保留为未完成。

复跑：

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/cache_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/caller_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_repeat.py
```

## 第七阶段：缓存首次初始化与原生十进制转换

本阶段补掉上一阶段 `@N` 证明中的两个前提，并保留旧的分层测试用于定位：

- [缓存首次初始化 144 组](issue-assets/native-text-rendering-20261021/cache-setup-execution.json)：每版 48 组，真实执行初始化函数、字体 setter、符号生成器和 GIF 构造器，与 [C 完整组合](issue-assets/native-text-rendering-20261021/cache_setup_model.c) 比较状态、完整 secondary 记录、旧 primary 记录不变、两个缓存及边界字节。覆盖旧队列 0/9/254/255、不同数字字高及 shear/outline。没有函数体替换。
- [十进制返回值 339 组](issue-assets/native-text-rendering-20261021/decimal-execution.json)：每版 113 组，原生 atoi 与下层运行库真实执行，和独立 [C 返回值模型](issue-assets/native-text-rendering-20261021/decimal_model.c) 比较。覆盖 ASCII 空白、符号、非法前缀、尾随字符、十进制进位边界、32 位回绕、64 位极值与超长溢出输入。errno/endptr 和非 ASCII 行为不在此返回值证明内。
- [原生转换＋预初始化缓存 60 组](issue-assets/native-text-rendering-20261021/repeat-native-decimal-execution.json)：移除 atoi 返回值截获，仍分离初始化用于定位。
- [首次初始化＋原生转换＋重复绘制完整组合 60 组](issue-assets/native-text-rendering-20261021/repeat-full-execution.json)：实际执行 lazy 初始化并由调用者清标志，再执行原生十进制转换与包构造。C 对照组合缓存初始化模型和 repeat 模型，比较完整字体状态、secondary 记录、两个缓存、完整输出缓冲区、lazy 标志及返回指针。该模式没有 atoi 或初始化函数体 stub。

### 指令适配范围

新增 [crt_adapter.py](issue-assets/native-text-rendering-20261021/crt_adapter.py)，补充 MOVZ/MOVN、带目标寄存器的 MULT/MULTU、MULTU1、MADD、PMFHL.LW、PCPYUD。语义与解码参考固定到 LRPS2 源码提交 `6664c60294ee05fe5e8c7645ab7da546dae78ed2` 的 [MMI 实现](https://github.com/libretro/ps2/blob/6664c60294ee05fe5e8c7645ab7da546dae78ed2/pcsx2/MMI.cpp) 和 opcode table；来源、文件哈希与适配清单见 [来源收据](issue-assets/native-text-rendering-20261021/crt-adapter-sources.json)。没有运行其他模拟器，也不把源码语义参考称为当前 LRPS2 核心的运行验收。

适配器只实现所声明的指令子集；未支持指令保持原状并让执行失败，不以函数结果替换掩盖缺口。原盘函数与运行库仍执行自身的分支、除法和多字运算。返回值模型一致性不等于 EE 指令集或整个 C 运行库已完整验证。

### 缓存状态究竟保存了什么

首次缓存生成使用数字字高 `F+2E`、数字 palette `F+32`、RGBA `F+24`，符号宽度与推进均传 0，Z 传 0。它临时关闭 shear/outline 并在末尾恢复，恢复旧绘制队列及记录指针；但 secondary Z 参数会保留为 0，secondary 起点字段变为 0。lazy 标志由上层 repeat 调用者清零，初始化函数本身不清标志。

两个缓存各 208 字节并相邻。缓存复制还会带入 packet 中未被写过的保留字节；本次 native/C 两侧均明确把临时 stack packet 区初值设为 A5，再验证这些字节保持，不把它们误认为初始化函数生成的固定常数。

随后的 `@N` 路径会重写当前主 palette、RGBA、调用 Z，以及按当前 B 类字宽／字高／推进生成的坐标。因此不能把 `@N` 最终显示高度直接归因于首次初始化时的数字字高；它的几何高度由使用时的 B 类参数决定。这一结论现有完整原生组合执行支持。

原生 atoi 的已验证返回值语义是：按十进制形成饱和到有符号 64 位范围的结果，然后截断并符号扩展为 int32。`2147483648` 返回 `-2147483648`，`4294967296` 返回 0；上层 repeat 的 32767 限制发生在这个 int32 结果之后。该结论适用于本阶段覆盖的 ASCII 输入域，副作用仍待单独审计。

### 复跑与未完成项

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_cache_setup.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_decimal.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_repeat.py --native-decimal
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_repeat.py --native-decimal --native-lazy
```

本阶段没有新增 GS／DMA 或 LRPS2 画面证明。完整目标仍未完成：缓存包装的非 `@` 转发和相邻 signed 几何路径、上游写入者与界面归属、测宽消费和分页、DMA／缓存时序、异常路径在实际调用场景中的影响仍需继续。

## 第八阶段：负数占位符与普通文本转发

新定位的相邻函数并非上一节 signed decimal 包装函数。它将**负数的绝对值当作减号占位符的重复数量**；非负值才交给专用数字生成器。例如输入 -3 对应三份原生 `817C` 减号的绘制单元，输入 123 则生成十进制数字。不能将所有负数参数都解释为要显示负号的数值。

[独立入口与样式表定位](issue-assets/native-text-rendering-20261021/geometry-inventory.json)：

| 入口 | Original | Best | SP |
| --- | --- | --- | --- |
| 负数占位符／非负数字包装 | 0x3A9F30 | 0x3AA700 | 0x3D5400 |
| 九字节样式表应用 | 0x3AA530 | 0x3AAD00 | 0x3D5A00 |

### 占位符的尺寸和对齐

[placeholder_model.c](issue-assets/native-text-rendering-20261021/placeholder_model.c) 重建负数分支和非负转发的完整可观察行为；[三版对照](issue-assets/native-text-rendering-20261021/placeholder-execution.json) 每版 52 组，共 **156 组**。比较完整字体状态、primary 不变、secondary 记录、两个缓存、全输出缓冲区、返回指针、lazy 标志和 GP 样式字节；覆盖初次／已初始化缓存、左右对齐、负字距、循环展开边界、32767 限制、INT32_MIN、12 个已取样样式表行和低字节 sentinel。

负数分支用数字专用 `F+2C/2E/30`，而 `@N` 分支用 B 类 `F+40/42/44`。负数分支起始坐标以 2048 为偏移，右对齐起点为 `x+2048 - count*数字推进 - 数字字宽 + 数字推进`，按原生有符号 16 位规则回绕。循环复制当前缓存单元后才更新下一位置。它使用调用者传入的 Z，直接生成 packet，不经过正文解析器或普通数字记录队列。

这里的高度也在每次使用缓存时重新写入。因此两条缓存分支共享初始化，不代表它们最终读取同一套高度：`@N` 取 B 类字高，负数占位符取数字字高。初始化本身的数字字高不能替代这两条使用路径的分析。

INT32_MIN 的取负仍是负数，循环不输出重复单元，只写前缀；它不会自动变成正确的十进制负数或 32767 个占位符。这证明原生行为，不证明实际调用者允许此输入。

### 样式与字号分开

样式参数先按有符号 8 位判断，低字节 0xFF 表示保持当前样式，例如 255 和 511 都跳过样式修改。其余值按九字节表行读取：首字节同时设置主／数字 palette，其余八字节覆盖 RGBA 和 outline RGBA，并更新 GP 样式字节。它不写字宽、字高或字距；修改结果不会在包装函数退出时回滚。

非负分支不使用这个样式参数，直接把数字、坐标、对齐、输出指针和 Z 交给底层数字函数，并强制其 chain 参数为 0。模型与原生对照包含这一分支，不能把负数分支的样式行为外推给正数。

本轮取样并执行验证了表的前 12 行；这不证明表总长度为 12，也不证明任意有符号索引安全。原生辅助函数没有表边界检查。

### 非 `@` 文本转发

[144 组转发对照](issue-assets/native-text-rendering-20261021/forwarding-execution.json) 每版 48 组，执行完整缓存文字包装函数和独立直接调用的原生 bridge，对照实际转发参数、返回值、完整状态、两类记录、packet、上传索引／计数／指针和 lazy 标志。覆盖空串、中文、混合英数、宽高控制符、换行、reset、队列／即时、atlas 已满、动态数字开关和不同描边状态。

非 `@` 输入确实原样交给正文 bridge，并将 chain 固定为 0；它不触发缓存初始化。该项目验证包装函数的透明转发，不冒充独立全 C 解析器证明；其下层解析与 GIF 构造另有前述 C 模型证据。

### 调用者范围仍待归属

扩展后的直接 J/JAL 候选清单显示，Original／Best 各有 200 处占位符包装调用、1075 处样式表应用调用；SP 为 197 和 1150。数字是可执行节扫描结果，不能等同于已确认的 UI 页面数量或已穷尽的间接调用。

复跑：

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/geometry_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_placeholder.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_forwarding.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/caller_inventory.py
```

本阶段仍为原盘整数指令与模型／组合证据，没有新增 LRPS2 图形验收。调用界面归属、上游替换缓冲区写入、测宽消费、分页和 DMA 时序仍未完成。

## 第九阶段：上游地址数据流、字体预设与姓名替换写入

新增 [dataflow_inventory.py](issue-assets/native-text-rendering-20261021/dataflow_inventory.py) 及 [三版结果](issue-assets/native-text-rendering-20261021/dataflow-inventory.json)。此前相邻 LUI/低位指令模式遗漏了间隔指令和寄存器 move，本次在直线基本块内传播常量地址，记录来源链，并在调用延迟槽处理后提取实参。GP 来自各 ELF `.reginfo`：Original `4537F0`、Best `453FF0`、SP `4D2870`。

为避免把线性反汇编当成完整控制流证明，跳转目标、分支／调用延迟槽之后及未知指令均丢弃寄存器事实；不跨块合并，不传播可变内存中的指针。可执行节中的嵌入数据、未证实可达的路径、动态指针及非标准 GP 使用仍需人工核对。这是候选追踪工具，不是完整程序静态分析器。

每版找到 35 处携带字体／替换缓冲区附近常量地址实参的直接调用候选。Original/Best 各记录 147 处替换缓冲区**近邻** store 候选，SP 为 159；近邻包含其他状态，不能把它们都计作姓名缓冲区写入。已由这些候选继续定位并执行验证下列两个具体函数。

### 上层字体预设不会同步显式尺寸

[独立入口、表项与汇编](issue-assets/native-text-rendering-20261021/preset-inventory.json)：Original `3AA8E0`、Best `3AB0B0`、SP `3D5DB0`。每行 22 字节，依次为 A 类 width/height/advanceX/advanceY、B 类四参数、数字 width/height/advanceX，共 11 个有符号 halfword。

[完整 C 状态模型](issue-assets/native-text-rendering-20261021/preset_model.c) 与 [1422 组原生对照](issue-assets/native-text-rendering-20261021/preset-execution.json) 验证：低 8 位索引被解释为有符号数，写 GP 选择字节，将分类模式置 1，更新上述 11 个尺寸，开启五个分类标志；**pen 和显式 width/height/advanceX/advanceY 完全保持原值**。因此“调用字体预设”不能当作“所有字体参数均复位”，后续 width/space 控制符切换到显式参数时仍可能读到之前保留的高度。该机制与前面已确认的显式／分类参数区分一致；不能据此把此上层函数当作图鉴物理行初始化函数。

本轮覆盖的索引范围由静态已知调用实参决定：Original/Best 0..50，SP 0..55；对每行检查三个不同初始状态及原值、+256、+2^32 参数别名。此范围是已观察索引下界，不是已证明的表总边界。原生函数没有索引检查；其他负索引和动态实参域尚待审计。

[表项数值比较](issue-assets/native-text-rendering-20261021/preset-semantic-comparison.json) 显示：Original/Best 的取样 51 行完全相同；SP 取样 56 行可按顺序匹配其中全部 51 行，剩余 5 行位于 SP 的 1、50、51、52、53。选定的值序列对齐是 Original 0→SP 0、1..48→SP 2..49、49..50→SP 54..55。存在重复表项，因此它只是值对齐候选，不是所有调用者的一一语义映射，也不证明版本迁移只需加一个固定偏移。

直线传播观察到 Original 921 处该预设直接调用候选，其中 820 处能恢复 a0 常量；Best 为 921/819，SP 为 994/891。其余输入与所有间接调用仍未归属；跨版本的这些计数差异不能直接当作新增 UI 页面数量。

### 找到并验证三个姓名替换缓冲区的写入者

[姓名确认入口](issue-assets/native-text-rendering-20261021/name-writer-inventory.json)：Original `30C430`、Best `30C800`、SP `312980`。它读取对象 +50/+54/+58 的三个输入字段指针，各字段数据从 +8 开始、+42 是有符号字节长度上限。按双字节格扫描，只有 `8140` 算空格；记住最后一个非空格格的位置，在其后写一个 NUL，原地修改输入，再调用原生 strcpy。

三个输入槽依次写替换 1、2、0，即 Original `55857E`、`55858F`、`558573`；替换 3 不由此函数修改。确认后对象 +7 置 1，对象 +A 的字节写到首替换缓冲区前一字节。该选择字节的 UI 语义尚未由画面证明。

新增 [C 模型](issue-assets/native-text-rendering-20261021/name_writer_model.c) 与 [144 组对照](issue-assets/native-text-rendering-20261021/name-writer-execution.json)：每版 48 组，完整比较对象、三个输入字段及包含四号缓冲区和近邻字节的全局 96 字节区域。覆盖空串、全空格、尾部空格、内部空格、满长、长度上限截断、零／负上限。测试字段长度取 8/8/5 格；更大或损坏输入域未证明安全。原生 strcpy 实际执行，由固定的非对齐目的地址选择字节复制路径，未替换函数体。

静态默认初始化候选 Original `14C594/14C5A8/14C5BC/14C61C` 依次把 `ランド`、`トラビス`、`ランド`、全角 `ＺＥＵＴＨ` 写入四个替换缓冲区。这些静态调用连接已保存于数据流结果，完整初始化函数执行尚未覆盖，不能与上述姓名确认函数的执行证明混为一谈。

### 本阶段边界与复跑

没有新增 LRPS2 画面验收，没有修改生产补丁或 ISO。姓名确认入口未发现直接 JAL 候选，后续仍要追踪回调表／间接调用归属；目前不能因未找到直接调用就判定它未使用。其他替换写入者、预设动态索引、界面初始化、测宽消费、分页和 DMA 时序继续保留。

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/dataflow_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/preset_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_preset.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/compare_presets.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/name_writer_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_name_writer.py
```

预设取样范围依赖已保存的数据流调用结果；若扩展分析发现更大常量索引，应重新导出表项、复跑模型并更新数值对照，不能把当前截取范围冻结成已证明上限。

## 第十阶段：姓名虚调用链与实际测宽消费

### 姓名确认入口由虚表调用

[三版虚表连接](issue-assets/native-text-rendering-20261021/callback-inventory.json) 独立定位构造函数写入的虚表，以及通用字段验证块读取并调用的 `+98` 槽：

| 版本 | 构造函数 | 虚表 | +98 目标 | 验证块入口 |
| --- | --- | --- | --- | --- |
| Original | 0x30BA00 | 0x449470 | 0x30C430 | 0x2C46E0 |
| Best | 0x30BDD0 | 0x449C70 | 0x30C800 | 0x2C4AB0 |
| SP | 0x311F50 | 0x4C7AE0 | 0x312980 | 0x2CB770 |

这解释了之前只有原始函数地址字、没有直接 JAL 的现象。构造函数的虚表赋值是静态指令证据；验证块至确认 writer 的间接边现已实际执行。

[360 组组合对照](issue-assets/native-text-rendering-20261021/name-gate-execution.json) 使用受控对象和原盘虚表，从验证块内部入口执行到原生共同出口：逐字段调用真实 strlen，按双字节格统计 `8140`，需要被检查的字段均含非空格内容时通过 `jalr` 进入真实确认函数，否则不写姓名并将控制寄存器 S7 设为 6。对照 [C 验证＋确认模型](issue-assets/native-text-rendering-20261021/name_gate_model.c)，比较虚调用次数／实参、控制码、完整对象／输入／全局缓冲区。

每版 120 组，覆盖空串、全空格、部分字段无效、有效字段，以及 0..3 的检查字段数。所有三字段指针均有效分配；NULL 字段和其他计数域不在本次模型范围。此证明不包括整个 UI handler 从入口到返回、实际按键事件可达性或自然运行中的对象构造。不能把该片段的 S7=6 擅自命名为已观察到的某条屏幕提示。

### strlen／strcpy 的对齐快路径

此前固定的姓名目标地址会令 strcpy 选择字节路径；本轮补齐两函数的 EE packed 路径。新增 [独立入口与汇编](issue-assets/native-text-rendering-20261021/string-inventory.json)、[full128 指令适配](issue-assets/native-text-rendering-20261021/string_adapter.py) 与 [来源收据](issue-assets/native-text-rendering-20261021/string-adapter-sources.json)。适配仅包括 LQ/SQ、PSUBB、PCPYLD/UD、PAND、PNOR，语义参考此前固定提交的 LRPS2 源码，未支持指令仍显式失败。

[2736 组成对检查](issue-assets/native-text-rendering-20261021/string-execution.json) 每版 912 组，共实际调用原盘 strlen／strcpy **5472 次**。覆盖源地址全部 16 种低位对齐、目的地址的对应／0／1／8／15 对齐、0/1/7/8/9/15/16/17/31/32/33/63 字节长度及随机非零字节；核对返回值、源不变、完整目标与两侧 guard 字节。仅对合法、NUL 终止、不重叠且有足够空间的缓冲区证明这些合同，不覆盖未终止、重叠或容量不足输入。

三版两函数的各自代码 SHA-256 相同；入口地址分别为 strcpy `1A0D88/1A1128/1A5238`，strlen `1A0EA0/1A1240/1A5350`。这不等于整个 C 运行库已完成证明。

### 一个完整的测宽→居中→绘制调用者

[独立调用者定位](issue-assets/native-text-rendering-20261021/centered-label-inventory.json)：Original `2C11C0`、Best `2C1590`、SP `2C82B0`。函数先 reset 字体、应用样式 13，设置 A/B 均为 16×10、推进 16×10，再从指针表取文本，以 measure(false) 得到负半宽，直接作为文字 bridge 的 X，Y=89。退出前恢复中性 RGBA/outline 并关闭 outline；它没有在测宽和绘制之间重新初始化字体。

新增 [完整 C 组合模型](issue-assets/native-text-rendering-20261021/centered_label_model.c) 与 [120 组原生对照](issue-assets/native-text-rendering-20261021/centered-label-execution.json)，每版 40 组。执行整个调用者及真实 reset/style/classifier/measure/parser/packet 函数，比较完整字体状态、绘制记录、全包缓冲区、返回值和上传请求。文本表项和 GP 索引是受控输入，不声称已识别它在自然运行中的具体界面。

| 受控输入 | measure(false) 得到的 X | 首个绘制记录 x/y/width/height | 最终 pen X |
| --- | ---: | --- | ---: |
| 一个普通汉字 `889F` | -8 | -8 / 89 / 16 / 10 | 8 |
| `330E`＋同一汉字 | -16 | -16 / 89 / 22 / 14 | 6 |
| `320E`＋同一汉字 | -11 | -11 / 89 / 14 / 11 | 11 |
| `340C`＋同一汉字 | -6 | -6 / 89 / 22 / 11 | 6 |

这里有两个独立作用：测宽器不识别 `33`，把该两字节控制符计成一字；绘制器识别它，但同时关闭分类模式，字宽和推进改用 reset 后保留的显式 22，字高为新设 14。因此字高控制符能间接改变绘制所选的字宽／推进，不能把它理解为只改变高度的无副作用操作。

这些是原生几何记录的数值，不是字形笔画包围盒或屏幕像素测量。表中是受控插入控制符的输入，尚未证明正式文本在这个调用点含这些控制符；它证明底层差异可以传递到一个完整真实调用者，而非已经观察到新的正式版 UI 缺陷。该结果也不能外推为所有图鉴／剧情调用者都会先测宽。

### 复跑与剩余范围

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/string_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_strings.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/callback_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_name_gate.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/centered_label_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_centered_label.py
```

本轮未新增 LRPS2 图形证据，未修改生产补丁／ISO。仍需完成剩余测宽消费者与间接调用归属、其他文本替换写入、布局／分页、完整 DMA 与缓存时序，以及实际调用场景中的 LRPS2 影响验证。

## 第十一阶段：图鉴字节拆行、完整行范围绘制与现有补丁对照

新增 [独立拆行／上下文函数定位](issue-assets/native-text-rendering-20261021/split-inventory.json)，覆盖计数、按序号选行、行范围循环、物理行初始化、颜色／上下文及 strncpy。SP 中物理行函数的短指令签名同时匹配另一处新增函数；本轮通过已独立定位的行范围循环的真实 JAL 目标消歧，再核对原生签名，没有按统一版本偏移猜测。

| 功能 | Original | Best | SP |
| --- | --- | --- | --- |
| 有限计数 | 0x220F70 | 0x221330 | 0x225D50 |
| 按序号取字节行 | 0x221030 | 0x2213F0 | 0x225E10 |
| 行范围绘制 | 0x221130 | 0x2214F0 | 0x225F10 |
| 物理行初始化／绘制 | 0x220DB0 | 0x221170 | 0x225B90 |
| 上下文绘制包装 | 0x225290 | 0x225650 | 0x22A200 |

### 字节行规则与返回值

[split_model.c](issue-assets/native-text-rendering-20261021/split_model.c) 和 [1785 组对照](issue-assets/native-text-rendering-20261021/split-execution.json)，每版 595 组，验证偏移、长度、返回值及输入不变；真实执行 strlen，包含其对齐 packed 路径。

- 两个分隔字节均从各版 GP 相对全局读取，原盘初值都是 `0A`；SP 的 GP 偏移与 Original/Best 不同。按字节查找，不识别 Shift-JIS 格边界或控制符参数。
- 选行成功必须行长度大于 0。空行返回失败，故前导空行或中间空行可以令行范围循环停止，而非自动留一空行后继续。
- 首次选行有 255 次扫描预算：索引 254 可以命中，255 失败。但这**不是全文最多 255 行**；行范围循环第一次成功后把相对行索引改为 0，从新指针继续选行。本轮完整调用案例实际经过 300 次物理行调用。
- `count_below_limit` 只在到达字符串末尾且计数未触及 limit 时返回行数；触及 limit 时返回 0。它不返回被钳制的最大值。空串、NULL 或非正 limit 返回 0。
- NULL 选行输入不修改输出偏移／长度；非 NULL 即使失败，也会按原生过程重置或推进输出。INT32_MIN 索引的减一回绕亦已比较，不能用简单 `index<0` 提前返回替代。
- `33 0A` 的参数被视为行边界；参数为 NUL 的控制符会被上游 strlen 提前截断。这一层的字节规则与主文字解析器能消费控制符 NUL 参数的规则不同。选行证明包含这类输入；完整绘制模型不将被切断的控制符冒充安全完整行。

### 完整原生行范围调用与 C 组合

新增 [library_range_model.c](issue-assets/native-text-rendering-20261021/library_range_model.c) 与 [三版 432 组完整调用对照](issue-assets/native-text-rendering-20261021/library-range-execution.json)。执行整段行范围函数及真实 strlen／strncpy、选行、物理行、字体分类初始化、颜色查表、上下文设置、文字解析和 packet 输出，没有替换下层函数体。对照完整字体状态、记录缓冲区、临时行区、全输出包、上下文全局值、调用次数、返回指针和上传请求。

覆盖单行／多行、前导／中间空行、尾部 LF、完整宽高控制段、空／NULL 输入、非法区间、254／255 选行边界、300 行连续处理、滚动起止行、即时／积累记录、NULL packet 引用、fade、已知颜色和 palette 分支。测试描述符使用正的有效尺寸，行内容不含被截断的控制符或替换操作；512 字节临时区与 1024 次模型循环保护只是分析容量，不是原生边界检查。

行范围的起止序号均包含在请求内。滚动选择后的第一行仍从描述符原始 Y 开始，后续 Y 按描述符 `+11` 的有符号字节推进，不按被跳过的行数增加 Y。合法请求即使选行失败、实际没有任何物理行调用，函数仍可返回 1；这个返回值不能当作“已经画出指定数量的行”。NULL packet 引用时，物理行初始化和上下文设置仍可发生，绘制包装提前返回，故证据中的 `physical_row_calls` 不等于产生了可见行。

每次物理行只从描述符更新分类 A/B 参数并打开分类标志，显式尺寸不重置。因此第一行临时字高可跨越物理换行保留；下一行一旦使用 width/space 等控制符切到显式参数，便会重新使用该保留高度。这是对整段原生调用的证明，补强了此前仅执行初始化片段的结论。

### 现有逐行同步补丁的完整调用验证

以同一套受控输入在指令执行内存中应用当前 `tools/srwz/library_body_metrics.py` 的正式 trampoline，新增 [432 组有声明补丁的对照](issue-assets/native-text-rendering-20261021/library-range-patched-execution.json)。apply 函数先检查原盘 hook／cave preimage，再仅改声明的 JAL 与 cave；未重建／写回 ISO。C 组合仅增加“每行先同步四个显式尺寸”的对应动作，其余过程与原生模型相同。

受控输入为 `33 0E 88 9F 0A 32 0E 88 9F`，行描述为 21×12、推进 21×14，进入前的显式尺寸为 18×10、推进 18×10：

| 执行变体 | 第一行进入时显式 W/H | 第一字几何 W/H | 第二行进入时显式 W/H | 第二字几何 W/H |
| --- | --- | --- | --- | --- |
| 原盘 | 18 / 10 | 18 / 14 | 18 / 14 | 14 / 14 |
| 声明的逐行同步补丁 | 21 / 12 | 21 / 14 | 21 / 12 | 14 / 12 |

两版执行均在 Y=36/50 调用这两行；几何与状态来自实际原始指令轨迹。此证明针对逐行恢复，不等于字形笔画高度、基线或英文光学对齐验收，也不替代已保存的 LRPS2 图片。

### 条件移动适配纠正及复跑

核对固定版本 LRPS2 `R5900OpcodeImpl.cpp` 后发现，早前 `crt_adapter.py` 的 MOVZ/MOVN 曾同时复制分析器保存的高 64 位，而原生只改低 64 位。已纠正，来源文件哈希加入 `crt-adapter-sources.json`／`string-adapter-sources.json`。strncpy 所需的条件移动适配同样保留高位。

已复跑受影响的十进制 339 组、原生转换 repeat 60 组、完整 lazy/转换 repeat 60 组、字符串 2736 组成对合同、姓名虚调用 360 组及居中调用 120 组，全部通过；旧结果的所比较返回值／状态／缓冲区未因修正改变。这只说明既有样例未受该适配错误影响，不能保留错误语义或将其解释为高位不重要。

### 复跑与剩余范围

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/split_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_split.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_library_range.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_library_range.py --sync-explicit
```

本轮原盘执行和声明补丁执行分开记账，均不是 GS／DMA 或新增 LRPS2 图形证明。原生拆行／逐行绘制核心已得到上述输入域的完整组合对照；图鉴 UI 的滚动状态、页数与选中字段如何产生 start/end，剧情模式的分页状态机、其他测宽消费者、DMA 时序和实际调用场景的 LRPS2 验收仍需继续。

## 第十二阶段：滚动对象、页面归属纠正与机体排版缺口

### 滚动对象和输入范围

[viewport-inventory.json](issue-assets/native-text-rendering-20261021/viewport-inventory.json) 独立定位了 setup、draw、can-down、up/down，并逐处保存六个 setup 调用的 descriptor／arrow getter 和立即数行数。对象字段：+4 文本指针、+8 首行、+C 可见行数、+10 正文描述符、+14/+16/+18 上／下箭头 Y 和箭头 X。

[viewport_model.c](issue-assets/native-text-rendering-20261021/viewport_model.c) 与 [3948 组原生状态对照](issue-assets/native-text-rendering-20261021/viewport-state-execution.json)，每版 1316 组，验证 setup 的低位参数存储、箭头坐标复制、首行归零、向上／向下和 can-down。真实执行有限行数计数与 strlen，无函数体替换。包含 NULL／空文本、空行、不同可见行数、254／255 行计数 sentinel 和有符号回绕边界；不把损坏输入域当作正常 UI 可达状态。

can-down 条件为：`visible_rows < int32(count_below_limit(text,255) - top_row)`。down 成功只将首行加 1；up 仅在首行大于 0 时减 1，故是逐行滚动。draw 将 `[top, top+visible-1]` 交给已验证的行范围函数；其后按 top>0 和 can-down 分别安排上／下箭头。箭头绘图尚未纳入该状态模型，不能将状态证明叫作整段 viewport 图形输出证明。

计数函数在触及 255 限制时返回 0，会令 can-down 在正常非负 top 时为 false；与前一阶段行范围可逐行处理 300 行并不矛盾。原生没有在这些方法内把首行自动钳制回文本末端，也没有把空行从逻辑行数中剔除。

### 纠正早期报告中的页面名称

此前按构造函数位置把三组正文描述表误标成角色／机体／术语。新增 [surface_binding_inventory.py](issue-assets/native-text-rendering-20261021/surface_binding_inventory.py) 与 [三版原始绑定链](issue-assets/native-text-rendering-20261021/surface-bindings.json)，逐步验证：

`viewport setup 调用 → 同一初始化路径创建的 renderer → renderer 写入的 vtable → draw 槽 +10 → metadata 函数 → descriptor getter → 原生标签文本`

角色链的标签包含“愛称”“声優”，机体包含“全長”“重量”，术语包含“：用語の切り替え”。由同一初始化路径同时设置的正文描述符和 visible_rows 绑定，结果如下：

| 页面 | Original 描述符 | Best 描述符 | SP 描述符 | 可见行数 | A/B 原生字形／推进 |
| --- | --- | --- | --- | ---: | --- |
| 角色 | 0x41F020 | 0x41F850 | 0x47A9B0 | 9 | 21×12／21×14 |
| 机体 | 0x41EEE0 | 0x41F710 | 0x47A870 | 5 | 21×10／21×12 |
| 术语 | 0x41F0E0 | 0x41F910 | 0x47AA70 | 5 | 21×12／21×14 |

原生标签和虚表链消除了仅凭某个 getter 或函数名推断用途的歧义。早期两份字体调查／修复报告已据此纠正。此前两个目标人物的原生高度12和已列 LRPS2 证据不因本次更名改变，但不能继续将其推广为机体正文也是高度12。

### 当前候选 ISO 的机体排版确有不匹配

现有原生逐行同步补丁从行描述符读高度，不依赖错误的页面名称，故机体会先恢复为10。问题在当前排版工具：`library_typography(text, tag)` 只按 DSCR／DSC2 标签选择高度12，Original/Best 与 SP 构建调用虽知道 domain，却没有把它传入；机体也因此得到英数14/13和尾部高度12。

新增 [三版候选 ISO 回读审计](issue-assets/native-text-rendering-20261021/robot-body-height-audit.json)，使用实际可执行文件归档偏移，解压 ROBO 字段，验证原生补丁并流式核对整个 ISO 的既有 SHA-256：

| 版本 | 机体 DSCR/DSC2 字段数 | 含高度12控制符的字段数 |
| --- | ---: | ---: |
| Original | 642 | 470 |
| Best | 642 | 470 |
| SP | 660 | 476 |

这些控制符计数结合统一生成规则，确认当前候选的机体字高 scope 与原生10不匹配；它不是新增的屏幕像素测量，也不证明每个含该控制符的字段都已在游戏中打开。候选 ISO 未被修改。

机体不能简单把恢复标签改为 `<height:0A>`：现有字节拆行会把它当 LF。后续修复必须让 native 拆行正确区分控制参数，或提供等效且经三版验证的安全恢复机制，再按 domain 生成对应高度。不能只改常量、接受中文在英数后变大，或把两个人物的通过结果当作机体验收。

### 复跑与未完成项

```sh
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/viewport_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/verify_viewport_state.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/surface_binding_inventory.py
work/venvs/unicorn-tests/bin/python docs/issue-assets/native-text-rendering-20261021/audit_robot_body_height.py
```

本阶段没有新增 LRPS2 会话，没有改生产代码或重建 ISO。原始目标保持完整：当前已确认的机体恢复缺口需与原生／工具共同修复；viewport draw 的箭头调用和更上层字段选择、剧情分页、剩余测宽消费、DMA／缓存时序及实际运行验收仍未完成。


## 第十三阶段：安全高度恢复、三版重建与光学对齐缺口

原生 `33` 字高处理器增加一个保留参数：`8A` 解码为10。其余255种参数保持原意。现有逐字节 LF 拆行不变，正文不插入原始 `33 0A`。三个独立地址的处理器和16字节辅助区均检查原生前像，辅助区紧接44字节行初始化跳板，两补丁写入范围不相交、应用顺序可交换。直接原生尺寸设置函数不受此扩展影响。此扩展改变全局解析器对保留参数138的含义；已审计三版原生图鉴三类归档，未发现该参数，**尚未证明剧情及所有其他字符串均无此参数**。

[1536组原生参数状态对照](issue-assets/native-text-rendering-20261021/height-encoding-execution.json)覆盖三版、两种入口分类状态和全部256种字高值，核对完整字体状态、scratch及文本指针。另以[504组完整行区间对照](issue-assets/native-text-rendering-20261021/library-range-safeheight-execution.json)执行真实拆行、原生行初始化、解析和packet生成，机体描述符使用21/10/21/12，覆盖英文加高、数字加高、中文安全恢复及跨行恢复。Unicorn中的一条EE MOVZ适配仅更新低64位；这些对照不是GS像素验收。原生未修改和仅行初始化补丁的432组对照均重跑通过，原生解析300组对照重跑通过。

排版接口显式接收domain。角色/术语高度12，英文补偿至14、纯数字至13；机体高度10，英文至12、纯数字至11，段尾以8A恢复10。字宽14、推进12保持。旧角色高度段重编译为机体段时移除旧闭合段再生成，保证幂等及可见文本不变。目前同一混合英数run仍按是否含字母选择整个run的高度，这是未完成项。

三版重建批次：`08313d75e7d5cf270f74218b0d84a86cbc236618018dcd923d50b6f5999b1244`。[ISO回读](issue-assets/native-text-rendering-20261021/safeheight-iso-audit.json)核验两种原生补丁和所有正文字段，机体中文闭合恢复均为8A，无原始LF字高参数；Original/Best各1568字段，SP1590字段。原来的robot-body-height-audit.json保留为旧批次缺口证据，不能再用于描述新批次。全套834项测试通过，1项跳过。

[LRPS2新截图及回执](issue-assets/native-text-rendering-20261021/safeheight-lrps2-review.json)：三版莉露/亚历克斯首屏与滚动后共12张，中文恢复、逐行尺寸及滚动未见新增异常；Original/Best DSC2为明确记录的临时选择标志，SP自然进入，原始记忆卡哈希未变。本轮未验收机体画面。

**用户指出的主要矛盾仍未关闭**：宽度紧缩后，字格高度相同不代表笔画高度一致；现有纵向补偿改善高度，但原生统一Y原点使英数笔画仍偏低。按取样包围盒计算，上移约1个原生坐标单位可作为后续受控实验起点，尚未实施或宣称画面通过。需要将笔画高度、垂直位置、混合run中数字高度分别验证；不应将小写e/o拉成大写高度，也不应改变后续中文和整行推进。

本阶段仍不构成完整反编译、全部测宽消费者兼容、剧情参数兼容或DMA/GS时序结论。


## 第十四阶段：字形 Y、复位缓存反例与原生上传／提交链

### 原生位置写入与控制符30的真实缓存语义

主解析器把 scratch `+30/+32` 的 pen X/Y 直接写入主记录 `+4/+6`；字高写入 `+E`，不会自动改变记录Y。packet构造再将记录Y与全局偏移相加，编码为左移4位的坐标字段；这里还不能直接声称它在某个输出分辨率下对应多少截图像素。垂直补偿应区分字形记录位置、文本pen、换行推进和输出缩放。

[原生复位对照](issue-assets/native-text-rendering-20261021/reset-cached-height-execution.json)新增三版12组：`33 HH 8260 30 FF 889F` 中，两个字形都继续使用本次解析缓存的 `21×HH`；字体状态中的显式尺寸则已被复位为 `22×11`。因此 `30` 不是“立即让本次解析所有临时局部量都重新读取默认值”。已有300组解析模型虽覆盖reset，本阶段将这一容易误读的语义单独提取为可检查证据。

第一版分析候选把临时标记编码进工作字高，并依赖工作字高与持久字高的差值判断。这在复位后失效，造成第二个字形高度140–142。[拒绝记录](issue-assets/native-text-rendering-20261021/optical-candidate-rejection.json)保留三版9个反例、旧代码和旧执行结果。**模型与原生执行一致，只证明模型复现了候选行为，不证明候选满足修复要求。** 第一候选不得用于生产。

修订候选使用当前解析调用栈 `SP+58..5B` 的独立标记。[三版栈帧归属审计](issue-assets/native-text-rendering-20261021/geometry-frame-inventory.json)检查96字节解析帧，其原生保存区到`+57`为止；原生解析器仅调用reset叶函数和48字节packet构造器，两者无重叠访问，也没有SP别名或间接调用。入口NOP位置初始化标记，每次height控制更新它，不新增全局持久字段。`8A`恢复10，`8B..8E`表示解码高度11..14并令显式模式的字形记录Y减1；真实工作高度一直保持解码后的值，pen和行推进不变。reset保留工作高度时也保留本调用的补偿语义；下次解析入口清零标记。

修订候选的[3216组双调用原生对照](issue-assets/native-text-rendering-20261021/optical-candidate-execution.json)执行6432次完整解析，覆盖全部256参数、入口分类状态、两种数字路径、复位、与标记相似的原生大字号、坐标回绕及下一次调用；另有[648组完整拆行／上下文／解析／packet组合](issue-assets/native-text-rendering-20261021/library-range-optical-candidate-execution.json)。这些helper仅放在分析器拥有的`0x1700000`区，不是生产代码空洞分配，不得将其地址直接用于游戏构建。**候选未写入ISO，也没有LRPS2光学验收；混合英数排版工具尚未生成这些新标记。**

### 延迟图集上传的完整字节构造

新增[transfer_model.c](issue-assets/native-text-rendering-20261021/transfer_model.c)和[510组原生对照](issue-assets/native-text-rendering-20261021/transfer-execution.json)，执行三版自己的上传构造器及真实REF辅助函数，对照完整描述包、引用链、全局指针和返回值。覆盖正负差值、向零除16、8字节对齐但非16字节对齐的包地址、原始参数比特。REF将地址向下对齐，原生不因此验证描述包是否真正16字节对齐；非8字节对齐的SD写会在本指令模型中触发异常，不属于成功调用域。REF辅助对空差值不追加项；追加项仅写16字节槽中的低8字节，不能假定高8字节已被本函数清零。

实际上传包由BITBLTBUF、TRXPOS、TRXREG、TRXDIR及IMAGE段组成；其DBP为`1180`、DBW为8，格式值依次`24/2C`。每半区512×240，源数据分别为atlas与atlas+`F000`，各`F00`个quadword，构造器返回包地址+112。先前静态报告中的TBP/TBW称谓已更正为上传目的字段DBP/DBW。

[120组完整调度对照](issue-assets/native-text-rendering-20261021/font-upload-pair-execution.json)覆盖三版六个原生dirty门控块，执行真实构造器和REF函数：dirty=0不写缓冲；非零时先清dirty，重建四项引用链，依次生成两个半区包，最后恢复调用前的current/previous指针，保留新的chain写指针。这证明的是请求构造及状态效果，**dirty清零并非DMA或GS已经完成的凭据**。

### 继续追到实际提交入口，并用LRPS2核验保留链

[三版独立提交绑定与汇编](issue-assets/native-text-rendering-20261021/submission-inventory.json)从第二个atlas块的后续调用找到关链函数、syscall100包装、通道等待函数、地址转换和提交函数。Original/Best提交入口`10E5B8`，SP为`10E548`；不能把Original所有偏移直接平移套用。后续代码在`1000A000`上轮询掩码100，两次通过同一提交入口分别发送字体链和另一条链。

[396组原生提交对照](issue-assets/native-text-rendering-20261021/submission-execution.json)包括144组地址转换和252组就绪通道组合。地址高nibble为7时替换为8，其他值保持；原生等待函数执行在start位已清的RAM通道影子上，没有替换函数体。随后若`channel+30`不是FFFFFFFF哨兵则写链地址，清`+20`计数，最后写`(control & FFFFFFF3) | 105`启动。记录实际写顺序并比较完整通道区。**这不证明真实MMIO忙等待、超时恢复、syscall100的缓存副作用或DMA完成时序。**

[三版LRPS2原盘冷启动](issue-assets/native-text-rendering-20261021/lrps2-upload-chain-verification.json)仅执行控制器和RAM读取，三版通道指针都实际为`1000A000`；内存中的提交函数字节哈希与各版原生ELF相符。保留的四项字体上传REF与模型逐项一致，两个包的目的字段、512×240传输尺寸及atlas/atlas+F000源地址也均匹配。未写代码、数据或原始记忆卡。采样是帧后保留缓冲快照，不能用它推断该帧内的提交先后、缓存可见性或完成时间。

本轮未更改生产补丁、排版工具或候选ISO。由于分析C模型增加了候选分支，已重新通过原生解析300、立即绘制303、未修改行范围432、逐行同步432及安全高度行范围504组对照。完整目标继续：光学候选的生产地址／源码兼容与LRPS2画面、混合英数排版、上传与scatter在完整frame CFG中的时序、忙通道／超时／缓存副作用、剩余格式化和替换写入者、间接调用及剧情分页等尚未完成。


## 第十五阶段：忙等待、复位恢复、调用路径时序与原位字号候选

### 原生忙等待不是错误返回

[独立三版入口](issue-assets/native-text-rendering-20261021/dma-wait-inventory.json)确认 Original/Best 等待函数`10E130`、恢复函数`10E8C8`，SP分别为`10E0C0`、`10E858`。原生等待计数初值为`01000000`，不是毫秒数。等待期间轮询通道控制位100；计数变负时调用诊断输出和恢复，再继续读取通道状态。

[210组带叶服务契约的对照](issue-assets/native-text-rendering-20261021/dma-wait-execution.json)和[498组执行真实中断包装的对照](issue-assets/native-text-rendering-20261021/dma-wait-native-interrupt-execution.json)比较完整通道区、设备影子寄存器、返回寄存器、诊断／中断调用及写入顺序。两套各包含12次完整原始计数循环，未缩短常量、跳过循环或人为注入计数值；诊断入口观察到计数为-1。短等待另以第1、2、3、16、255、1024次读取就绪的外部设备计划检查轮询。

恢复函数先取得中断保护状态，读取`1000F520`；若其10000位未置，写`1000F590`以临时设置该位；读取`1000E000`，保留旧通道控制值，写通道控制以清100启动位，然后把最初的设备使能值写回`1000F590`，按入口状态恢复中断，返回旧通道控制。原生包含对`1000E000`的一次读取，其值在本函数后续计算中未被使用；不能因值未使用便把该设备读取删掉。

等待函数在正常就绪和超时恢复后都从状态轮询得到零。外层提交函数不检查一个失败码，而是继续写链地址／计数并置启动位。因此“超时后不再提交”并非原生行为。上述测试使用RAM设备影子和外部就绪计划，**没有证明真实DMA进度、寄存器并发变化、缓存可见性或硬件耗时**。

### 中断包装的适用状态已单独还原

[1152组原生包装对照](issue-assets/native-text-rendering-20261021/cp0-wrapper-execution.json)执行原生普通分支和整数指令，只适配它使用的MFC0 Status、DI、EI及SYNC。适配依据固定版本的[LRPS2 COP0实现](https://github.com/libretro/ps2/blob/6664c60294ee05fe5e8c7645ab7da546dae78ed2/pcsx2/COP0.cpp)与[状态字段](https://github.com/libretro/ps2/blob/6664c60294ee05fe5e8c7645ab7da546dae78ed2/pcsx2/R5900.h)，[来源哈希](issue-assets/native-text-rendering-20261021/cp0-adapter-sources.json)单独保存；这不是对当前安装核心或真机的指令时序认证。

覆盖KSU、EIE、EDI、EXL、ERL组合、额外状态位及两种待事件位置。入口EIE已清时，禁用包装直接返回0；允许DI且EIE置位时清EIE并返回1。稳定状态下，若EIE置位而DI不被允许，该包装会重复尝试，本矩阵有18个有界观察未返回的案例；结合循环状态不变可确定这一模型中的非终止条件，**未证明自然游戏进入过该状态**。退出包装按权限设置EIE，并返回之前的EIE。EI事件请求只检查参考实现中的调度数值，不模拟真实中断投递；SYNC也不提供真实内存屏障验收。

498组组合已把先前的两个中断叶服务替换为真实原生包装加上述指令适配；仅诊断输出仍是外部叶服务，设备状态仍是影子。对所选可终止状态，恢复结束后CP0状态与入口相同，写入顺序与C模型逐项一致。

### 两条帧内路径的局部CFG已经闭合

[六个局部控制流图及汇编](issue-assets/native-text-rendering-20261021/frame-flow-inventory.json)从各版实际调用点绑定CPU scatter、描述包构造、缓存syscall100及两次提交。它们保留分支／延迟槽语义，没有未解析间接转移或跳出窗口的直接边。对于窗口内普通返回的调用边，scatter支配两次提交，对应的缓存调用也分别支配提交。

| 版本／路径 | CPU scatter调用点 | 两次DMA提交调用点 | 已验证的局部顺序 |
| --- | --- | --- | --- |
| Original／主循环 | 143440 | 1435E4、14368C | 先请求、再scatter、后同步／提交 |
| Best／主循环 | 143440 | 1435E4、14368C | 先请求、再scatter、后同步／提交 |
| SP／主循环 | 144740 | 1448E4、14498C | 先请求、再scatter、后同步／提交 |
| Original／第二路径 | 1CD720 | 1CD8E8、1CD930 | 先scatter、再请求、后同步／提交 |
| Best／第二路径 | 1CDAE0 | 1CDCA8、1CDCF0 | 先scatter、再请求、后同步／提交 |
| SP／第二路径 | 1D0E00 | 1D0FC8、1D1010 | 先scatter、再请求、后同步／提交 |

第一类窗口分别268／268／249个可达宏节点，第二类各120个。调用点来自各自原生ELF，未通过单一固定偏移猜SP地址。窗口中其他函数仍以普通调用／返回边表示，**它们的副作用和更上层帧入口归属尚未全部还原**；因此本结果不能升级为完整帧或异步设备时序证明。

### 字号补偿现在有可容纳于原代码区的候选

第十四阶段候选使用分析器专有RAM辅助地址。新增[原位重排候选](issue-assets/native-text-rendering-20261021/optical_packed_candidate.py)，不再依赖那两个地址：将width／height／space／纵向推进处理器重排为28／56／28／28字节，共140字节，容纳在原32..36控制处理器的144字节区；把36数字调色处理器移到现有16字节保留尾区，更新五个原生跳表项。保留区与44字节正文初始化跳板不重叠。

Y调整直接放入原字形记录构造基本块：移除冗余LUI并把319记录上限常量移到后续未使用V0的位置。解析入口初始化`SP+58`标记，光学height参数设置它并关闭分类；原生解析内部的分类写入均为零，恢复入口分类发生在字形构造结束后。这一数据流支持在内联块按标记调整Y，保持pen与推进不变。

[9372组双调用对照](issue-assets/native-text-rendering-20261021/optical-packed-candidate-execution.json)执行18744次完整原生解析，覆盖五种控制参数的全部256值、两种分类／数字路径、reset、坐标回绕，并补测记录318上限、图集跨半区、末格和已耗尽路径。对照全部字体状态、320条记录区、字形上传索引／计数／指针，并检查实际提前退出入口。另有[648组完整拆行到packet对照](issue-assets/native-text-rendering-20261021/library-range-optical-packed-execution.json)。新增参数含义限定为8A恢复10，8B..8E为高度11..14并上移字形；其他height参数保留原意。

[入口引用及前像审计](issue-assets/native-text-rendering-20261021/optical-packed-reference-audit.json)确认三版写入均在既有文件映射区、未增加段／BSS／堆内存；扫描范围内未见进入重排控制区或变更基本块内部的直接转移，旧控制处理器的五个原始地址字面量只出现于对应跳表项。该扫描**不是对未审计代码动态构造指针的全程序证明**。

本轮仍未修改生产补丁、排版工具、ISO或开展新的LRPS2画面测试。下一落地门槛是：审计新增保留参数在其他原生文本域中的占用、将已验证原位候选纳入三版构建、处理混合英数排版，再做LRPS2角色及机体画面验收。完整目标继续保留其余格式化／替换写入者、测宽消费与分页、完整调用归属及真实缓存／设备行为等未完成项。


## 第十六阶段：生产英数字高补偿与三版 LRPS2 校准

当前图鉴正文修复已纳入 Original、The Best、SP 的生产构建。横向紧缩维持 width14／advance12；中文字形高度逐行从原生描述符同步。字母根据字库可见笔画占用作纵向补偿：角色正文 height14，机体正文 height11，生成记录上移1；数字使用各面板原生 height12／10，不上移。混合英数段内部切换高度，但保持同一个闭合的横向紧缩段，避免 RX-78F14 等标识符被内部 height 控制符打断换行。段尾恢复角色21×12、机体21×10；机体高度10使用8A安全编码，避免参数被字节拆行器当作LF。

原生实现为 `tools/srwz/library_optical_metrics.py`，原位重排控制处理器与记录Y构造，不新增分配或持久字体状态。Original、Best、SP 构建和验证均接入；前像漂移／部分补丁被拒绝。分析候选的写入字节与生产 `regions()` 逐项比较。9372组双调用（18744次原生解析）与648组完整拆行到packet对照均通过；它们是指令执行证据，不是像素证据。全套838项测试通过，跳过1项。见 [测试日志](issue-assets/native-text-rendering-20261021/optical-production-tests.log)、[生产源码绑定](issue-assets/native-text-rendering-20261021/optical-production-source-bindings.json)。

原盘保留操作数审计覆盖三版已解码STAGE、图鉴文本字段、SRVC索引字幕，并对COMPDATA候选及ELF命中作结构分类。STAGE的5处命中位于MWo3头部字段，COMPDATA命中位于名字槽后的数值记录；没有把这些二进制数据当作文本控制符。该结论不覆盖其他资源格式、运行时构造字符串或全程序动态指针。见 [源流审计](issue-assets/native-text-rendering-20261021/native-optical-operand-audit.json)。

当前构建批次为 `49e4666f2c2fae2cc55c228a508e7621c13f5b91241e6f988f6202ef4019283d`。[ISO回读](issue-assets/native-text-rendering-20261021/optical-iso-audit.json)逐字段检查 Original／Best各1568、SP1590个正文，角色／机体逐字检查字母、数字、中文恢复参数；术语只做通用扫描，没有声称应用字高补偿。三版各绑定两个人物的3个源字段，旧22/22组合为0。

仅用LRPS2从这些ISO冷启动，核对莉露、亚历克斯首屏及滚动后12张图，再以独立冷启动核对魔神Z首屏／滚动6张图。中文尺寸及行距稳定，英文仍紧缩。Original／Best的后期DSC2继续通过隔离RAM中的可用性标志临时选择，退出前恢复；SP自然显示。原记忆卡各次前后SHA一致。初次附加机体导航未进入机体页，其图片排除，采用独立冷启动证据。见 [LRPS2审阅及命令记录](issue-assets/native-text-rendering-20261021/optical-final-lrps2-review.json)。

首轮数字height13并上移1实际偏大：莉露页14约高22像素，相邻“岁”约高20像素；校准后两者在亮度阈值100／120下均为20像素，底部均到y242。字母G及附近中文在阈值120下均约21像素。阈值140会因抗锯齿使部分字少1像素，低阈值亦有边缘差异；这支持当前取样的视觉接近，不是全字体逐像素等高证明。见 [校准前测量](issue-assets/native-text-rendering-20261021/optical-pixel-calibration.json)、[最终取样](issue-assets/native-text-rendering-20261021/optical-pixel-final.json)。大小写的正常字形比例保留。

完整反编译目标仍未完成：测宽调用者、上游格式化／替换、分页与异常输入、未审计资源的保留操作数、完整帧调用及真实缓存／设备行为仍按coverage保留。当前图鉴取样通过不能推广为全部剧情或所有页面的兼容性验收。没有commit／push。


## 第十七阶段：测宽结果消费者与两段文字居中缓存

上一阶段已将光学字高落入三版生产构建和LRPS2取样，属于实质进展。本阶段只新增反编译和指令证据，没有改生产源码、ISO或用户记忆卡，也未运行新的模拟器图形测试。

### 已重新绑定435处直接调用的局部参数和首次结果使用

[测宽消费者清单](issue-assets/native-text-rendering-20261021/measure-consumer-inventory.json)逐处校验原盘ELF身份和JAL／J编码，向前追踪局部A1常量定义，向后找到V0第一次读取。边界包括普通分支及其延迟槽；不会把延迟槽内的SH／ADDU漏算为“无消费者”。

| 版本 | 直接调用候选 | 局部A1=0（负半推进） | 局部A1=1（总推进） |
| --- | ---: | ---: | ---: |
| Original | 125 | 107 | 18 |
| The Best | 125 | 107 | 18 |
| SP | 185 | 162 | 23 |

全部435处在局部窗口内找到常量定义及首次V0使用，但这不证明全程序可达、所有入边执行该定义，或复制后寄存器的最终归属。首次使用包含浮点转换、16位存储／截断、比较和坐标加减；例如Original／Best各31处首次SH，SP32处。仍需继续追踪返回值拷贝、内存读者、间接调用和真实文本来源。清单保存窗口哈希及实际指令，不把固定偏移套到SP。

### 已闭合一个两段文字的缓存写入与绘制参数链

原生对象的+1C／+20是两段文本指针，写入尾段连续调用measure(text,0)，将结果的低16位分别SH到+24／+26。后续绘制块以LH读回，恢复有符号16位值，计算X=基准X+缓存值+90／548。这里的缓存是“负半推进偏移”，不是原始字宽。

| 版本 | 对象VA | 两次测宽调用 | 两处缓存读取 | 对应绘制桥调用 |
| --- | --- | --- | --- | --- |
| Original | 6D31C0 | 319544／319554 | 319718／319860 | 319744／31987C |
| The Best | 6D39C0 | 319914／319924 | 319AE8／319C30 | 319B14／319C4C |
| SP | 75FCD0 | 33D4A4／33D4B4 | 33D678／33D7C0 | 33D6A4／33D7DC |

[绑定与原始汇编](issue-assets/native-text-rendering-20261021/measure-cache-inventory.json)检查两次调用、文本指针／缓存字段、对象基址的原生形成指令及后续绝对读取。初始化后到尾段前未出现改写S0的普通GPR指令；不据此认证未还原被调函数的ABI／副作用。对象UI名称及完整生存期尚未命名。

[独立C模型](issue-assets/native-text-rendering-20261021/measure_cache_model.c)与[204组对照](issue-assets/native-text-rendering-20261021/measure-cache-execution.json)执行408次真实测宽，以及408个真实绘制参数块，比较完整0x90字体状态、完整0x30对象和六个绘制入参。入口字体状态、对象以及两个绘制块间的样式／图形调用后寄存器状态为明确的受控输入；没有以桩替换测宽函数。证明范围从字体预设之后的写入尾段开始，绘制块止于文字桥入口，不能称为整个对象初始化或整个绘制函数的还原。

对照确认两个容易遗漏的原生语义：第一段的width／space改变会保留到第二次测宽；缓存值是低16位截断后有符号读回。例如advance255的600／601个字形，原始偏移-76500／-76627，缓存读回-10964／-11091。此例是受控长输入，不表示自然界面实际使用这种长度。

### 现行控制段在原生居中调用中的具体差异已量化

[120组完整居中调用组合](issue-assets/native-text-rendering-20261021/optical-centered-label-execution.json)将当前排版工具实际生成的角色／机体控制段编码为受控JIS字节，注入已还原的居中调用；执行真实复位、样式、measure、生产字节一致的光学parser和packet路径，比较全部字体状态、记录、上传队列、包及返回值。字体／packet条件含普通／动态数字、立即／排队、atlas已满。使用现行工具源码哈希绑定；这是分析器中的原生指令证据，不是LRPS2画面，也不证明该调用自然收到图鉴正文。

| 注入逻辑文本 | 实际绘制横向推进 | 按推进计算的居中偏移 | 原生measure给出的偏移 | 额外向左偏移 |
| --- | ---: | ---: | ---: | ---: |
| A1亜 | 45 | -22 | -45 | 23 |
| RX-78F14亜 | 117 | -58 | -93 | 35 |
| 99.9%亜 | 81 | -40 | -57 | 17 |
| Geo亜 | 57 | -28 | -45 | 17 |
| A1B2亜 | 69 | -34 | -69 | 35 |

三版、角色／机体控制形状得到相同数字。表格来自非atlas耗尽案例，比较的是advance语义，不是可见墨迹包围盒的几何中心。原因已经按指令闭合：measure只将31当作调色跳过，识别32和34；33及其参数作为一个双字节字形参与计数，完全不解析高度。绘制parser则将33作为height消费。以A1亜为例，三处height被measure分别多计12、12、21，原本45的推进被算成90。

这一差异在普通height0E和扩展height8E下都存在，不能归因于新保留编码本身。图鉴正文直达逐行绘制的取样结果依旧有效；本测试也不能直接推断自然剧情或其他菜单错位。生产测宽器本轮保持原逻辑。下一步需要绑定这些居中／缓存调用的实际文本来源、确认哪些流确实携带height／换行／替换控制符，再决定共用语法与状态恢复的完整修改范围。

完整目标继续active：435处首次局部使用不是全部消费者归属证明，已闭合的一个缓存尾段也不是全部格式化／分页／动态资源和设备行为的完整反编译。日志见 [缓存组合](issue-assets/native-text-rendering-20261021/measure-cache-tests.log)、[光学居中组合](issue-assets/native-text-rendering-20261021/optical-centered-label-tests.log)。


## 第十八阶段：完整双对象初始化、阵型标签与名字来源

第十七阶段的尾段验证现已向上补齐为完整原生函数：Original 318FF0..319584、Best 3193C0..319954、SP 33CF50..33D4E4。独立[C还原](issue-assets/native-text-rendering-20261021/measure_source_model.c)组合七个真实辅助函数、字体预设和两次测宽；[原盘绑定与汇编](issue-assets/native-text-rendering-20261021/measure-source-inventory.json)从各版原始ELF读取调用、表地址、常量及前像哈希，不直接平移SP。

本阶段只新增反编译／分析证据。生产字高补丁、排版工具、ISO未改，未运行新的模拟器图形验收。上一轮有实质进展，完整目标继续active。

### 此函数消费的是两个输入对象内的名字缓冲区

两个参数各可为空。非空时，将`输入指针+28`直接存入展示对象的文本指针槽；为空时使用原盘“ーーーーー”占位串。两个输入按+25字节排序放入左右槽：任一为空则第一输入进槽1；否则第一字节小于第二字节，或两者相等且小于12时，第一输入进槽1；其他情况进槽0，第二输入取另一个槽。

这不是文本复制：展示对象保留原缓冲区的活指针，同时另外缓存当时的负半推进偏移。因此后续名字缓冲区被改写时，绘制会读取新字节；是否同时重新测宽，需要查更上游的改名／更新调度，尚未证明。不能仅凭缓存初始化正确便证明整个生存期都对齐。

+25还按<4、<8、<12、其余分为四类，空对象为第五类。每个非空输入的+19字节会被原函数修改：保留高6位，低2位取模3，故3变为0。展示初始化因此不只是读取输入状态。形态辅助函数读取三个指针+8／+C／+10；仅+8非空时返回3，否则返回归一化后的低2位，空对象返回0。另一个辅助函数沿+8→+A8指针读取+30字节，测试bit2或bit6，影响特定资源编号选择；没有把这些位命名为未经验证的游戏属性。

形态文字表在三版分别指向“トライ／センター／ワイド／ーーー”。这把该路径绑定到携带小队阵型标签的双对象展示；具体自然菜单和输入对象的完整上游类型／生命期仍未经过运行画面绑定，不能仅凭同一+28偏移就把所有名字写入点视为同一类型。

| 展示对象偏移 | 已还原用途 |
| --- | --- |
| +00／+01 | 分类映射字节 |
| +02／+04 | 分类资源编号；右槽另作编号转换 |
| +06／+08 | 两个输入各自的成对资源编号 |
| +0A／+0C | 形态／特殊资源编号；右槽转换为对应编号 |
| +0E／+10 | 分类关联编号 |
| +14／+18 | 阵型文字指针 |
| +1C／+20 | 原输入+28或占位串指针 |
| +24／+26 | 两次测宽结果的低16位 |
| +28／+2A | 与第一／第二输入绑定的编号 |

空对象分支有些资源字段保留旧值，不额外清零；模型保留这一行为。字段没有图形资源或真实页面归属证据时继续使用中性名称。

### SP的不同编号已作为实际语义参数处理

初次将Original字面资源编号用于SP的模型被真实SP对象字节差异否定。改为按每版原指令读取常量后，三版完整对照通过。其差异不是简单地址重排：SP的分类／形态资源编号比本路径Original编号高1B，分类关联编号高3，两输入编号高1，字体预设从22改为23。[逐版常量与预设行](issue-assets/native-text-rendering-20261021/measure-source-edition-comparison.json)保存具体值。

Original／Best预设22与SP预设23的11个半字相同：`14,9,14,9,14,9,14,9,11,9,10`，即两组分类尺寸／推进均为14×9，数字尺寸11×9、推进10。显式参数保持入口值；测宽遇到width／space后仍按原语义切换共享状态。该面板参数不应与角色正文21×12或机体正文21×10混用。

### 完整初始化与全局入口已执行7032组

[完整对照](issue-assets/native-text-rendering-20261021/measure-source-execution.json)每版2344组，共7032组，包含14064次真实测宽与7032次真实字体预设。3516组从完整函数入口进入，3516组从其前方的原生尾跳包装进入；包装实际读取两处全局指针后J到初始化函数。Original参数全局为6D5F04／6D5FCC，Best为6D6704／6D67CC，SP为762BD4／762C9C。

矩阵包括+25全部256值、+19低2位所有状态、特殊标志字节全部256值、指针链的空／断链／完整及+0C／+10非空分支、空输入组合、两个输入指针实际相同、空名／JIS英数字／现行控制形状等。比较完整展示对象、0x90字体状态、预设选择字节、输入对象和链节点的完整受控区、全局输入指针及返回值。原生函数及七个辅助函数没有被服务桩替换；仅沿用已声明的EE LQ／SQ等指令适配，不将其称为模拟器像素证据。

外层与七个辅助函数的52处非恒定条件分支全部到达，49处观察到两种结果。余下3处的未见方向分别受“形态只能为0..3，且前面比较已排除其他值”和“右槽形态字段只能来自已赋值的五种编号集合”约束；未把它们当作已执行边。包含测宽核心的总75处非恒定分支观察到72处，未覆盖的3处为本批字符串未进入的核心分类路径。既有测宽核心对照仍是独立证据，不能借此把本批覆盖率写成100%。见[覆盖摘要](issue-assets/native-text-rendering-20261021/measure-source-verification.json)、[测试日志](issue-assets/native-text-rendering-20261021/measure-source-tests.log)。

### 更上游已列出明确的追踪入口

[调用与名字写入候选](issue-assets/native-text-rendering-20261021/measure-upstream-inventory.json)每版找到3处直接进入此初始化函数的转移。除上述尾跳包装外，另两处从第一全局指针及一个原生getter取得两个输入；getter读取的全局来源仍需继续绑定写入者。对原生strcpy直接调用的局部指令窗口，还找到Original／Best各16、SP17个“目的地址形如某寄存器+28”的候选，保存源／目的寄存器上下文。

两个JAL入口的getter在三版均校验为LUI→JR→延迟槽LW，且返回寄存器为V0。实际全局来源如下，写入者仍待追踪：

| 版本 | 第一参数全局 | 第二参数getter读取全局 | getter入口 |
| --- | --- | --- | --- |
| original | 0x6d5f04 | 0x6d5248 | 0x34ddb0 |
| best | 0x6d6704 | 0x6d5a48 | 0x34e3b0 |
| sp | 0x762bd4 | 0x761e78 | 0x373280 |

这些49处只是偏移形状候选，可能属于其他结构，不能据其数量声称名字生产者已审计完。尚未覆盖间接调用、非strcpy写入、超出局部窗口的地址形成、上游全局对象生命周期及自然文本到达。下一步沿三个入口的全局写入者建立实际指针归属，再将确认的名字写入者与回读字体控制流相连；完整测宽消费者、格式化、分页和设备行为等目标仍未完成。


## 第十九阶段：输入指针写入、真实迭代刷新与5039命名路径

上一阶段补齐完整初始化和源指针边界，属于实质进展。本阶段继续沿写入者追踪；没有修改生产补丁、工具或ISO，也未运行新的模拟器图形验收。原盘身份、函数和两个真实UI控制流窗口保存在[归属清单](issue-assets/native-text-rendering-20261021/measure-owner-inventory.json)，完整目标保持active。

### 第一输入来自上下文+4，第三来源来自列表迭代器

原生上下文对象在Original／Best／SP分别为6D5F00／6D6700／762BD0。第一输入全局正是此对象+4，第二个持久输入全局是+CC。已找到参数化设置函数对这两个成员的写入，故不能用“没有直接SW到该绝对地址”推断没有写入者。

第一设置函数Original39B440、Best39BA40、SP的实际入口见归属清单：A1为空时返回-1，**不清旧指针**；否则写上下文+4，取输入+8到上下文+8，清上下文+C，写布尔标志字节，并同步两处镜像全局，返回1。布尔取决于完整A2是否非零，不是仅检查最低字节。本阶段真实执行此完整设置函数，没有服务桩。

第二设置函数把A1写上下文+CC，再按有符号低8位索引取其成员到+D0，并调用两个选择服务，最后同步镜像。其写入及调用点已定位，但两个服务副作用尚未闭合；本阶段**没有**将其标为已完成的整函数模型。

另一个用于UI预览的第二输入来自列表迭代器。以Original为例：迭代器34DD10，游标6D5238、索引发布槽6D5240、计数5CA8C4、表5C8250、当前选择6D5248、镜像6D30CC；三版独立地址见清单。表项步长12，取表项首指针，再连续读取+8、+8，得到实体指针；getter只从当前选择全局加载并返回。

| 情形 | 迭代器的真实行为 |
| --- | --- |
| 游标>=计数（有符号比较） | 发布当前索引，返回0；游标／旧选择／镜像保持 |
| 范围内表项为空 | 游标先加1，再返回0；旧选择／镜像保持，不继续扫描后续项 |
| 范围内表项非空 | 游标加1，按两次+8解引用写当前选择及镜像，返回1 |
| 调用复位函数 | 只将游标写0，其他状态不清除 |

没有负索引下界检查，后续两级指针也没有空值检查。本批在已映射的前置槽上测试-1索引，确认可进入表前12字节的受控槽；这不是自然游戏出现负索引或任意坏指针安全性的证明。

### 真实调用者何时重算缓存已经执行到分支汇合点

Original310E10／33BBE0、Best及SP对应位置已独立绑定。两个调用窗口都先调用上述迭代器，判断低字节是否等于1；成功才调用getter，再将上下文+4和getter返回值传入完整展示初始化。这一步重新测量两段名字，更新展示对象的+24／+26。失败分支不进入初始化，改写UI状态为20并跳到本地汇合点。

第一个调用者通过状态对象指针写1字节，第二个调用者直接写2字节状态槽。失败块的实际指令、地址和哈希已附于原盘汇编。对照执行完整失败块至汇合点；成功块止于缓存初始化返回，尚未执行其后另一个getter及13CDA0类展示服务。不能据此认证整个UI帧或其他状态分支。

独立[C组合模型](issue-assets/native-text-rendering-20261021/measure_owner_model.c)与[原生对照](issue-assets/native-text-rendering-20261021/measure-owner-execution.json)覆盖三版各400个场景，共1200场景、1932个步骤：732次成功初始化、1200次失败路径。每个场景真实执行复位及第一设置函数；实际UI窗口以原盘代码进入，无重写执行包装。对照完整输入节点、上下文、全局指针／镜像、字体状态、展示对象、选择字节、状态20写入及实际停机PC。

序列在第一次成功后更改名字再进入下一步：下一步成功时偏移重算；下一步遇空项或计数结束时，原展示指针、字体和缓存保持，UI状态变20。示例一字符名字在预设14推进下缓存-7，改成六字符后下一次成功缓存-42；若此时迭代失败，缓存仍为-7。数据是受控输入，不能直接称为自然页面发生了过期缓存；失败后的显示／离开调度仍须继续绑定。

### 已从“同为+28”推进到同一实体表的命名生产者

找到脚本分派函数的真实表：opcode减5000后按71项范围检查，索引39即操作码**5039**。对应处理块的两条名字复制路径都从命令+8取源指针，按`实体表+176×索引+40`计算目的，调用真实strcpy。实体表地址与一个上下文第二设置调用者形成的基址完全相同：

| 版本 | 5039处理块 | 实体表基址 | 步长／名字偏移 |
| --- | --- | --- | --- |
| Original | 1C28C0 | 58EC50 | 176／40 |
| The Best | 1C2C80 | 58F450 | 176／40 |
| SP | 1C5D10 | 616740 | 176／40 |

因此这条写入路径已具备同一实体表和地址缩放的绑定，不再只依赖+28偏移相同。分派、指针缩放、两处strcpy和消费侧上下文形成指令见[5039清单及汇编](issue-assets/native-text-rendering-20261021/squad-name-command-inventory.json)。命令参数的实体解析服务仍未闭合，尚未审计实际STAGE命令实例的源字符串、所有写入者或自然到达。

上述1200场景采用该实际实体表地址。在第一次成功后的改名步骤中，另有**432次真实5039已解析索引复制尾段**，执行命令+8加载、原地址缩放及原生strcpy，再运行迭代／缓存刷新路径；比较完整受控实体记录及实际复制返回指针。索引由分析器提供，命令分派及索引解析函数未执行，不能称为完整5039命令或自然剧情验收。测试文本短且NUL终止，亦不认证长名字溢出、畸形命令或源缓冲区边界。

[验证摘要](issue-assets/native-text-rendering-20261021/measure-owner-verification.json)和[测试日志](issue-assets/native-text-rendering-20261021/measure-owner-tests.log)分别列明计数和界限。现阶段继续开放：5039参数解析与实际STAGE记录审计，其他命名／复制／编辑路径及调用调度，第二设置函数服务副作用，成功分支后续绘制、全局／间接写入者，以及其余测宽消费者、分页与设备行为。


## 第二十阶段：原盘5039实例、选择器2解析及坐标副作用

上一轮已连接原生命名尾段和实际UI缓存刷新，属于实质进展。本阶段继续上溯参数解析，并扫描原盘和当前三版ISO的STAGE；只新增分析代码和证据，没有改生产补丁、工具或ISO。完整目标继续active。

### 当前查到的名字没有尺寸控制符

[源数据审计](issue-assets/native-text-rendering-20261021/name-command-source-audit.json)读取原盘／当前Original、Best各205个解码块，SP各68个块，保留每个原始5039字节命中并分类。两套Original各17处、Best各17处、SP各4处命中，全部为对齐的opcode加内部NUL字符串指针形状，没有丢弃无法解释的其他命中。对应文本全部无未知码和width／space／height等流控制；参数的高16位均为选择器2，低16位均小于8000。

当前中文使用该批次冻结构建项目的码表和别名解码，未拿日文原表解释替换后的中文码位。例如原盘“炎のＭＳ乗り”在当前ISO为“火焰MS驾驶员”。保留了可见英文。源文本、参数、原始12字节命令、实际文本指针、所在块哈希及成员哈希都保存在审计中。

这仍是完整原始字节扫描加指针／字符串形状分类，尚未证明上游脚本目录和取指流程能到达每个记录。下述执行实验从分派函数入口注入这些实际记录，也不替代自然剧情路径证明。结论只覆盖这些名字来源：不能把受控height注入产生的测宽偏移，归因为它们当前实际携带height。

当前三版ISO的完整文件SHA均重新核对，仍匹配第十六阶段批次49e4666f…；见[文件身份](issue-assets/native-text-rendering-20261021/name-audit-iso-identities.json)。

### 选择器2是120×3×6的查找，且有写入副作用

[原生函数绑定](issue-assets/native-text-rendering-20261021/name-lookup-inventory.json)和[C还原](issue-assets/native-text-rendering-20261021/name_lookup_model.c)现在包含选择器2查找、其坐标更新叶函数、选择器包装的0／2分支，以及完整分派入口中5039的直接ID分支。选择器0按原逻辑走选择器2；其他选择器与特殊参数仍未被映射成这个较窄分支。

查找依次扫描120个176字节实体，过滤实体+14低2位、可选+25分类条件、+24字节条件和+16的bit6。每个实体按3个成员指针、每成员6个槽位搜索，读取槽位定义中的16位ID与目标比较；可选标志再排除槽位+40的bit0。返回第一个符合条件的实体索引。

输入上下文非空时，函数入口先清+2F90／+2F94／+2F98；匹配后分别写实体、匹配槽位、成员指针。不匹配返回-1，这些输出保持已清零；上下文为空则不写这些输出。

匹配还可能改变实体坐标：若成员定义+30的bit2未置、实体+68的有符号父索引非负，则将父实体+6C／+6D复制到当前实体，并调用原生坐标更新函数。它把两个负的有符号坐标字节清0，再生成三个浮点字段：X为0.5×x，Z为-0.5×y，Y为地图高度有符号字节×0.25减浮点常量3AC49BA6。高度地址由地图指针+y×352+x×8取得；这里没有把行步长推断为完整地图维度。

本阶段实际执行这条副作用路径，未跳过坐标函数或仅对照查询返回值。父索引／指针及地图区域使用受控有效映射，未证明坏指针、越界父索引或任意名字长度安全。

### 包装函数的一个不成立条件按原样保留

原指令取`options & 100`后与1比较，结果只能是0或256，因此无法设置它试图产生的bit1。对包装0／2分支，实际传入查找的标志等价于`options & 0D`。此为原生控制流事实，不在本阶段“修正”。已对两个模式各1024种低10位选项逐版执行，包含隐藏对象、成员标志、空上下文等状态；选择器1／3和它们的查找函数仍未完成。

### 完整5039直接ID分支已从真实分派入口执行

原函数从命令首字读取操作码，减5000、做71项范围检查、跳转到5039处理块，执行选择器包装／真实查找／真实坐标函数／真实strcpy，再经其原生汇合和尾声返回。所有原盘和当前ISO提取记录都保留原始命令指针、文本指针及字节，针对受控运行对象图执行，没有预先提供查找结果。

Original／Best分派函数帧为200字节（十六进制），SP为210；这是从每版入口及其实际返回边绑定的差异，不能通过单一固定偏移猜测尾声。其余保存／恢复字段按原字节核对。

本轮[13000组主对照](issue-assets/native-text-rendering-20261021/name-lookup-execution.json)包括6768组直接查找、6144组包装0／2分支、88组完整5039分派。其中76组使用上述ISO提取记录（38组原盘、38组当前文本），其余验证模式0别名、模式2及查找失败。位置矩阵覆盖全部120个实体位置、3个成员位置和6个槽位位置。比较完整实体表、上下文、成员／定义／槽位区、源命令和文本区、返回值；5039成功另逐字节确认目的名字与ISO／fixture源字节及NUL一致。

另有1536组坐标叶函数对照：每版覆盖256组坐标输入对（x与255-x），并覆盖256种有符号地图高度字节。浮点字段按原始位比较，包含负零，直接执行Unicorn支持的原生COP1指令；不是用浮点结果桩替换代码。其证明范围为这些有限binary32数据和声明的EE整数适配，不包含任意FCSR状态、NaN／非正规数、EE通用浮点精度或真机时序。

见[计数和界限摘要](issue-assets/native-text-rendering-20261021/name-lookup-verification.json)、[测试日志](issue-assets/native-text-rendering-20261021/name-lookup-tests.log)。本阶段没有LRPS2新画面，不将指令实验称为图形验收。

后续仍须还原：5039选择器80批量搜索、选择器1／3及特殊8000..80FF参数转换；上游脚本记录目录与取指可达性；其他命名生产者和完整更新调度；其余测宽结果消费者、格式化／替换写入、分页、资源控制兼容和完整帧／设备行为。当前已扫描的无控制符名字流，不构成全程序控制符兼容性证明。

## 第二十一阶段：先解决英文高度和下缘突出

用户要求把工作重点收回英文高度及下方突出。本阶段停止扩展姓名／VM外围反编译，直接做 LRPS2 候选对照。完整反编译目标仍未完成。

在四个独立、只用于角色正文的 Original 测试 ISO 上对比 height13/Y−1、height14/Y−2、height13/Y0、height13/Y−2；生产基线为 height14/Y−1。测试候选直接修改原生字高解码和 record Y 生成指令，均从 ISO 冷启动，不依赖运行中代码 poke。候选的 height13 解码实验会影响8A，故明确不用于机体或发布；最终工具改为生成正常、已经支持的8D参数，原生补丁不变。

实际结果支持 **height13、record Y−1**：

- height13/Y0 的 G 下缘比相邻中文低约1像素，Geo低约2像素，不能只降低高度而取消上移。
- height14/Y−2、height13/Y−2 顶部明显偏高，不能只继续向上移动。
- height13/Y−1 的 G 可见高度约20像素；Geo可见高度约20像素，下缘与相邻“圣”字相同。EFA约19像素，邻近中文约20像素，仍有字形本身及光栅化导致的约1像素差别；不宣称每个字母与每个汉字的墨迹框完全相同。
- 数字仍用原生角色字高12和Y0；“14”及“岁”样本都是20像素。宽14、推进12保持不变。

排版工具字母高度公式从 `(height*41+18)//36` 改为 `(height*13+6)//12`，角色12→13（8D），机体10→11（8B）保持不变。作用域闭合、中文恢复、原生逐行同步、数字高度及行距没有改变。原生光学补丁已支持8D/Y−1，因此本次参数收敛无需再次改写机器指令；三版构建均回读核验原生补丁字节。

三版正式重建批次 `2431e91b9a261426ae0175f1ad6ba48053075cdd9398b320a41760bca5b73e3f`。Original／Best各1568个正文字段，SP1590个，回读检查通过。LRPS2 三版分别完成莉露／亚历克斯首屏和滚动页共12张截图；三版采样字形边界一致。Original正式构建的四张目标截图与选择的独立候选逐像素相同。Original／Best临时开启DSC2可见标志以显示目标长描述，之后恢复；SP自然显示，原始存储卡哈希前后一致。本轮未重跑机体画面，不能把旧批次机体验证当作新批次运行证明。

[前后对比](issue-assets/native-text-rendering-20261021/vertical-refinement/before-after.png)、[全部候选](issue-assets/native-text-rendering-20261021/vertical-refinement/comparison.png)、[运行测量](issue-assets/native-text-rendering-20261021/vertical-refinement/runtime-verification.json)、[三版滚动页](issue-assets/native-text-rendering-20261021/vertical-refinement/scroll-review.png)、[ISO回读](issue-assets/native-text-rendering-20261021/vertical-refinement/iso-audit.json)、[构建清单](issue-assets/native-text-rendering-20261021/vertical-refinement/production-build.json)、[源码绑定](issue-assets/native-text-rendering-20261021/vertical-refinement/source-bindings.json)。

测试状态：相关39项通过；最终完整套件838项通过，1项跳过（140.399秒）。第一轮已加载旧8E断言而产生的5个预期不匹配已在最终重跑中消除。`git diff --check`通过。未commit/push。

## 第二十二阶段：英文和数字再分别缩小一档

按用户要求，将原生角色正文高度12环境中的字母从13降为12（8C，保留record Y−1），数字从12降为11（0B，Y0）。中文恢复高度仍为12，宽度／推进／行距不变，英文水平宽14和推进12不变。机体正文的11／10对保持；作品标题／姓名等其他面板未在此轮调整。可见英文、数字及标识符内容保持原样。

此次只改排版工具的独立字母／数字高度选择；现有三版原生补丁已经支持8C和普通0B字高，无需新增机器指令。三版构建批次 `8d3bb9fe035b0cd2b1cfc846ba8fc2da34691eba86e20aeb09699a0ff4ba747c`；回读核验Original／Best各1568、SP1590个正文字段，作用域闭合和中文恢复通过。

LRPS2分别冷启动三版，复查莉露／亚历克斯首屏和滚动页共12张截图。采样G、Geo及数字可见高度约18像素，之前约20像素；EFA约18像素，之前约19像素。中文样本仍约19–21像素，三版采样边界一致。英文下缘未突出，当前视觉效果是英数字比中文略小；不把此样本结论推广到全部字形、机体页或作品标题。Original／Best为显示目标长描述临时修改DSC2可见标志后恢复，SP自然显示；原始存储卡哈希前后一致。

[缩小前后对比](issue-assets/native-text-rendering-20261021/smaller-body/before-after.png)、[运行测量](issue-assets/native-text-rendering-20261021/smaller-body/runtime-verification.json)、[首屏及滚动截图](issue-assets/native-text-rendering-20261021/smaller-body/final/)、[ISO回读](issue-assets/native-text-rendering-20261021/smaller-body/iso-audit.json)、[构建清单](issue-assets/native-text-rendering-20261021/smaller-body/production-build.json)、[源码绑定](issue-assets/native-text-rendering-20261021/smaller-body/source-bindings.json)。

相关39项测试通过；完整838项测试通过，1项跳过（146.094秒）。`git diff --check`通过。未commit/push。完整原生文本反编译目标仍未完成。

## 第二十三阶段：控制协议与后续排版入口全量检查

本阶段不继续扩展外围反编译，而是落实[控制与排版交接](TEXT_CONTROL_AND_LAYOUT_HANDOFF_20261021.md)中的现行工具检查。新增共享`control_layout.py`，让单元格和像素路径使用完整控制token及同一预算；补齐`@N`重复流、末位NUL无损记法及数值方括号协议的字节保护；动态tm／@／方括号参数禁止误进静态重排。保留原生measure的已知差异，未新增MIPS修改。

全量检查涵盖发布配置指定翻译映射：154,706字段、91种具体控制写法，0失败／0未知语法；1,398条长文本预览无失败。角色／机体预览改用真实生产字号编译器，旧写回入口拒绝把生成的height作用域灌入作者语料。流程保词补“古恩”，仅本篇overview:014、SP synopsis/002调整物理换行，文字、控制顺序及行数预算保持。

三版批次`89b22f798773b433d61f651491f019d3add2e5f28fbc5a4d30e995a479bc33f4`重建并回读4,726个图鉴字段；SP独立检查33文案／69原生控制。LRPS2三版两人物12张新截图与第二十二阶段逐像素相同；SP自然武器提示、三角打开驾驶员报告及叉返回另已到达。完整套件共843项，842通过、1项跳过。详见[全量处理结果](TEXT_CONTROL_LAYOUT_AUDIT_20261021.md)及[收据](issue-assets/control-layout-audit-20261021/receipt.json)。动态展开精确宽度、全部原生消费者及完整反编译仍未完成。


## 第二十四阶段：无需新height标签的紧缩数字记录与剧情排查

梗概013实测为14×10，邻近中文16×10；问题来自横向紧缩未联动高度以及源字形比例，而非本例数字绘制高度大于中文。生产解析器增加紧缩数字H−1、显式height优先，并按原范围／标志等价重排分类选择区容纳辅助检查。三版15,360组差分、源字形样本、三版自然梗概、人物回归和剧情扫描见[专题记录](COMPACT_DIGIT_HEIGHT_AND_STORY_AUDIT_20261021.md)。新增方案不改测宽器，不新增控制参数，不把全量剧情／分页／GS时序等未完成要求标为完成。
