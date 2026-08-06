# 正式生产流水线

本页定义当前生产事实源、构建顺序和失败门。阶段性实验、旧候选哈希和研究过程
不属于生产文档。

## 1. 事实源

生产选择必须由四类输入闭包决定：

| 输入 | 位置 | 责任 |
| --- | --- | --- |
| SurfaceSpec | `config/surfaces/` 及领域配置 | 来源成员、记录、地址、容量和 renderer |
| 中文语料 | `corpus/zh/` | 译文、状态、来源哈希和术语引用 |
| Codebook／字体账本 | `config/encoding/`、`config/fonts/` | 字符、码位、glyph、字体和追加式分配 |
| BuildProfile | `config/build-profiles/`、`config/ui-*`、`config/iso/` | 本次构建允许组合的 surface 和成员 |

机器生成的 `manifests/` 是输入与结果摘要，不是手工修改后反向驱动构建的来源。
`work/` 与 `build/` 都可重建，不能存放唯一译文或唯一决策。

## 2. 数据流

```text
固定原版 ISO
  -> 严格解析与稳定记录 ID
  -> 日文来源哈希 reconciliation
  -> 中文状态、术语和结构 token 校验
  -> 字符需求与 append-only glyph 分配
  -> 行宽、行数、固定 span／arena 预算
  -> domain writer 与独立回读
  -> Rust 原生格式重编码
  -> component manifest
  -> 单候选 ISO 与 UDF/LBA 回读
  -> 匹配 ISO／存档的 PCSX2 目标流程
  -> hash-only runtime receipt
```

任一步出现来源漂移、未知 ID、缺字、无法编码字符、结构 token 变化、文本溢出、
指针前像不符、压缩预算超限、成员位移或运行证据不匹配时必须失败。

## 3. 语料状态

```text
todo -> draft -> reviewed -> final -> runtime_verified
```

- 日文原文是唯一翻译源。
- 英文、攻略和官方中文资料只能作为参考或术语证据。
- `$n/$F`、控制码、printf token、换行和遮蔽结构必须保持运行语义。
- `runtime_verified` 只授予在精确候选上实际到达并验收的记录。
- 技术 canary 位于 `corpus/fixtures/`，不计入正式翻译覆盖率。

正式 release 范围由 `corpus/releases/v1.json` 决定。术语必须引用
`corpus/glossary/` 中的独立决定，禁止对派生 TSV 或 dashboard 做孤立字符串
替换。

## 4. 解析、导出与审校

```bash
python3 tools/parse_srwz_iso_data.py --force
python3 tools/export_srwz_corpus.py --force
python3 tools/review_srwz_translations.py --check-only
```

解析输出包含 94,189 条稳定记录；含原文的完整 JSONL 只写入 `work/`，可提交
manifest 只保存计数、哈希和边界。

剧情审校至少执行：

```bash
python3 tools/audit_first_five_language_quality.py --force
python3 tools/report_story_translation_queue.py
```

当前剧情首译批处理、导入和人工二校规则见
`LOCAL_MODEL_TRANSLATION_WORKFLOW.md`。

## 5. 字体

VT1 主字库固定为 4,480 个 `24×24/4-bpp` glyph。生产规则是：

- 码位／glyph registry 首次冻结后只追加，不因语料排序变化而重排；
- 单字节可打印 ASCII 保留固定 renderer 索引；
- 中文分配必须有明确字符、码位、glyph、来源字体和使用者；
- 不把“空白”“未被当前码表引用”直接当作运行安全槽；
- 字库覆盖、完整解压和具体目标画面分别验收。

```bash
python3 tools/analyze_srwz_font.py --force
python3 tools/audit_full_chinese_font_plan.py --force
```

当前静态全量方案有 4,193 个连续中文槽，现有语料需要 1,899 个。该结果只证明
容量，不证明 raw trail、direct-index 或所有目标画面运行安全。详细结论见
`FONT_ANALYSIS.md`。

## 6. 写回

所有 writer 必须：

1. 锁定源文件大小、SHA-256 和目标前像；
2. 为每个写入区间登记唯一 owner；
3. 拒绝静默截断、未知控制码、未配对 HI/LO 和非零未授权池；
4. 完成独立反序列化、指针／offset 重读和非目标字节检查；
5. 将候选写入 profile 隔离目录，不修改原版输入。

固定 span、文本池、STAGE allocation、MTV_PROS、SLPS/COMPDATA 指针和 archive
offset 的详细契约见 `WRITEBACK_CONTRACT.md`。

## 7. 压缩

生产 profile 统一使用 `tools/native/srwz-codec-rs/` 的 clean-room Rust codec。
Python codec 保留为严格 decoder、round-trip 和结构 oracle。当前生产规则：

- 保持游戏原生格式，不引入 Deflate/LZMA 或运行时解压补丁；
- `min-match-length=3`；
- 受影响 suffix 允许保留未改变的原压缩前缀；
- COMPDATA 执行 145,408-byte／71-sector 硬门；
- 任何候选均需由独立 Python decoder 完整回解；
- archive alignment、offset、成员 LBA 和最终 ISO 分别复核。

格式和预算见 `SRWZ_COMPRESSION.md`。

## 8. 当前生产范围

当前候选组合包括：

- P10 菜单、人物／机体／武器数据库和 researched display names；
- 标题、玩家设置、幕间、战场、结算、搜索等 fixed-span UI；
- 世界史与双主人公开场资料；
- 五张中文 KVMDATA atlas；
- STAGE 001–009、018 剧情切片；
- 对应的 VT1、SLPS、COMPDATA、MTV_PROS、HB 和 STAGE 组件。

最新 ISO 的静态结构、成员与译文回读已经通过；匹配该精确 ISO 的目标场景
PCSX2 验收仍待完成。当前 P10 字库是过渡运行候选，全量中文字库尚未晋级。

## 9. 新增一个 surface

1. 在 parser 中产生稳定 ID，并固定日文来源哈希。
2. 登记 SurfaceSpec、renderer、容量和指针／offset owner。
3. 写入中文语料并引用 glossary 决定。
4. 审计 token、行宽、行数、编码和 glyph 闭包。
5. 生成或追加字体账本；禁止重排已有 assignment。
6. 运行 domain writer，验证前像、边界和独立回读。
7. 使用 Rust codec 重编码并检查 byte budget。
8. 组合 component，生成 manifest。
9. 一次构建单一 ISO，验证 UDF、成员和 LBA。
10. 在匹配存档上执行目标 PCSX2 case，并登记 hash-only receipt。

## 10. 发布门

正式补丁至少要求：

- release 范围内译文和术语状态闭包；
- 无缺字、token 变化、布局硬错误和未登记写入；
- 所有组件确定性重建；
- 当前单一 ISO 的静态、runtime 和 visual 证据闭包；
- 原版数据、ISO、存档和私有运行文件不进入发布包；
- 补丁从固定原版生成，附输入哈希、版本、许可证和复验命令。
