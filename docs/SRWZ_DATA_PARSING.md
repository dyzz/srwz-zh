# SRWZ 汉化数据解析

状态：上游汉化流程实际使用的菜单、数据库、剧情、摘要和 VT1 字库归档已经能够
从日版 ISO 基线独立解析。文本结果可与固定上游工作区逐条对照；当前对照为
94,189/94,189 条完全一致。

本页描述的数据解析阶段只做只读提取、解码和结构解析。后续已经单独实现
clean-room 编码器和通用写回 dry-run 原语，但仍没有正式成员 writer、
ISO 回包或游戏运行验证。

## 解析范围

上游 `SRWZ.py` 的汉化数据流最终使用以下五个 ISO 成员：

| ISO 成员 | 汉化用途 | 中文仓库解析 |
| --- | --- | --- |
| `SLPS_258.87` | 系统菜单、嵌入式 MIPS 文本指针、归档 offset 表、stage 函数表 | 13 个菜单 section、934 条 |
| `DATA/COMPDATA.BN` | 战斗台词、零件、武器、关卡名、能力和按钮等数据库文本 | 解码为 524,032 字节；8 个 section、1,481 条 |
| `DATA/STAGE.BIN` | 剧情说话人、胜负/SR 条件和对话 | 205 块全部解码；154 个文本 stage、91,746 条 |
| `DATA/MTV_PROS.BIN` | 过场摘要 | 14 块全部解码；12 个文本块、28 条 |
| `DATA/VT1.BIN` | 字库归档 | 14 段 offset 清单；第 2 段严格解码为 1,290,240 字节 |

ISO 共有 66 个普通文件。其余大部分为音频、影片、战斗资源、模型或上游只做整体
替换的图像归档；固定上游没有从这些文件提取额外可翻译 XML。这里不把“未见文本
解析器”扩张成“文件没有任何文字”的格式结论。

一个上游遗漏已在中文流程中补齐：`extract_all_archives()` 的白名单只有
`COMPDATA.BN` 和 `VT1.BIN`，但后续 `extract_all_summary()` 实际依赖
`MTV_PROS.BIN`。`parse_srwz_iso_data.py` 会直接切分、解码并解析
`MTV_PROS.BIN`，不依赖该白名单。

## 数据流和边界

```text
日版 ISO
  -> 7z 只读提取五个明确成员到 work/disc/
  -> SLPS/SEG 固定 offset 或 config/stage-offsets.json 切片
  -> tools/srwz/codec.py 严格解码
  -> text.py 解析 SRWZ 字符、控制码和换行
  -> menu.py / stage.py / summary.py 解析结构与指针
  -> work/parsed/srwz-data.json
  -> reference.py 对照相邻上游 XML
```

所有原始成员、解压字节和日文全文留在被忽略的 `work/`。可提交的
`manifests/iso-data-parse.json` 只保存哈希、计数和聚合对照结果。

## 稳定中间表示

每条文本均保留：

- 不依赖日文内容的稳定 ID；
- 来源文件、section 和结构 ordinal；
- 原始 pointer offset；
- stage 的 speaker ID 和 text offset；
- SLPS 的 embedded HI/LO MIPS offset；
- MTV_PROS 的固定分配长度；
- 未知编码计数。

ID 形式：

```text
menu/SLPS/04/0012
story/001/speaker/003
story/001/condition/00/01
story/001/dialogue/01.02/0007
summary/09/004
```

当前 94,189 个 ID 全部唯一，文本解码过程中没有出现未知字符码。

## 与上游结果对照

默认参考目录是相邻固定上游的 `2_translated/`。比较只使用 XML 中不应随翻译变化的
字段：

- 菜单：section、`JapaneseText`、`PointerOffset`、embedded HI/LO；
- 剧情：entry 类型、section、`JapaneseText`、`PointerOffset`、`SpeakerId`；
- 摘要：`JapaneseText`、`PointerOffset`。

真实基线结果：

| 域 | 中文解析文件 | 上游文件 | 精确相同 | 不同 entry |
| --- | ---: | ---: | ---: | ---: |
| 菜单/数据库 | 2 | 2 | 2 | 0 |
| 剧情 | 154 | 154 | 154 | 0 |
| 摘要 | 12 | 12 | 12 | 0 |

剧情的 91,746 条进一步分为 8,469 个 speaker、558 条条件和 82,719 条对话，
覆盖 7,034 个剧情 section。

对照基准的目录聚合 SHA-256 已记录在
`manifests/iso-data-parse.json`。工具发现缺文件、条目数量变化或任一字段不同时
返回非零状态，不会只比较总数。

## VT1 和字体边界

SLPS offset 表将 `VT1.BIN` 分成 14 段。严格分类结果：

- 8 段是完整 SRWZ 压缩流；
- 4 段以可解码流开头，但其后还有非零数据，记录为
  `stream_prefix_with_nonzero_tail`，不把尾部吞作 padding；
- 2 段不能按当前 SRWZ 流解码，记录错误和输入 offset。

上游字体替换只改第 2 段；该段在原版中是 599,344 字节，严格消费 599,329 字节，
尾部 15 字节全零，解码为 1,290,240 字节。其解码 SHA-256 为
`e68a24df2daaf16f472e55e0ba9b2282752bb70225aedc0bbb8aeef7713662bd`。

上游没有提供 atlas 内部 glyph 布局的解析器，而是整体替换生成好的 `2.bin`。
不过原版 `0x13C5C0` 的缓存填充循环已确认 decoded 段是连续的
`24×24/4-bpp` glyph：`glyph_index × 288`、每行 12 字节、共 24 行，
低 nibble 在左。当前工具已能无损读取、写回并渲染这些 glyph。
原版 `0x13A7AC..0x13A990` 进一步确认 `< 0x989F` 码值使用
`(lead-0x81)×192+(trail-0x40)`，更大码值线性查找
`0x3F7D70` 的 4-byte 扩展表。固定文本表 6,860 项中有 3,704 项能静态
映射到不同 glyph；完整逐项结果位于被忽略的
`work/font/glyph-code-map.json`。剩余槽位尚未据此判定为可覆盖。
`VWF_Properties.xlsx` 经只读检查包含 108 条 ASCII 记录和四个宽度列；上游将其顺序
写成 108 × 4 = 432 字节的 `font_properties.bin`，再由 ASM 注入 SLPS。它是汉化
生成输入，不是原版 ISO 中已有的宽度表。

## 使用方法

首次准备成员：

```bash
python3 tools/verify_original_disc.py
python3 tools/extract_iso_member.py \
  SLPS_258.87 \
  DATA/COMPDATA.BN \
  DATA/MTV_PROS.BIN \
  DATA/STAGE.BIN \
  DATA/VT1.BIN
```

如果 `STAGE.BIN` 已按哈希准备好，不要覆盖；只补提取缺失成员。

完整解析并对照上游：

```bash
python3 tools/parse_srwz_iso_data.py --force
```

只解析、不依赖相邻上游 XML：

```bash
python3 tools/parse_srwz_iso_data.py --no-reference --force
```

完整本地输出位于 `work/parsed/srwz-data.json`，其中包含日文原文，不能提交。

## 已完成与后续阶段

已经完成：

- 五个汉化关键成员的原版哈希验证；
- STAGE、COMPDATA、MTV_PROS 和 VT1 字库段的严格解码；
- 菜单、数据库、剧情、条件、说话人和摘要的结构解析；
- 可用于中文语料层的唯一稳定 ID；
- 与固定上游 XML 的逐条精确对照。

尚未包含在“数据解析完成”结论中的写回工作：

- SLPS/COMPDATA 文本池、STAGE 文本 arena 和 VT1 专用 writer；
- 文本池重排、pointer/embedded MIPS 写回；
- 中文字体 rasterize 和稳定槽位分配；
- ISO 回包；
- PCSX2 正常流程和运行接受性验证。

STAGE/MTV_PROS 的原生重压缩和对齐归档重建、MTV_PROS 定长文本覆盖及 SLPS
offset dry-run 已单独完成，见 `docs/WRITEBACK_CONTRACT.md`。

这些属于后续构建和运行验证阶段，不能由只读解析结果代替。
