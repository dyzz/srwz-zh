# 工程规划

状态：方向基线，E1 最小输入骨架已开始实施。本文规定 SRWZ 中文工程从首个
两字 canary 发展为可持续汉化流水线时的事实源、模块边界、验证层次和实施
顺序。已落地的 SurfaceSpec、codebook、中文语料和 BuildProfile 契约见
`PRODUCTION_PIPELINE.md`；本文不表示所有模块已经完成，也不替代
`ROADMAP.md` 中按游戏内容划分的里程碑。

## 1. 目标与边界

本工程的目标不是维护一组可以偶然生成中文 ISO 的脚本，而是建立一条可以从
固定日版 ISO 重复执行、逐组件审查、对错误 fail-closed、最终生成不含原版数据
补丁的汉化生产线。

工程方向吸收 `sdgundam/ref-project` 已验证的原则，但不复制 NDS 专属实现：

1. 日版游戏是唯一事实源；
2. 所有可汉化数据只通过一个正式提取层进入工程；
3. 日文事实、中文决策和生成产物分离；
4. 地址、记录几何和渲染约束各有唯一归属；
5. 正式构建是从原版到候选结果的一次变换，不允许 patch-over-patch；
6. 每个组件都有来源、输出、差异所有者和验证结果；
7. 静态、PCSX2 运行和视觉证据互不替代；
8. 每个真实事故都必须修正生产器，并留下能 RED→GREEN 的防回归门。

当前不作为工程规划重点：

- 补齐全部说明文档；
- 立即重命名或移动现有目录；
- 大规模翻译或发布补丁；
- 在尚未证明数据方案不足前设计运行时 hook；
- 为了统一外观而重写已验证的 clean-room 模块。

## 2. 事实源

每类事实只允许有一个正式所有者。其他文件只能引用或由它生成。

| 事实 | 正式所有者 | 是否提交 | 规则 |
| --- | --- | --- | --- |
| 原版字节 | `rom/srwz.iso` | 否 | 必须匹配固定大小和 SHA-256 |
| 原版成员与解析结果 | 正式 extractor 生成的 `work/` snapshot | 否 | 不手改；由公开 manifest 固定聚合哈希 |
| 地址、表结构、记录几何 | `config/surfaces/` | 是 | parser 和 writer 必须读取同一份定义 |
| 中文译文 | `corpus/zh/` | 是 | 只保存中文决策、稳定 ID 和来源哈希 |
| 术语和编辑决策 | `corpus/glossary/` | 是 | 跨 surface 使用同一 canonical 词条 |
| 字符到游戏码位 | `config/encoding/codebook.json` | 是 | 字体、编码器和检查器共用 |
| 字形来源与生成参数 | `config/fonts/` 和字体生成配置 | 是 | 产物必须确定性生成 |
| 文本池/码位/空洞分配 | allocation ledger | 是 | 分配提交后不可被另一所有者复用 |
| 上游逆向知识 | `vendor/` + `config/upstream.lock.json` | 是 | 固定提交、可比较、不得依赖未提交状态 |
| 构建结果 | 机器生成 manifest | 是 | 不能人工宣称通过 |
| 运行和视觉结论 | evidence record | 是或外部固定引用 | 必须绑定具体构建哈希和 surface |

日文全文是否进入 Git 与事实源原则无关。当前项目继续采用本地重新提取：日文
正文留在 `work/`，仓库提交稳定 ID、来源成员哈希、source-text SHA-256、计数
和聚合摘要。

## 3. 目标流水线

```text
日版 ISO
  -> source verification
  -> canonical extractor
  -> local JP snapshot + public extraction manifest
                                      |
corpus/zh + glossary -----------------|
surface/layout registry --------------|
codebook + font source ----------------|
                                      v
                           production build profile
                                      |
                           per-surface domain writers
                                      |
                     SLPS / COMPDATA / STAGE / MTV_PROS / VT1
                                      |
                         component manifest + static gates
                                      |
                               PS2 DVD ISO build
                                      |
                    PCSX2/PINE runtime + visual acceptance
                                      |
                              patch/release manifest
```

`config/canary/` 当前是首个研究型纵向切片。它已经只引用
`config/build-profiles/canary-menu.json`，不再拥有独立译文、码位和 surface
offset；后续也只能作为 build profile 的 golden/fixture 环境。

## 4. 模块边界

目录是否立即调整不重要，以下逻辑边界必须逐步成立。

### 4.1 Core

无文件 I/O 副作用、可单元测试的规则：

- codec：文本 token 和压缩流的严格编解码；
- layout：成员、归档、表、指针和虚拟地址/文件 offset 关系；
- font：code→glyph、glyph pack、raster 和字宽；
- corpus：稳定 ID、译文状态和 reconciliation；
- writeback：前像、所有者、分配、重定位和差异计划；
- archive：chunk 编码、对齐、offset 表和重读；
- verify：组件级不变量和 gate 注册。

当前 `tools/srwz/` 继续承担 core 角色。可复用逻辑不得回流到顶层 CLI。

### 4.2 CLI/orchestration

负责参数、磁盘 I/O、外部工具和步骤编排，不重新实现 core 规则。最终收敛为
一个主入口，具体命令名称可以后定：

```text
srwz verify-source
srwz extract
srwz reconcile
srwz build --profile canary-menu
srwz verify --profile canary-menu
srwz release-check
```

现有 `tools/*.py` 在迁移期继续可用；新功能优先进入 core，再由薄入口调用。

### 4.3 Domain writers

writer 面向语义记录，不面向一次性文件 offset。计划分为：

| writer 类型 | 第一批目标 | 主要责任 |
| --- | --- | --- |
| embedded/pool | SLPS、COMPDATA | 定长覆盖、池分配、普通指针和 MIPS HI/LO |
| summary | MTV_PROS | allocation、chunk 重编码、SLPS offset 表 |
| story | STAGE | 文本 arena、speaker、内部指针、归档和 HB offset 表 |
| font | VT1 | 字符需求、码位、glyph、chunk 和 SLPS offset 表 |
| executable | SLPS/ASM | 前像、允许区间、写入所有者和代码补丁审计 |
| container | PS2 DVD ISO | 成员替换、顺序/LBA、UDF/ISO9660 和输出哈希 |

所有 writer 都返回组件 bytes 和结构化 metadata，不直接修改原版或最终 ISO。
每个 writer 的通用输出契约应至少包含：

```text
component id
source size/hash
output size/hash
semantic owners
changed ranges
pointer/offset updates
allocation usage
round-trip/reparse result
warnings and failed gates
```

## 5. Surface registry

`ref-project` 最值得迁移的设计之一，是读取和写入共享同一个布局事实源。SRWZ
应建立统一的 `SurfaceSpec`，逐步替代散落在 CLI、canary 配置和文档里的地址。

每个 surface 至少声明：

```text
surface_id
source_member
record identity rule
layout/table geometry
parser
codec profile
render/font profile
writer type
allocation model
byte and pixel limits
static gates
runtime fixture
```

首批 surface：

1. `menu/slps/opening-select-scenario-description`；
2. `menu/compdata`；
3. `summary/mtv-pros`；
4. `story/stage`；
5. `font/vt1/main-24x24`；
6. `map/mapname/fixed-records`；
7. `image/kvm/*` 和 `image/jtim/*`。

同一文本如果在多个渲染路径出现，应登记为多个 surface acceptance，不能因为
在一个菜单中显示正常就推断其他路径同样安全。

## 6. 提取与 reconciliation

正式 extractor 是唯一允许从原版产生语义记录的路径。研究脚本可以帮助发现
格式，但一旦结论进入生产构建，必须迁入正式 extractor/layout。

长期必须有两道独立门：

### extraction_fresh

从固定原版重新提取，结果的记录集合、稳定 ID、来源位置和聚合哈希必须与当前
manifest 一致。提取算法变化时，重新生成结果并审查差异。

### zh_reconciliation

双向检查：

1. 每条 `corpus/zh` 记录必须唯一命中正式 extractor 的 JP 记录；
2. 一个独立于正式 extractor 的扫描/结构检查器发现的可显示记录，也必须被
   extractor 覆盖。

第一方向防止陈旧译文和错位 key；第二方向防止 extractor 与 writer 一起遗漏
相同区域而形成“内部一致、实际不完整”的假绿。

## 7. 语料状态

正式翻译记录至少包含：

```text
id
domain/kind/surface
source member hash
source text hash
translation
editorial status
notes / glossary references
```

在生产语料冻结前，应将“编辑状态”和“运行验收”分离：

```text
editorial_status: todo -> draft -> reviewed -> final
runtime_acceptance:
  - surface_id
  - build/profile id
  - component/ISO hash
  - evidence id
  - result
```

原因是同一译文可能出现在多个 surface，且旧构建上的一次运行成功不能自动证明
新字体、新 writer 或新 ISO 上仍然成功。当前 `runtime_verified` 线性状态可在
迁移期保留，但不能成为最终发布模型。

## 8. Codebook、字体和分配

正式 codebook 必须同时是编码器、字体 writer、缺字检查和运行 evidence 的
输入。禁止在单个 canary 或 writer 中私有分配字符。

分配规则：

1. 字符需求只从选定 profile 的最终译文和必要 UI 字符计算；
2. 已有映射保持稳定，除非有明确迁移和全量重编码；
3. “原版为空”只表示候选，不表示可用；
4. 候选码位和 glyph 必须经过语料引用、原版引用、代码引用和运行路径审计；
5. 每个已分配槽位进入 ledger，记录所有者、前像和证明；
6. codebook 与 VT1 字形必须在同一组件构建中一起验证；
7. 字体段大小、压缩语法、offset 和运行时完整解压哈希都是门禁。

当前 `987E/987F` 与 glyph 4478/4479 只作为已验证 canary 分配；其中
`987F` 证明原 renderer 能实际消费一次 `0x7F` 尾字节。P1 世界史 profile
另把反汇编证明可寻址的 `0x7F/0xFD/0xFE/0xFF` 空隙登记为
`raw_standard_addressable` 离线候选，不把它们升级为运行安全槽；每种实际
使用的新 trail 类仍须在精确组件／ISO 上单独绑定 PCSX2 证据。

## 9. Build profile 和一次构建

profile 只选择要构建的语义内容和验收范围，例如：

```text
canary-menu
canary-summary
canary-story
content-alpha
release
```

profile 不保存原始游戏字节，不重复保存译文，也不写私有 patch 逻辑。它引用：

- entry ID 集合或状态过滤器；
- surface 集合；
- codebook/font policy；
- writer 集合；
- 必须通过的 static/runtime/visual gates。

正式构建必须从固定原版开始执行一次变换。禁止：

- 先生成已知错误产物再运行 fixer；
- 从上一版中文 ISO 继续打补丁；
- writer 之间通过临时修改同一文件传递隐式状态；
- 手工修改生成后的 manifest 来宣布通过。

## 10. Manifest

manifest 分三层：

### Source manifest

固定原版、成员、上游提交、字体和工具链输入。

### Component manifest

由本次构建自动生成，记录每个组件的输入/输出、语义 owner、差异、分配和重读
结果。它是构建产物，不是人工编写的状态报告。

### Acceptance/release manifest

把确定的 component/ISO 哈希绑定到 static、runtime 和 visual evidence。候选
构建与正式发布哈希分开；候选变化不应被误报为 release anchor 失败。

仓库可以提交不包含游戏字节的公开投影，但投影必须由完整报告自动生成并有
freshness gate，不能长期维护两份人工摘要。

## 11. 验证梯度

所有变更按以下顺序升级：

```text
unit tests
  -> component round-trip/reparse
  -> static component/ISO gates
  -> offline render oracle
  -> PCSX2 fresh-boot smoke
  -> targeted PINE/runtime fixture
  -> full-screen + field crop visual judgment
  -> clean-copy release rebuild
```

每一层只证明自己的范围：

- static 证明结构和字节不变量；
- offline oracle 证明已建模的字形、控制码、宽度和框体关系；
- PCSX2/PINE 证明游戏实际加载、解压和执行；
- visual 证明最终像素没有重叠、裁切、基线、错字或邻区污染；
- clean-copy rebuild 证明没有依赖当前脏工作区或缓存。

第一批工程 gates：

| gate | 目标 |
| --- | --- |
| `source_baseline` | 原版及关键成员匹配 |
| `extraction_fresh` | 提取结果未漂移 |
| `zh_reconciliation` | JP/zh 双向覆盖 |
| `codec_roundtrip` | 严格 consumed/output 一致 |
| `codec_game_grammar` | 禁止游戏解压器不接受的块语法 |
| `component_diff_allowlist` | 未登记字节变化为零 |
| `archive_layout` | chunk、对齐、padding 和 offset 重读 |
| `pointer_semantics` | 普通指针、HI/LO 和表项指向正确 owner |
| `font_codebook_consistency` | 码位、glyph、字形和容量一致 |
| `asset_roundtrip` | TIM2 像素、CLUT、header、padding 和容器重读一致 |
| `slot_liveness` | 分配目标无现有引用或所有者冲突 |
| `text_budget` | 字节、行数、框体和文本池不过载 |
| `iso_layout` | 成员、顺序、LBA、UDF/ISO9660 和 DVD 判定 |
| `runtime_evidence_fresh` | evidence 与当前构建哈希绑定 |
| coverage ratchets | 已关闭的 JP/缺字/未知 surface 数量不能回退 |

每个新 gate 必须证明“有牙齿”：

1. 保留最小、可公开或可由 mutation 生成的已知错误条件；
2. 错误条件必须令目标 gate RED；
3. 修复结果必须 GREEN；
4. gate 名称、事故 ID 和保护的不变量互相引用。

“所有 gates 通过”只表示已知事故类型受到保护，不表示未知缺陷不存在。

## 12. Offline render oracle

94,189 条文本不可能依赖人工进入游戏逐条检查。M2 前后应建立 PS2 文本离线
渲染模型，逐步覆盖：

- 24×24/4-bpp glyph；
- code→glyph 普通/扩展分支；
- 控制码、换行和终止；
- 每个 surface 的真实 advance；
- 行宽、框体、标点禁则和裁切；
- 字形空白、错位、风格和未知码位。

oracle 必须用当前 PCSX2 实际截图校准。每次字体、测宽或绘制路径发生变化，都
需要重新做 parity；oracle 不能替代运行时控制流和长时间稳定性测试。

## 13. 运行证据

runtime fixture 必须描述如何从 fresh boot 到达目标 surface，并且“没有到达”
算失败而不是跳过。证据至少绑定：

```text
profile/build id
ISO hash
PCSX2 version and launch mode
game id
target surface
reached-state proof
PINE addresses/hashes where applicable
log summary/hash
screenshot hash
verdict and known limits
```

首个 `测试` canary 是 `menu/slps/opening-select-scenario-description` 的 golden
fixture。它证明普通开场菜单，不证明战斗、数据库、剧情、存档或其他字体路径。

## 14. 事故与经验

未来的经验记录不是开发日志，而是错误理论和永久门禁之间的索引。每条至少应有：

```text
incident id
believed
why plausible
broken/disproven by
root cause
truth/invariant
producer fix
guard
RED fixture
affected components/surfaces
```

经验的归宿：

| 内容 | 长期位置 |
| --- | --- |
| 历史错误和推理过程 | lessons catalog |
| 当前仍有效的约束 | architecture/binding rules |
| 自动防回归 | gate + RED fixture |
| 本次构建事实 | manifest/evidence |

首批应固化的 SRWZ 事故：

1. clean-room round-trip 通过但 zero-literal 块触发游戏 post-tested copy loop
   下溢：生产器必须满足游戏运行语法；
2. `mkisofs` 成员内容正确但 PCSX2 将镜像识别为 CD：容器语义和介质判定必须
   独立验证；
3. 原版空白 glyph 只代表候选：只有明确分配并在具体 surface 运行验证的槽位
   才能进入 codebook。

## 15. 实施阶段

当前实施快照：

| 阶段 | 状态 | 已落地 | 尚缺 |
| --- | --- | --- | --- |
| E0 | 已完成 | component/ISO/runtime/visual 哈希链和事故 gates | 后续只允许显式更新 golden |
| E1 | 已完成 | SurfaceSpec、中文记录、codebook、`canary-menu`、reconciliation 和固定 component/ISO lock | 后续统一 CLI 属于 E3 工程化 |
| E2 | 已完成 | menu、MTV_PROS summary、STAGE growing dialogue 三类 writer/profile/fixture；三条独立 PCSX2 证据和完整组合 smoke | 扩大语料前进入 E3 |
| E3 | 进行中 | 前五关和世界史布局门、P0/P1/P2 UI 字库、fixed-span writer、1,307 项动态名、两个 embedded fresh-boot 分区的 P3 slice、静态组合 UI ISO、五张中文 atlas 独立候选和 21 用例运行矩阵 | P3／atlas 运行归属、余下名称、其余 embedded UI、离线 render oracle 和逐屏证据 |
| E4–E5 | 未开始 | E2 可复用 clean-room 生产基础 | 在 E3 退出条件满足后实施 |

### E0：冻结首个纵向切片

目标：把当前两字 canary 固定为可复现 golden，不再继续向专用 canary 追加能力。

交付：

- 当前 source/component/ISO/runtime/visual 哈希链；
- canary 所覆盖和不覆盖的 surface 边界；
- zero-literal 和 ISO/CD 事故对应的生产器 gate；
- 当前实现按逻辑组件进入可审查 Git 提交。

退出条件：

- 干净工作区能够重建相同 canary ISO；
- 当前测试、上游快照、组件校验全部通过；
- runtime/visual 证据能够由 manifest 定位；
- 无生产步骤依赖旧故障 ISO 或手工修复。

### E1：建立正式 extractor-first 生产骨架

目标：用正式 `corpus/zh` 记录和生产 writer 重建同一个菜单 canary。

交付：

- surface/layout registry 最小版本；
- `extraction_fresh` 和 `zh_reconciliation`；
- 正式 codebook 中的 `测/试` 分配；
- `canary-menu` profile；
- component manifest 自动生成；
- 一个统一 build/verify 编排入口。

退出条件：

- canary 配置不再直接拥有 replacement text；
- 修改 `corpus/zh` 是改变菜单译文的唯一方式；
- parser 和 writer 不再各自维护该 surface 的地址；
- 新路径生成与 E0 相同或经显式批准的新 golden。

### E2：三类 surface canary

状态：已完成。`canary-summary` 使用固定 allocation 和 suffix 重编码；
`canary-story` 在原条目 allocation 加相邻零 slack 中容纳增长文本，并对
pointer 前像、重读、HB offset、归档对齐和非目标 chunk 自动门禁。三个隔离
ISO 分别通过 PCSX2 运行与画面验证，`canary-complete` 组合 ISO 另通过菜单、
摘要和剧情加载 smoke，详见
`manifests/canary-complete-validation.json`。SLPS/COMPDATA pool writer
也已完成普通 pointer、MIPS HI/LO、零池、对齐、溢出和重读单元门禁；当前菜单
canary 仍刻意使用已验证的原位定长 allocation。

目标：证明菜单、数据库/摘要和剧情三种数据/渲染路径。

交付：

- SLPS/COMPDATA pool writer；
- MTV_PROS production writer；
- STAGE arena/pointer/archive writer；
- 通用 VT1/font writer；
- `canary-menu`、`canary-summary`、`canary-story`；
- 三条独立 PCSX2 runtime fixture。

退出条件：

- 三种 canary 都从正式 corpus/codebook/profile 构建；
- 每种 surface 都有 static、runtime 和 visual 证据；
- 文本增长、对齐、offset 和指针语义由自动门禁保护。

### E3：规模化验证

目标：在扩大翻译前，让全量静态和离线检查可重复运行。

交付：

- offline render oracle 及 PCSX2 parity；
- 全量 encodability、glyph、行宽和文本池检查；
- coverage ratchets；
- evidence freshness；
- clean-copy deterministic build。

退出条件：

- 所有选定译文可以批量编码和离线渲染；
- 未知字符、空字形、框体溢出和未登记差异均为零；
- 已知错误 mutation 能令对应 gates RED。

### E4：翻译生产

目标：按 surface 和内容域逐批扩大，而不是一次全量写回。

顺序：

1. 系统菜单和短标签；
2. 机体、驾驶员、武器、技能和摘要；
3. 序章/教程剧情；
4. 主人公路线；
5. 共通和分支路线；
6. 图像内嵌文字及特殊路径。

每批都必须带：

- glossary/review 结果；
- component manifest；
- coverage 变化；
- offline render findings；
- 受影响 surface 的运行证据。

### E5：发布

目标：从固定原版生成不含原版字节的用户补丁。

退出条件：

- clean-copy 两次构建一致；
- 全组件和最终 ISO hash 固定；
- 全路线/关键存档/战斗路径回归；
- release manifest 与证据完整；
- 补丁格式证明不能重建或携带未经授权的原版数据。

## 16. 当前代码的迁移定位

| 当前实现 | 长期定位 |
| --- | --- |
| `tools/srwz/codec*.py` | production core，继续强化 |
| `tools/srwz/corpus.py` | corpus/reconciliation 基础 |
| `tools/srwz/project.py` | 已实现的 profile/SurfaceSpec/codebook reconciliation |
| `tools/srwz/writeback.py` | 通用计划与分配基础 |
| `tools/srwz/writers.py` | domain writer 起点 |
| `tools/srwz/font.py` | 正式 font writer 基础 |
| `tools/srwz/canary.py` | E0 golden 构建器，能力迁出后不再扩张 |
| `build_static_canary.py` | 迁移期入口，最终由 profile build 替代 |
| `build_canary_iso.py` | container writer/validator 基础 |
| `verify_pcsx2_font_runtime.py` | runtime harness/PINE 基础 |
| 当前 `manifests/*.json` | E0 证据基线，后续改由构建自动投影 |

迁移采用“包住并替换”，不重写已验证算法：

1. 先为现有逻辑补正式输入/输出契约；
2. 再把 canary 特有数据移到 corpus、codebook 和 profile；
3. 保持旧 golden 做 differential；
4. 新路径完全覆盖后才退休旧入口。

## 17. 当前优先队列

1. E3：为综合测试 ISO 取得六份原生 memory card，并执行 14 个非映射逐屏
   用例；每个结果必须绑定精确 ISO、PINE、日志、截图／序列和断言；
2. E3：继续用五张隔离中文 atlas 候选逐一完成截图和
   421／2,292／3,634／2,083／1,262 像素 texture-delta 双门；综合候选中的
   同一图片不能替代场景归因；
3. E3：继续按官方术语／人工确认批次扩展当前 1,493 个尚未满足 researched
   精确传播门的非空名称字段，并补全 offline render oracle、coverage ratchet、
   evidence freshness 和 clean-copy deterministic build；
4. 对同一候选 ISO 完成 PCSX2 逐屏路线后，再扩展 P1/P2 和后续剧情。

E0-E2 已完成：SurfaceSpec、正式 `测/试` codebook、三域 `corpus/zh`、
四个隔离/组合 profile、自动 component manifest，以及菜单、摘要、剧情三条
独立 PCSX2 fixture 均已落地。P0 的 418 条 SLPS 与 44 条 COMPDATA 静态菜单
文本也已由 fixed-span profile 全部覆盖。动态显示名现已完成全结构解析和
开场 45 字段组件；researched 精确切片另选 1,262 项，并以 29 个新
allocation、4 个退役 assignment 复用和 29 个重绘字形完成统一 renderer。
标题、P0 菜单、合计 1,307 项动态名、P2 字库和世界史已经进入静态验证的
`ui-p2-core` ISO。五张中文 atlas 均已有独立、等长、零 LBA 位移候选；测试
专用 P3 综合镜像另把两个 fresh-boot embedded UI 分区的 23 条决定、五图
suite 和前五关 `HB/STAGE` 合入 P2 UI，完成 7 成员静态容器验收并锁定
21 个运行用例。余下 1,493 个非空名称、其余 embedded UI、五张 atlas 的
运行归属和逐屏运行验收仍未覆盖。

工程规划期间不把“文档数量”“脚本数量”或“单元测试数量”当作完成标准。每一阶段
是否完成，只由该阶段声明的可重建产物、机器门禁和运行/视觉证据决定。
