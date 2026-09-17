# 本地 work 目录

项目本地工作数据统一放在 `srwz-zh/work/`，即本仓库根目录下的 `work/`。
父目录 `Super-Robot-Wars-Z/work/` 已合并移除，后续存档、构建缓存和验证记录均使用
本仓库的目录。`work/` 被 Git 忽略，不提交原盘数据、组件或记忆卡。

## 分类

| 路径 | 内容与保留边界 |
| --- | --- |
| `work/saves/` | 原始存档、记忆卡和测试副本；按来源分目录，不能用同名文件覆盖 |
| `work/runtime/` | 模拟器配置、运行记录、截图及场景证据 |
| `work/review/` | 审阅材料、验证报告和登记中的 Git worktree；保留未提交的源码修改 |
| `work/review/community-web/` | 社区网站修改前副本、补丁和验证记录 |
| `work/release/<version>/` | 发布过程日志、上传文案和发布操作记录 |
| `work/cleanup/` | 清理前清单、迁移路径、文件身份与恢复位置 |
| `work/build/` | 当前组件、按版本隔离的构建工作区和共享输入快照 |
| `work/disc/`、`work/font-source/`、`work/toolchain/` | 构建所需的原版成员缓存、字体及工具链 |
| 其他现有子目录 | 分析、编辑、写回、审计等专项材料；按用途保留 |

长期镜像改为 `build/chd/` 下的日文父 CHD 与汉化子 CHD，xdelta 和补丁 ZIP 留在
`build/release/`。ISO / ISO ZIP 仅按需临时生成；保留与还原规则见
[ISO 目录契约](ISO_DIRECTORY_LAYOUT.md)。

## 父目录迁移

2026-09-09 合并时的路径映射如下，迁移文件逐一核对大小与 SHA-256：

| 原父目录路径 | 本仓库路径 |
| --- | --- |
| `../work/save/` | `work/saves/parent-work/` |
| `../work/v0.4.0发布说明.txt` | `work/release/v0.4.0/发布说明.txt` |
| `../work/recent-review-results-20260906/` | `work/review/community-web/recent-review-results-20260906/` |
| `../work/library-review-site-20260908/` | `work/review/community-web/library-review-site-20260908/` |
| `../work/library-navigation-groups-20260908/` | `work/review/community-web/library-navigation-groups-20260908/` |
| `../work/library-compact-20260908/` | `work/review/community-web/library-compact-20260908/` |
| `../v0.3.0发布说明.txt` | `work/release/v0.3.0/v0.3.0发布说明.txt` |
| `../v0.4.0发布说明.txt` | `work/release/v0.4.0/v0.4.0发布说明.txt` |
| `../BISLPS-25887S7` | `work/saves/parent-work/BISLPS-25887S7` |
| `../tmp/` | `work/analysis/parent-tmp-20260828/` |
| `../local-archive/r14-finalization-20260809T150227Z/` | `work/review/legacy-r14-finalization-20260809/`，保留审阅、运行记录及报告 |

历史报告中记录的原路径保持原样，查找实物时使用上表。已有 `work/saves/` 中的
同名记忆卡独立保留，不与迁入文件合并。两份 v0.4.0 文案内容不同，分别保留为
`发布说明.txt` 和 `v0.4.0发布说明.txt`。

## 构建缓存清理

清理前先核对 `manifests/editions/{original,best}/current.json`，保留其中登记的
当前工作区及 `input_digest` 对应的共享快照，同时保留根工作区的生产组件和依赖。

首次合并时归档了 22 个历史隔离工作区内的 `project/work/build/`。这些批次的源码快照、
原盘缓存和工具链仍在；604 份报告、日志、布局文件及预览复制回原路径。
审阅 worktree、存档和运行证据未作为缓存清理。

用户随后要求积极清理不必要文件。2026-09-09 已永久删除本次发布清理中登记的旧
构建缓存、旧 R14 authoring 数据、Python/Finder 缓存和多余 ISO；不再保留这些文件
在回收站中的副本。删除前核对并保留了对应的报告、截图和脚本，以及六个 ISO 槽位、
发布包、存档、当前工作区和未提交源码。

首次迁移清单在 `work/cleanup/work-consolidation-20260909/plan.json`。后续文件迁移
记录在 `work/cleanup/file-cleanup-20260909/result.json`，永久清理清单和证据保留
路径在同目录 `permanent-cleanup.json`。这些记录保留历史文件身份，不能再作为从
回收站恢复已删除大文件的指引；复验历史批次时需从固定输入重建。清理不会增加
任何运行验收结论。

## 2026-09-17：CHD 保存与构建缓存清理

两份日文父 CHD、v0.4.1 两份子 CHD、v0.4.2 四份子 CHD 全部重新提取并核对
原 ISO 哈希后，删除本体 ISO、ISO ZIP、重复镜像和旧候选。两代父盘以硬链接共用数据。
清理旧隔离构建中的生成游戏二进制，以及根工作区和私有工作区的 ISO 装配数据；
当前组件、共享输入快照、源码、报告、布局、运行截图与存档保留。
Special Disc 的原盘、候选及正在进行的分析不在此次清理范围。

清理记录、逐文件删除清单、源码保护校验和 ISO 还原脚本位于
`work/cleanup/chd-only-20260917/`。构建前需按需从父 CHD 还原 `rom/original.iso`
或 `rom/best.iso`；旧历史 receipt 仍记录原始路径，不意味着临时 ISO 继续存在。
