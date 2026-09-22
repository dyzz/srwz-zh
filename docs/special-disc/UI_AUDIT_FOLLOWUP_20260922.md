# SP UI 遗漏与后续检查清单

更新：2026-09-22。原始检查依据 **103 张原始截图、80 张代表性画面**；其后已修复下述 5 个术语列表名称，并追加独立的 LRPS2 冷启动截图。以下原始镜像身份仅对应修复前基线。

- 被测镜像：`build/iso/special-disc/sp-current.iso`。
- 被测 SHA-256：`e725740d7cc650e7222b6747b33ac63d62a3e62dfea84be52de9da57625ba498`。
- 存档：此前下载的 `super-robot-taisen-z-special-disc.19218.cbs`（中断存档 `BISLPS-25920Q`），通过隔离记忆卡加载。
- 环境：LRPS2 Software (SW)，金手指关闭；源卡和ISO前后哈希一致。此身份只绑定本轮截图，不推定后续同路径镜像仍相同。

## 1. 已确认的汉化遗漏：术语列表名称

以下 5 项属于同一组“列表名称与说明正文更新不一致”的问题，现均为 **已修复，LRPS2 验证通过；PCSX2 人工验收待进行**。表格保留修复前观察，修复后证据见下文。

| 编号 | 当前列表显示 | 对齐目标／下一步 | 依据 | 截图 |
| --- | --- | --- | --- | --- |
| SPUI-001 | サイド3 | Side 3 | 同条目正文标题已确认 | [84](../../work/runtime/lrps2/sp-ui-audit-20260922/run/84-term-side3-selected.png) / [85](../../work/runtime/lrps2/sp-ui-audit-20260922/run/85-term-side3-description.png) |
| SPUI-002 | プラント肘議会…（异常汉字） | PLANT评议会议长 | 同条目正文标题已确认；旧编码残留仅为根因假设 | [89](../../work/runtime/lrps2/sp-ui-audit-20260922/run/89-term-plant-selected.png) / [90](../../work/runtime/lrps2/sp-ui-audit-20260922/run/90-term-plant-description.png) |
| SPUI-003 | ロゴス | LOGOS | 现有 library-terminology.json 的 keyword/018 canonical；尚未单独打开正文核对 | [12](../../work/runtime/lrps2/sp-ui-audit-20260922/run/12-term-list.png) |
| SPUI-004 | ブロックワード | BLOCK WORD | approved 运行期术语表 entry_index=36；现有英文专名 | [91](../../work/runtime/lrps2/sp-ui-audit-20260922/run/91-terms-page2.png) |
| SPUI-005 | オーバーコート | Overcoat | approved 运行期术语表 entry_index=41；现有英文专名 | [91](../../work/runtime/lrps2/sp-ui-audit-20260922/run/91-terms-page2.png) |

修复后：5 项均使用现有 approved 运行期术语表 `corpus/runtime/stage-keywords-v1.json` 的目标文本（index 10、21、19、36、41），没有重新翻译。`BLOCK WORD`、`Overcoat` 等专名保留既有英文。

### 修复实现与验证

- 当前镜像：`build/iso/special-disc/sp-current.iso`；SHA-256 `8321e37e11829d947cb7953351a1cfcb49eba91033990228d8acd4863c3248dc`。
- 根因已确认：通用 COMPDATA 迁移仅按原文本加 4 字节对齐空白原位写回，这 5 个名称均因容量不足被跳过；日文残留字节在中文字库中显示为异常字。
- SP 专用写回绑定 `COMPDATA + 0x67400` 的 52 项指针表，按日文源文本绑定共享术语。三个名称使用已核验的后续空白；`LOGOS`、`Overcoat` 使用“塞文堡”“荣耀之星”后的空白区，并将其中一个空标签指针移至仍为 NUL 的位置。其他解压字节、非目标名称、ISO 成员大小和 LBA 不变。
- 编码使用资料库 stored-text 字库，空格为 `0x8140`。首轮菜单编码候选因实机缺字被拒绝，未作为通过证据；新增防误用测试与目标字节回读约束。
- 写回已接入 `tools/special_disc/writeback/build_full_text.py`，独立验证已接入 `tools/special_disc/verification/verify_full_text.py`；当前镜像增量更新入口为 `update_current_keyword_names.py`。
- LRPS2 Software 冷启动、关闭金手指、隔离记忆卡：5 项列表及说明标题、三页列表、排序切换、退出返回标题界面均通过。只复用本次候选生成的即时状态，不加载旧镜像状态。源 CBS、源卡与 ISO 运行前后哈希一致。
- 静态检查：52 个术语、5 个既有机体名、14 个驾驶员字段以及 12 个已登记 ISO 成员回读通过；SP 测试 105 项中 100 通过、5 跳过；最终定向测试 7/7 通过。
- 限制：完整历史构建复验缺少 `work/build/special-disc/full-text/runs/build-kufhjaja/frame/report.json`，未宣称该复验通过。PCSX2 人工验收仍待进行。其他页面的证据缺口保持原状。

[新旧截图对照](../../work/runtime/lrps2/sp-keyword-fix-20260922/report.html) · [修复验证报告](../../work/runtime/lrps2/sp-keyword-fix-20260922/REPORT.md) · [精确镜像与逐图回执](../../work/runtime/lrps2/sp-keyword-fix-20260922/receipt.json) · [增量写回及 ISO 边界回读](../../work/verification/sp-current-keyword-list-names/readback.json)

| 编号 | 已确认名称 | 新列表截图 | 新说明截图 |
| --- | --- | --- | --- |
| SPUI-001 | Side 3 | [列表](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/04-side3-list.png) | [说明](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/04-side3-description.png) |
| SPUI-002 | PLANT评议会议长 | [列表](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/06-plant-list.png) | [说明](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/06-plant-description.png) |
| SPUI-003 | LOGOS | [列表](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/05-logos-list.png) | [说明](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/05-logos-description.png) |
| SPUI-004 | BLOCK WORD | [列表](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/08-block-word-list.png) | [说明](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/08-block-word-description.png) |
| SPUI-005 | Overcoat | [列表](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/09-overcoat-list.png) | [说明](../../work/runtime/lrps2/sp-keyword-fix-20260922/run/09-overcoat-description.png) |

## 2. 排除项与范围说明

| 观察 | 本次归类 | 处理 |
| --- | --- | --- |
| 小队名 `フリーデン`，同屏机体名“和平号”（图83） | **存档遗留问题，按用户反馈归类** | 从当前UI缺陷和汉化补漏任务中移出；保留截图作来源说明。本轮没有新增存档字段级验证，不为此修改镜像或源存档。 |
| 普通读取列表为空（图03） | 下载包是中断存档 | 通过“继续”能进入EX-HARD MISSION6第10回合，不记为读档失败。 |
| 日文／英文曲名（图14、46） | 原曲名保留观察 | 不算乱码，不据此次截图新增曲名翻译任务；既有英文、缩写和数字继续保留。 |
| 设定图内日文姓名、色指定等（图80） | **既有范围排除** | `docs/special-disc/STATUS.md` 的“已有范围与待定项”已明确设定资料图内说明／批注不在当前汉化范围，不列为待补漏。 |
| 入场动画、加载过渡黑屏、名称横向滚动 | 过程帧 | 后续正常到达的截图已保留，不记为故障。 |
| 流程图未选中节点时底栏为空 | 操作状态 | 图81／82已确认选择节点后的话名与梗概正常出现。 |

## 3. 尚未覆盖的运行检查

下列是**证据缺口，不是已经发现的缺陷**。按实际可达条件补查，不将无入口／无可用组合直接判为损坏。

| 编号 | 范围 | 本轮已到达／缺口 | 后续检查 |
| --- | --- | --- | --- |
| SPCHK-01 | 资料库完整条目 | 机体、人物只抽查样本；术语三页已看，正文只抽查；Q&A只看一组答案。 | 补查剩余条目、长文滚动、分页末行及Q&A各分类。 |
| SPCHK-02 | 剧情流程及关卡入口 | SP/Z流程图已进入，SP梗概仅一个节点；剧情模式仅列表与奖励说明。 | 补查Z梗概、各剧情组起始／最终话、分支及关卡入口。 |
| SPCHK-03 | 特别剧场播放与壁纸 | 四个子模式列表已到达，设定图一张；未播放影片和中断对话；壁纸入口未出现。 | 先确认壁纸的可达条件，再查壁纸／幻灯片设置及影片／对话播放控制。 |
| SPCHK-04 | 战斗鉴赏设置分支 | 普通模式、机体／版本／武器选择及演出片段已查看。 | 补查简易模式、驾驶员／地形／命中等设置、BGM及配置保存／读取。 |
| SPCHK-05 | 精神与战术操作 | 精神仅到使用机体选择；战舰菜单与移动范围已到达。 | 补查精神列表／说明／确认、攻击预览／武器详情、援攻援防／反击及其他可用指令。 |
| SPCHK-06 | 战斗结果与关卡结束 | 只有战斗中片段，未完成整场战斗或关卡。 | 补查伤害结算、击坠、奖励、胜利／失败／通关及对应确认框。 |
| SPCHK-07 | 整备深层页面 | 能力、改造参数、培养分类、强化零件槽、小队与集市入口已查看。 | 补查技能学习／购买确认、实际装备及部件说明、换乘／换装、小队支援及集市出售；使用隔离卡。 |
| SPCHK-08 | 帮助、搜索与系统选项 | 仅部队表帮助、精神搜索首页及系统首页样本。 | 补查项目说明／按键一览、搜索各分类、快捷指令、BGM歌曲选择及部队改名。 |
| SPCHK-09 | 完整存读档流程 | 中断存档可继续；普通读取为空；保存槽和中断保存确认已看。 | 在隔离卡新增普通存档并回读，验证覆盖保存、取消、再启动继续；保留源卡哈希。 |
| SPCHK-10 | PCSX2人工验收 | 本轮仅LRPS2 Software截图。 | 对对应精确镜像另做PCSX2人工页面验收，不沿用自动截图作为通过结论。 |

## 4. 证据位置与本次变更

- [截图册](../../work/runtime/lrps2/sp-ui-audit-20260922/report.html)、[完整检查报告](../../work/runtime/lrps2/sp-ui-audit-20260922/REPORT.md)、[逐图身份与检查记录](../../work/runtime/lrps2/sp-ui-audit-20260922/receipt.json)、[逐帧操作](../../work/runtime/lrps2/sp-ui-audit-20260922/run/commands.jsonl)。
- [机器可读后续清单](../../work/runtime/lrps2/sp-ui-audit-20260922/followup.json)包含5个已修复名称及新证据、10组待检查范围及小队名排除依据。
- 所有截图与模拟器数据继续留在Git忽略的 `work/runtime/lrps2/sp-ui-audit-20260922/`；本文只登记结果，不复制ROM、BIOS或存档进版本库。
- 原始整理阶段没有修改镜像；后续本次修复已更新源码与当前 SP ISO，基线截图仍保持原样。提交范围为修复源码、绑定配置、测试及本检查记录；ISO 与截图留在本地。
