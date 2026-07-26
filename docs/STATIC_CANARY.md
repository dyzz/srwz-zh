# 最小简体中文静态 canary

状态：已生成并静态验证 `SLPS_258.87` 与 `DATA/VT1.BIN` 的本地候选副本，
并重建 ISO。PCSX2/PINE 已确认游戏自己的解压器生成了与预期完全一致的
1,290,240-byte 字库，也确认开场文本在 EE 内存中与构建预期逐字节一致。
`SELECT SCENARIO` 的实际渲染截图已经保存并通过目视检查。

## 结论

首个 canary 不需要修改或注入 MIPS 代码。原版已经把 `0x987E` 和 `0x987F`
当作双字节文本，并通过普通公式分别解析到 glyph 4478、4479。两个槽位在原版
VT1 中都是全零字形，固定码表没有使用这两个 code，94,189 条已解析文本中也
没有它们。

当前构建仍保留这个 E0 golden，但生产数据已迁到：

- surface/layout：`config/surfaces/menu-slps-opening.json`；
- 中文决策：`corpus/zh/menu.json`；
- 字形分配：`config/encoding/codebook.json`；
- 选择和 gates：`config/build-profiles/canary-menu.json`。

`config/canary/minimal-slps-font.json` 不再保存 `glyphs` 或 `text_patch`。
静态 writer 和 PINE 都从同一 profile 读取译文、assignment 和 offset。

当前候选修改 Start 后第一屏 `SELECT SCENARIO` 的上项说明：

```text
ゲーム本編をプレイします。
ゲーム测试をプレイします。
```

完整句子都是 13 个双字节字符加 `NUL`，长度 27 字节；只有 `本編`
（`96 7B 95 D2`）变为 `测试`（`98 7E 98 7F`）。文本池不增长、指针不变化。
原版 `0x139B00` 测宽路径把被替换位置的四个 code 都归到相同的默认双字节
宽度分支；句中其他字符和位置均不变。

## 原版代码证据

证据只来自固定原版 `SLPS_258.87` 的 R5900 反汇编，没有复制上游 ASM：

- `0x139B78..0x139C08`：测宽路径读取双字节 code，并把文本指针前移 2；
- `0x139CB8..0x139CF8`：不在 `0x8140..0x889E` 特殊区间时使用默认双字节
  宽度，原文和 canary 均属此类；
- `0x13A5F8..0x13A630`：绘制路径组合两个输入字节；
- `0x13A898..0x13A990`：`code < 0x989F` 使用普通 glyph 公式；
- `0x13C5C0..0x13C6B0`：从 `glyph_index × 288` 复制
  `24 × 12` 字节到字形缓存。

`config/canary/minimal-slps-font.json` 固定了这五段原版指令的文件 offset、
尺寸和 SHA-256。构建器同时确认候选 SLPS 中这些窗口完全不变：

```text
runtime hook count = 0
code injection      = false
changed code bytes  = 0
```

普通公式为：

```text
glyph = (lead - 0x81) × 192 + (trail - 0x40)
```

因此：

```text
0x987E -> glyph 4478
0x987F -> glyph 4479
```

`0x987F` 不是标准 CP932 字符，但游戏文本解析器并不按 CP932 trail 合法性
过滤；它按上述自己的双字节分支和 glyph 公式处理。这里只依赖已固定的原版
行为。

## 槽位边界

原版 glyph 4467..4479（code `0x9873..0x987F`）都是 288 字节全零记录，
但当前只分配末尾两个：

| 字符 | code | glyph | 原始字形 | 当前分类 |
| --- | --- | ---: | --- | --- |
| 测 | `987E` | 4478 | 全零 | 已分配；开场 surface 已运行验证 |
| 试 | `987F` | 4479 | 全零 | 已分配；开场 surface 已运行验证 |

静态失败门包括：

- code 已存在于固定 `tbl_all.json`；
- 94,189 条语料中的任一真实 token 使用保留 code；
- 原版 glyph 不再是固定全零前像；
- code 不能由普通公式解析到声明的 glyph；
- raster、packed glyph 或最终文件哈希漂移；
- 文本长度、宽度类别、原始字节、VT1 offset 或未分配 glyph 发生变化。

原版可执行文件和已解析语料之外仍可能存在未覆盖的运行时引用。当前 PCSX2
验证证明 4478/4479 canary 的完整字库加载成功，但不能仅据此把其余 11 个空白
槽位或全部未引用 glyph 推广为正式中文字库容量。

## 字体来源与生成参数

字体使用官方 Noto Sans CJK SC 2.004 Regular，固定到
`notofonts/noto-cjk` 提交
`f8d157532fbfaeda587e826d4cd5b21a49186f7c`，许可证为 OFL-1.1。
字体和许可证本体只下载到被忽略的 `work/font-source/`；仓库提交锁文件和
哈希，不提交 16 MB 字体。

当前 raster 契约：

- ImageMagick `7.1.2-27 Q16-HDRI arm64`；
- 72 DPI、22 pt、`24×24`、居中；
- hinting 关闭、antialias 开启；
- 8-bit gray 用整数四舍五入量化到 0..15；
- 低 nibble 为左像素，打包后每字形 288 字节。

字体、raster 和 packed glyph 任一 SHA-256 不符都会停止构建。

## 复现

```bash
python3 tools/validate_build_profile.py
python3 tools/fetch_canary_font.py
python3 tools/build_static_canary.py --force
```

输出全部位于 `work/build/canary-menu/components/`：

- `SLPS_258.87`：原尺寸，SHA-256
  `a78158abde3b5a6e4ec1861f23690d59da48afaca37d2836811b5b16ae0dbdfe`；
- `DATA/VT1.BIN`：127,501,136 字节，SHA-256
  `49b01d15102bf8544acca1aa7164523a02cf5b29dbc7c6dcf97d0ca7e2bf73fa`；
- `canary-glyphs.png`：两个量化后 glyph 的预览；
- `canary-validation.json`：完整的 byte-free 验证报告。

SLPS 只有 28 个实际差异字节：开场句中的 4 个文本字节和因 VT1 第 2 段
增长而更新的 offset 表字节；五个原版指令窗口均不变。

VT1 第 2 段现在使用 header-preserving suffix 重编码：变更前的完整压缩块
逐字节保留，只从首个受影响 block 重新编码。结果为 599,742 字节，整个 VT1
只增长 400 字节，仍落在原成员 sector allocation 内。其余 13 个 chunk 完全
不变，新 offset 全部 16 字节对齐并能从候选 SLPS 精确重读；ISO 后续成员无需
移动。PCSX2/PINE 的完整目标缓冲区哈希证明该流已被游戏解压器接受。

可提交摘要见 `manifests/static-canary-validation.json` 和
`manifests/canary-iso-validation.json`。

## 开场可见性验证

2026-07-26 使用 PCSX2 v2.6.3，以
`-nogui -fastboot -nofullscreen` 启动当前 ISO，并通过命令行
键盘映射进入 Start 后的 `SELECT SCENARIO`。上项说明实际显示为：

```text
ゲーム测试をプレイします。
```

验证材料：

- 截图：
  `work/runtime/canary-menu-current/screenshots/menu-surface.png`，
  1280×960，
  SHA-256
  `ce6fc5caf5d4f67ff06b616a52928ea69f427ff875d4b46e4abac38b19e1258c`；
- PINE：`0x0043A2EA` 的 27 字节字符串 SHA-256 为
  `d672e7dab676be4a323ae16efe42e313966e61b6cb7889bc9070ff5d14880743`，
  与构建预期完全一致；
- 完整运行时字库 SHA-256 仍为
  `cc44fa82d1581c3eb1c5852d017efbcbe8e454d4cbd9f374688c408fb236a119`；
- 256 秒日志中没有 TLB miss。

截图中 `测试` 两字完整可见、共用同一基线，没有重叠、截断或令说明句越出
现有框体。该证据只覆盖开场普通菜单渲染路径；战斗、剧情、存档和长时间流程
仍需分别验证。
