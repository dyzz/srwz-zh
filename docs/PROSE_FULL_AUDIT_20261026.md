# 梗概与滚动字幕全量检查（2026-10-26）

本次范围是 Original、The Best、Special Disc 的剧情流程梗概及 MTV_PROS／MTZSPROS 滚动正文，不包含人物辞典、对话框、事件画廊等其他显示面。使用独立测试 ISO，不替换 production current；提交记录不包含测试 ISO，未推送。

## 最终排版规则

- 保留原生字体 step 和英数字紧缩。中文词、人名允许拆行；紧缩控制闭合段和结构控制保持完整，标点禁则保留。
- 滚动正文按原生可用宽度选择最晚合法断点，优先填满前行，不再为均衡末行提前换行。保留原生段落边界、空白分隔及首行一格全角缩进。段尾余字允许短行。
- 梗概保持已确认的 30 格上限（480），最少行数后均衡正文；不将滚动字幕的逐行填满规则误套回已确认的梗概。
- 普通本篇长滚动正文为 22 格（528）；SP 为 23 格（575）。`summary/03/000`、`summary/04/000` 的原生 clip 只有 504，必须限定为 21 格，不能沿用 528。
- 不增加对齐字距、整行缩放或为排齐而新增语料标签。编译器自动生成游戏已有的尺寸控制，恢复后续中文的 W/H/step；不声称实现了新的原生自动分类补丁。

## 覆盖和证据

三版合计 307 字段：Original 138、The Best 138、SP 31；其中梗概 241，滚动正文 66。去除 Original／Best 共用候选后为 169 条。所有候选原生控制的逐字几何比较通过，物理行 1,103（含空白行），非空行 971；没有额外字距。三版 v8 测试 ISO 的 307 字段均精确回读通过。

梗概在 LRPS2 原生详情框中全量受控回放，241/241 通过，共 37,429 条原生字形坐标和尺寸记录。回放只临时切换详情页正文指针，读取同一 ISO 中已有正文；标题固定，截图 ID 标识正文来源。指针已恢复。这不表示全部剧情节点均已自然解锁。该回放使用 v6；已与 v8 字段逐一比较 payload SHA256，所有梗概完全一致。

滚动正文 34/34 个非空原生节目均完成 LRPS2 回放，共 66 字段；回放文本与 v8 ISO 对比 66/66 一致。长文保存滚动前、中、末段序列；含多个定时文本对象的节目分别保留各组画面。Original／Best 女主开场采用 v8 测试 ISO 正常新游戏路线；其余节目为兼容开场背景下的受控回放，各自保留原生字体、坐标、裁剪区。部分回放压缩测试时间，后来发现长节目不适合这种测试方法；这些节目的最终证据改用原始时间和运动参数，不能把早期黑屏／退出记作游戏本身缺陷，也不能把所有回放称为自然剧情通关。

v8 将滚动 `rawt` 按实际编码的 NUL 结尾字符串重建长度，同步更新 section、节目长度和归档偏移。部分带大量分配余量的受控回放在该格式下恢复显示。现有证据仅支持这种测试输出可回读、可回放，不足以将“原版分配余量非法”或某个原生缓存机制定为根因。所有最终选用的回放文本均再次与 v8 ISO 内文本逐项比较。

## 产物与复核入口

- 测试 ISO、SHA256、报告冻结快照：`work/build/prose-step-preview-20261026-v8/`。
- 逐字段 ISO 回读、原生片段、回放文本一致性证明：`work/analysis/all-prose-audit-20261026/` 下 `*-readback.json`、`readback-summary.json`、`fixture-text-proof.json`。
- 梗概原生字形及截图：`work/runtime/lrps2/all-prose-audit-20261026/flow/`。
- 滚动截图和回执：同目录 `single/`、`trimmed/`、`exact-timing/`、`female-v8/`。最终映射以 `scroll-evidence.json` 为准，不使用早期失败 reel 或错误的 female-natural 路线作通过证据。
- 审查页：`http://127.0.0.1:8766/all-prose-audit/index.html`；滚动正文：同目录 `scroll.html`。
- 相关 32 项测试通过（断词 4、既有排版 19、本轮固定 step 5、原生字幕保护 4）。完整套件运行 812 项，跳过 7，仍有 1 项失败：`test_sp_event_gallery_fidelity.test_original_view_changes_are_retained`。它涉及同时存在的事件画廊视图配置改动，不在本轮梗概／滚动范围内，未修改该配置来掩盖失败。首次套件的重定位错误提示兼容性失败已修正；最终日志为 `full-tests-final.log`，不能称为全套通过。

仅使用 LRPS2。原始记忆卡保持不变；运行使用复制卡。受控回放、正常路线、静态几何和 ISO 回读的证明范围分别记录。

## 提交留存与复现边界

已验证输入冻结在 `docs/issue-assets/prose-step-audit-20261026/layout-report.json`，与 v8 构建输入字节一致。复写命令：`python3 tools/text_layout/build_prose_step_preview.py --report docs/issue-assets/prose-step-audit-20261026/layout-report.json --out work/build/prose-step-review-new`。需要本地合法源盘、当前基础 ISO 和字体提案，基础身份由 manifest 校验；输出必须为新目录。该命令消费已审阅排版，不代表正式 release 排版入口已切换。

固定 step 分行算法留存为 `tools/srwz/prose_step_partition.py`，5 项回归测试为 `tests/test_prose_step_partition.py`。实验性字体可视化与报告生成脚本仍在本地 work 目录。冻结输入确保本次已验证文字可以复写，不依赖重新生成离线报告。精简逐字段回读与回放文本对照证明在同一 issue-assets 目录，完整运行轨迹和截图仍按上文 work 路径保存。

提交前再次运行工作区完整套件：816 项，跳过 7，结果 OK；另运行已留存的 5 项分行算法测试通过。此前事件画廊失败在工作区后续改动后不再出现，其配置、实现和测试改动不属于本轮提交，仍留在工作区。此结果不表示已将那些改动一并提交。摘要见 `docs/issue-assets/prose-step-audit-20261026/commit-verification.json`。
