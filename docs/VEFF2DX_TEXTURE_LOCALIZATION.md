# VEFF2DX 图片材质文字汉化

> 技术参考：本文保留 VEFF2DX/PSMT4 结构、几何和定长写回方法；当前发布入口以
> `BUILD_AND_RUNTIME.md` 为准。

本文只记录 `EFF/VEFF2DX.BIN` 中 PSMT4/TIM2 图片文字的生产处理方法。目标是把
预绘制日文替换为中文，同时保持原调色板、TIM2 元数据、归档 offset、成员大小和
ISO 扇区边界不变。

这不是“把导出的 PNG 改好再覆盖回去”的流程。导出图只用于识别、审校和确定坐标；
正式写回由锁定原始前像的 writer 从译文和布局参数确定性生成。

## 1. 与 KVMDATA UI 图集的关系

“中场休息”、机体、机师、小队、集市、选项、数据管理和下个地图不在
`VEFF2DX.BIN`，而在 `KURODATA/KVMDATA.BIN` chunk 6。两条链只共享索引图、
原调色板、定长压缩和 LBA 不变等底层原则：

- VEFF2DX 场景选择标题读取全局 VT1 的 24×24/4-bpp glyph，并为新字符串调整
  动画 frame 的 quad；
- KVMDATA 中场休息图集按九个原日文切片直接擦除和重绘，不改变贴图布局或 quad，
  当前静态中文使用 HarmonyOS Sans SC Light；
- 两者的 mask、palette index、字体渲染和 writer 均不得互相套用。

KVMDATA 的完整规则见 `KVMDATA_ATLAS_LOCALIZATION.md`。

## 2. 三种文件的责任

图片浏览器会在以下目录展示同一资源的不同视图：

```text
by-member/EFF/VEFF2DX.BIN/
  chunk-NNNN/decoded/record-NNN_oXXXXXXXX/
    record.tm2
    picture-NNN.png
    picture-NNN.indices.png
```

| 文件 | 用途 | 能否作为生产写回输入 |
| --- | --- | --- |
| `picture-NNN.indices.png` | 把索引 `0..15` 强制显示为黑到白，便于看清文字和 mask | 否 |
| `picture-NNN.png` | 应用一个 CLUT bank 的 RGBA 预览，便于检查颜色和透明度 | 否 |
| `record.tm2` | 从原始成员严格提取的完整 TIM2 record，保留所有 picture、CLUT 和元数据 | 只作为前像与解析依据，不直接覆盖归档 |

`.indices.png` 会把所有像素强制显示为不透明。图上的黑色通常只是索引 `0`，不能
据此判断游戏中存在黑底。`picture.png` 也只是所选 CLUT bank 的离线预览，不代表
所有动画状态或运行时材质参数。

## 3. PSMT4、CLUT 与透明色

PSMT4 picture 的每个像素只保存一个 4-bit 索引：

```text
像素索引 0..15 -> 当前 CLUT bank 的 RGBA
```

透明度属于 CLUT 和运行时材质状态，不属于索引图本身。PS2 32-bit CLUT 的 Alpha
满值是 `0x80`；导出 PNG 时使用：

```text
PNG alpha = min(255, PS2 alpha * 255 / 128)
```

场景选择标题的活动调色板中，索引 `0` 是 `(0, 0, 0, 0)`，因此当前 writer 用
索引 `0` 清除原文字。中文笔画继续使用索引 `1..15`，复用原来的颜色、阴影和
抗锯齿层级。writer 不修改任何 CLUT 字节。

这条“索引 `0` 可清空”的结论只适用于已经检查过的材质和绘制状态。其他 TIM2、
其他 CLUT bank 或其他动画 pass 的索引 `0` 可能不是透明色。新增目标必须分别确认：

1. 目标 quad 实际使用的 picture 和 CLUT bank；
2. 原文字外背景采用的索引；
3. 该索引在活动 CLUT 中的 Alpha；
4. 选中、未选中、淡入淡出等状态是否切换 palette 或材质参数。

不得按 RGB 黑色猜透明色，也不得重新量化或替换原 CLUT。

## 4. 生产写回流程

每张图片材质按以下顺序处理：

1. **锁定来源**：登记成员、chunk、stored 范围和 SHA-256。
2. **解压 chunk**：按 `srwz_stream` 严格解码并验证 consumed bytes 与尾部零填充。
3. **锁定 TIM2**：登记 record/picture、offset、大小、格式、尺寸和 SHA-256。
4. **反交错**：把 PSMT4 GS 存储顺序转换成逻辑 `width × height` 的索引数组。
5. **清除 mask**：只在登记矩形或逐像素 mask 内写入已验证的透明背景索引。
6. **生成中文字模**：从全局 release 字库读取目标字符的 24×24/4-bpp raster，
   按该场景登记的裁切、字宽和 advance 写入索引图。
7. **调整几何**：字符串宽度改变时，修改对应动画 frame 的 quad 坐标；不能只改
   纹理后依赖原来的裁切范围。
8. **重新交错**：把逻辑索引写回 PSMT4 GS 存储顺序，并执行双向 round trip。
9. **定长重压缩**：使用生产 Rust codec，`max_output_size` 固定为原 stored slot；
   输出不足部分补零，超过原槽立即失败。
10. **归档回读**：重新解压输出 chunk，核对索引、TIM2、CLUT、metadata、padding、
    archive size、offset 和所有非目标字节。
11. **ISO 与运行验收**：重建唯一候选，确认成员扇区预算与后续 LBA 不变，再在精确
    ISO 上进入目标画面检查所有状态。结构回读不能替代 PCSX2 画面验收。

原则上只改索引像素和经过登记的 quad 坐标。原 CLUT、其他 picture、TIM2 header、
未授权动画数据和归档 offset 必须 byte-exact。

## 5. 字模与排版

VEFF2DX 当前场景选择标题从 `config/fonts/zh-localization-font.json` 对应的
HarmonyOS Sans SC Regular 全局 VT1 字库取字。基础 raster 规则是 22px 字形写入
24×24 字槽，统一基线，不使用逐字视觉补丁。该规则不适用于直接从字体文件渲染的
KVMDATA 静态 UI 图集。

材质 writer 读取已经生成的全局 4-bpp glyph，而不是再次用另一套字体直接绘制。
场景配置只负责：

- 需要清除的 mask；
- 中文字符串；
- `x/y`；
- 输出字宽和 advance；
- 必要的 texture quad 几何调整。

为适配固定图片布局，可以对 24×24 glyph 做统一的居中裁切，但必须保持 24px 原生
高度和原 4-bpp 抗锯齿值。禁止逐字缩放、单独上移下移或把 RGBA PNG 重新量化成
索引图。

## 6. 当前场景选择标题实例

当前生产目标是：

```text
member:        EFF/VEFF2DX.BIN
effect_id:     295
chunk:         296
record:        0 at decoded offset 0x18FF0
picture:       0
geometry:      256×256 PSMT4
stored slot:   30,656 bytes
```

配置位于 `config/full-story-components.json` 的 `scenario_select_effect`。当前操作为：

```text
clear:  x=0, y=48, width=248, height=26, fill=index 0

正篇:   x=2,   y=48, glyph_width=20, advance=21
教学:   x=108, y=48, glyph_width=22, advance=24
剧情:   x=161, y=48, glyph_width=22, advance=24
```

最终组合为“正篇剧情”和“教学剧情”。writer 同时调整 60 个动画 frame 的 240 个
quad，使两组标题按实际非透明像素居中。当前输出压缩为 30,245 bytes，并在原槽内
保留 411 bytes 零填充；归档大小和所有 offset 不变。

实现入口：

- `tools/build_full_story_components.py::_apply_scenario_select_effect`
- `tools/build_full_story_components.py::_apply_scenario_title_geometry`
- `tools/srwz/psmt4.py`
- `tools/verify_full_story_iso_content.py::verify_scenario_select_effect`

重建组件：

```bash
python3 tools/build_full_story_components.py \
  --config config/full-story-components.json --force --refresh-manifest
```

生成唯一 ISO 时使用：

```bash
python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json
```

## 7. 第二份重复纹理已按独立目标写回

当前导出中，下面两张逻辑索引图像素相同：

```text
chunk-0296/decoded/record-000_o00018ff0/picture-000.indices.png
chunk-0297/decoded/record-000_o00050a20/picture-000.indices.png
```

运行截图已经确认 `chunk-0297` 是普通／EX 困难／特殊模式选择页。因此它现在以
`mode_select_effect` 独立登记为 `effect_id 296`，不复制 `chunk-0296` 的压缩流：

```text
chunk:       297
record:      0 at decoded offset 0x50A20
stored slot: 32,608 bytes
clear:       x=0, y=74, width=204, height=50
segments:    普通 / EX困难 / 特殊 / 模式
output:      32,354 bytes + 254 bytes zero padding
```

四段中文分别留在原来的 `ノーマル`、`EXハード`、`スペシャル`、`モード`
切片范围内，所以动画 quad 和布局字节保持原样。最终组合为“普通模式”、
“EX困难模式”和“特殊模式”。两块纹理分别锁定 stored/decoded/record 前像、
独立 Rust 压缩预算和最终 ISO 回读，仍禁止互相复制压缩流。

## 8. 新材质准入清单

新增任何图片文字目标前，至少登记并验证：

- [ ] 运行画面与 member/chunk/record/picture 的映射；
- [ ] 原版 member、stored chunk、decoded payload 和 TIM2 SHA-256；
- [ ] picture 格式、尺寸、swizzle 和 shared CLUT 关系；
- [ ] 每个运行状态实际使用的 CLUT bank 与透明背景索引；
- [ ] 日文 owner、中文译文、字体来源、mask、坐标和宽度；
- [ ] 修改像素全部位于授权 mask；
- [ ] CLUT、metadata、其他 picture 和非目标字节 byte-exact；
- [ ] PSMT4 与 codec 双向 round trip；
- [ ] 压缩结果不超过原 stored slot；
- [ ] archive/member 大小和 ISO LBA 不变；
- [ ] 精确候选上的目标画面截图与正常流程验证。

任一项未知时，该图片只能停留在识别／审校阶段，不能晋级为生产写回。
