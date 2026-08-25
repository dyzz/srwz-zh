# 文档索引

当前文档只保留 v0.3.0 发布说明、可执行构建流程和仍适用的工程约束。研究过程、
内部问题记录、候选比较和历史发布文档需要追溯时使用 Git 历史。

| 文档 | 内容 |
| --- | --- |
| `../README.md` | 项目介绍、v0.3.0 内容、下载与源码构建 |
| `RELEASE_NOTES_V0.3.0.md` | v0.3.0 发布说明 |
| `BUILD_AND_RUNTIME.md` | ISO、发布包和运行验收边界 |
| `AUTOMATED_RUNTIME.md` | LRPS2/libretro.py 逐帧按键、截图与本地 receipt |
| `PRODUCTION_PIPELINE.md` | 生产事实源、构建顺序与失败门 |
| `ARCHITECTURE.md` | 数据边界、构建分层和工具链归属 |
| `ISO_DIRECTORY_LAYOUT.md` | `rom/work/build` 的目录所有权与清理边界 |
| `THIRD_PARTY_FONTS.md` | 字体来源、版本和许可证 |

## 技术参考

以下文档保留格式研究、资源定位和写回约束。部分文档会记录形成当前配置时使用的
维护命令；v0.3.0 的现行发布入口仍以 `BUILD_AND_RUNTIME.md` 为准。

| 文档 | 内容 |
| --- | --- |
| `SRWZ_COMPRESSION.md` | SRWZ 压缩格式、Rust codec 和容量约束 |
| `FONT_ANALYSIS.md` | VT1 字库结构、码位与 glyph 映射 |
| `WRITEBACK_CONTRACT.md` | 文本、指针、归档和前像写回契约 |
| `TEXTURE_LOCALIZATION_INVENTORY.md` | 贴图中文化成员、格式和最终 ISO 落点 |
| `KVMDATA_ATLAS_LOCALIZATION.md` | KVMDATA 图集结构与写回方法 |
| `VEFF2DX_TEXTURE_LOCALIZATION.md` | VEFF2DX PSMT4 场景标题结构 |
| `MAPMODEL_WORLD_MAP_TITLES.md` | MAPMODEL 世界地图标题结构与定位 |
| `STAGE_ROUTE_MAP.md` | 章节、路线、资源号和分支映射 |
| `LIBRARY_V02_SCOPE.md` | LIBRARY 资料库中文化范围与资源边界 |

Python 构建入口见 `../tools/README.md`，机器可读结果见
`../manifests/README.md`。文档中的数字若与当前 manifest 不一致，以 manifest 和
精确制品哈希为准。
