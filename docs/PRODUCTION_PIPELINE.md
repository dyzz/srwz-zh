# 正式生产流水线

本页定义当前生产事实源、构建顺序和失败门。阶段性实验、旧候选哈希和研究过程
不属于生产文档。

## 1. 事实源

生产选择必须由四类输入闭包决定：

| 输入 | 位置 | 责任 |
| --- | --- | --- |
| 领域配置 | `config/story-component.json`、`config/assets/` 及各 writer 配置 | 来源成员、记录、地址、容量和 renderer |
| 中文语料 | `corpus/zh/` | 译文、状态、来源哈希和术语引用 |
| Codebook／字体账本 | `config/encoding/`、`config/fonts/` | 字符、码位、glyph、字体和追加式分配 |
| 组合配置 | `config/full-story-components.json`、`config/iso/` | 本次构建允许组合的领域和成员 |

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

正式 release 范围由 `corpus/releases/v1.json` 决定。术语必须引用
`corpus/glossary/` 中的独立决定，禁止对派生 TSV 或 dashboard 做孤立字符串
替换。

## 4. 原版成员与审校

```bash
python3 tools/verify_original_disc.py
python3 tools/extract_iso_member.py \
  SLPS_258.87 DATA/VT1.BIN DATA/STAGE.BIN DATA/COMPDATA.BN \
  DATA/NISVDATA.BIN DATA/HSFC.BIN BTL/SRVC.BIN BTL/SRVC.SEG EFF/VEFF2DX.BIN
python3 tools/extract_iso_member.py MAP/MAPMODEL.BIN
python3 tools/prepare_zh_release_font.py --force
```

原版成员只从锁定 ISO 明确提取到忽略的 `work/disc/`。正式日文基准和中文决定
已经按领域保存在 `corpus/ja`、`corpus/zh` 和 `corpus/glossary`；生产 builder
直接解析锁定成员并按稳定 ID、原文哈希和结构 token 对账，不消费预生成的总解析
报告。

审校结果直接落入 `corpus/zh` 和 `corpus/glossary`；模型输出、TSV、网页队列和
阶段性 review JSON 均为可删除中间物，不属于生产闭包。

## 5. 字体

VT1 主字库固定为 4,480 个 `24×24/4-bpp` glyph。生产规则是：

- HarmonyOS Sans SC 1.0 是剧情、UI、图集和战斗对话的统一字体家族；
  VT1 动态字库的默认 flavor 为 `config/fonts/zh-localization-font.json`
  （Regular），场景配置只保留字号、画布、基线和字节预算；
- 固定静态图集可以在同一官方字体家族内登记受锁字重。当前仅
  `ui-intermission-atlas-zh` 使用
  `config/fonts/zh-localization-font-light.json`，并对标题和七个菜单统一使用
  Light；这不改变 VT1 的 Regular 字形；
- 原始字体和许可证只下载到忽略的 `work/font-source/`，提交物保留官方压缩包、
  archive member、大小和 SHA-256 锁；
- HarmonyOS Sans 缺少的 `〜∀♪` 只允许通过全局 flavor 中的明确 Noto fallback；
  任何非空白可见字符产生全零 raster 都直接失败；
- `config/fonts/zh-font-base.json` 只定义 VT1 布局、codec 和全局 rasterizer；
  `config/fonts/zh-release-font.json` 是唯一活动字体 profile；
- `config/encoding/zh-release-font-assignments.json` 是唯一活动码位／glyph 快照，
  首次冻结后只追加，不因语料排序变化而重排；
- `%s/%2$s/%d…`、`$c/$f/$l/$n/$F`、`{XX}` 与 `@?<tag:XX>` 统一走
  既有无损控制语法，不拆成字形；字库覆盖只把“30%”中的字面 `%` 计为显示字符，
  遇到 `%02d`、`$q` 等未登记但疑似占位符的语法则直接失败、禁止猜测；
- 新增字符可使用任一 renderer 可寻址的双字节位置，包括当前发布映射未占用的
  原日文位置；ASCII、控制码、已占用主映射／别名和结构兼容映射不回收；
- 单字节可打印 ASCII 保留固定 renderer 索引；
- 中文分配必须有明确字符、码位、glyph、来源字体和使用者；
- 不把“空白”“未被当前码表引用”直接当作运行安全槽；
- 字库覆盖、完整解压和具体目标画面分别验收。

```bash
python3 tools/fetch_zh_font.py
python3 tools/fetch_zh_font.py \
  --flavor config/fonts/zh-localization-font-light.json
python3 tools/update_zh_release_font_snapshot.py --apply
python3 tools/rebuild_zh_font.py --refresh-manifests --refresh-asset-ratchets
```

`rebuild_zh_font.py` 只生成一次 `zh-release-font`：它扫描 `corpus/zh`
下所有使用运行时字体的非空 `translation` 字段，因此菜单、数据库、全文剧情和
后续战斗对话共用同一份字符→码位→glyph 映射。已经离线渲染进纹理的
`corpus/zh/ui-atlas/*.json` 由配置显式排除并逐文件锁定 SHA-256，不占用 VT1
码位；其像素与几何仍由各图集构建器验证。随后独立回读固定大小 VT1，并依次重建 154 个
STAGE 块、六组 UI 图集、组合图集和最终整合组件。KVMDATA 与 VEFF2DX 的
不同排版边界分别见 `KVMDATA_ATLAS_LOCALIZATION.md` 和
`VEFF2DX_TEXTURE_LOCALIZATION.md`。

最终组合消费 `release-base-ui` 的四个固定成员，并证明其映射是全局 release
快照的严格子集；历史分期不再进入活动配置和工具目录。

`--refresh-asset-ratchets` 只用于确认过的全局字体变更，并要求同时刷新 manifest；
日常复验省略该选项。后续战斗对话只需把翻译 JSON 放入 `corpus/zh`，新增字符会
由 `update_zh_release_font_snapshot.py` 从锁定的剩余候选中只追加、不重排
旧映射；updater、prepare、verifier 都会拒绝单字符模式区的新映射。随后重建
release，不再创建新的 VT1 profile。

当前静态 release 有 3,419 个主映射、693 个 surface-safe 别名，剩余追加候选槽为
264。“邓”使用的默认宽度槽来自一个在完整活动语料中出现次数为 0 的片假名
surface-safe alias；原片假名主码位未改动，回收记录固定在分配快照 extension 中。
该结果只证明当前语料覆盖、容量和组件回读，不证明
所有 raw trail、direct-index 或目标画面的运行安全。底层容量分析见
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
Python decoder 只保留源码供隔离的格式研究和对照测试，任何生产与静态验收入口均不
调用。当前生产规则：

- 保持游戏原生格式，不引入 Deflate/LZMA 或运行时解压补丁；
- 生产链统一使用 `rust-fit`，match 参数由当前 profile 锁定；
- `rust-fit` 重压完整 decoded payload，不继承旧 Python encoder 的 block；
- COMPDATA 执行 145,408-byte／71-sector 硬门；
- 任何候选均需由 Rust decoder 完整回解；
- 同一物理压缩流先解码一次，在 decoded workspace 完成全部有序写入与前置检查，
  最后只压缩一次并做一次最终 Rust 回读；
- 当前 `COMPDATA.BN` 的六组写入共用一个 workspace，`STAGE.BIN` chunk 0 的概览与
  系统对白共用另一个 workspace；
- archive alignment、offset、成员 LBA 和最终 ISO 分别复核。

格式和预算见 `SRWZ_COMPRESSION.md`。

## 8. 当前生产范围

当前候选组合包括：

- 基础 UI 组件中的菜单、人物／机体／武器数据库和 display names；
- 标题、玩家设置、幕间、战场、结算、搜索等 fixed-span UI；
- 世界史与双主人公开场资料；
- 六张中文 KVMDATA atlas；
- MAPMODEL 成员 81..195 的全部已审校 WORLD MAP 地名标题；
- 154 个 STAGE 剧情块、STAGE/HSFC 概要和完整 SRVC 战斗字幕；
- 全局 `zh-release-font`、KVMDATA 六图和 VEFF2DX 场景标题。

当前 v0.1.0 ISO 已完成静态结构、16 个组件和统一整盘内容回读；
`manifests/zh-release-full-story-iso-content-validation.json` 与当前精确哈希一致。
匹配 v0.1.0 精确哈希的新游戏、读档和目标战斗字幕运行验收仍待完成。

## 9. 新增一个 surface

1. 在 parser 中产生稳定 ID，并固定日文来源哈希。
2. 在对应领域配置中登记 renderer、容量和指针／offset owner。
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
