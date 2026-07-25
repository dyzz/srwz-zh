# VT1 字库与码位分析

状态：已确认 decoded VT1 字形记录为 `24×24`、4-bpp、每字形 288 字节，
并能无损读取、写回和渲染。原版 SLPS 的普通双字节分支和扩展查表均已实现；
当前 6,860 项文本表中有 3,704 项能静态对应到原版字形。glyph 4467..4479
已确认是全零、码表未分配且已解析语料无对应 token 的静态候选；其中
4478/4479 已用于 `测试` canary。PCSX2/PINE 已证明包含这两个字形的完整
decoded 字库与预期一致；Start 后 `SELECT SCENARIO` 的目标菜单显示也已实际
截图。其余 11 个静态候选槽位的运行时安全仍未证明。

## 可复现命令

```bash
python3 tools/analyze_srwz_font.py --force
python3 tools/render_srwz_font.py --force
python3 tools/render_srwz_font.py \
  --source original --all-mapped --columns 32 --scale 2 \
  --output work/font/verified-codebook-glyphs.png \
  --metadata-output work/font/verified-codebook-glyphs.json --force
```

完整 JSON 位于被忽略的 `work/font/font-analysis.json`；可提交摘要位于
`manifests/font-analysis.json`。工具只保存哈希、计数和 decoded offset，
不会把解码后的原版字库写入可提交位置。渲染图
`work/font/ascii-glyphs.png`、3,704 项原版大图
`work/font/verified-codebook-glyphs.png` 及逐格映射 JSON 也位于忽略目录。

## 原版字体段

`SLPS_258.87` 的 VT1 offset 表把 `DATA/VT1.BIN` 分为 14 段。上游替换的字体
是第 2 段：

- 原版 slice：599,344 字节；
- 实际压缩流消费：599,329 字节；
- 零填充：15 字节；
- 解码大小：1,290,240 字节；
- 解码 SHA-256：
  `e68a24df2daaf16f472e55e0ba9b2282752bb70225aedc0bbb8aeef7713662bd`。

## 已确认的 glyph 格式

原版 `SLPS_258.87` 的 `0x13C5C0` 字体缓存填充函数给出了直接证据：

- 源地址为 `decoded_font + glyph_index × 288`；
- 每行复制 12 字节；
- 共复制 24 行；
- 目标缓存每行跨 256 字节，即逻辑纹理宽度为 512 个 4-bpp 像素；
- 一个源字形因此是 `24 × 24 × 4 bit = 288` 字节；
- 每字节低 nibble 是左像素，高 nibble 是右像素。

decoded 字体段恰好包含 `1,290,240 / 288 = 4,480` 个 glyph。当前实现
`decode_glyph()`、`encode_glyph()` 和 `replace_glyph()` 已通过低/高 nibble
顺序和无损 round-trip 单元测试。

`render_srwz_font.py` 已从上游候选段直接渲染出可辨认的
`0/1/A/B/M/W/a/g/~`，因此像素格式不再是假说。

## 上游英文候选字库与 ASCII 映射

只读解码相邻上游的 `2_translated/font/2.bin` 后：

- 压缩大小：614,050 字节，无尾部填充；
- 解码大小仍为 1,290,240 字节；
- 与原版相比改变 9,648 字节、2,502 个连续差异区间；
- 首个变化位于 glyph 167 内，最后一个位于 glyph 286 内；
- glyph 167..286 的对齐区域为 120 个 glyph，其中 100 个实际改变；
- 所有变化都落在这个 `120 × 288 = 34,560` 字节区域，区域外改变 0 字节。

早先的 `108 × 320` 解释只是由相同乘积产生的巧合，已由原版复制循环和真实
字形渲染推翻。

ASCII 补丁的静态映射为：

```text
glyph = code - 0x20 + 0xBF
code >= 0x5E 时再加 1
```

因此空格为 glyph 191，`A` 为 224，`~` 为 286；glyph 253 是映射跳过的
槽位。可打印 ASCII 共 95 个槽位，上游候选实际改变其中 89 个，未改变的
glyph 是 191、201、219、221、223 和 254。`VWF_Properties.xlsx` 的
108 行则是宽度属性记录数量，不能再用来定义 bitmap record 大小。

上游同目录 `arc_font.bin` 与 `2.bin` 的实际解码结果不同，不能把它视为
`2.bin` 的可重复生成源。

## 原版 code→glyph 映射

原版 `SLPS_258.87` 的 `0x13A7AC..0x13A990` 给出了两条路径。

普通路径处理 `< 0x989F` 的码值：

```text
glyph = (lead - 0x81) × 192 + (trail - 0x40)
```

这个公式在固定文本表中覆盖 3,488 个码值。`0x989F` 及以上进入位于
虚拟地址 `0x3F7D70`、ELF 文件 offset `0x2F97F0` 的线性查找表。每项 4 字节：

```text
uint16 little-endian code
int8 row
uint8 packed_position
glyph = row × 224 + packed_position
```

原版表共有 229 项、223 个唯一 code；其中 227 项会被阈值分支访问，
按“首个匹配获胜”得到 221 个唯一 code。与固定文本表相交后有 216 个受支持
扩展码。另有 `995B/FA93/FABA/FAE5/FBE9` 五个 SLPS 表项不在
`tbl_all.json` 中。

因此固定码表的真实静态结论是：

- 文本表共 6,860 个双字节映射、6,859 个唯一字符；
- 3,488 个普通码加 216 个扩展码，共 3,704 个码有已验证字形；
- 其余 3,156 个文本表码没有原版 renderer 可证明的字形映射；
- 3,704 个受支持码引用 3,704 个不同 glyph，普通与扩展槽位重叠为 0；
- 4,480 个 glyph 中另有 776 个未被这份固定文本表引用。

`work/font/glyph-code-map.json` 为每个受支持码记录了 Unicode 字符、
glyph index 和 `glyph_index × 288` byte offset。这里的“未引用”不等于
“可覆盖”：它们可能由别的渲染路径、硬编码 UI 或运行时状态使用，仍需语料
扫描和 PCSX2 canary。

此前按 40 个 lead byte 和标准 trail 枚举出的 660 个
`candidate_unmapped` 也仍只是码位空间统计，不能替代上述 renderer 映射。

## 当前静态 canary

`config/canary/minimal-slps-font.json` 使用 code `987E/987F` 对应的
glyph 4478/4479，生成两个简体中文字形并重建 VT1 第 2 段。该路线不修改
运行时代码；详细前像、字体许可证、raster 契约和输出哈希见
`STATIC_CANARY.md`。

## 下一完成门

1. 继续对其余 glyph 建立“可显示、保留、静态候选、未知”分类，并用
   PCSX2 决定静态候选能否升级为可覆盖。
2. 扫描 94,189 条真实语料的实际 code 使用，排除硬编码和非文本引用。
3. 为中文字形确定字体来源、字号、hinting、基线和 4-bpp raster 参数。
4. 用 `replace_glyph()` 生成 decoded 字体候选，并用原生编码器重建 VT1 第 2 段。
5. 继续把“完整字库加载通过”和“具体 glyph 在目标界面正确显示”分开验收；
   未单独覆盖的槽位仍只能算静态候选。
