# 图片资源、地图名与复杂字体分析

状态：已完成第一轮原盘范围清单、严格 TIM2 元数据解析、单图渲染、上游图像
差异定位和外部 writer 初筛。当前可以证明大量资源可提取和读取；候选调查已
确定采用严格原位 `minimal_local_writer` 路线。真实 `KVMDATA` chunk 5
4-bpp byte-identical no-op 和 `VT1` 标题纹理 8-bpp 索引 canary 均已完成；
后者已重压缩、写入隔离 ISO，并通过 PCSX2 画面和运行时纹理转储验证。

## 1. 本轮新增的可重复能力

`tools/srwz/tim2.py` 独立解析 SRWZ 实际使用的 TIM2 v4 文件头和 picture 头，
验证总长、header/image/CLUT 大小、边界、尺寸、bpp、mipmap 和 indexed
palette。多 picture 记录允许后续 picture 显式复用前一兼容 CLUT；原始字节中
只出现 `TIM2` magic、但结构或边界不成立的候选不计为图片。

```bash
python3 tools/inventory_srwz_assets.py \
  --reference-kvm ../2_translated/images/KVMDATA.BIN \
  --manifest-output manifests/asset-inventory.json \
  --force
```

完整逐 chunk/picture 结果写到被忽略的
`work/assets/asset-inventory.json`；可提交投影只含大小、哈希、数量和格式。
配置中的 member、压缩标志及 SLPS offset 表范围来自固定上游提交
`a6cefe8b51dfd949e16000442084d24594841e8f` 的
`project/archives.json`，所有读取、解压、TIM2 校验和 ISO 访问均由本仓库实现。
TIM2 header/CLUT 字段含义另与 ImageMagick 官方
[`coders/tim2.c`](https://github.com/ImageMagick/ImageMagick/blob/main/coders/tim2.c)
交叉核对；只采用格式事实，没有复制其实现。ImageMagick 本身使用其
[官方许可证](https://imagemagick.org/script/license.php)。

ImageMagick 当前可直接只读渲染单 picture TIM2，不需要本项目重复写像素
decoder。项目入口只负责从 ISO/归档定位和切出记录，以 `PNG8` 展开当前活动
CLUT，并限制 PNG 落在被忽略的 `work/`：

```bash
python3 tools/render_srwz_tim2.py KURODATA/KVMDATA.BIN \
  --chunk 5 \
  --output work/assets/render/kvm-original-05.png \
  --force
```

该入口不会导出或保存 `.tm2`，不会修改原成员。多 picture TIM2 的元数据已经
可解析，但 ImageMagick 的 TIM2 reader 拒绝多 picture 文件，因此当前渲染入口
不把“元数据可读”冒充“每一幅 picture 都能渲染”。

首个最小写回入口只接受上述 renderer 生成后再编辑的 256×256 PNG，并重建完整
`KVMDATA.BIN` 成员：

```bash
python3 tools/inject_srwz_tim2.py KURODATA/KVMDATA.BIN \
  --chunk 5 \
  --edited-png work/assets/writeback/kvm5-reference.png \
  --output work/assets/writeback/KVMDATA-noop.bin \
  --report work/assets/writeback/KVMDATA-noop.json \
  --manifest-output manifests/tim2-writeback-noop.json \
  --force
```

它不是通用 PNG→TIM2 编码器：只允许编辑图使用原图中已经实际出现的 RGBA
颜色，以原始 index→RGBA 对照重新打包低/高 nibble；header、GS registers、
CLUT、padding、chunk 长度和 archive offset 均不改。

## 2. 原盘 TIM2 范围

第一轮扫描读取 14 个 SLPS offset 归档和 3 个直接成员：

| 成员 | chunk | SRWZ 解码 | 有效 TIM2 | picture | 初步用途 |
| --- | ---: | --- | ---: | ---: | --- |
| `EFF/VEFF2DX.BIN` | 301 | 301/301 | 412 | 842 | 2D 特效和小纹理，多 picture/共享 CLUT 很多 |
| `KURODATA/KVMDATA.BIN` | 21 | 原始块 | 20 | 20 | UI atlas、立绘、机体插图 |
| `DATA/MTV_BGC.BIN` | 196 | 196/196 | 196 | 196 | 320×240 过场背景 |
| `DATA/MTV_PROP.BIN` | 23 | 23/23 | 23 | 23 | 过场 props/大图 |
| `DATA/VT1.BIN` | 14 | 12 可解码前缀、2 非流 | 9 | 16 | 背景/纹理；主字库不是 TIM2 |
| `DATA/NISVDATA.BIN` | 7 | 7/7 | 8 | 8 | UI/场景纹理 |
| `AID_DATA/AIDDATA.BIN` | 2 | 2/2 | 1 | 1 | 小型图像 atlas |
| `DATA/HSFC.BIN` | 4 | 4/4 | 4 | 4 | 图像资源 |
| `MAP/MAPMODEL.BIN` | 4 | 4 个可解码前缀 | 1 | 4 | 地图模型纹理 |
| `DATA/JTIM.BIN` | 直接成员 | 不适用 | 24 | 24 | 标题/UI atlas/场景背景 |
| `DATA/MTV_ITEM.BIN` | 直接成员 | 不适用 | 8 | 8 | 道具/人物轮廓图 |

其余已扫描归档 `MTV_PROS`、`MTVZKNRT/KW/PT` 和 `COMPDATA` 没有严格有效
TIM2。总计 712 个原始 magic 中，706 个形成完整记录、包含 1,146 个 picture；
`VEFF2DX` 的 6 个剩余 magic 没有通过完整记录边界，继续保留为未验证候选，
不计入图片覆盖。

这只是选定归档和直接成员的首轮范围，不代表 ISO 所有图像格式都已识别。
BTL 的 SEG 归档、PSS 影片、模型内嵌纹理和非 TIM2 图形仍需单独清点。

## 3. 已确认的图片内嵌文字

### 3.1 KVMDATA

`KVMDATA.BIN` 的 21 块中，20 块是 TIM2，另 1 块为 metadata。批量 contact
sheet 已在本地生成：

```text
work/assets/render/kvm-original-contact-sheet.png
```

固定上游没有图片源文件或可重复转换脚本；构建时
`tools/python/lib/kurodata.py` 只把预制的整个 `KVMDATA.BIN` 和
`KVPDATA.BIN` 复制进结果。精确比较表明：

- 原版与上游 `KVMDATA.BIN` 同为 3,335,408 字节；
- 仅 chunk 5 和 6 发生变化；
- 共 17,137 个差异字节、2,659 个不连续差异区间；
- chunk 5 是 Shop/Bazaar/Buy/Sell 等商店 atlas；
- chunk 6 是 Intermission/Robots/Pilots/Bazaar/Save/Load 等整备菜单 atlas；
- `KVPDATA.BIN` 在该固定上游结果中保持原版 SHA-256。

因此上游确实做过图片英化，但只是把预制二进制整体放回，不能由其仓库重新生成。
而且原版 chunk 4、7、11 仍可见日文栅格文字；它们在上游结果中 byte-exact
未变。当前不能把上游状态称为“图片汉化完成”。

### 3.2 VT1 标题菜单

PCSX2 原版标题页纹理转储中的 `START/LOAD/CONTINUE/LIBRARY` atlas 已反查到：

```text
DATA/VT1.BIN / chunk 6 / TIM2 record 1 / picture 0
```

资源归属不是靠文字外观猜测：运行时 512×256 RGBA 纹理与 stored 8-bpp picture
的每个 index 像素计数逐项一致；stored picture 的四个透明 index 计数之和也
恰好等于运行时的 87,096 个透明像素。此前对 `KVMDATA` chunk 2/4 的候选修改
在真实标题画面中均不可见，因此已作为负面实验排除，不进入通过清单。

固定 canary 把 picture 0 中 351 个 index `63` 原位替换为已存在的 index
`97`，不改 CLUT、其他 picture 或 TIM2 metadata。PCSX2 转储验证原颜色
`FFFF1F80` 从 351 降到 0，目标颜色 `64646480` 从 4,022 增到 4,373；
351 个变化像素全部是该 RGBA 替换，透明像素计数不变。标题画面中 `START`
亮黄色填充相应变为灰色，菜单布局和其余资源正常。

坐标级写回随后完成：固定 PSMT8 映射与原版 PCSX2 纹理逐像素一致，
`START/LOAD/CONTINUE/LIBRARY` 已替换为
`开始/读取/继续/资料库`。四张中文 mask 同时写入黄色选中和绿色未选中
八个 128×32 槽，只使用已有 index `48..79`，不改 CLUT。PCSX2 已分别截图
验证第一项和第四项选中状态；运行时转储纹理与离线预览 RGBA 哈希完全相同。
完整锁和证据见 `manifests/title-menu-zh-validation.json`。

### 3.3 JTIM

`JTIM.BIN` 的 24 个有效记录可以直接渲染。当前 contact sheet：

```text
work/assets/render/jtim-contact-sheet.png
```

record 0 的标题副标和 record 5 的 option/攻略/角色事典/用语事典/音响选择等
均是图像内文字；record 9–23 主要是场景背景。上游没有发现对应 parser、
writer 或替换文件，所以这些是中文项目新增的明确图片翻译范围。

### 3.4 MTV_ITEM

8 个记录均可渲染，当前主要看到道具和人物轮廓，没有确认需要翻译的栅格文字。
这类“已解析但未发现文字”的结论只适用于当前可见图，不扩张到其他过场归档。

## 4. 新发现的 MAPNAME 文本

`MAP/MAPNAME.BIN` 不是图片。它恰好由 195 个 256-byte record 构成，每条是：

```text
Shift-JIS payload + NUL + 全零 padding
```

`tools/srwz/mapname.py` 已严格验证 195/195 条：

- 所有 record 都有 NUL；
- NUL 后 padding 全零；
- 所有 payload 都能严格 Shift-JIS 解码；
- 195 个稳定 ID 全部唯一；
- 189 个不同文本；
- 最长 payload 30 字节。

```bash
python3 tools/parse_srwz_map_names.py \
  --manifest-output manifests/map-name-parse.json \
  --force
```

日文全文只写到 `work/parsed/map-names.json`。固定上游只有 ISO 文件清单，没有
MAPNAME parser 或译文。因此现有 94,189 条语料并非原盘全部可显示文本；正式
extractor 下一步应把 `map/name/000..194` 纳入 SurfaceSpec/语料 reconciliation。

目前只完成 parser，未批准直接写回。虽然每条有 255-byte payload 容量，中文
仍需使用游戏实际 codebook，并先证明 MAPNAME 的运行时渲染函数走主字库路径。

## 5. 复杂字体结论

本轮没有发现“另一个可直接加简体字的 TIM2 字库”。

- VT1 第 2 段的主字库仍是连续 `4,480 × 24×24/4-bpp` glyph，不是 TIM2；
- VT1 内识别出的 9 个 TIM2 记录是全屏背景、山地景观或纹理 atlas；
- chunk 6/9 的可见结果没有证据表明它们是文本字库；
- 图片内文字必须按 TIM2 atlas 单独汉化，不能靠扩主字库自动改变；
- 上游 108×4 ASCII VWF 属性是 ASM 注入的英文化数据，不是原版中文可复用的
  多字体宽度系统。

主字库当前的真实容量门仍然存在：

- 4,480 个 glyph 由原版加载循环和缓存大小固定；
- 固定文本表只静态证明 3,704 个 glyph 的映射；
- “未被该表引用”的 776 个 glyph 不等于安全空槽，仍可能由代码或其他成员
  直接引用；
- 只有末端 13 个全零槽可作为候选，4478/4479 已由 `测试` canary 分配并运行
  验证；其余 11 个还没有逐槽运行批准；
- 直接在字库末尾追加字符会越过当前解压大小、glyph count、缓存和索引范围，
  除非同时修改 SLPS loader/allocator/lookup，并做运行验证。

规模化中文字体的正确方向仍是：对全原盘 code/glyph 活性做独立扫描，优先建立
可替换槽 ledger；若容量不足，再把“扩大 glyph 表和运行时缓存”作为独立 ASM
项目，不把两者混在图片翻译里。

## 6. 写回进度与尚缺能力

当前已经完成：

1. `tools/srwz/tim2_writeback.py` 的固定 256×256/4-bpp 原位注入；
2. 合成 fixture 的 nibble 顺序、尺寸/格式/颜色/尾部拒绝和 byte-exact no-op；
3. 真实 chunk 5 的 32,768-byte image data、512-byte 16-bpp CLUT 和 archive
   几何验证；
4. 真实 no-op 的整份 `KVMDATA.BIN` byte-identical：
   `cd469075dd56c5fe1ba0c03ad4b5878b1684e7b0d22a7129c1b71cb14087f9a8`；
5. 一个离线单像素 edit：只改变 member 半开区间 `[166784,166785)`，重新
   渲染 RGBA 与编辑 PNG 完全一致，非目标字节全部不变；
6. `VT1 chunk 6 / record 1` 六 picture、共享 CLUT 的固定 512×256/8-bpp
   picture 0 index 替换，351 个 image byte 变化，container/CLUT/其他 picture
   不变；
7. clean-room greedy 重压缩、16-byte 对齐、VT1 重建和 SLPS offset 表重读；
   另外 13 个 VT1 chunk byte-exact；
8. 两次相同 ISO 构建得到
   `3214488e0dd08184db8f05cd2e8b698c772768936e24cbbe56013635bf786d5a`，
   64 个未替换成员 byte-exact、ISO9660/UDF 结构通过；
9. PCSX2 v2.6.3/PINE 标题截图和纹理转储通过，DVD、0 TLB miss，运行时
   `351/351` 像素只发生预期颜色替换。

图片“能写”到“可生产汉化”之间仍缺：

1. 把图片 surface 纳入正式 `SurfaceSpec`/译文/字体来源，而不只保留 canary
   profile；
2. 为 PS2 swizzled 4/8-bpp 图实现坐标级 index 编辑；当前 8-bpp canary 是
   不依赖坐标的全局 index 替换；
3. 每张图的文字/非文字分类、翻译 owner、字体来源和视觉布局；
4. palette/alpha 修改及 16/24/32-bpp direct-color 写回；
5. 对其他 multi-picture/shared-CLUT 布局逐 fixture 扩展，不能从本次固定
   VT1 布局外推为通用 writer。

当前可以安全继续的顺序：

1. 以已确认归属的 VT1 标题 atlas 为 fixture，补坐标级 PS2 8-bpp
   swizzle/unswizzle，并做 byte/pixel/no-op 测试；
2. 设计一处短中文图片 canary，登记译文 owner、字体来源和布局边界；
3. 重建同一 profile ISO，执行 PCSX2 视觉、纹理转储和回归；
4. 将相同方法扩展到已确认含文字的 KVMDATA/JTIM surface；
5. 并行将 MAPNAME 接入正式 extractor 和只读 surface。

不得把 ImageMagick 的 PNG 输出直接改名成 TIM2，也不得复制上游预制
`KVMDATA.BIN` 作为中文构建输入；PNG 必须经过本项目的严格布局、颜色、前像和
重渲染验证。

外部工具调查结果、固定 fixtures、`ptr2tools` 真实失败样本和最小注入器接受门
见 `TIM2_TOOLCHAIN_ACCEPTANCE.md`。
