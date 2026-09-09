# 剧情／战斗台词扩容安全审计（2026-09-05）

结论：当前 Original 版生产制品通过了本轮源数据、全量重建、写入边界和 ISO 回读检查，
未发现扩容越过所属文本池、损坏主指针、增加 decoded 大小或移动 ISO 成员 LBA。
STAGE 对内部地址引用的检查仍不完整，当前生产 ISO 的目标运行验收也未完成；
因此结论是“当前制品的已识别结构与存储边界安全”，不能提升为“任意扩容均安全”或
“全剧情／全战斗运行时安全已证明”。

本轮只作审计并保存报告，没有修改生产 writer、语料、构建配置或 ISO，没有 commit/push。
不包含 `build_best_candidate.py` 的 Best 版迁移算法。

## 版本与证据绑定

| 对象 | 本轮核对值 |
| --- | --- |
| 中文仓库 HEAD | `bac4b88b112f0da8b7b8680b2a4d1e015a976d40` |
| 上游对照 | `fortiersteven/Super-Robot-Wars-Z`，本地锁定提交 `a6cefe8b51dfd949e16000442084d24594841e8f` |
| 当前生产 ISO SHA-256 | `c1d4d44821919553b257a870686abbe1a25d1cacc135eb712220db9bc9afcaef` |
| 剧情基础组件 STAGE SHA-256 | `ed0077cccf79d3daca5e3e285555ed62f7815ea277c00ecfe3dd451ec90a1898` |
| 最终集成 STAGE SHA-256 | `848dfc4caa8ac810151112fa114765cfdddd68ab158889596037144878e4e9b7` |
| 最终 SRVC.BIN SHA-256 | `42d5bb1b40daf03aaf9da1b60a7d77e645aee0ef794483123ecd3bad8b3fcf6a` |

上游本地 HEAD 与 `config/upstream.lock.json` 一致，对照的 `stage.py`、`SRWZ.py`、
`project/archives.json` 无工作区修改。尝试 `git ls-remote` 时远程返回
`Repository not found`，故本报告不声称已比较上游最新提交。

中文仓库已有的 `config/editorial/`、`tests/test_polish_feedback_pilot.py`、
`tools/editorial_review/build_polish_feedback_pilot.py` 不属于本次审计改动。

## 与上游实现的区别

| 层次 | 锁定上游 | 当前中文生产实现 | 安全含义 |
| --- | --- | --- | --- |
| 剧情 payload | `stage.py::insert_XML_text()` 从最早对白位置开始连续写入，字符串按 4 字节对齐，然后更新 XML 中的指针 | `writers.py::repack_stage_texts_in_place()` 只使用 parser 确认的原字符串及其至下个 16 字节边界的连续零填充 | 中文实现限制了可复用空间，不把文本之后所有内容都视为可覆盖区 |
| 剧情记录覆盖 | 上游写回依赖所选 XML 条目 | 当前要求全关可重定位对白／条件集合精确覆盖；说话人随 payload 编码 | 不允许只移动一部分记录后清空共享文本区 |
| STAGE 压缩归档 | `SRWZ.py::pack_stage_archive()` 连续拼接、重新计算 chunk offsets，并写回 HB 的 `0x7670` 表 | 每个 chunk 重压后必须不超过原 span；补零至原长；HB 不变 | 当前不需要为扩容修改归档 offset 或磁盘布局 |
| STAGE 额外指针 | 对照写回路径未见完整 alias 所有权检查 | 只允许 parser 主指针、运行时关键词／编队结构指针和锁定的非指针例外 | 已解决已知的 9 个起点同值候选，但不能推出所有引用形式都已覆盖 |
| SRVC | 上游配置只将其定义为 `compressed=0`、由 `SRVC.SEG` 分段的归档；该锁定版本未找到字幕文本池 writer | 独立解析索引、压紧同一 chunk 的完整文本池、重写相对 text offset | SRVC 安全性由本项目的结构与回读证据支持，不能归因于“沿用上游已验证字幕扩容” |

上游定位：`../tools/python/lib/stage.py:247`、`../tools/python/lib/SRWZ.py:1206`、
`../project/archives.json:94`。本地生产定位：`tools/srwz/writers.py:1269`、
`tools/build_story_component.py:1356`、`tools/srwz/srvc.py:343`、
`tools/build_full_story_components.py:7018`。

## 本轮重新执行的检查

1. 关闭增量缓存，调用 `build_story_component.build(..., incremental=False)` 重建全部
   170 个 STAGE，返回的 STAGE/HB 与现有基础组件逐字节相同；没有覆盖生产输出。
2. 对源 STAGE 全部 205 个 chunk 与基础组件解码比较，重新计算 parser 所有文本区间，
   核查 placement 对齐、范围、不重叠、主指针、类型契约、辅助 ticker／Z Report 槽位。
   **所属区间及允许的指针字段以外，变化字节数为 0。**
3. 独立调用 SRVC 生产构建入口，58,740 条记录重建／回读通过，输出与现有组件
   逐字节相同。再次按原文本池及索引 offset 字段建立字节掩码，**范围外变化为 0**。
   头部、metadata、未索引尾部、65 个零记录 chunk、SEG 和总文件大小保持。
4. 重新运行 `verify_full_story_iso_content.py`，不使用已有回读缓存：170 个 STAGE、
   83,668 条对白、670 条条件、8,733 条说话人，共 93,071 条翻译回读通过，
   报告中的 62 项检查均为真。
5. 比较原盘与成品 ISO：66 个成员的 LBA 全部相同；STAGE、HB、SRVC.BIN、SRVC.SEG
   大小保持，成品成员与当前组件逐字节相同。再解码成品 STAGE 全部 205 个 chunk，
   decoded 大小均与原盘一致；84,338 个主指针仍指向审计 placement；STAGE 140 的
   `0xF720` 保持原非指针数值。
6. `tests.test_stage_repack_safety`、`tests.test_srvc`、`tests.test_codec_worker`、
   `tests.test_compressed_workspace` 共 **21 项测试通过**。另做了下述内部引用隔离反例。

### 当前容量数据

| 指标 | STAGE 剧情／条件 | SRVC 战斗字幕 |
| --- | ---: | ---: |
| 覆盖 | 170 个 STAGE，84,338 条可重定位物理记录 | 353 个 chunk，其中 288 个有索引；58,740 个物理记录 |
| 严格原槽超限 | 557 个物理记录，484 个 placement，涉及 130 个 STAGE | 29 个逻辑 ID，88 个物理记录，涉及 28 个 chunk |
| 最大单条增量 | 18 字节（包含说话人／换行／NUL 的 payload） | 24 字节（含 NUL） |
| 最小剩余量 | 170 个剧情基础组件压缩块的最小余量为 20 字节 | 实际有扩容记录的 chunk 最小池余量为 222 字节 |
| 额外信息 | 166 个 STAGE、84,092 个物理记录发生地址变化 | 全部索引池合计 2,165,802 字节，使用 1,653,034，释放 512,768 |

STAGE 的“20 字节”是剧情基础组件所选 170 个块的压缩余量；整个成品 STAGE 的
205 个块中最小余量为 5 字节（chunk 204），不能混用统计范围。所有块均未溢出。
SRVC 有 14 个其他 chunk 的池余量为 0，但其中没有本次统计的超原槽实例。
池总余量不能跨 chunk 借用，压缩余量也不是 decoded 文本池可用容量。

当前 SRVC 最大增量是 `battle:09162`，chunk 120 / record 22，37 → 61 字节；
其次 `battle:21270`，chunk 285 / record 91，35 → 57 字节。两者含原文外语及中文说明，
应列为单句长度、换行与实际停留时间的运行验收目标。最紧的扩容池是 chunk 51，余 222 字节。

## 未闭合的安全检查

### P2：STAGE 内部引用不受当前起点同值门保护

`writers.py:1478` 的扫描只匹配 `target_offset in selected_source_offsets`。
若存在指向说话人之后的正文、字符串后缀或填充区的引用，它既不会被拒绝，也不会进入
类型契约；`tests/test_stage_repack_safety.py:59` 还明确测试内部同值 word 保持不变。
保持一个字段的原值，并不能证明其目标文本重排之后该引用仍有效。

本轮隔离反例添加两个直接对白记录和一个指向第一条正文内部的额外引用：

- 额外字段 `0x50` 指向 decoded `0x226`，原来读到 `There`；
- 主文本重排后，第一条由 `0x220` 移到 `0x200`，第二条由 `0x200` 移到 `0x220`；
- writer 正常返回，额外字段仍指向 `0x226`，现在读到第二条的 `Yes`。

这是验证门的可复现缺口，**不是当前生产游戏已发生串词的证据**。

本轮扩大扫描，发现当前源盘 31 个位于 owned regions 外、数值指向其内部／填充的
4 字节对齐候选。剧情 writer 均未改写这些字段：

- 5 个已经通过锁定编队清单定位为 `record6+23` 字符串字节：STAGE 043 的
  `ティンプ` 一处，STAGE 128 的 `アーキタイプ` 四处。最终组件对其翻译是所属编队
  文本的正常改动，不属于指针重写。
- 剩余 26 个呈现数值表／记录字段形态，最终 ISO 仍保持其原 4 字节。本轮没有将其
  擅自标为真指针，也没有将仅凭局部数值模式的推断提升为已验证类型契约。

例如 STAGE 104 `0xC540` 的值是 `0x00770011`，恰好落到旧文本 `0x19920` 的
第二字节；STAGE 140 `0xF65C` 恰好命中旧文本的对齐填充。数值命中本身不能证明指针。
完整候选及前像在 `final-stage-binding.json`。

若要把“引用安全”升级为强保证，应先裁决这 26 个候选，再对整个 owned interval
建立类型化引用检查：已知非指针保留，真引用按明确语义迁移，未知类型拒绝。
禁止恢复“凡数值相等就重写”的旧做法。本轮也没有证明所有拆分 MIPS 地址构造、
非对齐或相对引用形式均已穷尽。

### 当前重排范围大于必要扩容范围

builder 对全部 170 个 STAGE 无条件调用整关重排；166 个发生地址变化。
其中 **36 个没有任何严格原槽超限记录，仍发生机械搬移**。
这与 `TEXT_CAPACITY_EXPANSION.md` 所写的“无必要超槽时保持原槽”不一致。
它不是本轮发现的越界故障，但使依赖重定位正确性的范围大于实际扩容范围。
是否改为仅对需要扩容的关卡重排，应作为独立生产变更处理并重新构建验证。

### 文档快照已落后

`TEXT_CAPACITY_EXPANSION.md` 首页“9 个候选仍未解决”已不符合当前生产实现：
本轮重新构建通过的类型契约计数是关键词 1、编队 7、非指针 1。
其 SRVC “2 个逻辑 ID／14 个物理实例／最大 +2”也已变成当前的 29／88／+24。
`STAGE_TEXT_REPACK_INVENTORY.md` 的 2026-09-03 快照也不能替代本轮最新统计。
旧文档作为历史决策证据保留，判断当前容量请使用本报告及绑定的机器结果。

## 运行时证据范围

已读取现存第一关 50 句 canary 的 LRPS2 receipt，状态为 `passed`，绑定的是
`aa7a5eddca95c32fb335d4b45ad3b0cd6b26b419946c5ac185f7ef9bb016dd26`，
不是当前生产 ISO。本轮没有重新运行 LRPS2 或 PCSX2。

该 receipt 能支持特定 canary／节子路线／输入序列的历史运行结论，不能覆盖当前
170 个 STAGE、关键词／编队 alias 的全部分支或 29 条 SRVC 扩容台词。
当前回读可证明文件、指针和文本内容一致；还不能证明每个文本消费者的临时缓冲区、
显示时长、翻页与人物切换都接受新长度。

运行验收优先覆盖：STAGE 002 的关键词 alias，7 个编队 alias 所在关，STAGE 140
数值表相关流程；SRVC 的最大两条增量及 chunk 51；新游戏／读取存档进入关卡，
完整战斗动画中字幕换行与人物切换。每项应绑定当前 ISO 哈希，仍保留 `runtime_pending`。

## 本地证据与复跑

证据目录：`work/audit/text-capacity-safety-20260905/`（忽略目录，未提交原盘衍生数据）。

| 文件 | 内容 |
| --- | --- |
| `fresh-story-build.json` | 无缓存剧情重建与现有组件哈希／字节一致性 |
| `audit.py`、`audit.log` | 源区间／写入掩码、SRVC 重建、ISO 边界和最终指针复核 |
| `stage-byte-audit.json` | 全部 STAGE 容量与超槽 placement、31 个内部地址候选 |
| `srvc-byte-audit.json` | SRVC 全量报告、88 个扩容实例、逐 chunk 容量 |
| `iso-member-boundaries.json` | 原盘／当前 ISO 的 LBA、大小和成员哈希 |
| `final-stage-binding.json` | 最终 ISO 主指针、非指针字段、31 个候选分类 |
| `final-chunk-budgets.json` | 最终 STAGE 全部 205 个块的压缩预算 |
| `interior-reference-reproducer.json` | 内部引用缺口的隔离样本结果 |
| `iso-readback.json` | 本轮完整生产 ISO 回读结果 |

从仓库根目录复跑逐字节审计：

```sh
python3 work/audit/text-capacity-safety-20260905/audit.py
```

复跑全量 ISO 回读时使用新的报告名，或明确传入 `--force` 覆盖审计报告：

```sh
python3 tools/verify_full_story_iso_content.py \
  --report work/audit/text-capacity-safety-20260905/iso-readback.json --force
```
