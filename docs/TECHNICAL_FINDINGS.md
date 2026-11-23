# 技术结论汇总（来自已清理的过程记录）

2026-11-23 整理 `docs/` 时，过程记录、复测日志和交接文档被删除。其中仍然有用的技术结论收在这里，每条注明原文件和日期。原文都还在 git 历史里，可用 `git show eb9c1f90:docs/<文件名>` 查看。

有专门文档的结论不在这里重复，例如文本渲染逆向、可见文字编码规则、写回契约、三合一盘技术说明。这里只收那些原本只写在过程记录里的结论。

## 文本宽度与排版

- 拉丁字母、数字连续 3 个以上的可见字符要收窄，用 `<width:0E><space:0C>` 标签；汉字和标点保持原生宽度。这条规则覆盖了约 4,250 条拉丁/数字文本。（`COMPACT_VISIBLE_COUNT_20260928.md`、`COMPACT_TEXT_EXECUTION_20260928.md`）后来比例字宽渲染上线，战斗台词里包住拉丁文本的宽度标签就去掉了：341 行中去掉 338 行，最宽的字幕行 410 px，上限 462 px，ARMSX2 4 倍画面验证无误。（`BATTLE_TAG_REMOVAL_DOUBTS_20261110.md`、`BATTLE_APOSTROPHE_VALIDATION_20261110.md`）
- 战斗台词分行：保留原有换行，只合并单字或单个标点的行尾。（`BATTLE_POLISH_CODEX_HANDOFF_20261109.md`）
- SP 问答排版审计发现的问题有两类：数字、单位和缩写被拆到两行，以及闭标点落到行首。（`special-disc/QA_FULL_LAYOUT_AUDIT_20260920.md`）
- 文本扩容在文本池范围内是安全的，但 STAGE 内部引用没有完全受到门槛检查。（`TEXT_CAPACITY_SAFETY_AUDIT_20260905.md`）

## 字体与贴图

- ImageMagick 要关闭字形微调（hinting），必须写 `-set type:hinting off`，`-define` 写法不生效。字高逐行下沉的差异有一部分来自 hinting。（`FONT_NOHINT_RUNTIME_20261115.md`、`FONT_HEIGHT_ROW_DROP_REVIEW_20261115.md`）
- 底行统一下沉一行的规则会让汉字高度参差不齐，已改为只把底行第 20 行有笔画的汉字下移一行。（`FONT_HEIGHT_ROW_DROP_20261115.md`）
- 三个版本的图鉴页用不微调的 22 px 字体都显示正确；剧情、地图、战斗三处的缩进也都核对过。（`FONT_22PX_LIBRARY_RUNTIME_20261115.md`、`FONT_22PX_INDENT_ACCEPTANCE_20261115.md`）
- 商店标题从 42 px 放大到 62 px，只改了 KVMDATA 第 5 页的矩形 (3,1,137,61)。（`BAZAAR_HEADING_ENLARGEMENT_20261003.md`）
- SP 指令标题变形的原因：按 28×17 采样，却以 22/24 px 加斜切显示。修正方法是重新冻结 38×20 和 36×20 的块，矩形改为 1:1。（`special-disc/COMMAND_HEADINGS_20260920.md`）
- SP 的括号把原版 8169/816A 的 4-bpp 像素复制到中文码位 8FE8/8FEB。（`special-disc/PARENTHESES_RUNTIME_20260928.md`）
- 小数倍放大时出现的 1 px 接缝，是因为槽位裁剪区刚好止于精灵边缘。（`V0.5.0_POST_RELEASE_ISSUES.md`）

## 引擎与运行时

- 名称替换标记是 `81 A6`。Battle Viewer 里的名字副本是旧的，改名时必须一起同步。（`SP_NAME_AND_DESCRIPTION_FIXES_20261006.md`）
- 本篇和 BEST 共用同一条主人公名动态覆盖路径，这条路径会调换全名的顺序。（`LIBRARY_PROTAGONIST_NAMES_INVESTIGATION_20260910.md`）
- 旧存档会把过时的小队名留在内存和默认值里。修复办法是重新取名，不要读取旧的即时存档。（`BEST_THE_HEAT_USER_SAVE_20261010.md`）
- SP 名场面中途退出会跳过原生的镜头清理，留下残余镜头，靠状态重置解决。（`SP_GALLERY_STATE_RESET_20261106.md`）
- SP 名场面字幕：字号 32，区域 x 64–576、y 388–428，白字加描边。（`SP_EVENT_SUBTITLE_QUALITY_V7_20261013.md`）
- SP 名场面的关卡初始化和魔神 Z 机体替换，由原生的机体交换机制处理。（`SP_EVENT_STAGE_AND_SUBTITLES_V6_20261013.md`）

## 语料与构建

- 战斗台词：本篇和 BEST 共用主语料；SP 读取共用语料，再按日文指纹叠加自己的语料。（`BATTLE_LINE_VARIANTS_20261110.md`）
- 本篇的基底是 Original，再从 Best 移植四处 COMPDATA 字段修正和若干文本修正。（`BEST_BACKPORT_CHECKLIST.md`）
- 本篇和 BEST 的文本一致，SP 曾因冻结快照而落后。（`MAIN_BEST_SP_NAME_CONSISTENCY_AUDIT_20261016.md`）
- 审阅站导出 SP 名字时，必须合并 SP 名称写回契约，不能只看冻结的 SP 独有过滤结果。（`special-disc/REVIEW_SITE_NAMES_20260929.md`）
- 构建变慢的根因：`_partition_tokens` 在每个断点都重算切片宽度。改用前缀和索引后，构建时间降到 259 s，产出的 ISO 完全相同。（`BUILD_PERFORMANCE_20261007.md`）
- 强制全量构建从 131.75 s 降到约 67 s，做法是加缓存、去掉重复校验。日常构建统一走 `build_editions.py`，并去掉了重复的整盘哈希。（`BUILD_TIME_ANALYSIS.md`、`BUILD_PERFORMANCE_20260927.md`）
- 单独重跑某个组件会覆盖已锁定的报告，所以加了锁定保护。（`special-disc/BUILD_RECORDS_REPAIR_20260920.md`）
