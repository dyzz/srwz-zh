# 当前贴图汉化修改总表

本文记录截至 2026-08-09、当前 `zh-release-full-story` 生产链中所有会改变字形或
图片像素的写回。它是定位索引，不替代各格式的详细实现文档：

- `FONT_ANALYSIS.md`：VT1 动态字库；
- `KVMDATA_ATLAS_LOCALIZATION.md`：KVMDATA 固定 UI 图集；
- `VEFF2DX_TEXTURE_LOCALIZATION.md`：VEFF2DX 场景材质与动画 quad。

当前真正发生栅格变化的 ISO 成员共有四个：

| ISO 成员 | 当前修改 | 最终组件 SHA-256 | v0.1.0 原 LBA |
| --- | --- | --- | ---: |
| `DATA/VT1.BIN` | 标题主菜单、全局动态字库、107 张进关标题 | `90e7f0e0a1d41e6460850adb6c72b5114c8c0cfd4c2bfe28e9cc7fe9a49f4fb5` | 1,588,772 |
| `KURODATA/KVMDATA.BIN` | 6 张固定 UI 图集 | `4cf9a6c3645e36d795499622787443c539b3ad09898715244b226d9065d7eb6b` | 1,289,810 |
| `MAP/MAPMODEL.BIN` | 78 个唯一 WORLD MAP 地名标题，覆盖成员 81..195 | `234710f2d39ae70b854d6f46a5f24e94c4085713b46bf4653b30371b52349518` | 1,652,964 |
| `EFF/VEFF2DX.BIN` | 剧情选择、模式选择两块 PSMT4 材质 | `4445b2a8669861a87eb79cb4862f0c8a17841785ee5a990d70554e59f464ae10` | 1,291,582 |

`SLPS_258.87` 也必须与上述成员一起构建，但它承担的是 VT1 offset 表、关卡
selector、动画 quad 和文本位置等伴随数据，不是贴图本体。当前组件 SHA-256 为
`88ae1ca89506e17338a1a9634f5e48ca08b2546fc104948a0e6e3e21ccc89b70`，v0.1.0 LBA 为
455。

以下位置均为**成员内偏移**，不是 ISO 文件绝对偏移。区间统一采用半开区间
`[start, end)`。

## 1. DATA/VT1.BIN

### 1.1 全局动态字库

这不是 TIM2，而是游戏自己的压缩 4-bpp 字形段。

| 项目 | 当前值 |
| --- | --- |
| VT1 顶层 offset 表 | `SLPS_258.87` 文件偏移 `[0x2FA100, 0x2FA13B)` |
| 顶层 chunk | `2` |
| 当前最终组件槽位 | `DATA/VT1.BIN [0x9B6AC0, 0xA6BF60)` |
| 槽位大小 | `0xB54A0` / 742,560 bytes |
| 当前压缩流 | `0x89473` / 562,291 bytes |
| 槽尾零填充 | `0x2C02D` / 180,269 bytes |
| 解压大小 | `0x13B000` / 1,290,240 bytes |
| 字形数量 | 4,480 |
| 单字形 | `24×24`、4-bpp、288 bytes (`0x120`) |
| 像素顺序 | 线性；每字节低 nibble 为左像素，高 nibble 为右像素 |

解压后的 glyph `n` 位于 `[n × 0x120, (n + 1) × 0x120)`。当前发布快照共有
3,265 个主映射、701 个 surface-safe 别名和 1 个来源兼容映射；最终字库组件改变
3,966 个 glyph。可打印全角／半角 ASCII 的固定 renderer 身份仍按字库合同保留。

事实源和实现位置：

- 字体总配置：`config/fonts/zh-release-font.json`
- 共享栅格规则：`config/fonts/zh-font-base.json`
- Regular 字体 flavor：`config/fonts/zh-localization-font.json`
- 字符→码位→glyph 快照：`config/encoding/zh-release-font-assignments.json`
- 原版成员锁：`config/fonts/original-font-baseline.json`
- 准备与重建：`tools/prepare_zh_release_font.py`、`tools/rebuild_zh_font.py`
- VT1/SLPS 写回：`tools/build_zh_font_component.py`
- 字形格式：`tools/srwz/font.py`
- 栅格器：`tools/srwz/font_rasterizer.py`
- 静态结果：`manifests/zh-release-font-validation.json`
- 主要测试：`tests/test_zh_release_font.py`

静态 manifest 状态是
`offline_global_zh_release_font_coverage_passed_runtime_pending`。它证明字形覆盖、
压缩回读和成员大小，不等于当前精确 ISO 的完整运行时字库验收。

### 1.2 标题画面主菜单 TIM2

“开始／读取／继续／资料库”是当前 `release-base-ui` 基线继承的旧贴图写回。最终
组件继续保留这块中文材质；它不能因为历史构建配置已折叠就从当前贴图清单中省略。

| 项目 | 当前值 |
| --- | --- |
| VT1 顶层 chunk | `6` |
| stored 槽 | `DATA/VT1.BIN [0xA751B0, 0xAE7710)` |
| stored 槽大小 | `0x72560` / 468,320 bytes |
| 当前压缩流 | 463,318 bytes |
| 槽尾零填充 | 5,002 bytes |
| decoded 大小 | 2,349,392 bytes |
| TIM2 record | record 1，decoded offset `0xEF7A0`，size 792,880 bytes |
| picture | picture 0，`512×256`、8-bpp PSMT8；record 共 6 个 picture，共享 CLUT |
| 中文标签 | `START` → 开始；`LOAD` → 读取；`CONTINUE` → 继续；`LIBRARY` → 资料库 |

picture 0 的前八个 `128×32` 槽分别保存四个标签的选中和未选中状态：

| 状态 | 标签序号 | 矩形 `(x,y,w,h)` | 调色板索引 ramp |
| --- | ---: | --- | --- |
| 选中 | 0..3 | `(0,0,128,32)`、`(0,32,128,32)`、`(0,64,128,32)`、`(0,96,128,32)` | `48..63` |
| 未选中 | 0..3 | `(0,128,128,32)`、`(0,160,128,32)`、`(0,192,128,32)`、`(0,224,128,32)` | `64..79` |

每个状态的四个槽都被完整重建，合计改变 12,514 个索引像素；其他五个 picture、
TIM2 metadata 和 CLUT 保持不变。低层 8-bpp TIM2 解析／写回仍位于
`tools/srwz/tim2_writeback.py`。

当前生产链直接消费：

- `work/build/release-base-ui/components/DATA/VT1.BIN`
- `work/build/release-base-ui/components/SLPS_258.87`
- `manifests/release-base-ui-validation.json`

这条旧流程在 `release-base-ui` 合并时删除了活动 config 和高层 writer；详细前像、
mask 和构建收据仍可从 Git 中追溯：

```bash
git show 1d1a739^:config/canary/tim2-vt1-title-zh.json
git show 1d1a739^:manifests/title-menu-zh-validation.json
git show 1d1a739^:tools/srwz/title_menu.py
```

历史候选曾完成标题菜单画面验证，但当前继承的是后来定长 Rust 重压的流；旧截图
不能自动充当 v0.1.0 精确流的运行收据。

### 1.3 107 张进关标题 TIM2

进关画面的大标题不是 COMPDATA 动态文字。SLPS 根据场景记录中的 graphic selector，
从 VT1 顶层 group 8 里选择一张独立压缩 TIM2。

| 项目 | 当前值 |
| --- | --- |
| VT1 顶层 group | `8` |
| group 8 区间 | `DATA/VT1.BIN [0xAE9090, 0xBD6A50)` |
| group 8 大小 | `0xED9C0` / 973,248 bytes |
| group 8 内部 offset 表 | `SLPS_258.87` 文件偏移 `0x31BD30`，117 个 little-endian `u32` |
| 可玩标题 selector | `1..107` |
| loader 表索引 | `selector + 8`，即 `9..115` |
| 107 槽总体范围 | `DATA/VT1.BIN [0xBA8500, 0xBD6A50)` |
| 每槽解压大小 | `0x40E0` / 16,608 bytes |
| TIM2 record | 解压数据偏移 `0x20`，大小 `0x40C0` |
| picture | `512×64`、4-bpp、image size `0x4000`、32 色 CLUT |
| 像素顺序 | 线性、low-nibble-first；不是 PSMT4 swizzle |
| 字形排版 | 24px 原字形横向扩为 48px，advance 50，`y=4`，整体居中 |

第一张和最后一张当前落点为：

| 标题 | ordinal / selector / loader index | VT1 槽位 |
| --- | --- | --- |
| 太空先锋 | `0 / 1 / 9` | `[0xBA8500, 0xBA8BF0)` |
| 迈向无尽战争之环 | `106 / 107 / 115` | `[0xBD6070, 0xBD6A50)` |

用户重点检查的第 38 话标题“被安排的决战”对应 Stage Name ordinal 72、selector 73、
loader index 81，槽位为 `DATA/VT1.BIN [0xBC7BE0, 0xBC8440)`。这里的“第”“话”
不在这张 512×64 标题贴图内，也没有被标题 writer 修改。

107 张中 105 张使用完整 16 级索引。为满足各自原压缩槽预算，ordinal 70
“被昭示的明天”和 ordinal 97“你与我的身影”使用 8 级量化；尺寸、CLUT、TIM2
header 和槽边界仍保持不变。

selector 的来源不是假设的 Stage Name 顺序，而是 COMPDATA 中 204 条场景记录：

```text
decoded COMPDATA base address:  0x6D6800
scenario records address:       0x734950
decoded payload offset:         0x5E150
record count / stride:          204 / 0x30
title pointer field:            +0x00
graphic selector field:         +0x1C
```

Stage Name 共 122 项。ordinal `0..106` 拥有上述 107 张贴图；ordinal `107..115`
是 9 条路线选择动态文字，`116..121` 是 6 条内部／测试记录，它们不拥有独立进关
标题贴图。

事实源和实现位置：

- 标题译文：`corpus/zh/menu/stage-names.json`
- selector、TIM2、排版和压缩合同：
  `config/full-story-components.json` → `full_stage_titles.graphics`
- 标题文字和 selector 写回：
  `tools/build_full_story_components.py::_apply_full_stage_titles`
- 107 张图写回：
  `tools/build_full_story_components.py::_apply_full_stage_title_graphics`
- 4-bpp pack/unpack 与标题 raster：`tools/srwz/stage_title_graphics.py`
- 每张槽位、哈希和量化记录：
  `manifests/full-story-components-validation.json` → `stage_titles.graphics.titles`
- 回读检查：`tools/verify_full_story_iso_content.py`
- 主要测试：`tests/test_stage_title_graphics.py`

## 2. KURODATA/KVMDATA.BIN 固定 UI 图集

当前组合修改 6 个互不重叠的 chunk。每个目标 chunk 为 `0x8240` / 33,344 bytes，
包含 record 0、picture 0 的 `256×256` 4-bpp TIM2。writer 只在登记矩形内重建像素，
保留 CLUT、TIM2 header、padding、其他 picture、其他 chunk 和成员大小。

### 2.1 六个 chunk 总表

| chunk | KVMDATA 区间 | 原定位文字 → 中文 | 修改矩形 `(x,y,w,h)` | 配置 |
| ---: | --- | --- | --- | --- |
| 2 | `[0x10480, 0x186C0)` | `SHIP` → 机体 | `(80,0,49,16)` | `config/assets/ui-info-atlas-zh.json` |
| 4 | `[0x20900, 0x28B40)` | `COMMAND MENU` → 指令菜单 | `(2,100,164,17)` | `config/assets/ui-battle-command-atlas-zh.json` |
| 5 | `[0x28B40, 0x30D80)` | `バザー` → 交易所 | `(3,1,137,61)` | `config/assets/ui-bazaar-atlas-zh.json` |
| 6 | `[0x30D80, 0x38FC0)` | 场间标题和主菜单 9 个切片 | 见下一表 | `config/assets/ui-intermission-atlas-zh.json` |
| 7 | `[0x38FC0, 0x41200)` | 编队 3 个切片 | 见下一表 | `config/assets/ui-formation-atlas-zh.json` |
| 11 | `[0x52070, 0x5A2B0)` | `までクリア！` → 已通关！ | `(60,0,94,24)` | `config/assets/ui-stage-clear-atlas-zh.json` |

chunk 6 的 9 个切片：

| 中文 | 矩形 `(x,y,w,h)` |
| --- | --- |
| 中场休息（普通标题） | `(0,0,215,31)` |
| 中场休息（粗标题） | `(0,106,218,29)` |
| 机体 | `(0,135,69,27)` |
| 机师 | `(139,135,99,27)` |
| 集市 | `(0,162,63,22)` |
| 下个地图 | `(63,162,100,22)` |
| 选项 | `(0,184,101,25)` |
| 小队 | `(0,209,88,22)` |
| 数据管理 | `(0,231,111,25)` |

chunk 7 的 3 个切片：

| 中文 | 矩形 `(x,y,w,h)` |
| --- | --- |
| 新建小队 | `(98,26,74,20)` |
| 移至后备区 | `(172,26,84,20)` |
| 移至小队区 | `(44,178,67,22)` |

chunk 11 的第三段原范围是 `x=50..153, y=0..23`，其中闭引号位于保留区。中文
writer 只清除 `x=60..153` 的固定 `までクリア！` 后缀，再把“已通关！”左移
16px 写入同一 94×24 矩形。因此以下元素不属于本次修改：

- `第`、`話`；
- 章节数字精灵；
- 标题前后的引号；
- 运行时拼入的关卡标题（它来自 VT1 group 8）。

### 2.2 文件和构建位置

中文事实源：

- chunk 2：`corpus/zh/ui-atlas/info-v1.json`
- chunk 4/5/6/7：`corpus/zh/ui-atlas/core-menus-v1.json`
- chunk 11：`corpus/zh/ui-atlas/stage-clear-v1.json`

原图定位和擦除前像：

- `config/assets/maps/tim2-kvm2-info.json`
- `config/assets/maps/tim2-kvm4-battle-command.json`
- `config/assets/maps/tim2-kvm5-bazaar.json`
- `config/assets/maps/tim2-kvm6-intermission.json`
- `config/assets/maps/tim2-kvm7-formation.json`
- `config/assets/maps/tim2-kvm11-stage-clear.json`

候选登记：

- chunk 2/4/5/6/7：`config/assets/ui-atlas-candidates.json`
- chunk 11：`config/assets/ui-stage-clear-atlas-candidates.json`

通用 writer 与入口：

- `tools/srwz/ui_atlas_localization.py::build_ui_atlas_localization`
- `tools/ui_atlas.py`（`build`、`verify`、`build-suite`、`verify-suite`）

单图预览和组件均在各自 profile 下：

```text
work/build/<profile>/reference.png
work/build/<profile>/localized.png
work/build/<profile>/components/KURODATA/KVMDATA.BIN
```

六图最终以 `config/assets/ui-atlas-suite-zh.json` 的 `disjoint-byte-patch` 合成；chunk
顺序为 `2,4,5,6,7,11`，所有权重叠数为 0。相对原版 KVMDATA 共改变 12,812
bytes、1,572 个连续范围。最终文件位置为：

```text
work/build/ui-atlas-suite-zh/components/KURODATA/KVMDATA.BIN
work/build/zh-release-full-story/components/KURODATA/KVMDATA.BIN
```

对应 manifest：

- `manifests/ui-info-atlas-zh-validation.json`
- `manifests/ui-battle-command-atlas-zh-validation.json`
- `manifests/ui-bazaar-atlas-zh-validation.json`
- `manifests/ui-intermission-atlas-zh-validation.json`
- `manifests/ui-formation-atlas-zh-validation.json`
- `manifests/ui-stage-clear-atlas-zh-validation.json`
- `manifests/ui-atlas-suite-zh-validation.json`

所有六份机器 manifest 目前仍使用
`static_localized_component_validated_runtime_mapping_pending`。用户已经在实际画面确认
chunk 6 的场间菜单和 chunk 11 的“已通关！”显示，但这些人工观察尚未改写成新的
hash-locked runtime receipt；chunk 2/4/5/7 不能仅凭静态图集回读宣称运行映射完成。

## 3. EFF/VEFF2DX.BIN 场景选择材质

两块目标都是 `256×256` PSMT4 TIM2，复用原 CLUT。VT1 全局字库只提供 24×24
中文 glyph；writer 把 glyph 写入各自登记的材质坐标，再把完整 decoded effect
定长压回原槽。

VEFF2DX chunk offset 表位于 `SLPS_258.87 [0x31ABB0, 0x31B067)`，归档对齐为
16 bytes。

### 3.1 effect 295 / chunk 296：剧情选择

| 项目 | 当前值 |
| --- | --- |
| VEFF2DX stored 槽 | `[0x2201990, 0x2209150)` |
| 原槽大小 | `0x77C0` / 30,656 bytes |
| decoded 大小 | `0x49E50` / 302,672 bytes |
| TIM2 record | decoded offset `0x18FF0`，size `0x101F0`，record 0 / picture 0 |
| 清除矩形 | `(0,48,248,26)`，回填 index 0 |
| 写入片段 | 正篇 `(2,48,w20,a21)`；教学 `(108,48,w22,a24)`；剧情 `(161,48,w22,a24)` |
| 最终组合 | 正篇剧情、教学剧情 |
| 当前压缩流 | `0x7625` / 30,245 bytes |
| 槽尾填充 | `0x19B` / 411 bytes |

标题长度改变后，同时修改 60 个动画 frame 共 240 个 quad 的 x 坐标。伴随的两条
动态说明文字仍是 SLPS 文本，但它们的起始 x 也在
`SLPS_258.87` record `0x319720` 和 `0x319730` 调整，以保持视觉中心一致。

### 3.2 effect 296 / chunk 297：模式选择

| 项目 | 当前值 |
| --- | --- |
| VEFF2DX stored 槽 | `[0x2209150, 0x22110B0)` |
| 原槽大小 | `0x7F60` / 32,608 bytes |
| decoded 大小 | `0x81880` / 530,560 bytes |
| TIM2 record | decoded offset `0x50A20`，size `0x101F0`，record 0 / picture 0 |
| 清除矩形 | `(0,74,204,50)`，回填 index 0 |
| 写入片段 | 普通 `(22,74,w22,a24)`；EX困难 `(104,74,w20,a21)`；特殊 `(33,98,w22,a24)`；模式 `(125,98,w22,a24)` |
| 最终组合 | 普通模式、EX困难模式、特殊模式 |
| 当前压缩流 | `0x7E62` / 32,354 bytes |
| 槽尾填充 | `0xFE` / 254 bytes |

四段中文仍位于原切片和原 quad 覆盖范围内，因此 chunk 297 不修改动画几何。

事实源和实现位置：

- 两块目标、坐标、前像和压缩预算：
  `config/full-story-components.json` → `scenario_select_effect` / `mode_select_effect`
- 通用写回：`tools/build_full_story_components.py::_apply_scenario_select_effect`
- PSMT4 swizzle：`tools/srwz/psmt4.py`
- 最终回读：`manifests/full-story-components-validation.json` →
  `scenario_select_effect` / `mode_select_effect`
- ISO 回读：`tools/verify_full_story_iso_content.py`

两块材质必须独立从各自原压缩流构建。即使原始逻辑索引图相同，也不能把 chunk
296 的压缩结果复制到 chunk 297。

## 4. MAP/MAPMODEL.BIN 世界地图地名

第一关开场滚动字幕后的“月面 地球联邦军卢特提姆基地”，以及同一 WORLD MAP
系统的其他地名，都是 MAPMODEL 压缩成员中的原始 4-bpp 像素，不是运行时字体。
SLPS 在文件偏移 `0x2FAAD0` 保存 197 个 little-endian `u32` 顶层 offset；标题使用
成员 `81..195`，共 115 个成员、78 个唯一日文前像。

| 项目 | 当前值 |
| --- | --- |
| 日文地名 raw 区间 | decoded `[0x1DE0, 0x3DE0)` |
| 英文副标题 raw 区间 | decoded `[0x3E40, 0x5E40)` |
| 单块几何 | `512×32`、4-bpp |
| 像素顺序 | linear、low-nibble-first、行方向上下翻转 |
| 唯一标题 | 78；其中 70 个重绘、8 个同文 no-op |
| 成员写回 | 101 个重压、14 个 byte-exact 保留 |
| 字体 | HarmonyOS Sans SC Light 1.0 |
| 最小重压余量 | 14,191 bytes |

writer 逐成员验证原始日文 raw SHA-256，只清除原文字的非零包围框，再把中文紧
包围框居中写回同一范围。英文 `WORLD MAP` 副标题、日文块以外的 decoded 内容、
成员 allocation、顶层 offset 和整个 archive 大小均保持不变。事实源和实现位置：

- 译名表：`corpus/zh/ui-atlas/world-map-titles-v1.json`
- 完整代码调用链与格式：`docs/MAPMODEL_WORLD_MAP_TITLES.md`
- 布局与输入锁：`config/full-story-components.json` 的 `world_map_titles`
- writer：`tools/srwz/world_map_titles.py`
- 回归测试：`tests/test_world_map_titles.py`
- 结果：`manifests/full-story-components-validation.json` 的 `world_map_titles`

## 5. 不属于贴图像素修改的伴随项

以下内容与画面有关，但不应计入“贴图修改数量”：

- `SLPS_258.87` 的 VT1 顶层表、group 8 内部表、场景 selector、VEFF quad 和说明
  文字 x 坐标；
- `DATA/COMPDATA.BN` 的 Stage Name 文本、204 条场景记录和路线选择动态文案；
- `DATA/NISVDATA.BIN` 的 effect name 文本；
- `DATA/STAGE.BIN`、`DATA/HSFC.BIN` 和 `BTL/SRVC.*` 的剧情、概要、字幕文本；
- `第`、`話`、数字精灵和通关滚动条引号；
- 导出的 PNG。PNG 是预览／审校产物，不是生产写回事实源。

## 6. 最终组合、ISO 与验证边界

四类贴图最终汇入：

```text
work/build/zh-release-full-story/components/DATA/VT1.BIN
work/build/zh-release-full-story/components/KURODATA/KVMDATA.BIN
work/build/zh-release-full-story/components/MAP/MAPMODEL.BIN
work/build/zh-release-full-story/components/EFF/VEFF2DX.BIN
work/build/zh-release-full-story/components/SLPS_258.87
```

组件总配置和结果：

```text
config/full-story-components.json
manifests/full-story-components-validation.json
```

当前 v0.1.0 ISO：

```text
build/iso/v0.1.0/srwz-zh-v0.1.0.iso
size:   3,758,358,528 bytes
sha256: 40ddc19e752cde0eaa1e9c3baaa98ca52a15c9e169f1676ab315297f33a61c2c
report: build/iso/v0.1.0/iso-validation-v0.1.0.json
```

静态 ISO report 已确认四个成员按上述 SHA-256 写入，并保持原 LBA。它只证明结构、
成员读回和扇区布局，不自动证明每个运行画面正确。任何后续 VT1、KVMDATA、
MAPMODEL 或 VEFF2DX 改动都必须继续满足：

1. 压缩结果不得超过原 stored slot；
2. 成员大小不得增长；
3. 后续成员 LBA 不得移动；
4. 非目标 TIM2 header、CLUT、picture、chunk 和像素必须保持 byte-exact；
5. 静态读回与目标运行画面分别登记，不得互相替代。

## 7. 重建命令

全局字体或字体需求改变时：

```bash
python3 tools/fetch_zh_font.py
python3 tools/fetch_zh_font.py \
  --flavor config/fonts/zh-localization-font-light.json
python3 tools/update_zh_release_font_snapshot.py --apply
python3 tools/rebuild_zh_font.py \
  --refresh-manifests --refresh-asset-ratchets
```

单独重建某张 KVMDATA 图集时，把 `<config>` 换成相应的
`config/assets/ui-*-atlas-zh.json`：

```bash
python3 tools/ui_atlas.py build \
  --config <config> --force
python3 tools/ui_atlas.py verify \
  --config <config> --force --refresh-manifest
```

重建六图组合、最终组件和 ISO：

```bash
python3 tools/ui_atlas.py build-suite \
  --config config/assets/ui-atlas-suite-zh.json --force
python3 tools/ui_atlas.py verify-suite \
  --config config/assets/ui-atlas-suite-zh.json \
  --force --refresh-manifest
python3 tools/build_full_story_components.py \
  --config config/full-story-components.json \
  --force --refresh-manifest
python3 tools/build_iso.py \
  --config config/iso/zh-release-full-story-build.json
```

本表的数字若与未来构建结果冲突，以相同候选的 config、manifest 和精确制品哈希为
准；不能跨候选混用 offset、SHA-256 或运行截图。
