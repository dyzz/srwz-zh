# KVMDATA UI 图集文字汉化

本文记录 `KURODATA/KVMDATA.BIN` 中固定 UI 图集的生产写回规则。当前六组生产
配置的所有中文字形都以 4 倍分辨率栅格化、一次面积平均缩回目标尺寸并冻结；普通
构建不再调用 ImageMagick。它与
`VEFF2DX_TEXTURE_LOCALIZATION.md` 共享索引图、原调色板、定长压缩和 ISO LBA
不变等底层约束，但两者不是同一个资源，也不能共用排版或几何策略。

| chunk | 中文标签 | 配置 | 冻结字形数 |
| ---: | --- | --- | ---: |
| 2 | 机体 | `ui-info-atlas-zh.json` | 1 |
| 4 | 指令菜单 | `ui-battle-command-atlas-zh.json` | 1 |
| 5 | 交易所 | `ui-bazaar-atlas-zh.json` | 1 |
| 6 | 中场休息及七个菜单标签 | `ui-intermission-atlas-zh.json` | 9 |
| 7 | 新建小队、移至后备区、移至小队区 | `ui-formation-atlas-zh.json` | 3 |
| 11 | 已通关！ | `ui-stage-clear-atlas-zh.json` | 1 |

六组配置合计 16 块冻结字形；每组都有独立的
`config/assets/*-render-snapshot.json`，并由 `ui-atlas-suite-zh.json` 在互斥字节范围内
合成为一个 KVMDATA 组件。

## 1. 与 VEFF2DX 的边界

| 项目 | KVMDATA UI 图集 | VEFF2DX 场景选择标题 |
| --- | --- | --- |
| 成员 | `KURODATA/KVMDATA.BIN` | `EFF/VEFF2DX.BIN` |
| 当前目标 | chunk 6 幕间菜单、chunk 11 通关提示 | effect 295 / chunk 296 |
| 文字生成 | 按原日文切片直接渲染 HarmonyOS Sans | 读取全局 VT1 的 24×24/4-bpp glyph |
| 排版 | 保持原切片大小与位置，不调整贴图布局 | 必要时修改动画 frame 的 quad 坐标 |
| 背景处理 | 整个登记切片强制回填背景索引 `0` | 只清除登记 mask 内原文字 |
| 写回入口 | `ui_atlas_localization.py` | `build_full_story_components.py` |

VEFF2DX 文档中的“从全局 glyph 裁切”和“修改 quad”只适用于 VEFF2DX。中场休息
图集必须严格替换原日文切片：先清空整个切片，再在同一矩形中居中放置中文，不能
扩张矩形、重排菜单或覆盖相邻的数字、`1st/2nd/3rd/score` 等元素。

## 2. 事实源与所有权

- `config/assets/maps/tim2-kvm6-intermission.json`：原始归档、chunk、TIM2 和第一块
  擦除前像；不拥有中文译文。
- `corpus/zh/ui-atlas/core-menus-v1.json`：中文标签的唯一文本事实源。
- `config/assets/ui-*-atlas-zh.json`：六组源切片、字体 flavor、字号、索引层、4 倍
  渲染规则、冻结渲染锁和输出哈希。
- `config/assets/ui-*-atlas-render-snapshot.json`：已审字形的 outline/fill 灰度 mask
  及整图预览；普通生产构建只消费快照。
- `manifests/ui-intermission-atlas-zh-validation.json`：确定性组件回读结果。
- `config/assets/ui-atlas-suite-zh.json`：六张 KVMDATA 图集的互斥字节所有权合成。

提交的 PNG 不是写回输入。生产组件从锁定原始前像和冻结 mask 确定性重建；只有在
译文、字体或渲染规则经过明确审改后，才允许用显式冻结命令重新栅格化并更新快照。

## 3. 中场休息切片

当前目标为 `KURODATA/KVMDATA.BIN` chunk 6、record 0、picture 0。九个源切片如下：

| 中文 | `x` | `y` | 宽×高 | 样式 |
| --- | ---: | ---: | ---: | --- |
| 中场休息 | 0 | 0 | 215×31 | 26px，右斜 12° |
| 中场休息 | 0 | 106 | 218×29 | 26px，右斜 12° |
| 机体 | 0 | 135 | 69×27 | 18px，右斜 12° |
| 机师 | 139 | 135 | 99×27 | 18px，右斜 12° |
| 集市 | 0 | 162 | 63×22 | 18px，右斜 12° |
| 下个地图 | 63 | 162 | 100×22 | 18px，右斜 12° |
| 选项 | 0 | 184 | 101×25 | 18px，右斜 12° |
| 小队 | 0 | 209 | 88×22 | 18px，右斜 12° |
| 数据管理 | 0 | 231 | 111×25 | 18px，右斜 12° |

九块中文统一使用
`config/fonts/zh-localization-font-light.json`，即锁定官方压缩包内的
HarmonyOS Sans SC Light 1.0。它只是同一 HarmonyOS Sans 家族的静态图集字重
变体；VT1 动态字库继续使用 Regular。

## 4. 擦除、调色板与选中状态

每个切片都锁定原始 RGBA SHA-256，并执行以下顺序：

1. 只在登记矩形内把全部像素强制重建为背景索引 `0`；
2. 在同一矩形中写入冻结的中文 mask；标题和菜单先在 4 倍分辨率栅格化，以高分辨率
   整行像素位移右斜 12°，再用精确面积平均一次缩回目标尺寸。倾斜过程不插值、不
   生成第二层边缘；26px 标题描边为 0.5px，18px 菜单描边为 0.25px；
3. 标题 outline 使用索引 `1..7`、fill 使用 `8..15`；
4. 菜单 outline 使用索引 `1..7`、fill 使用 `8..14`；
5. 对整个矩形执行强制 reindex，禁止残留原日文像素或旧索引边缘；
6. mask 外、其他数字行、箭头和 TIM2 元数据保持 byte-exact。

选中与未选中的亮暗由原图索引层和运行时 palette/材质状态产生。writer 不画白底、
绿色矩形或选中框，也不通过改 RGB 猜测运行效果。索引 `8` 只能出现在实际字形边缘，
不能成为覆盖切片的实心矩形。

## 5. 关卡通关滚动条

chunk 11 的第三个精灵段覆盖 `x=50..153, y=0..23`，内容为固定闭引号和
`までクリア！`。中文组件只擦除 `x=60..153, y=0..23` 的固定后缀并重绘
“已通关！”，因此 `第`、`話`、引号和数字精灵均保持原样。

关卡标题正文不属于 KVMDATA，也不是 COMPDATA 文本或运行时逐字排版。SLPS 的
标题加载器按关卡 selector 从 `DATA/VT1.BIN` 顶层 group 8 取出一张独立压缩资源；
解压后是 512×64、4bpp 的 TIM2。`build_full_story_components.py` 从 204 条原始关卡
节点记录读取真实 selector，为 107 个可玩关卡标题逐槽生成中文 TIM2，并把每张
压缩流硬适配回原 slot，保持 group 8 内部偏移表、顶层归档边界、VT1 成员大小和
ISO LBA 不变。Stage Name 的另外 15 项没有独立进关贴图：9 条路线选择文案和
6 条内部／测试记录由 COMPDATA 文本链覆盖。KVMDATA 的“已通关！”与 VT1 的
关卡标题是两条独立写回链。

译文事实源为 `corpus/zh/ui-atlas/stage-clear-v1.json`，生产配置为
`config/assets/ui-stage-clear-atlas-zh.json`。中文在 94×24 擦除区内显式左移
16px，使“已”接在保留的闭引号之后；不修改运行时 quad 宽度或 SLPS 绘制代码。

## 6. 构建与验证

先取得同一官方字体包中的 Light 字重：

```bash
python3 tools/fetch_zh_font.py \
  --flavor config/fonts/zh-localization-font-light.json
```

重建并验证独立图集：

```bash
# 仅在有意修改译文、字体或渲染规则时逐项重新冻结；普通 build 不运行此命令
python3 tools/freeze_ui_atlas_renders.py \
  --config config/assets/ui-intermission-atlas-zh.json --force

python3 tools/ui_atlas.py build \
  --config config/assets/ui-intermission-atlas-zh.json --force
python3 tools/ui_atlas.py verify \
  --config config/assets/ui-intermission-atlas-zh.json \
  --force --refresh-manifest
```

再合入六图套件和当前发布组件：

```bash
python3 tools/ui_atlas.py build-suite \
  --config config/assets/ui-atlas-suite-zh.json --force
python3 tools/ui_atlas.py verify-suite \
  --config config/assets/ui-atlas-suite-zh.json \
  --force --refresh-manifest
python3 tools/build_full_story_components.py \
  --config config/full-story-components.json --force --refresh-manifest
```

Python 入口只负责解析、编排和回读；生产压缩全链路必须由 Rust codec 完成。
`manifests/full-story-components-validation.json` 必须同时满足
`backend_policy = rust-only`、`python_encoder_used = false`，所有候选只要求装入原
stored slot，不要求无条件使用 maximum 策略。

当前发布 ISO 由以下命令覆盖构建，不另存递增候选：

```bash
python3 tools/build_iso.py \
  --config config/iso/zh-release-full-story-build.json
```

静态通过只证明切片、索引、归档、成员和 LBA 合同成立。最终仍需在该精确 ISO 上
检查正常/选中菜单、两种“中场休息”标题和所有七个标签；截图或短暂启动不能替代
目标画面验收。
