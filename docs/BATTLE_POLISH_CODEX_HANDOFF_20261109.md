> 2026-11-10 更新：撇号三条已写回，排版运行验证与三版构建已完成，见 [收尾验证](BATTLE_APOSTROPHE_VALIDATION_20261110.md)。下文保留原交接记录。

# 战斗台词排版与润色交接（2026-11-09）

接手前先读仓库根目录的 `CLAUDE.md`。本文所有路径相对 `srwz-zh/`。

## 现状

| 项目 | 状态 |
| --- | --- |
| 战斗字幕排版 | 已写回 `corpus/zh/battle/srvc-lines.json`，**未提交** |
| 行尾标点放宽 | 已进校验，**未提交**，当前没有台词用到 |
| 润色候选 | 已写回 1,976 条（11-09 写 1,960，11-10 跟进 17 条里有 16 条是之前搁置的），**未提交**；5 条不改。回执 `config/editorial/battle-polish-20261109.json`、`battle-followup-20261110.json` |
| 战斗台词标签 | 341 条里去掉 338 条的宽度／间距标签，3 条含英文撇号的保留。疑点见 `docs/BATTLE_TAG_REMOVAL_DOUBTS_20261110.md` |
| 候选 ISO | `build/iso/test/integrated-{original,best}.iso` 是 23:00 的构建，含战斗换行、战斗开引号全角、剧情续行空格。`integrated-sp.iso` 停在 21:45，只含前两项 |
| 正式 ISO、审核站 | 都没更新 |

战斗语料现在的 sha256 以 `a564a78813c0` 开头。它叠了四层未提交改动：换行、另一项工作的称谓定稿 80 条、润色 1,960 条、11-10 的跟进 355 条。

工作区里的改动是本轮和其他工作混在一起的。**不要 reset、stash 或顺手提交**。提交只在用户明确要求时做，且只有 `main` 一个分支。

本轮的未提交文件：
- 语料和锁：`corpus/zh/battle/srvc-lines.json`、`config/full-story-components.json`、`config/editorial/` 下 5 个文件（community-20260928-night、community-20260929-night、mail-pun-review-20260907、story-battle-polish-20260907、wings-name-confirmation-20260913）
- 排版校验：`shared/text-layout/engine.mjs`、`shared/text-layout/engine.test.mjs`、`tools/srwz/build_layout.py`、`tests/test_js_build_layout.py`
- 开引号全角：`tools/srwz/proportional_metrics.py`、`shared/text-layout/proportional-metrics.mjs`、`tests/test_tag_free_integrated.py`
- 剧情续行空格：`tools/srwz/continuation_indent.py`（新）、`tools/srwz/proportional_hooks.py`、`tools/srwz/armsx2_text_probe.py`、`shared/text-layout/proportional-selection.mjs`、`shared/text-layout/engine.d.mts`、`shared/text-layout/proportional.test.mjs`、`tools/build_story_component.py`、`tools/build_full_story_components.py`、`tools/verify_full_story_iso_content.py`、`tools/special_disc/writeback/migrate_slps_text.py`、`tools/special_disc/writeback/migrate_stage_dialogue.py`、`tools/special_disc/verification/verify_full_text.py`、`tests/test_continuation_indent.py`（新）
- 工作区里 `corpus/zh/story-dialogue/` 的 38 个文件、`config/editorial/special-disc/stage-context-reuse.json` 和提交 1a824e82 是并行的另一项工作，不是本轮的。
- 删除行数门禁：`tools/srwz/srvc.py`、`tools/build_full_story_components.py`、`tools/special_disc/writeback/migrate_srvc.py`、`tests/test_srvc.py`
- 测试字面量：`tests/test_community_feedback_battle_round_3.py`、`_round_4.py`、`test_community_feedback_final_pending.py`、`_stage_055.py`、`_stage_126.py`、`tests/test_release_workflow.py`
- 文档：`docs/BATTLE_LINE_BREAKS_20261109.md`、`docs/issue-assets/battle-line-breaks-20261109/`、本文

`docs/ISO_DIRECTORY_LAYOUT.md` 和其余未跟踪文档不是本轮的。

## 用户已定的规则

**排版**
- 原换行是有意的，不要因为放得下就合并。第二行不要求和日文行数一致。
- 只有第二行是单字加标点、或只有标点时才考虑合并。已合并 27 条。
- 还剩 22 条单字或纯标点末行，用户看过，**都不合并**：18 条断在句末标点后（如“派整备班去受损区块！⏎快！！”），4 条有审核意见。
- 续行开头一个全角空格。战斗字幕最多两行。
- 战斗字幕开头的 “ 保持全角宽度，让续行和第一行正文对齐。

**行尾标点上限**（按 Metal 4× 实测可用值再留 2px，只看行尾字形，按推进值）

| 行尾 | 比 462 多 |
| --- | ---: |
| ？ 》 | +20 |
| ： 】 | +21 |
| ” ） | +22 |
| 。 | +23 |
| 、 | +24 |
| ， ； | +26 |
| ！ | +27 |

汉字、拉丁、… 和 — 仍是 462。只放宽校验，自动换行仍按 462。实测记录在 `docs/BATTLE_LINE_BREAKS_20261109.md` 和 `docs/issue-assets/battle-line-breaks-20261109/boundary.json`。

**文本**
- 有过线上意见或人工定稿的台词不动，不管意见是否被采纳。写回前必须重新核对线上意见。
- 判断时要考虑作品和台词的触发场景。只改确有问题的句子，不做同义替换，不加原文没有的信息，不把短喊拖长。
- 不要只为换行改写句子。

## 润色写回（2026-11-09 23:39，已做）

用户两次交代“你来处理吧”“你先专注战斗台词的润色处理”，没有导出逐条决定。由 Claude 把 1,981 条候选逐条读过后定稿，决定文件是 `work/review/battle-polish-20261109/decisions-claude-20261109.json`。

| 结果 | 条数 | 说明 |
| --- | ---: | --- |
| 写回 | 1,960 | 其中 13 条改写过措辞或换行 |
| 不改 | 5 | battle:01369、01625、13718、15615、20226：现译成立，或只是同义替换、只动了换行 |
| 搁置，等用户定 | 11 | 格蕾塔的 父ちゃん／あんた 改“当家的”（battle:05703、05708、05710、05711、05712、05719、05721、05724、05726、05742、05746）。剧情 story/085 现译是“老爸”，要改得两边一起改 |
| 搁置，已被定稿 | 5 | battle:01720、08731、12967、14680、14698：当天的称谓定稿改过这几句，属人工定稿，不再动 |

- 改写的 13 条：11 条是候选把两行并成了一行，按“原换行不动”恢复成两行（06563、06580、17293、17895、18002、18451、22716、23543、23584、23662、24441）；09246 的 暑苦しい 改成和 02808 一致的“热得烦人”；14701 按当天的称谓规则去掉“酱”。
- 写回前重新拉了线上意见（3,891 条，15:35 UTC），本行和同源句都没有命中。基线、候选校验、战斗宽度门禁（开引号全角）、末行规则、字形全部通过。
- 工具 `tools/editorial_review/apply_battle_polish_20261109.py`，不带 `--apply` 是空跑。写回前的语料和锁在 `work/review/battle-polish-20261109/backup-before-writeback/`。
- 锁刷新了 2 个文件：`config/full-story-components.json` 和 `config/editorial/story-honorific-merged-writeback-20261109.json`。
- **没有构建，也没有实机验证**。全量测试 973 项里失败 5 项，都指向剧情对话和 SP 图鉴对话快照，是另一项工作的剧情写回带来的。构建停在字库步骤：那轮剧情写回用了字库没有的“窒”，要先更新字库快照。这两件事解决后再构建三版并进战斗抽查。
- “译名疑点”页的 199 条没有处理，仍等用户定。

## 11-10 的跟进（已写回 355 条）

- **用户在审阅页选定的 5 条**（battle:01720、08731、12967、14680、14698）：都选“候选，去掉称谓”。01720 另按用户意见把「は、はい…」从“是、是的…”改成“嗯、嗯…”。战斗台词里另外两条「は、はい！」（11851、20992）是军人应答，仍作“是、是！”。
- **格蕾塔 12 条**：查证她是卡拉斯的遗孀（原作各话简介；游戏内图鉴写“卡拉斯·卡拉斯的妻子”，剧情 story/085 有“为死去的丈夫守节”），「父ちゃん」「あんた」指亡夫。剧情 story/085/dialogue/01.26/0003 当天已定稿为“老伴”，战斗台词统一跟它，含之前写成“老爹”的 05704。审阅页上这 12 条留了“当家的”“老公”两个备选，用户想换可以直接点。
- **去标签 338 条**：见 `docs/BATTLE_TAG_REMOVAL_DOUBTS_20261110.md`。3 条含英文撇号的没去（19705、21251、21270）。
- 工具 `tools/editorial_review/apply_battle_followup_20261110.py`，备份在 `work/review/battle-polish-20261109/backup-before-followup/`。锁刷新了 `config/full-story-components.json` 和称谓回执。`tests/test_release_workflow.py` 里 battle:24510 的字面量同步去了标签。
- 仍然没有构建和实机验证，原因同上。去标签改变了英文和数字的画法，构建恢复后要进战斗看 BIG-O、PLANT、Mk-II 和带百分号的台词。

## 润色审核页

- 目录 `work/review/battle-polish-20261109/`，地址 http://localhost:8794 ，纯静态页面，启动配置是 `.claude/launch.json` 的 `battle-polish-review`。
- 写回之后页面改成了审阅页（2026-11-09 深夜）：每条带说话人和对手的战斗头像、触发场景、条件、出现次数，以及处理结果（已写回、未改、待定）。默认先显示 16 条待定。“译名疑点”页的 199 条同样带头像和上下文。
- 数据由 `build_context.py` 生成：读社区站目录数据（`srwz-community-web/public/data/catalog/`）、候选、决定文件和当前语料，头像克隆到 `portraits/`。语料或决定变了就重跑它。
- 页面是逐条点选：每条把几种具体译文并排列出（语料现状、候选、原译，待定条目另有备选），用户点哪条就选哪条，也可以自己写；“同类全选”把当前筛选里带同名选项的条目一次选完。选择存在浏览器 localStorage（键 `srwz-battle-polish-20261109-choices`），点“导出我的选择”得到 `battle-polish-choices.json`：`rows` 里每条有 `pick`、`text`（`/` 是换行）和 `changes`（是否要改语料），`notes` 是译名疑点的维持或改写。拿到文件后只写 `changes` 为真的条目，写回前照样过线上意见、基线和版式校验。
- 候选 `candidates.json`：`source` 为 `first` 的 1,743 条来自首轮，`context` 的 238 条来自全量复审。过程材料在 `recheck/`，细则是 `RUBRIC.md`。
- 待用户定的重点：battle:14873「ゼラヴィオン」现译“泽拉拜亚”，建议“泽拉维昂”，术语校验会拦，需人工放行。

## 写回步骤（用户交回决定后）

1. 只处理 `decision` 为 `accept` 的条目。
2. **重新拉线上意见**，所有分页都要拉完：
   `https://srwz.dreamquest.club/api/review-suggestions?status=all&scope=all&limit=500&offset=N`
   `targetType` 为 `battle-line` 且 `targetId` 命中的，或归一化日文相同的同源句有意见的，一律不写，列给用户。归一化方式见 `recheck/build_packets.py` 的 `norm`。
3. **检查基线**：每条候选的 `curFull` 必须等于语料当前 `translation`，`sha` 必须等于 `source_text_sha256`。不一致的不写，列给用户。
4. 组装译文：`“` + 按 `/` 分段、用字面量 `\n` 加一个全角空格连接 + 结尾 `”`（`curFull` 以 `”` 结尾才加）。控制标记、拉丁、数字原样保留。
5. 校验：`check_ctx.py` 通过；`verify_stored(rows, 'battle')` 通过；不产生单字或纯标点末行；不产生新字形。
6. 写语料，仅刷新 `config/full-story-components.json` 中 `srvc_battle_text.corpus` 的当前输入锁。`config/editorial/` 下的历史写回哈希、大小和确认记录不得随语料更新；两轮脚本已改用同一个限定范围的锁刷新函数。
7. 在 `config/editorial/` 新增写回回执，形状参考 `mail-pun-review-20260907.json`，记录条目、新旧译文、线上快照时间。
8. 跑测试，处理写死了旧文本的字面量：
   `/opt/homebrew/bin/python3 -m unittest discover -s tests`
   `node --test shared/text-layout/engine.test.mjs`
   当前基线：973 项通过，8 项跳过；engine 29 项通过。
9. 构建候选：`/opt/homebrew/bin/python3 tools/build_editions.py --candidate --editions original,best,sp`

## 验证要求

- 用 ARMSX2 无头 runner 自己验证，不要让用户测试。用法见根目录 `CLAUDE.md`。需要 numpy 的脚本用普通 `python3`，并带 `PYTHONPATH=tools`。
- 实机脚本范例：`docs/issue-assets/battle-line-breaks-20261109/` 的 `natural.py`（真实战斗回读）、`sheet.py`（Metal 4× 样张）、`boundary.py`（裁切边界）。
- 排版改动三版都进过战斗。Best：内存里 90 条新换行，0 条旧换行。Original（敌方回合连续战斗）：14 条新换行，0 条旧换行，实际画出 battle:22857 两行。SP（战斗鉴赏）：52 条新换行，0 条旧换行，实际画出 battle:11373 两行。脚本与证据在 `docs/issue-assets/battle-polish-handoff-20261109/`。
- runner 长时间开着文字追踪会涨到 10 GB 内存，之后截图全黑甚至崩溃，游戏本身正常。要截图时先存档，换一个干净会话 `run 600` 出画面后再读档。
- **续行对齐已修**：战斗字幕里开头的 “ 恢复全角推进（22px），和续行缩进同宽。改动在 `tools/srwz/proportional_metrics.py` 的 `CJK_FULL_WIDTH` 和 `shared/text-layout/proportional-metrics.mjs`，语料没动，候选 ISO 已重建。剧情对话（“ 16px 对缩进 21px）没有动。详见 `docs/BATTLE_LINE_BREAKS_20261109.md` 末节。
- **剧情对话续行已修（SP 未建）**：续行行首空格写入时换成空白字码 `0x93FD`，推进 16px，和压缩后的引号同宽；排版引擎默认按这个宽度计算。Original、Best 候选 ISO 已重建并实机验证。SP 的代码已接好，但 SP 构建被 `config/editorial/special-disc/stage-context-reuse.json` 的锁漂移拦住（并行工作 22:07 的改动），锁刷新后要重建 SP 并冷启动验证剧情对话。详见 `docs/BATTLE_LINE_BREAKS_20261109.md` 末节。
- 验证度量改动必须冷启动。度量表随可执行文件载入 EE 内存，旧即时存档里是旧表。
- ISO 只按路径引用。确需冻结用 `cp -c`，不要 `cp`。测试 ISO 放 `build/iso/test/`。
- 不要自动播放声音。

## 之后会碰到的

- `shared/text-layout/` 下的 `engine.mjs`、`proportional-metrics.mjs`、`proportional-selection.mjs`、`engine.d.mts` 改过，审核站构建的 `layout:check` 会报漂移，需要在 `srwz-community-web` 跑 `npm run layout:sync`。
- `tools/srwz/chinese_layout.py` 的 `battle_subtitle_layout_issues` 是旧的定宽检查，仍按 462，没有接入放宽。写回流程里如果调到它，用到放宽的句子会被拒。
- 不要对战斗台词重跑无标签集成，除非传 `preserveLineCount:false`，否则会把末行单字的问题带回来。
