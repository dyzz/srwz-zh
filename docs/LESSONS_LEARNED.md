# LESSONS_LEARNED — 错误路径目录

这份文档沿用参考项目的事故记录方法：不是罗列最终结论，而是记录一个看似合理
的判断怎样被证据推翻，以及哪一道自动门防止它复发。新增条目必须对应真实实验、
失败产物或运行证据；规划中的风险不写成“已学到的教训”。

条目格式：

> **曾以为** → **为什么看似合理** → **如何被推翻** → **事实** → **守门**

---

## A. 压缩和游戏运行语法

### A1. Clean-room round-trip 通过，不等于游戏解压器可运行

- **曾以为：** 只要 `decode(encode(data)) == data`，新 VT1 压缩流就可由游戏
  使用。
- **为什么看似合理：** clean-room 解码器能够严格解出候选流，解码内容和目标
  字库完全一致；旧候选的压缩尺寸变化也提供了一个看似合理的 32 MiB 边界解释。
- **如何被推翻：** PCSX2 在游戏解压器 `0x001C6DE8` 发生 TLB miss；块统计发现
  旧流 175,385 个 block 中有 139,993 个 zero-literal block，第一个位于输入
  offset 48、输出 offset 576。
- **事实：** 游戏 literal/match copy 是 post-tested loop。literal count 为
  0 会先减成 `0xFFFFFFFF` 再失控复制；这是游戏运行语法约束，不是普通
  round-trip 属性。
- **守门：** `tools/srwz/codec.py` 拒绝 zero-literal 和未结束输出前的
  zero-match；单元测试固定故障；greedy 构建还必须通过游戏内完整 decoded-font
  SHA-256。

### A2. 能表达 extended distance，不等于使用了最短表示

- **曾以为：** distance 大于 8 时把 token seed 写成 0，再写完整 coded integer，
  已经是合法且足够接近原版的编码。
- **为什么看似合理：** strict decoder 能完整回解，按钮子集也能在 71 sectors
  内启动；继续增加 match chain 看起来才是压缩率优化方向。
- **如何被推翻：** DLL CIL 显示最高 7-bit 组小于 8 时会放入三 bit seed；原版
  COMPDATA 的 12,521 个合格 token 全部这样编码。旧完整 P0 后缀有 1,796 个
  合格 token 把 seed 写成 0，逐个多占 1 byte。
- **事实：** coded integer 的 seed 是压缩决策的一部分。原始后缀 1,930-byte
  差距中，compact seed 单独收回 1,808 bytes；完整 P0 从 147,050 降至
  145,237，恢复 71-sector 原位布局。
- **守门：** `greedy` 保持旧字节行为；`size-constrained` 用真实序列化成本和
  compact seed，并以 `max_output_size=145408` 失败关闭。真实流 manifest
  固定 missed-seed 数、cost 总和、71-sector gate 和 PCSX2/PINE 0 TLB。

## B. ISO 容器和模拟器判定

### B1. 成员内容正确，不等于 PS2 DVD 镜像正确

- **曾以为：** 只要重建 ISO 中 66 个成员可读、替换成员哈希正确，通用
  `mkisofs` 输出就可用于 PCSX2。
- **为什么看似合理：** ISO9660/UDF 目录和成员内容都能被静态工具读取，文件级
  diff 没有发现错误。
- **如何被推翻：** PCSX2 v2.6.3 把该镜像识别为 CD，随后错误读取扇区并产生
  宿主崩溃；输出根目录 data length 为 2048，而原盘为 960。
- **事实：** PS2 容器验收包含介质类型、目录形态、成员顺序/LBA、UDF 识别和
  模拟器判定，不能退化为“文件能打开”。
- **守门：** 正式后端固定为 `mkps2iso v1.1.1`；构建器独立验证 66 个成员、
  ISO9660/UDF、根目录 960、DVD 判定、LBA shift 和整镜像 SHA-256；`mkisofs`
  不再是发布后端。

### B2. 归档总长度可容纳，不等于可以移动后续成员 LBA

- **曾以为：** VT1 字库扩展后，只要 ISO 能容纳增长量、成员哈希和目录都正确，
  就可以把后续 `STAGE.BIN` 顺延。
- **为什么看似合理：** `mkps2iso` 重建出的 UDF/ISO9660 完整，字体和剧情压缩流
  都能被 clean-room 解码器往返；顺移版本也保持整镜像大小不变。
- **如何被推翻：** 带原版 HB/STAGE、只把 VT1 扩大并令 STAGE 后移 86 sector
  的控制镜像，仍在 `pc=0x0019DD94` 访问 `0x02000000` 时 TLB miss；同一份
  大字库在 VT1 总长和后续 LBA 恢复原值后可以进入第一关并显示中文。
- **事实：** 本游戏至少有读取路径依赖原盘的后续文件物理 LBA，目录记录正确
  不能替代原位置。当前 first-five profile 必须保持所有成员 LBA 不变。
- **守门：** 字体增长只借用 VT1 前一 chunk 已验证的 175,968-byte 全零尾部，
  VT1 总长保持 127,500,736；前五关 STAGE 使用 lazy greedy suffix 压缩并落在
  原扇区间隙内；ISO 清单要求 `shifted_member_count=0`、`shift_sectors=0`，
  最终还要在 PCSX2 中通过无 TLB 的第一关可见文本验证。

## C. 字库和码位分配

### C1. 空白 glyph 和未引用 code 只是候选，不是安全槽位

- **曾以为：** 原版字形为空、且固定码表/语料没有引用的 code，可以直接当作
  中文容量。
- **为什么看似合理：** 静态扫描得到连续空白 glyph，94,189 条已解析语料没有
  对应 token，码表也没有冲突。
- **如何被推翻：** 静态结果只能说明当前样本没有已知引用；它不能证明所有
  renderer 分支、动态构造文本、存档或未覆盖流程都不会使用这些位置。
- **事实：** “公式可寻址候选”“已分配”“在某个 surface 运行验证”是三种
  不同状态。当前 `987E/987F` 只批准给开场菜单的 `测/试`；P1 可以依据锁定
  指令窗口生成 raw-trail 离线候选，但不能把一次 `987F` 运行成功外推成
  `0xFD/0xFE/0xFF` 或整张组件的安全结论。
- **守门：** `config/encoding/codebook.json` 是唯一分配账本；BuildProfile
  只能选择显式 `assigned` 项；code/glyph/raster/owner 全部固定，冲突扫描、
  运行内存哈希和 surface 截图分别保留。

### C2. 缺字集合排序不是稳定的码位分配

- **曾以为：** 每次按当前译文缺字排序，再顺序填入候选槽位，可以得到确定性
  codebook。
- **为什么看似合理：** 同一份语料重复构建时顺序稳定，所有字符也都能编码，
  单次字体和 STAGE 往返检查均会通过。
- **如何被推翻：** 删除两个旧字并新增一个字后，排序位置改变，后续数百个字符
  全部换码；STAGE 压缩结果因此增长一个 sector，ISO 后续成员 LBA 随之漂移。
- **事实：** 确定性排序只保证“同输入同输出”，不保证版本间码位稳定。已经
  发布到文本或存档里的字符编码必须具有持续身份。
- **守门：** `config/encoding/first-five-allocations.json` 采用追加式账本；
  退役字符保留槽位，新字符只追加，proposal、字体构建和 STAGE 构建都验证账本
  SHA-256。

### C3. “码表能编码”和单字节可打印都不是 renderer 契约

- **曾以为：** 固定表里存在字符即可直接写入；普通 ASCII 也能按单字节原样
  输出。
- **为什么看似合理：** clean-room 文本解码器可以把这些字节还原为同样文本，
  最终 ISO 回读也不会报告未知码。
- **如何被推翻：** 运行截图中“隶、仗、估、儿”等字符留空；`10` 的 `0x30`
  又进入游戏控制语法，使“我在10天前到任”的后半句错位。静态反查确认 121 个
  固定表 code 不在 renderer 扩展表，普通 ASCII 则与控制字节空间重叠。
- **事实：** 文本 codec、renderer code→glyph 和控制语法是三份不同契约。
  最终文本相等不能证明画面可达。
- **守门：** 前五关所有普通 ASCII 和 121 个 table-only 字符都使用显式双字节
  override；`$n/$F` 在编码器中先于 override 识别并保留；覆盖审计要求不可达
  glyph、普通单字节 ASCII 和混合汉字来源同时为 0。

### C4. 沿用日文行数不是中文布局

- **曾以为：** 逐条保持日文原文的换行数量，可以避免文本框溢出并保留演出节奏。
- **为什么看似合理：** 每条译文最多三行，旧的 26 字符长度检查也全部通过。
- **如何被推翻：** PCSX2 画面出现大量不必要的短行；去掉行数耦合后，第一版
  自动平衡又把“我们、开发、刚才、兵器、项目”等中文词拆开。
- **事实：** 日文换行只能作为可选语义提示，不能决定中文行数。合格布局必须
  同时考虑中文标点、词语边界、专名、运行时玩家名展开宽度和文本框容量。
- **守门：** `reflow_first_five_dialogue.py` 按 24 glyph cell、最多 3 行生成；
  `$n/$F` 预算 6 格，术语、标题、ASCII 词组及已审出的常用词不可拆分，闭标点
  和语气助词不得落在续行开头。检查模式必须零改动；语言审计再次独立验证宽度、
  行数和禁则。前五关由 3,124 行降为 2,160 行，系统中文分词辅助审查为
  0 个词内断行。

## D. 工程事实源

### D1. 验证成功的临时 canary 不能继续承担生产数据职责

- **曾以为：** 把 `glyphs`、`source_text`、`replacement_text` 和 offsets 放在
  一个 canary JSON 中，最容易保住已验证结果。
- **为什么看似合理：** 两字纵向切片很小，单文件可直接驱动 writer，也已经有
  输出 SHA-256 和运行截图。
- **如何被推翻：** 同一 entry 的地址、译文和字形分配开始分别出现在构建器、
  PINE 验证器、manifest 和文档；扩大到第二个 surface 会形成多个可修改事实源。
- **事实：** canary 是 golden 和验收夹具，不是语料库或 layout registry。
  生产含义应由 SurfaceSpec、`corpus/zh`、codebook 和 BuildProfile 分工持有。
- **守门：** canary 配置已移除 `glyphs` 和 `text_patch`；静态 writer 与 PINE
  都调用 `load_build_profile()`；单元测试明确拒绝事实源回流，并验证新链生成
  与 E0 完全相同的 SLPS、VT1 和预览 SHA-256。

## E. 图片索引和渲染

### E1. PNG8 默认抖动会破坏源 index 到 RGBA 的一对一关系

- **曾以为：** ImageMagick 读取 indexed TIM2 后直接输出 `PNG8:`，同一个
  palette index 在整张图中自然会得到同一个 RGBA。
- **为什么看似合理：** chunk 2、4、6 的灰阶 CLUT 都满足该假设，定位
  canary 能 byte-exact 回写。
- **如何被推翻：** chunk 7 的轻微色偏 CLUT 触发默认 palette dithering；
  同一个源 index 4 被量化成多个灰度，严格 writer 在 `(22,30)` 主动拒绝。
- **事实：** PNG8 颜色量化是渲染步骤，不是源 TIM2 索引事实；抖动后的 RGBA
  不能作为可逆索引映射。
- **守门：** `render_tim2_png8()` 强制传入 `+dither`；单元测试固定命令，
  原三项 profile 必须保持全部输出锁不变，chunk 7 还必须证明 16 个源 index
  各自只有一个展开 RGBA 后才允许写回。
