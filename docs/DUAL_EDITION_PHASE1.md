# 双版本构建阶段 1：版本上下文与 Original 保真

> 本文保留阶段 1 的历史范围及结果。后续已接入 BEST 后端，最新入口与证据见 [当前 BEST 构建](BEST_CURRENT_BUILD.md)；下文的 BEST 未实现状态只适用于阶段 1。

> ISO 整理（2026-09-05）：原盘现为 `rom/original.iso` 和 `rom/best.iso`，
> 新隔离输出使用 `current-original.iso` / `current-best.iso`。本阶段下列历史构建
> 的重复 ISO 已回收；原始 receipt 和输入快照保留，其旧路径不能视为现存文件。
> 长期保留的五份镜像见 [ISO 目录契约](ISO_DIRECTORY_LAYOUT.md)。

2026-09-05。按 [六步方案](DUAL_EDITION_BUILD_PLAN.md) 实施第一阶段。**Original 已能从新入口完成构建与最终 ISO 语义读回；BEST 只注册身份契约，正式原生写回尚未接入。**

## 实现边界

| 文件 | 当前责任 |
| --- | --- |
| `config/editions/original/edition.json`、`config/editions/best/edition.json` | 独立原盘大小/哈希、ELF 身份、STAGE/COMPDATA 布局、四字段策略与可用适配器 |
| `config/release/dual-current.json` | 两版注册表；共享图鉴全开放、不写存档标志、各版原生动画政策 |
| `tools/srwz/edition.py` | 严格配置加载、只读 `EditionProfile`、`BuildContext` 和互不重叠的版本目录 |
| `tools/srwz/release_inputs.py` | 一次捕获配置、语料、manifest、工具和上游 Python 源码；用实际文件内容及模式计算快照哈希 |
| `tools/build_editions.py` | 全目标预检、每版写入锁、Original 完整构建、可选旧链保真断言、独立 ISO 和批次记录 |
| `tools/verify_editions.py` | 验证批次完整性、冻结输入、版别/原盘契约、真实 ISO 字节与语义回读记录之间的绑定 |
| `tests/test_editions.py` | 20 项身份、目录、快照、锁及错误记录拒绝测试 |

阶段 1 没有复制一份需要单独维护的生产构建器。`original-production-v1` 适配器将同一套工具与输入复制到 `work/build/zh-release-original/<run_key>/project/`，在该目录中启动子进程。工具内部现有相对路径因此落在独立目录；后续按版本写回的模块仍需逐步参数化。工具代码也进入输入快照，未提交的润色按实际内容固定，不以 Git HEAD 代替内容身份。

首次执行可复用本地原盘解包、字库下载、工具链及已审核图片的缓存，但各组件继续校验其来源锁。文件使用独立复制，APFS 支持时使用写时复制克隆，不建立可写硬链接。已审核 AIDDATA/TRICMN 索引图片仍走现有冻结快照。重定位后的 CMake 生成目录单独重建，避免旧绝对路径造成写入串目录。

本阶段强制运行完整 Original 组件链，暂未复用旧入口依赖 Git 和全局路径的增量调度器。ISO、构建日志、生成配置及缓存均在独立执行目录；最终产物复制到 `build/iso/zh-release-original/`。工作目录的现有 `srwz-zh-current.iso` 继续代表 Original。

## 执行方式

在仓库根目录运行：

```sh
# 查看身份与可用状态，不写文件
python3 tools/build_editions.py --plan

# 完整构建 Original，同时要求组件和 ISO 与现有生产输出锁逐字节一致
python3 tools/build_editions.py --editions original --require-legacy-equivalence

# 使用构建结果中返回的 batch_manifest
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original.json
```

后续润色改变了输出字节时，可省略 `--require-legacy-equivalence`。该选项只增加与快照中旧生产输出锁的一致性断言，省略后仍检查原盘、各组件及最终 ISO 读回。

目前直接执行默认目标 `original,best` 或 `--editions best` 会在任何构建写入和原盘扫描之前失败，并报告 BEST 原生写回未实现。不会先重建 Original 再失败，也不会调用冻结的 `build_best_candidate.py`。

## 实际验证

本轮基于 `bac4b88` 的生产锁，从新入口重建 Original，以下为本次产物身份：

| 项目 | 结果 |
| --- | --- |
| 输出 | `build/iso/zh-release-original/current-original.iso` |
| 大小 | 3,758,358,528 字节 |
| SHA-256 | `c1d4d44821919553b257a870686abbe1a25d1cacc135eb712220db9bc9afcaef` |
| 旧链保真 | 23 个替换成员的大小/哈希及最终 ISO 哈希全部一致 |
| ISO 语义读回 | 170 个 STAGE 记录、93,071 条译文 |
| 自动测试 | `python3 -m unittest discover -s tests`：216 项通过（包含新增 20 项） |
| 批次记录验证 | `edition_batch_receipt_integrity_passed`；仅 Original，`both_editions=false` |
| 生产目录隔离 | 当前 ISO、原 ISO 配置、完整组件配置和语义回读 manifest 的前后哈希均相同 |
| 本版记录 | `manifests/editions/original/current.json` |
| BEST 正式产物 | 未构建；身份注册不代表写回已实现 |
| PCSX2 / LRPS2 | 本轮未运行，`runtime=not_tested` |

最终输入哈希为 `b931aec48fbeda0f5db2cee4ed77bc5bc0b0280ad9a182fc4073e76b371b8eec`，构建后核验与当前实际输入文件一致。具体快照、独立执行目录、语义回读文件及哈希由本版记录提供。完整构建/测试日志、`isolation.json` 和 `batch-verification.json` 存放于本地 `work/analysis/dual-edition-phase1-20260905/`；这些本地记录不替代模拟器验收。

## 下一阶段

按阶段 2 从 BEST 原生 ELF 接入字库、归档目录和中文功能补丁的明确前值契约，继续保留 BEST 官方代码修改并应用现有全开放语义。不得用统一地址差或删除成员/前值检查来消除版本冲突。随后完成来源绑定、BEST STAGE 正式写回与其他资源，最后开放同一批次的双 ISO 构建及跨版语义比较。
