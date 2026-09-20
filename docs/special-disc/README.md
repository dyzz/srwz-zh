# Special Disc 汉化

Special Disc（SP／SD，暂称“特别篇”）使用共享中文语料、码表与基础解析库，并保留独立的产品配置、工具和本地构建目录。目前处于开发预览阶段。

| 入口 | 用途 |
| --- | --- |
| [Pro 校订合并记录](PRO_REVIEW_IMPORT.md) | 校订稿已合入；282 处现有语料文字更新，190 个新增字段待写回；ISO 未更新 |
| [Pro 校订疑问处理](PRO_REVIEW_RESOLUTION.md) | 25 条术语疑问结案，同步 1 条索引；7 条误提取已证实为跳转表并排除 |
| [非关卡文本分类导出](NON_STAGE_TEXT_EXPORT.md) | 仅 SP 新增／修改：主目录 1,940 条，含附录 2,282 条；Markdown＋JSON＋ZIP |
| [当前译稿全量候选](FULL_TEXT_CANDIDATE.md) | 8,629 条既有译稿写回、排版与新镜像验证 |
| [首批文本候选](TEXT_CANDIDATE.md) | 两关实际写回、共享字库增补、候选镜像与验证边界 |
| [目录契约](LAYOUT.md) | 当前实际目录、旧路径兼容、保存边界及后续收敛方式 |
| [文本写回实施计划](TEXT_WRITEBACK_PLAN.md) | 文本落点、绑定规则、组件合成、两关候选与 WB-01～WB-07 任务依赖 |
| [进度与后续计划](STATUS.md) | 2026-09-19 盘点，初稿／写回／验收状态分开记录 |
| [详细规划与研究记录](PLAN.md) | 内容范围、格式研究和早期迁移记录 |
| [工具说明](../../tools/special_disc/README.md) | 写回、翻译、导出、图片和校验工具入口 |
| [目录登记](../../config/products/special-disc/workspace.json) | 机器可读路径映射 |
| [预览图片快照](../../config/assets/special-disc/preview.json) | 18 份图片输入和 3 份调色板的大小、哈希 |

已完成目录整理及当前 8,629 条译稿的全量写回。最新文本镜像位于 `build/iso/special-disc/full-text/`，详见全量候选记录；原图片预览和两关候选保留。目录登记不是正式生产构建配置。

从仓库根目录做不依赖第三方库的只读自检：

```sh
python3 tools/special_disc/check_workspace.py
```

当前预览为 `build/iso/special-disc/preview/sp-image-preview.iso`。原盘位置不变，历史 LRPS2 记录也保留原路径。

SP 原盘入口统一读取 `config/products/special-disc/disc-inventory.json` 的 `sp.path`，即当前 `rom/Super Robot Taisen Z - Special Disc [J].iso`。导出、字体安装、资源迁移、预览装配和图片检索共用此路径；本篇复用来源与已汉化候选保持各自版本身份。

## 2026-09-20 Git 收录验证

本次收录 SP 源码、配置、7 份语料、编辑决定、图片快照与文档，以及共享字库新增的 42 个映射和 SP STAGE 解析支持。ISO、原盘、组件、用户校订 ZIP、作者中间稿和运行证据仍保留在 Git 忽略的本地目录中。当前工具依赖上述本地输入，尚不是只给原盘即可从零复建的发行流水线。

- 45 项相关测试通过：SP 图表／写回／非文本保护、共享 STAGE 解析与字库构建。
- 工作区检查通过：57 个 Python 源文件、65 个兼容路径和 21 个锁定图片输入。
- 共享字库的旧主映射、别名和兼容映射逐项不变；新增 42 个映射，分配快照哈希一致。
- 全工作区测试运行 355 项，2 失败、1 错误、1 跳过。两个本篇措辞断言分别涉及 `battle:00113` 和 `story/014/dialogue/02.02/0073`，使用已提交 HEAD 的语料可复现；Z Report 错误为缺少本地 `rom/original.iso`。这些问题未混入 SP 提交修复。
- 本次没有重建或替换 ISO；Pro 校订后的补字、容量、排版及 190 个新增字段绑定仍按合并记录跟进。
