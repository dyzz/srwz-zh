# 文档索引

当前文档只保留 v0.3.0 发布说明、可执行构建流程和仍适用的工程约束。研究过程、
内部问题记录、候选比较和历史发布文档需要追溯时使用 Git 历史。

| 文档 | 内容 |
| --- | --- |
| `../README.md` | 项目介绍、v0.3.0 内容、下载与源码构建 |
| `RELEASE_NOTES_V0.3.0.md` | v0.3.0 发布说明 |
| `BUILD_AND_RUNTIME.md` | ISO、发布包和人工运行验收边界 |
| `PRODUCTION_PIPELINE.md` | 生产事实源、构建顺序与失败门 |
| `ARCHITECTURE.md` | 数据边界、构建分层和工具链归属 |
| `ISO_DIRECTORY_LAYOUT.md` | `rom/work/build` 的目录所有权与清理边界 |
| `THIRD_PARTY_FONTS.md` | 字体来源、版本和许可证 |

Python 构建入口见 `../tools/README.md`，机器可读结果见
`../manifests/README.md`。文档中的数字若与当前 manifest 不一致，以 manifest 和
精确制品哈希为准。
