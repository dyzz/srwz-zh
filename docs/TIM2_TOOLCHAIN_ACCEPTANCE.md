# TIM2 工具链选择与验收

状态：候选调查和 `minimal_local_writer` 已完成两级验证；真实 `KVMDATA`
chunk 5 no-op 已通过 byte/pixel/archive 门，`VT1 chunk 6 / record 1 /
picture 0` 的固定 8-bpp 索引 canary 已通过归档、ISO、PCSX2 画面和运行时纹理
转储门。ImageMagick 继续负责单 picture 读取、PNG 预览和通用图像处理。

## 1. 已确定的职责边界

不需要重复实现的部分：

- ImageMagick 已能把本游戏的单 picture TIM2 读取为 PNG；
- `tools/render_srwz_tim2.py` 只负责从 ISO/归档定位、必要时解压、严格切出
  TIM2，再调用 ImageMagick；它不是另一个像素 decoder；
- `tools/srwz/tim2.py` 只做结构、边界和 metadata oracle，用于拒绝 false magic
  和检查写入结果，不承担图像编辑。

当前最小 writer 明确不覆盖的部分：

- 通用 8-bpp PNG 坐标写回和 direct-color 图像；
- 生成或修改 CLUT、PS2 alpha 和 palette 排列；
- 任意 multi-picture/shared-CLUT 布局和通用 TIM2 创建。当前只额外接受已固定
  的六 picture VT1 标题记录，并对 picture 0 做全局 index 替换。

## 2. 外部工具准入门

候选工具必须同时满足：

1. 源码和许可证明确，允许本项目使用和分发构建说明；
2. 能在 macOS 原生命令行执行，不依赖 Wine、Mono 或 Windows helper；
3. 非交互、参数可固定、两次运行结果确定；
4. 支持 TIM2 v4，至少能写本项目首个 canary 所需的 4-bpp indexed texture；
5. 能明确控制尺寸、bpp、CLUT 深度、mipmap、alpha 和 palette 行为；
6. 输出能通过 `tools/srwz/tim2.py` 的严格 header/size/bounds 检查；
7. no-op round-trip 的解码像素与 alpha 完全一致；
8. 能保持目标 archive chunk 的几何约束，或输出大小可由外层归档安全重建；
9. 不把未经许可的游戏字节、上游预制 BIN 或私有字体作为运行依赖。

只有“能生成一个 ImageMagick 可以重新打开的 `.tm2`”不够；最终接受者是游戏，
还必须通过 PCSX2 实际纹理加载和视觉验证。

## 3. 固定验收样本

首轮评估按难度递增：

| fixture | 格式 | 用途 |
| --- | --- | --- |
| `KVMDATA` chunk 5 | 256×256、4-bpp、indexed | 首个 UI atlas/no-op writer |
| `KVMDATA` chunk 12 | 512×512、8-bpp、indexed | 8-bpp 和 256 色 CLUT |
| `JTIM` record 0 | 616×232、16-bpp | direct-color |
| `JTIM` record 9 | 320×168、32-bpp | 32-bpp/alpha |
| `VT1` chunk 6 record 1 | 512×256、8-bpp、六 picture/共享 CLUT | 已通过固定 index 运行 canary |
| `VEFF2DX` 代表记录 | 多 picture/共享 CLUT | 高级特效兼容性 |

样本字节只在被忽略的 `work/` 中临时提取；可提交结果只保存来源 member/chunk、
输入哈希、工具版本、输出哈希和比较统计。

## 4. 验收流程

每个候选依次执行：

```text
固定原盘验证
  -> 本项目定位/解压/切出 TIM2
  -> 候选工具 decode
  -> 不修改图像地 encode
  -> 本项目严格 reparse
  -> ImageMagick 独立 decode
  -> 像素、alpha、尺寸和 palette 语义比较
  -> 固定 chunk/归档重建
  -> PCSX2 原图 no-op canary
```

no-op 通过后，才做一处可见但无翻译争议的测试像素；确认实际加载后，再设计中文
图像 canary。不能从“PNG 看起来一样”跳过容器和运行时验证。

## 5. 决策结果

评估后只允许三种结论：

- `adopt`：固定外部版本/提交，项目只写薄 adapter 和验证器；
- `contribute`：现成工具基本可用，补最小缺口并向其上游贡献；
- `minimal_local_writer`：没有合格工具时，只实现首个已登记 surface 所需子集，
  不扩张为通用 TIM2 编辑器。

无论选择哪条路线，ImageMagick 都保留为独立读取/视觉 oracle，不负责证明游戏
写入兼容。

## 6. 候选初筛（2026-07-25）

以下结论基于链接所示源码仓库和固定提交，不根据二进制工具宣传推断能力。此表是
当前可查到候选的工程筛选结果，不声称穷尽所有历史私有工具。

| 候选 | 固定源码 | 许可证 | 写回能力 | macOS/命令行结论 | 结果 |
| --- | --- | --- | --- | --- | --- |
| ImageMagick | 本机 `7.1.2-27` | ImageMagick License | 无；本机 `TM2` 为 `r--` | 原生 arm64 CLI | 保留为读取/视觉 oracle |
| [TIM2dump](https://github.com/polymood/tim2dump) | `188f934d74b4da9d7b6a34ce224bcf166328a82c` | MIT | 只解析并导出 BMP/PNG | CMake 声明支持 Apple Clang | 不属于 writer |
| [DCExtractor](https://github.com/muddle12/DCExtractor) | `01fddadc40d2103d9775c47320244807811a71cc` | GPL-3.0 | README 明确说明不能 repack | .NET Framework 4.6.1 | 拒绝 |
| [PS-Image](https://github.com/MeganGrass/ps-image) | `69952e2b980cc9416e559bbdb766e13fc9171bf1` | MIT | `sony-lib` 的 TIM2 类只有 open/export，没有 save | Visual Studio 2022、DirectX、GUI | 拒绝 |
| [Rainbow](https://github.com/marco-calautti/Rainbow) | `51bb1834181c474893bdfbd810e3a45fe6397914` | GPL-2.0 | 有 TIM2 import/save、multi-layer/multi-CLUT | .NET Framework 4.0+ 或 Mono、GUI；本项目禁止 Mono | 能力参考，不采用 |
| [PZ-TM2-Converter](https://github.com/lehieugch68/PZ-TM2-Converter) | `7c50d472576a291dd2eba72916a823c970b858d5` | MIT | 用原 TM2 作模板，覆盖 4/8-bpp index 数据 | .NET Framework 4.7.2，结束时等待按键 | 不能作为原生非交互工具 |
| [ptr2tools](https://github.com/posesix/ptr2tools) | `57f124920c583b080f0ff1ba0fbc2e2a0b95f382` | 仓库自带允许使用、修改和分发的许可 | 针对 PaRappa 2 的 TM0/虚拟 GS 注入 | 修正 include 路径后可编译为 arm64 CLI | 真实 4-bpp fixture 失败，见下 |
| [Kuriimu](https://github.com/IcySon55/Kuriimu) | `ebfbf8de50755cc32a7e1ea4aee394628d49d3d2` | GPL-3.0 | TIM2 adapter 明确 `CanSave => false` | 旧 .NET Framework GUI | 拒绝 |
| [BokuNoNatsuyasumi2](https://github.com/HilltopWorks/BokuNoNatsuyasumi2) `TIM2.py` | `b1b48080170dceed7399ec290808e0a866da4992` | 仓库未声明许可证 | 有游戏专用原位 PNG 注入 | Python，但含固定游戏路径/布局 | 未授权源码，不使用或复制 |
| 两个 GitHub gist（[`pbtm2.py`](https://gist.github.com/penguino118/afeb198ad6ba5495311bc24fe195548e)、[12Riven KLZ](https://gist.github.com/Timo654/d9701127172198c7e00ab96da43da995)） | 调查日页面版本 | 未声明许可证 | 前者为游戏专用容器；后者把 PNG 嵌入 `PNGFILE3`，不是标准像素 TIM2 | Python | 不使用或复制 |

`PS-Image` 的 README 把 `.TM2` 列在支持格式中，但这不能等同于写回：其固定
`sony-lib` 子模块提交甚至不含当前的 `sony_texture_2.*`；检查当前
`sony-lib` 的公开 TIM2 类，也只有 `OpenTIM2` 和 `ExportImage`。因此不能因为
GUI 能打开 TM2 就把它当成 writer。

### 6.1 ptr2tools 的本机实测

这是唯一进入本机 native build 的候选：

```text
source commit: 57f124920c583b080f0ff1ba0fbc2e2a0b95f382
compiler: Apple clang++ / arm64
fixture: KURODATA/KVMDATA.BIN chunk 5
fixture SHA-256: 9f7e7c8bad898cd1bcd1d9596237fcfec5239cd00522ac1643d975bbe6c0369f
fixture format: 256x256, 4-bpp indexed, 256 CLUT entries
reference ImageMagick PNG8 active-CLUT render: 9 used colors
ptr2tools render: 1 color, fully transparent
```

失败原因可以从源码直接解释：`tim2upload()`/`tim2download()` 只在虚拟 GS
内存与 TIM2 间复制 texture pixels，没有把 TIM2 文件内的 palette/CLUT
装入或写回；`extract` 随后从全零 CLUT 读取颜色。它即使能在 macOS 编译，也
不满足首个 4-bpp indexed fixture，因此不进入 archive no-op 或 PCSX2 门。

### 6.2 当前决策

当前调查中没有候选同时满足许可证、原生 macOS 非交互执行和 SRWZ 4-bpp CLUT
写回三项准入门。路线因此确定为：

```text
minimal_local_writer
```

这里的“writer”不是通用 PNG→TIM2 编码器，而是固定 canary 的严格原位索引
注入器：

- 输入必须是已通过严格 parser 的单-picture `KVMDATA` chunk；
- 只接受 256×256、4-bpp、无额外 mip level 的既有容器；
- ImageMagick 以 `PNG8` 负责原 TIM2 和编辑 PNG 的 RGBA 展开；
- 只允许使用原图中已经实际出现的 RGBA 颜色，不生成或改写 palette；
- 保留 header、GS registers、CLUT、padding 和总长度，仅覆盖 image data；
- no-op 必须得到 byte-identical TIM2；
- 真实 chunk 写回后必须严格 reparse，归档仍保持原 offset/size；
- 首个可见 canary 只改已登记 atlas 的少量像素，再进入 PCSX2 验证。

第二个固定子集接受 `VT1 chunk 6 / record 1` 的准确六 picture 布局，只将
picture 0 中一个已存在的 8-bit index 全局替换为另一个已存在 index。它不解析
坐标，不改 1,536-entry CLUT，并要求 source index 出现次数等于配置前像。

这条边界避开了调色板量化、PS2 alpha 反编码、任意共享 CLUT/multi-picture
布局和通用 TIM2 创建。任何超出两个固定布局的输入都必须明确拒绝，不能静默
降级。

## 7. 实现和真实验收结果

实现：

- `tools/srwz/tim2_writeback.py`：纯函数、固定布局、fail-closed 4-bpp nibble
  和 VT1 8-bpp index writer；
- `tools/srwz/imagemagick.py`：`PNG8` 渲染和确定性 RGBA8 adapter；
- `tools/inject_srwz_tim2.py`：只读 ISO 定位、同大小 chunk 替换、重渲染验证、
  完整 archive 输出和 byte-free report；
- `tools/build_tim2_runtime_canary.py`：VT1 解压、固定 record 修改、clean-room
  重压缩、归档对齐、SLPS offset patch 和组件报告；
- `tests/test_tim2_writeback.py`：no-op、低/高 nibble、未知颜色、RGBA 长度、
  oracle 不一致、尺寸、8-bpp、CLUT 和尾部拒绝。

真实 `KURODATA/KVMDATA.BIN` chunk 5：

```text
chunk: [166720,200064), 33344 bytes
image: [64,32832), 32768 bytes
CLUT: 256 entries, 16-bpp, 512 bytes
source/output member SHA-256:
  cd469075dd56c5fe1ba0c03ad4b5878b1684e7b0d22a7129c1b71cb14087f9a8
no-op changed pixels/bytes: 0 / 0
visual RGBA exact: true
non-target archive bytes exact: true
```

另一个离线单像素验证只改变 member `[166784,166785)`，改变 1 pixel/1 byte，
重渲染 RGBA 与编辑 PNG 一致。该 KVMDATA 实验本身的
`runtime_acceptance` 仍为 `not tested`，不能代替下述 VT1 运行证据。

可提交证据为 `manifests/tim2-writeback-noop.json`；实际重建成员和编辑 PNG
只保存在被忽略的 `work/assets/writeback/`。

### 7.1 VT1 标题菜单运行验收

PCSX2 原版纹理转储先把标题 atlas 精确归属到
`DATA/VT1.BIN / chunk 6 / record 1 / picture 0`。stored index count 与
运行时 RGBA histogram 逐项一致，不依赖离线预览的 swizzle 外观。

固定 edit 为 index `63 → 97`，恰好改变 351 个 image byte。组件构建保留 TIM2
metadata/CLUT/其他 picture 和 13 个非目标 VT1 chunk；重压缩后 decoded
round-trip exact，SLPS 只更新 VT1 offset 表。隔离 ISO 两次构建得到相同
SHA-256，PCSX2 v2.6.3 识别为 DVD、PINE 正常、0 TLB miss。

运行时纹理转储只出现 351 个像素变化，全部为
`FFFF1F80 → 64646480`；标题截图中 `START` 亮黄色填充变灰，菜单布局完整。
提交证据见 `manifests/image-canary-validation.json`。

### 7.2 标题四项中文写回

固定标题 fixture 已实现 PSMT8 坐标级 swizzle/unswizzle。原图静态解出
131,072 个逻辑像素，与 PCSX2 原版转储逐像素一致，地址覆盖无重复、无越界。
四项译文为：

| 原文 | 中文 |
| --- | --- |
| `START` | `开始` |
| `LOAD` | `读取` |
| `CONTINUE` | `继续` |
| `LIBRARY` | `资料库` |

ImageMagick 以固定 Noto Sans CJK SC 2.004（OFL-1.1）生成四张 128×32 灰度
mask；writer 把它们分别量化到原图已有的黄色 `48..63` 和绿色 `64..79`
调色板 ramp，覆盖八个文字槽。CLUT、TIM2 metadata、其余五个 picture、目标
记录外 decoded 数据和 13 个非目标 VT1 chunk 均保持不变。

写回改变 12,514 个逻辑像素/存储 byte；clean-room greedy 重压缩后精确解回。
隔离 ISO SHA-256 为
`fdeebb1b86b86f883e5ce8e3ecd3667f3ae665eb82cbe0f191ec133c6c4df1d4`。
PCSX2 v2.6.3 中第一项、第四项选中截图均显示正确，DVD、PINE running、
0 TLB miss。游戏转储的 512×256 标题纹理与离线预览 RGBA SHA-256 都是
`19539f6f607aed4fa52b1b99dc003950982e0a7470792dbd9a8b09e596f99d7e`，
即逐像素一致。提交证据见 `manifests/title-menu-zh-validation.json`。

该能力仍是绑定已验证 VT1 标题布局的最小 writer，不是任意尺寸、任意 PSM、
任意 CLUT 的通用 TIM2 编码器。

## 8. UI atlas 映射 canary

通用 4-bpp 定位器现在接受一个固定矩形、一个原图已有的替换 RGBA，以及必须
逐像素保留的背景 RGBA 集合。它只擦除 mask 内非背景像素；mask 外、登记背景、
TIM2 header/CLUT/padding、其他 chunk 和完整归档长度必须不变。这样既能处理
透明底的 chunk 2，也能处理同时含透明黑和不透明黑的 chunk 6，而不会把整块
背景 alpha 一并改掉。TIM2→PNG8 展开必须显式使用 `+dither`：chunk 7 的
轻微色偏 CLUT 已证明默认 palette dithering 会让同一源 index 量化成多个
RGBA，从而破坏可逆写回映射；关闭抖动后 16 个源 index 均保持一对一 RGBA。

### 8.1 信息页 `SHIP`

`KURODATA/KVMDATA.BIN / chunk 2 / record 0 / picture 0` 是
256×256/4-bpp indexed atlas，离线可见
`SHIP/PARTS/PILOT/ROBO/SEARCH/WEAPON/MAP DATA`。其隔离 canary 只擦除
`SHIP` 的 `x=80, y=0, width=49, height=16`，改变 299 个逻辑像素和
185 个 image/archive byte。完整 KVMDATA 等长，ISO 有 65 个未替换成员、
零 LBA 位移，SHA-256 为
`9343889dc72c6d3fc2287f0ac279912fb1ae7e1e1123ee15150f667e50bc78f6`。

复验：

```bash
python3 tools/build_ui_atlas_map_canary.py --force
python3 tools/verify_ui_atlas_map_canary.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-info-atlas-map-canary-build.json
python3 tools/verify_ui_atlas_map_canary_iso.py --force
```

同一 mask 现另有中文生产候选。`config/assets/ui-info-atlas-zh.json` 从受审
corpus 取得 `机体`，用锁定 LXGW 字体和原图调色板 ramp 在已擦除前像内增加
318 个文字像素；相对原图精确变化 421 个像素和 183 个 archive byte。
TIM2 回读 RGBA 精确，完整 KVMDATA 等长；独立 ISO 有 65 个未替换成员、
零 LBA 位移，SHA-256 为
`d31f3d3dbffc59da595b2d27bb516efec34af12426bda2b3d6f2a67ffdb9ddd0`。

```bash
python3 tools/build_ui_atlas_localization.py --force
python3 tools/verify_ui_atlas_localization.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-info-atlas-zh-build.json
python3 tools/verify_ui_atlas_map_canary_iso.py \
  --config config/iso/ui-info-atlas-zh-build.json --force
```

### 8.2 战场 `COMMAND MENU`

`KVMDATA chunk 4 / record 0 / picture 0` 的隔离 canary 只擦除
`COMMAND MENU`，mask 为 `x=2, y=100, width=164, height=17`。该矩形结束于
右侧相邻符号之前、下方数字行之上；背景透明像素保持不变。组件改变 2,297 个
逻辑像素和 1,221 个 archive byte，完整 KVMDATA 等长。隔离 ISO 只有一个
替换成员、65 个未替换成员和零 LBA 位移，SHA-256 为
`067626adbaac4ab0189df3b653c1da040d1ea18783667dc2b3ba7b598cae65c1`。

复验：

```bash
python3 tools/build_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm4-battle-command-map.json --force
python3 tools/verify_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm4-battle-command-map.json --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-battle-command-atlas-map-canary-build.json
python3 tools/verify_ui_atlas_map_canary_iso.py \
  --config config/iso/ui-battle-command-atlas-map-canary-build.json --force
```

### 8.3 幕间标题

`KVMDATA chunk 6 / record 0 / picture 0` 的隔离 canary 只擦除顶部
`インターミッション`，mask 为 `x=0, y=0, width=185, height=31`。替换色
为既有不透明黑，并同时保留透明黑与不透明黑背景；右侧箭头、数字行和其余标签
保持不变。组件改变 803 个逻辑像素和 509 个 archive byte，完整 KVMDATA
等长。隔离 ISO 同样只有一个替换成员、65 个未替换成员和零 LBA 位移，
SHA-256 为
`dafe4737f797b611e02a0dcf68096a40e9b3c61ae4fa98d979b19a00ce0ca0df`。

复验：

```bash
python3 tools/build_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm6-intermission-map.json --force
python3 tools/verify_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm6-intermission-map.json --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-intermission-atlas-map-canary-build.json
python3 tools/verify_ui_atlas_map_canary_iso.py \
  --config config/iso/ui-intermission-atlas-map-canary-build.json --force
```

### 8.4 编成 `新規編成`

`KVMDATA chunk 7 / record 0 / picture 0` 的隔离 canary 只擦除
`新規編成`，mask 为 `x=98, y=26, width=74, height=20`。该矩形与右侧
`リザーブへ` 之间保留两列空隙，不覆盖上方 `Event No/Leader/Pilot` 或下方
数字列。组件改变 1,325 个逻辑像素和 691 个 archive byte，完整 KVMDATA
等长。隔离 ISO 只有一个替换成员、65 个未替换成员和零 LBA 位移，SHA-256
为
`5f05e41f9ba2e410d36a985ca9a87f177d6622ee4e5340d5c0f0ad1ba4fe844c`。

复验：

```bash
python3 tools/build_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm7-formation-map.json --force
python3 tools/verify_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm7-formation-map.json --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-formation-atlas-map-canary-build.json
python3 tools/verify_ui_atlas_map_canary_iso.py \
  --config config/iso/ui-formation-atlas-map-canary-build.json --force
```

### 8.5 商店 `バザー`

`KVMDATA chunk 5 / record 0 / picture 0` 的隔离 canary 只擦除顶部大号
`バザー`，mask 为 `x=3, y=1, width=137, height=61`。右侧文字从 `x=143`
开始，下方英文 `Bazaar` 从 `y=65` 开始，均不在 mask 内。组件改变 2,197 个
逻辑像素和 1,210 个 archive byte，完整 KVMDATA 等长。隔离 ISO 只有一个
替换成员、65 个未替换成员和零 LBA 位移，SHA-256 为
`6805fbd0bbfe98ef613ab7a4f4eddf184517b681a800b06a3fa1ba5af2ec2d04`。

复验：

```bash
python3 tools/build_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm5-bazaar-map.json --force
python3 tools/verify_ui_atlas_map_canary.py \
  --config config/canary/tim2-kvm5-bazaar-map.json --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-bazaar-atlas-map-canary-build.json
python3 tools/verify_ui_atlas_map_canary_iso.py \
  --config config/iso/ui-bazaar-atlas-map-canary-build.json --force
```

上述结果都只证明离线写回和 ISO 注入确定性，运行映射仍为 `not_tested`。
信息页必须同时看到中文标签出现在原位置和 421 像素 texture delta；战场、
商店、幕间和编成仍必须分别看到目标标题缺失和
2,297／2,197／803／1,325 像素 delta。记录精确 PCSX2、ISO、存档、截图及
转储哈希后，才可升级候选场景映射。静态 preview、ISO 启动或任意 UI 变化
都不够。
