# Special Disc 工具

唯一日常镜像：`build/iso/special-disc/sp-current.iso`，同名 `.json` 为当前回执。
全量构建原子更新该路径；读盘、导出及专项检查均引用 `special_disc.source.CURRENT_ISO`。
预览和两关文本只作为构建基线，保存在 `work/build/special-disc/baselines/` 的哈希锁定差分中；
构建时临时还原，进程退出自动清除。原盘、组件、语料、截图和历史回执保留。

这是从 Claude Opus 的工作目录整理出的开发工具集合，目录契约见 [LAYOUT.md](../../docs/special-disc/LAYOUT.md)。原图片预览已接入 11 个组件；另有当前译稿全量文本候选和保留的两关候选入口，详见 [首批候选](../../docs/special-disc/TEXT_CANDIDATE.md)。

| 目录／入口 | 用途与写入范围 |
| --- | --- |
| `verification/scan_squad_names.py` | 按本篇规则扫描 SP 小队名，核对冻结位置；显式 `--freeze` 才更新清单 |
| `verification/verify_squad_names.py` | 小队名字库、容量、原槽压缩及组件回读检查；`--components` 核对组合后的实际组件 |
| `translation/import_pro_review.py` | 核验校订 ZIP 的 ID、原文和不可变字段，归并别名并导入；默认只生成计划 |
| `verification/preflight_pro_review.py` | 校订稿共享字库覆盖及流程图／旁白排版预检，不改写译文 |
| `verification/audit_exe_non_text.py` | 独立验证 7 个跳转表误提取项的 MIPS 读取／跳转指令及当前 ISO 原字节 |
| `writeback/exe_data_guard.py` | 已验证非文本位置的共用排除表及重叠写入保护 |
| `check_workspace.py` | 标准库只读自检：兼容链接、输入图片哈希、Python 语法 |
| `writeback/build_full_text.py` | 当前 8,629 条译稿全量写回；原子更新 `sp-current.iso`，支持 `--assemble-only` |
| `writeback/write_frame_text.py` | 固定格、摘要、旁白、梗概、地图名、章节标题池；按文字面限制布局 |
| `writeback/write_image_labels.py` | 5 处图片文字；默认读取冻结像素，`--refreeze` 才重新绘制 |
| `writeback/build_text_candidate.py` | 使用共享字库构建流程，生成两关文本组件与差分基线；支持 `--assemble-only` |
| `writeback/` | 组件写入 `work/build/special-disc/components/`；`build_preview.py` 更新预览差分基线与回执，不保留第二个 ISO |
| `export/export_sp_only_text.py` | 当前交付：从全量包排除本篇已有原文，生成 SP 新增／修改分类包；仅布局差异也排除 |
| `export/export_non_stage_text.py` | 当前 SP 非关卡文本完整分类导出；Markdown＋JSON＋ZIP，含复用内容，关卡外围与战斗台词分附录；不覆盖已有导出目录 |
| `export/export_sd_text.py` | 从本地原盘／组件导出到 `work/review/special-disc/text-export/out/` |
| `translation/` | 初稿、术语、审阅表；批次和结果位于 `work/authoring/special-disc/translation/`。`assemble.py` 会更新语料，`run.py` 等会调用翻译 API |
| `images/` | 作者工作包位于 `work/authoring/special-disc/images/`；部分脚本导入时也会生成资料，因此不能用批量 import 作为无副作用检查 |
| `verification/verify_full_text.py` | 从最终全量候选 ISO 重新解析文本、名称、固定页和系统模板，写独立回读报告 |
| `verification/survey_stage_bindings.py` | 原生 STAGE 全量绑定调查，列出唯一答案、歧义与缺少复用的记录；不生成组件 |
| `verification/audit.py` | 读取当前 ISO、清单和语料，写 `work/review/special-disc/status/verification.json`；不重建或运行模拟器 |

从仓库根目录执行。涉及文本与图像的工具沿用项目依赖：NumPy、Pillow；图片作者工具还使用 OpenCV 和 SciPy。选择已经安装这些库的 Python，系统自带 Python 可能缺依赖。开发路径建议使用 Python 3.11 以上。

只读检查：

```sh
python3 tools/special_disc/check_workspace.py
python3 tools/special_disc/verification/audit.py
```

预览装配更新中间差分基线，仅在需要重建输入时运行：

```sh
python3 tools/special_disc/writeback/build_preview.py
```

`build_preview.py` 消费当前本地组件和锁定的图片输入，不负责自动生成全部组件，也不代表正式发布流程。图片输入位于 `config/assets/special-disc/preview/`，输入锁为相邻的 `preview.json`；它不会自动消费作者目录新图。

既有 `run_full.sh` 批处理仍保留在 `work/authoring/special-disc/translation/`，供历史批次复现；Python 源码只有本目录这一份。身份卡、SD 术语参考位于 `config/editorial/special-disc/`，当前暂定状态不变。
