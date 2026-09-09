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

最终 ISO、ZIP 和 xdelta 仍在 `build/`；六个 ISO 槽位及不可覆盖的冻结发布镜像见
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

历史报告中记录的原路径保持原样，查找实物时使用上表。已有 `work/saves/` 中的
同名记忆卡独立保留，不与迁入文件合并。

## 构建缓存清理

清理前先核对 `manifests/editions/{original,best}/current.json`，保留其中登记的
当前工作区及 `input_digest` 对应的共享快照，同时保留根工作区的生产组件和依赖。

本次只归档 22 个历史隔离工作区内的 `project/work/build/`。这些批次的源码快照、
原盘缓存和工具链仍在；604 份报告、日志、布局文件及预览复制回原路径。
审阅 worktree、存档和运行证据未作为缓存清理。

本地恢复清单在 `work/cleanup/work-consolidation-20260909/plan.json`，结果在同目录
`result.json`；两者也随归档保存。归档位于用户回收站中清单指定的目录，尚未永久删除。
恢复历史构建时，先核对清单，按需取回文件到独立位置；不要覆盖原路径后来生成的
新文件。清理不会增加任何运行验收结论。
