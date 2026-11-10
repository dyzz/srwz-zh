# 战斗台词去标签的疑点（2026-11-10）

**后续处理已完成：**用户授权补齐撇号后，最后 3 条也已去标签；ARMSX2 冷启动 Metal 4× 对照覆盖撇号、百分号、英文大小和词间距。详见 [核验记录](BATTLE_APOSTROPHE_VALIDATION_20261110.md)。下文保留排查过程，原先“3 条保留／未实机”的描述属于处理前状态。

战斗台词里的 `<width:0E><space:0C>…<width:16><space:16>` 标签共 341 条、358 处，包住的都是英文、数字和少量符号。已去掉 338 条，3 条保留。去掉后英文和数字由比例排版自动处理，和剧情、图鉴一致。

全部 338 条去标签后通过战斗字幕宽度校验，最宽的一行 410px（上限 462px），没有换行变化。**还没有构建，也没有实机看过。**

## 一、保留标签，等用户定（3 条）

英文撇号 `'` 不在比例字表里，去掉标签后会按全角一格（22px）画，变成 “It ' s”。剧情和战斗里都没有无标签撇号的先例。

| 编号 | 现在（带标签） | 去掉后的行宽变化 |
| --- | --- | --- |
| battle:19705 | 冲啊，达令！Let's Go！！ | [274] → [284] |
| battle:21251 | It's Showtime！！ | [193] → [203] |
| battle:21270 | It's Grand Finale！⏎（终幕到了！） | [186, 178] → [196, 178] |

可选的处理：保留标签（现状）；或把撇号加进比例字表，需要改运行时度量表的槽位布局，现在只有 3 个符号槽位，已被 `-`、`.`、`/` 占满。

## 二、已去掉，但显示会有变化（建议实机看一眼）

### 百分号（11 条）

`%` 同样不在比例字表里，去掉标签后是全角宽（22px），带标签时是 12px。剧情里已有 32 条无标签的“数字+%”，所以按同一做法处理了。

| 编号 | 现在 | 行宽变化 |
| --- | --- | --- |
| battle:06115 | 看得见敌人的动作…！⏎我确实超越了100%！ | [240, 231] → [240, 241] |
| battle:09110 | 舰体损伤度超过70%！ | [246] → [256] |
| battle:10856 | 出来吧，⏎赏你100%的输出！ | [108, 209] → [108, 219] |
| battle:11874 | 前部炮塔的运转率⏎已降至52%！ | [198, 157] → [198, 167] |
| battle:13116 | 损伤率突破70%…不妙… | [273] → [283] |
| battle:14716 | 嘿嘿，因为在丽花面前，⏎干劲120%哦！ | [257, 165] → [257, 175] |
| battle:15678 | 呃！推力降至68%！ | [220] → [230] |
| battle:19204 | 舰体损伤度超过40%！ | [247] → [257] |
| battle:22508 | 讨厌女人，⏎就等于浪费了人生的99%！ | [130, 290] → [130, 300] |
| battle:24719 | 了解！⏎能量，10%…20%… | [86, 211] → [86, 231] |
| battle:25699 | 什、什么！？损伤率70%！？ | [292] → [302] |

### 英文词间的空格

比例排版把英文单词之间的空格画成 5px。带标签时是 12px 一格。涉及的多词短语：Turn Type、THE HEAT、The Big、Game Over、King Gainer、Destiny Plan、Blaze Up、Thank you very much、Cross Range、OPEN GET、FLAME UP、Freeze King、Du musst fortgehen、YOU LOSE、Yes Sir、Get Slash、Hyper Boil、Hip Heavy、Final Stage，以及用全角空格的 SWITCH　ON（3 条）。

| 编号 | 现在 |
| --- | --- |
| battle:24510 | 切换——盖塔波塞冬！！⏎SWITCH　ON！！ |
| battle:24515 | 切换·盖塔狮虎！！⏎SWITCH　ON！！ |
| battle:24960 | 切——换·盖塔龙！！⏎SWITCH　ON！ |

这是全局的词间距规则，剧情里的 Side 3 等也是这样。如果觉得太挤，要改的是规则，不是这几条台词。

### 字形大小

带标签时英文按手工尺寸画（宽 14、步进 12，等距）。去掉后走比例排版：字母各自的宽度，字母高 12、数字高 11，和剧情对话里的英文同一套。行宽在引擎里前后一致（除上面两类），但字距观感会变。

## 三、去标签涉及的已有意见和测试

- 23 条带标签的台词在审核站有过意见。这次只去标签、没改措辞，所以照常处理了：02221、04727、05590、09162、09191、09223、16181、16191、16264、16322、16717、18152、19525、19572、19610、20828、20829、21243、23421、23459、23461、24510、24515。
- 2 处测试钉着带标签的原文：`tests/test_release_workflow.py` 的 battle:24510 已同步改掉；`tests/test_community_feedback_battle_round_4.py` 的 battle:02221 只核对编号，不用改。
- SP 专属战斗台词（`corpus/zh/special-disc/battle-lines.json`）本来就没有这类标签。
- 图鉴（1,650 处）、SP 其他文本（55 处）和菜单（48 处）里还有同类标签，这次没有动，只处理了战斗台词。

## 四、标签里包过的全部内容

BIG-O（34）、S-1（31）、KLF（26）、PLANT（20）、Turn Type（15）、THE HEAT（14）、BIG-DUO（13）、LFO（12）、BIG-FAU（9）、PSG（9）、The Big（8）、Mk-II（8）、G-Bit（8）、RX3（8）、LOGOS（6）、THE CRUSHER（5）、Big（4）、Action（4）、FAITH（4）、303（4）、Over（4）、Fire（3）、King（3）、Game Over（3）、70%（3）、DNA（3）、SOF（3）、808（3）、OPEN GET（3）、SWITCH　ON（3）、2500（2）、King Gainer（2）、100%（2）、Destiny Plan（2）、Destiny（2）、Blaze Up（2）、Goodbye（2）、Thank you very much（2）、Queen（2）、Cross Range（2）、2000（2）、Dove（2）、MAGNA（2）、FLAME UP（2）、Sol（2）、IMA（1）、Alright（1）、Crisis（1）、Fist（1）、180（1）、Turn（1）、Gainer（1）、Freeze King（1）、1000（1）、YES（1）、Du musst fortgehen（1）、YOU LOSE（1）、Princess（1）、Yes Sir（1）、Get Slash（1）、7-A2（1）、3-12（1）、CIWS（1）、3000（1）、52%（1）、FCS（1）、200（1）、Hyper Boil（1）、300（1）、0.2（1）、120%（1）、Gran（1）、G-Soldier（1）、68%（1）、4500（1）、100（1）、T-Bone（1）、022X（1）、MS（1）、909（1）、606（1）、Hip Heavy（1）、40%（1）、Let's Go（1）、CAN（1）、FLY（1）、Actiooon（1）、It's Showtime（1）、Final Stage（1）、It's Grand Finale（1）、99%（1）、TFO（1）、MCR（1）、8.75（1）、BLAZE UP（1）、Genocideron（1）、0.01（1）、10%（1）、20%（1）、III（1）

回执 `config/editorial/battle-followup-20261110.json`，工具 `tools/editorial_review/apply_battle_followup_20261110.py`，写回前的备份在 `work/review/battle-polish-20261109/backup-before-followup/`。

## 五、Codex 接手核验（2026-11-10）

已逐条对照当前语料和跟进回执：355 条均与回执一致，包括用户选定的 5 条、格蕾塔 12 条、去标签 338 条。338 条只删宽度／间距标签，可见文字、数字、空格和换行原样保留；当前仍有标签的恰好是上面的 3 条撇号台词。355 条均通过当前比例排版的静态宽度检查；338 条中最宽 410px。

**度量结果和实机效果要分开。** 用当前 JavaScript 引擎同时量带标签和去标签文本，338 条里只有 11 条的 12 个 `%` 度量发生变化；英文、数字及词间空格的静态度量相同。原因是 JavaScript 的比例字母查表优先于宽度标签。运行时的 `style_selector` 还会根据自动／显式字号状态选路，旧宽度标签可能走原生绘制，因此不能用这份静态结果宣布字形和词间距的实机疑点已解决。上面的 5px、12px 需要注明对应的绘制路径，仍应在同一候选版本上用 ARMSX2 做带标签／去标签对照。

处理结论：

- 战斗与剧情的续行对齐规则分开：战斗开引号恢复为全角 22px，续行仍用原来的 U+3000 全角空格（22px），不换新空格；剧情开引号为 16px，语料续行仍记 U+3000，由剧情写入路径转为新空白字码 `0x93FD`（16px）。本轮未改战斗缩进。当前静态引擎已分别复核为 22/22 和 16/16。
- 338 条已去标签稿保留；不重复改文案或换行。
- 3 条撇号暂留标签。现有比例表确实没有 `'`；去掉后静态推进会增加 10px。这是符号度量支持和验证任务，不需要为了去标签删撇号或改英文。
- 11 条百分号未超宽，但 `%` 的字形大小／字距仍待实机核验；英文多词短语另选 `Thank you very much`、`SWITCH　ON` 等代表项对照。
- 本次只完成静态审计，未构建 ISO、未做实机验证、未处理线上。

另修复了一个回执问题：两轮战斗写回脚本把 `config/editorial/story-honorific-merged-writeback-20261109.json` 当成现行输入锁，刷新了历史哈希和大小。已从 `backup-before-writeback/` 的原始备份恢复其 4 个字段，完整条目和确认记录没有变化；两个脚本现在只更新 `config/full-story-components.json` 中的 `srvc_battle_text.corpus`，历史回执不再随语料刷新。fable 两份战斗回执仍保留当时实际操作的记录。

审计数据：`work/review/battle-tag-removal-audit-20261110/static-audit.json`。恢复记录：同目录 `historical-receipt-restoration.json`。
