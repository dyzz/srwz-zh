# 给 AI 的实施说明：向本篇 VT1 增加 XAN 头像资源

日期：2026-10-06。项目根目录：`/Users/nate/Super-Robot-Wars-Z/srwz-zh`。

本文仅描述 **VT1 图片资源新增及其配套索引**。压缩处理方案已另外提供，不在本文重复。当前尚未实施资源写入；以下是实施输入与验收契约。

用户最新截图确认缺的是完整战斗动画左下角的小头像，已静态确认该框走 VT1 小头像加载链。转交时优先阅读 [战斗小头像 ELF 绑定说明](VT1_XAN_SMALL_PORTRAIT_BINDING_20261006.md)。当前修复只需要小头像及其绑定；本格式文档中的半身像部分作为其他场景的资源说明保留。

## 1. 任务范围

向本篇的 `DATA/VT1.BIN` 增加两条候选资源：XAN 战场小头像、XAN 剧情半身像。保留所有已有图片 ID，使已有记录解压后的完整数据保持不变。

需要交付两个配套文件：

1. 新的 `DATA/VT1.BIN`：各自头像组内增加一条完整压缩资源记录。
2. 对应版本的主程序：更新两组的成员偏移表，使新增记录可被图片 ID 定位。

本次不增加人物、机体或剧情内容；不修改人物／表情映射表，不分配人物视觉 ID，也不修改剧情、战场或菜单调用。新增资源能被定位，不等于游戏已经会显示 XAN。

## 2. 已核对的版本与记录编号

当前输入镜像：

- Original：`build/iso/zh-release-original/current-original.iso`，主程序 `SLPS_258.87`。
- BEST：`build/iso/zh-release-best/current-best.iso`，主程序 `SLPS_732.70`。

本次读回的两版 VT1 字节完全相同：大小 **127,500,736 字节**，SHA-256：

```text
bb43ed66fc32ee6cc7f0244e706c54ed245c53631258fae8cdb9e5b82ed17fd5
```

这是日期快照。开始实施时必须重新读取实际输入，核对大小、哈希与偏移表；不要仅依赖文件名。主程序版本和哈希见 [snapshot.json](issue-assets/vt1-xan-resource-plan-20261006/snapshot.json)。

以下分组、图片 ID 均从 **0** 开始。两个头像组独立编号，VT1 没有统一的“最后图片 ID”。

| 类型 | 本篇 VT1 分组 | 现有记录数 N | 现有最后图片 ID | 计划新增图片 ID |
| --- | ---: | ---: | ---: | ---: |
| 战场小头像 | 10 | 1742 | 1741 / `0x06CD` | **1742 / `0x06CE`** |
| 剧情半身像 | 11 | 2516 | 2515 / `0x09D3` | **2516 / `0x09D4`** |

不挪用已有记录 ID，包括具有保留／回退含义的 0、1。

## 3. SP 候选源资源

从 SP 原始镜像提取完整记录，不以网站导出的 PNG 作为写回事实源。SP 原盘来源及成员哈希锁见 `config/products/special-disc/disc-inventory.json`，读取入口为 `tools/special_disc/export/export_sd_text.py` 中的 `Disc.original()`。

| 类型 | SP VT1 分组 | SP 图片 ID | 原压缩记录字节数 | 解压后字节数 |
| --- | ---: | ---: | ---: | ---: |
| 战场小头像 | 12 | 1094 | 13,117 | 16,896 |
| 剧情半身像 | 13 | 1550 | 83,491 | 262,672 |

SP 主程序 `SLPS_259.20` 的 VT1 外层表位于文件偏移 `0x353790`，小头像成员偏移表位于 `0x368910`，半身像成员偏移表位于 `0x36A470`。

这些记录来自 SP 中名为 `ＸＡＮ` 的对白事件及人物视觉 ID 553 的映射：小头像表情 0 指向 1094，半身像表情 0 指向 1550。

**视觉正确性仍待核验。** 用户认为当前导出头像的外观不太对。目前只确认重新从原盘导出的 PNG 与原有导出文件相同，尚未完成游戏内画面对照；这不能排除像素排列或调色板解释有误。对外表述应为“XAN 候选资源／原盘映射对应记录”，不能声称已经完成视觉验收。

另外，SP 的人物视觉 ID 553 在本篇对应薇拉。本文的新增图片 ID 与人物视觉 ID 是不同编号空间；不得把 SP 的 553 写入本篇人物映射。

## 4. 加入 VT1 的数据是什么

每条新增记录是完整的 SRWZ 压缩流。解压后结构如下：

| 类型 | 前部调色板 | 像素区域 | 尾部 |
| --- | --- | --- | --- |
| 小头像 | `0x200` 字节，256 色 PSMCT16 | `0x4000` 字节，128×128 PSMT8 | 无 |
| 半身像 | `0x200` 字节，256 色 PSMCT16 | `0x40000` 字节，512×512 PSMT8 | `0x10` 字节，保留原数据 |

这两条解压记录没有 `TIM2` 文件头。像素数据保持 PS2 原生 swizzle 排列，调色板保持原生 CSM1 存储顺序。直接移植原始记录或对其完整解压数据重新压缩时，不需要把它们转换成 PNG 再写回。

**禁止把裁剪后的导出图当成原生纹理。** 当前半身像 PNG 是从原生 512×512 画布裁剪得到，裁剪框为 `[0, 180, 512, 512]`。写回必须保留完整原生画布、调色板及 16 字节尾部。格式实测见 [xan-format-proof.json](issue-assets/vt1-xan-resource-plan-20261006/xan-format-proof.json)。

### 4.1 VT1 文件格式

`VT1.BIN` 是混合资源档案，包含头像、字体、音频和部分菜单资源。不要把整个文件当成一个 TIM2，也不要把所有分组当成同一种图片结构。以下仅适用于本文的两个头像组。

VT1 文件起点不是可自描述的头像目录。头像定位需要读取对应主程序中的两级偏移表；主程序版本与 VT1 必须配对。

```text
主程序：VT1 外层偏移表（小端 uint32）
    ↓ 取 group_start、group_end
VT1.BIN：某个头像组的字节区间
    ↓ 主程序：该组的成员偏移表（小端 uint32，组内相对偏移）
第 i 条记录：VT1[group_start + offsets[i] : group_start + offsets[i+1]]
    ↓ 使用已有的 SRWZ 解码器
完整解压数据：原生 CLUT + 原生像素 + 可选尾部数据
```

成员表是 N+1 个偏移对应 N 条记录，末尾项是结束偏移，不是额外图片。记录区间之后、外层分组终点之前可以存在分组尾部填充；它不属于最后一张图片。记录自身也可能有压缩流结束后的填充，提取时应分别记录“分配记录长度”和“解码器 consumed 长度”。

图片名称、尺寸、记录数和人物 ID 不以通用图像文件头形式写在这些头像记录内。提取器从版本／分组参数得知尺寸与记录数；不能按 `TIM2` 标识扫描获得完整头像清单。

### 4.2 原生图片格式与偏移

下表的偏移相对于**解压后记录起点**，采用左闭右开区间：

| 内容 | 128×128 小头像 | 512×512 半身像 |
| --- | --- | --- |
| 256 色 CLUT | `[0x00000, 0x00200)` | `[0x00000, 0x00200)` |
| 原生 PSMT8 像素 | `[0x00200, 0x04200)` | `[0x00200, 0x40200)` |
| 原生尾部数据 | 无 | `[0x40200, 0x40210)` |
| 完整解压记录长度 | `0x4200` / 16,896 | `0x40210` / 262,672 |

像素值是 0–255 的调色板索引，不是灰度或 RGB。CLUT 有 256 个小端 16 位颜色值。当前解析使用 PSMCT16 的 R5/G5/B5 分量：R 位 0–4、G 位 5–9、B 位 10–14；导出时每个分量左移 3 位。透明度使用当前游戏特定的 TEXA/AEM 解释：颜色字为 0 时透明，其余为不透明。不能直接套用普通 ARGB1555 的最高位透明规则；该显示解释仍须游戏内画面对照。

从逻辑颜色索引 i 定位到 CSM1 存储槽位的公式为：

```python
stored_palette_index = (i & 0xE7) | ((i & 0x08) << 1) | ((i & 0x10) >> 1)
```

像素必须按 PS2 GS PSMT8 swizzle 规则还原为逐行索引，不能只把原始像素块按宽度 reshape。仓库已有 `tools/srwz/tim2_writeback.py::unswizzle_psmt8()`。导出 PNG 的像素和 CLUT 经过上述还原；写回的 `.psmt8.bin` 与 `.clut.bin` 则保留原生存储顺序。

## 5. VT1 与主程序索引的修改关系

VT1 内的图片记录不自带独立 ID 字段，主程序成员偏移表的下标就是图片 ID。偏移表不在 VT1 文件里。

| 主程序文件偏移 | Original | BEST |
| --- | --- | --- |
| VT1 外层分组偏移表 | `0x2FA100` | `0x2FA880` |
| 小头像成员偏移表 | `0x30E8F0` | `0x30F070` |
| 半身像成员偏移表 | `0x310430` | `0x310BB0` |

外层偏移是相对于 VT1 文件起点的偏移；成员偏移是相对于其头像组起点的偏移。表项为小端 `uint32`。

对于原有 N 条记录，成员表包含 N+1 个偏移：

```text
记录 i 的绝对起点 = group_start + offsets[i]
记录 i 的绝对终点 = group_start + offsets[i + 1]
```

处理完成后，在原来的记录顺序末尾增加一条记录：

```text
原有：记录 0 … N-1，偏移 offsets[0 … N]
新增：记录 0 … N，  偏移 offsets[0 … N+1]
                         新图片 ID = N
```

已有记录的压缩长度若变化，需要重新计算组内所有成员偏移；不只是在旧表后追加一个数。原来的末尾偏移项会成为新记录的起点，新增末尾项是新记录的终点。

本次在原有成员表后观察到零填充，可作为增加表项的候选区域：

| 类型 | Original 原表末尾之后 | BEST 原表末尾之后 | 已观察连续零字节 |
| --- | --- | --- | ---: |
| 小头像 | `0x31042C` | `0x310BAC` | 8 |
| 半身像 | `0x312B84` | `0x313304` | 12 |

新增一条记录需增加一个 4 字节偏移项。写入前必须再次检查该区域的前像，并确认它是可使用的填充、没有其他引用；同时审计加载代码有无固定记录数或最大 ID 限制。**“此处为零”本身不能证明新增 ID 已可被加载器接受。** 若加载器还需修改，先明确该资源层限制和所需补丁，不能悄悄扩大本次范围。

## 6. 文件与边界契约

- 保持 VT1 总大小为实际输入大小；本次快照为 127,500,736 字节。
- 保持两个头像组的外层起止偏移。只在组内重排记录及尾部填充，不从其他分组借空间。
- 保持所有非头像分组逐字节不变，包括字体、音频、菜单等资源。
- 保持所有已有图片 ID，已有记录完整解压数据逐字节不变。
- 新增记录完整解压数据与锁定的 SP 候选源记录逐字节相同。
- 新成员表覆盖的记录区间不得重叠、越界；新增记录终点不得超过原头像组终点。
- 主程序仅修改本任务所需的成员偏移表及经确认可用的新增表项；人物／表情映射等区域保持不变。
- 若生成候选 ISO，保持 VT1 与所有后续成员的原 LBA、扇区预算和其他成员数据。

## 7. 交付与验收

先输出独立候选资源和对应主程序，不覆盖当前生产镜像或冻结发布。

配套报告至少包含：输入镜像／成员身份，候选成员哈希，新旧分组边界，新旧成员偏移表，新增图片 ID，新增记录的压缩及解压大小，主程序修改范围，以及已有记录与非目标分组的完整性验证。

静态验收必须确认：

1. 每条已有记录解压后的完整数据与输入相同。
2. 两条新增记录解压后的完整数据与 SP 候选源相同。
3. 通过新增图片 ID 从候选 VT1 读回的就是相应新增记录。
4. 表项扩展的前像及加载器数量限制已核对。
5. 文件大小、分组边界、非目标字节和版本对应关系全部符合契约。

资源静态验证、ISO 独立读回与游戏内视觉／运行验证须分别记录。正式生产接入前，仍需 PCSX2／人工证据确认新增资源实际显示正确，并复查新游戏及旧存档进入 STAGE；本篇暂未接入调用时，测试调用方案另列，不能把“尚未显示”写成“显示通过”。

## 8. Extract：直接可运行的头像提取器

附带脚本：[tools/extract_vt1_portraits.py](../tools/extract_vt1_portraits.py)。这是只读提取器，支持 Original、BEST、SP；可以从 ISO 读取成员，也可以读取已经导出的主程序及 VT1 文件。脚本不依赖同级网页项目，也不需要 Pillow。运行环境是本仓库 Python + 已构建的仓库 Rust codec；压缩／解压工具的既有准备方式沿用对方已有说明。

在项目根目录运行，使用新的输出目录。先提取两条 SP 候选资源：

```sh
python3 tools/extract_vt1_portraits.py \
  --edition sp \
  --iso 'rom/Super Robot Taisen Z - Special Disc [J].iso' \
  --kind battle --record 1094 \
  --output work/analysis/xan-extract/sp-battle

python3 tools/extract_vt1_portraits.py \
  --edition sp \
  --iso 'rom/Super Robot Taisen Z - Special Disc [J].iso' \
  --kind story --record 1550 --crop-preview \
  --output work/analysis/xan-extract/sp-story
```

提取当前本篇最后一条记录，核对版本／ID 定位：

```sh
python3 tools/extract_vt1_portraits.py \
  --edition original \
  --iso build/iso/zh-release-original/current-original.iso \
  --kind battle --record 1741 \
  --output work/analysis/xan-extract/original-last-battle

python3 tools/extract_vt1_portraits.py \
  --edition best \
  --iso build/iso/zh-release-best/current-best.iso \
  --kind story --record 2515 \
  --output work/analysis/xan-extract/best-last-story
```

也可以使用已导出的原生成员文件：

```sh
python3 tools/extract_vt1_portraits.py \
  --edition original \
  --exe work/disc/SLPS_258.87 --vt1 work/disc/DATA/VT1.BIN \
  --kind story --record 2515 \
  --output work/analysis/xan-extract/original-native-last-story
```

同一组可使用 `--record 2 100 0x6CD` 提取多个 ID；`--all` 提取所有实际图片记录，跳过保留记录 0、1。`--record` 与 `--all` 二选一。原有输出文件不会被覆盖，重复执行请换新输出目录。

若候选主程序已扩展成员表，新建记录的读回例子是：

```sh
python3 tools/extract_vt1_portraits.py \
  --edition original \
  --exe /path/to/candidate/SLPS_258.87 \
  --vt1 /path/to/candidate/DATA/VT1.BIN \
  --kind battle --record-count 1743 --record 1742 \
  --output /path/to/candidate/readback/battle-1742
```

这里的候选路径是占位符，换成实际文件。半身像新增记录对应 `--kind story --record-count 2517 --record 2516`。`--record-count` 用来告诉提取器候选成员表的实际记录数量，本身不会修改文件，也不能证明游戏加载器接受新 ID。

每张图的输出含义：

| 输出 | 内容及用途 |
| --- | --- |
| `battle-1094.stored.bin` 等 | 从成员偏移区间原样取出的完整记录，含任何分配区间填充 |
| `*.decoded.bin` | 完整解压数据，含 CLUT、原生像素及半身像尾部；写回／比对事实源 |
| `*.clut.bin` | 512 字节原生 CLUT，保留 PSMCT16/CSM1 存储顺序 |
| `*.psmt8.bin` | 原生 swizzled 索引像素，无 CLUT、无图像头 |
| `*.png` | 未裁剪的完整原生尺寸 PNG：128×128 或 512×512，8 位索引色、256 色 PLTE、tRNS 透明表 |
| `*.preview.png` | 仅指定 `--crop-preview` 时输出的独立预览图；不能代替原生记录 |
| `manifest.json` | 输入成员哈希、版本与分组、表位置、记录偏移、压缩流 consumed、解压数据哈希、输出文件哈希和裁剪框 |

提取成功表示数据定位和当前解码规则可以运行。manifest 明确保留 `visual_validation = not_verified_in_game`；导出器不是游戏内视觉验证器。

已用 SP 的两条候选记录、当前 Original 的末尾小头像、当前 BEST 的末尾半身像、原版原生成员的末尾半身像验证，共 5 个实际提取案例。校验包含源记录解压回读、输出哈希、原生 CLUT／像素切片、未裁剪 PNG 尺寸，以及保留 ID／错误版本／已有输出的失败处理。SP 小头像 PNG 与原有导出逐字节一致，SP 半身像裁剪预览也与原有导出逐字节一致。验证报告见 [extract-validation.json](issue-assets/vt1-xan-resource-plan-20261006/extract-validation.json)。这些结果仍不代表游戏内视觉验收。

## 9. 参考代码

- `srwz-community-web/scripts/special_disc_portraits.py`：SP 两组头像的参数、映射和提取定位；此文件位于项目根目录的同级网页项目中。
- `srwz-community-web/scripts/extract_vt1_portraits.py`：本篇参数、原生头像数据解析及 PNG 导出；同上。
- `tools/special_disc/export/export_sd_text.py`：SP 原盘成员身份检查及 VT1 外层表读取。
- `tools/srwz/best_build.py`、`config/editions/best/source-layout.json`：Original 与 BEST 的版本映射契约。

当前结论：**VT1 层面增加两条完整图片记录，同时配套更新对应版本主程序的成员偏移表；人物映射与显示调用留给后续独立任务。**
