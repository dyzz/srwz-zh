# 文档索引

以 `config/` 的锁文件和 `manifests/` 的机器可读结果为事实基线；本文档目录
解释流程和边界。被忽略的 `work/` 只是可重建缓存和本地证据，不是唯一来源。

## 当前实现与操作

| 文档 | 内容 |
| --- | --- |
| `ARCHITECTURE.md` | 仓库边界和完整构建流水线 |
| `ENGINEERING_PLAN.md` | 事实源、目标模块、验证梯度和工程实施阶段 |
| `PRODUCTION_PIPELINE.md` | 已实现的 SurfaceSpec、profile、codebook、语料和门禁 |
| `ISO_DIRECTORY_LAYOUT.md` | 原盘、中间态、最终 ISO 和运行证据目录契约 |
| `SRWZ_DATA_PARSING.md` | ISO 数据覆盖、结构解析和上游 XML 对照 |
| `ASSET_ANALYSIS.md` | TIM2 图片清单、MAPNAME 文本、图像汉化和复杂字体边界 |
| `RUNTIME_LOCALIZATION_AUDIT.md` | 基于 PCSX2 实际截图的已汉化范围、人物能力／武器／系统菜单缺口和后续优先级 |
| `IMAGE_EXPORT.md` | 按 BIN/归档层级全量导出 TIM2、调色板预览规则和覆盖边界 |
| `TIM2_TOOLCHAIN_ACCEPTANCE.md` | TIM2 writer 候选调查、真实 fixture 结果和最小注入器验收门 |
| `SRWZ_COMPRESSION.md` | 自定义压缩格式、严格解码和确定性编码 |
| `WRITEBACK_CONTRACT.md` | 文本、归档、offset 和前像保护 |
| `FONT_ANALYSIS.md` | VT1 字库格式、码位到 glyph 映射、P1 raw-trail 可寻址容量与运行边界 |
| `STATIC_CANARY.md` | `本編` → `测试` 无 hook 基础与 E2 共用字体路径 |
| `ISO_BUILD_AND_PCSX2.md` | `mkps2iso` 构建、PCSX2 和 PINE 验证 |
| `PCSX2_RUNTIME_WORKFLOW.md` | 隔离 portable 会话、memory card、savestate 谱系、启动／停止和证据回收 |
| `UI_COVERAGE_TEST_PLAN.md` | UI 场景清单、P0/P1 字库门槛、实施顺序和 PCSX2 路线矩阵 |
| `ROADMAP.md` | 按游戏内容划分的正式汉化里程碑 |
| `LESSONS_LEARNED.md` | 被证据推翻的错误判断和防复发 gate |
| `../CONTRIBUTING.md` | 贡献边界、翻译决策、验证分层和提交发布清单 |

代码模块、命令入口和“自研/上游参考/第三方工具”归属见
`../tools/README.md`。

## 调研与审计记录

| 文档 | 内容 |
| --- | --- |
| `UPSTREAM_REUSE.md` | 固定上游 Python 快照的选择和复用边界 |
| `TOOLCHAIN_ROADMAP.md` | macOS 工具链、armips 和补丁审计 |
| `ISO_TOOLCHAIN_RESEARCH.md` | 已比较的 ISO 路线及淘汰原因 |
| `STAGE_ROUTE_MAP.md` | 从游戏数据解析得到的章节/路线顺序 |

`prompts/IMPLEMENT_DECODER.md` 是首个 clean-room 解码器任务的历史验收规范，
保留用于追踪约束，不作为当前操作入口。

## 本地非提交目录

`rom/` 只放用户原盘，`work/` 保存可重建的提取、组件、authoring 和运行数据，
`build/` 保存实际运行的最终产物。具体 profile 隔离、清理边界和恢复方式见
`ISO_DIRECTORY_LAYOUT.md`。
