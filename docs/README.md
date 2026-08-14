# 文档索引

这里只保留当前规范、最终技术结论、可执行流程和待完成门禁。研究过程、候选比较、
失败路线和阶段性实验不在当前文档树中重复保存；需要追溯时使用 Git 历史。

## 从这里开始

| 文档 | 内容 |
| --- | --- |
| `../README.md` | 项目范围、当前候选、事实源和常用验证 |
| `ARCHITECTURE.md` | 数据边界、构建分层、上游与工具链归属 |
| `PRODUCTION_PIPELINE.md` | 当前生产输入、命令、写回顺序和失败门禁 |
| `RUNTIME_LOCALIZATION_AUDIT.md` | 已有运行结论、当前缺口和验收范围 |
| `LIBRARY_V02_SCOPE.md` | v0.2 完整 LIBRARY 范围、曲名保留规则和发布门 |
| `RELEASE_NOTES_V0.2.0.md` | v0.2.0 测试版新增内容、验证和已知限制 |
| `V0.2.0_TODO.md` | 不阻断 v0.2.0 测试版发布的剩余中文化与运行覆盖 |

## 最终技术结论

| 文档 | 内容 |
| --- | --- |
| `SRWZ_COMPRESSION.md` | 压缩格式、生产 Rust codec 和预算约束 |
| `FONT_ANALYSIS.md` | VT1 字库格式、code→glyph 映射和容量边界 |
| `TEXTURE_LOCALIZATION_INVENTORY.md` | 当前全部贴图改动总表：成员、chunk、TIM2、矩形、偏移、构建文件和最终 ISO 落点 |
| `MAPMODEL_WORLD_MAP_TITLES.md` | WORLD MAP 地名的 STAGE 调用链、MAPMODEL 4-bpp 格式、78 项语料和定长回写证据 |
| `KVMDATA_ATLAS_LOCALIZATION.md` | KVMDATA 固定 UI 切片、字体字重、强制索引层和中场休息实例 |
| `VEFF2DX_TEXTURE_LOCALIZATION.md` | VEFF2DX 场景选择标题的 PSMT4、quad 和定长回写方法 |
| `WRITEBACK_CONTRACT.md` | 语料状态、前像、分配、指针和归档写回契约 |
| `STAGE_ROUTE_MAP.md` | 章节顺序、主人公路线和分支映射 |

## 操作流程

| 文档 | 内容 |
| --- | --- |
| `BUILD_AND_RUNTIME.md` | ISO 构建、单候选管理、PCSX2/PINE 和运行证据 |
| `ISO_DIRECTORY_LAYOUT.md` | `rom/work/build/runtime` 目录所有权与清理边界 |
| `../CONTRIBUTING.md` | 贡献、提交和发布检查 |

代码模块与外部依赖归属见 `../tools/README.md`；机器可读结果见
`../manifests/README.md`。文档中的数字若与当前 manifest 不一致，以 manifest
和精确制品哈希为准。
