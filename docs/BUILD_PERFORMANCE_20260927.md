# 构建流程整理与耗时复测（2026-09-27）

本轮把日常构建统一到 `python3 tools/build_editions.py` 一个入口，去掉三类重复：同一 ISO 在一次构建里被反复整盘哈希；工具目录里任意文件（包括 `tools/README.md`）变动都会让整套组件缓存失效并升级为强制全量；SP 的每个写入器进程各自还原一遍基线镜像、写入器串行执行。校验点没有减少，只去掉重复计算与不必要的失效。

后续已加入 SP 组件增量，本文下方的 SP 全量说明为优化当时的状态；最新依赖规则、实测及
增量／全量等价证据见 [SP 增量构建实测](SP_INCREMENTAL_BUILD_20260927.md)。

## 实测结果

| 场景 | 修复前 | 修复后 | 口径 |
| --- | ---: | ---: | --- |
| Original+BEST，工具源码（`tools/srwz`）有改动 | 154.2 秒 | 111.3 秒 | 组件层按自身指纹全量重建剧情组件；修复后仍复用逐字形字体栅格、复用工具链 |
| Original+BEST，只有语料改动（承接上一批缓存） | 61.6 秒（仅 Original，2026-09-22） | 47.7 秒（两版） | 组件 6.6 秒、封盘 0.1 秒（增量，0 个变更成员）、回读 20.1 秒、BEST 17.1 秒 |
| Original+BEST，相同输入重跑 | 15.2 秒（三版） | 5.6 秒首次／0.6 秒（进程内） | 首次需把当前盘与日常副本身份写入缓存；之后无整盘哈希 |
| SP 完整构建 | 108.9 秒 | 53.4 秒 | `sp-full-text` 96.0 → 49.4 秒 |

Original 各阶段（语料改动、承接缓存）：

| 阶段 | 2026-09-22 | 本轮 |
| --- | ---: | ---: |
| iso-toolchain | 4.995 | 0.144 |
| components | 19.050 | 6.640 |
| iso | 10.259 | 0.098 |
| readback | 17.202 | 20.063 |
| 日常副本复制、哈希与 skip 验证 | 1.572 | 0.044 |

SP 各阶段：`write_system_text` 17.7 → 16.8 秒，`migrate_stage_dialogue` 7.7 → 6.1 秒，`migrate_srvc` 4.3 → 2.6 秒，`write_frame_text` 11.0 → 2.6 秒，`write_image_labels` 11.1 → 3.1 秒（后三者与 system→STAGE 链并行，组件阶段 51.8 → 29.7 秒）；封装含独立回读 43.9 → 19.6 秒，其中回读与发布 13.5 → 1.0 秒。

均为本机已有缓存条件下的实测，不代表空缓存冷启动。上表“修复前”取自 `work/editions/9d9f525e…/original-best.json`、`work/editions/a70810ac…/sp.json` 与 [2026-09-22 复核](BUILD_PERFORMANCE_20260922.md)。

## 修改内容

1. **统一哈希入口 `tools/srwz/file_identity.py`。** 每个文件身份（设备、inode、大小、mtime、ctime）只计算一次 SHA-256；进程内记忆全部文件，≥1 MiB 的摘要写入 `work/cache/file-identity.json`，同一构建的所有子进程通过 `SRWZ_FILE_IDENTITY_STORE` 共享。摘要只在文件稳定后记录（mtime 早于 2 秒且哈希前后身份不变）。`release_inputs.copy_file` 的 APFS 克隆继承来源摘要；`publish_verified` 在原子改名后保持绑定（改名会改变 ctime）。ISO 成员哈希（`iso9660.sha256_member`）按同一身份缓存区间摘要。原先分散在 8 处的 `sha256_file` 实现（`build_iso`、`build_release`、`archive`、`verified_cache`、`release_inputs`、`build_text_update_iso`、`rebuild_zh_font`、SP 工具）全部委托给该模块。`--force-rebuild` 或 `SRWZ_REHASH=1` 禁用持久层。
2. **冻结输入只含构建定义。** `release_inputs.is_build_input` 把 `*.md`、写作辅助脚本（`editorial_review/`、`rebalance_story_dialogue.py`、`build_story_unbroken_words.py`）、导出／审阅工具、LRPS2 运行工具、模板和开发期汇编源排除在输入快照之外。
3. **缓存承接范围。** `edition_incremental.seed_text_update` 只在 `COMPONENT_BUILD_DEFINITION_ROOTS`（与 `rebuild_zh_font` 的链缓存共用，定义在 `srwz/build_fingerprints.py`）内出现“不是上一批次自身刷新”的变化时才拒绝；与上一批次输出逐字节一致的回执／锁同步回仓库不算变化。承接内容新增上一批次的 ISO 基线与增量回执。
4. **不再自动升级为强制全量。** `build_editions` 只在用户传 `--force-rebuild` 时给组件层加 `--force-rebuild`、给封盘加 `--refresh-extraction`；其余情况组件层自行判断，`rebuild_zh_font` 的全量路径也传 `--reuse-raster-cache`，只有字体来源、fallback、rasterizer 与分配表完全一致时才复用逐字形栅格。
5. **增量封盘真正可用。** `build_iso` 的增量回执改为按源盘与上一输出的内容哈希绑定（schema 2），私有工作区里的克隆基线可以命中；克隆走 `copy_file`。
6. **工具链。** `bootstrap_mkps2iso.py` 在固定 commit 与版本行匹配时不再重跑 CMake；`reset_relocated_cmake` 只删除 CMake 状态，保留已构建的可执行文件。`build_text_update_iso._verify_original_iso` 对新 inode 的同一原盘按锁定 SHA-256 重新绑定，不再每个私有工作区重跑一遍 Redump 四哈希审计。
7. **SP。** `special_disc/baselines.export_baseline` 由 `build_full_text.py` 还原并校验一次基线，通过 `SRWZ_SP_BASELINE_TEXT_CANARY` 交给写入器与 `verify_full_text.py`，子进程只核对大小与（已缓存的）哈希；system→STAGE 链与 SRVC、frame、图像写入器并行；临时 ISO 用克隆代替整盘复制；SP 也承接根工作区的 Cargo target。
8. **入口收敛与文档。** 删除 `build_best_candidate.py`（及其测试）与 `update_qa_editions.py`；`README.md`、`tools/README.md`、`CONTRIBUTING.md`、`PRODUCTION_PIPELINE.md`、`BUILD_AND_RUNTIME.md`、`BUILD_EDITIONS.md` 统一以 `build_editions.py` 为唯一日常入口，分步命令降为排错用途，版本号与输出路径改为 v0.4.2 与 `build/iso/zh-release-*/`。提交前检查去掉 `verify_original_disc.py`、`compileall` 与两条 `--help`。新增 `tools/prune_edition_workspaces.py`（默认只列出，`--apply` 才删除）。

## 验证与边界

- 全部单元测试通过（501 项，6 项按环境跳过），新增 `tests/test_file_identity.py` 以及承接规则、CMake 状态、SP 基线共享、原盘重绑定的用例。
- Original 与 BEST：语料改动前后、只加换行再还原的两次构建，ISO 哈希均为 `59f1b177…`／`3f4da20d…`，与本轮前最后一次构建一致；增量封盘识别出 0 个变更成员。
- SP：本轮 ISO 为 `892689db…`，与 09-23 相比 system、frame、image-labels 组件逐字节一致，STAGE 与 SRVC 因 09-25／26 的本篇语料（SP 通过 `stage-context-reuse` 与共享战斗台词复用）而变化；把两者的写入器单独串行重跑，输出哈希与并行运行完全相同。
- 文件身份缓存不改变任何校验点：所有“大小 + SHA-256 必须等于锁”的判断保持原样，只是同一身份的摘要不再重复计算；就地写入、替换、复制或克隆都会得到新身份并重新哈希。
- 未做：`verify_full_story_iso_content.py` 的逐 STAGE 增量回读（约 20 秒 Python 语义校验是语料更新后最大的固定成本；需要按块记录输入指纹的旁路回执，设计要点见下节）；BEST 后端每次完整重解码（约 17 秒）；语料改动后的 SP 仍是完整重建；发布策略已定为全部内置 skip：`freeze_release.py` 取代 `prepare_release_variants.py`，`build_release.py` 新增 schema 4（每版一份补丁并回读 skip hook），v0.4.2 的 schema 3 配置仍可重建。
- 未运行 PCSX2 或 LRPS2；本轮不构成运行验收。

## 后续：逐 STAGE 增量回读的设计要点

`verify_full_story_iso_content.py` 目前先证明 25 个替换成员与组件输出逐字节一致，再对整盘做一次完整语义回读；`--refresh-manifest` 路径不读取其验证缓存，且 ISO 在脚本内被哈希两次（第二次现已由身份缓存吸收）。剩余约 20 秒中绝大部分是 170 个 STAGE 块、93,071 条条目的 Python 语义校验（布局、编码、说话人、条件、引号风格）与 340 次 `parse_stage`。可行的增量方案：

- 自然单位是 STAGE 块而非成员。每块的输入为最终块与原版块的字节、`SLPS` 中该块的函数地址、由码表 proposal 投影的文本表、`corpus/zh/story-dialogue/stage-NNN.json`、`story-conditions.json` 与 `story-speakers.json` 中该关卡子集、布局 profile 以及组件报告中的该关卡记录。
- 需要一份独立于 manifest 的旁路回执，为每块保存上述输入指纹与该块的完整逐块记录（现有报告的 `stages` 已含偏移、大小、哈希与计数，但缺输入指纹与聚合所需的明细）。
- 未变块直接沿用记录；聚合值（总数、最大宽度、引号风格计数、动态条件关卡集合、玩家选择回读、第 2／16 话专项）从逐块记录重建；`apply_stage_keyword_popups` 已支持 `changed_stages`/`prior_report`。
- `SLPS_258.87`、`HEDBDY/HB.BIN` 与码表 proposal 变化时必须整盘重跑；增量结果的 manifest 必须与 `--force` 全量逐字节相同，并以此作为等价测试。

结构化记录：`manifests/editions/build-performance-20260927.json`。
