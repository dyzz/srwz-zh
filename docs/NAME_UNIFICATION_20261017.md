# 本篇／BEST／SP 译名统一（2026-10-17）

承接 [译名一致性审计](MAIN_BEST_SP_NAME_CONSISTENCY_AUDIT_20261016.md)。用户在 [SP 与本篇译名对照页](https://claude.ai/artifact/Uh2pqvmZnscTCH3qdfdoH1) 逐条确认了 85 条，又对 4 个与术语表冲突的问题作了补充回答。完整决定见 `config/editorial/name-unification-20261017.json`。

## 补充决定

| 问题 | 决定 |
| --- | --- |
| ∀高达 5 个人名，确认页选择与术语表已批准写法相反 | 按本次选择：特泰丝·哈雷、米姆·米德加尔德、梅莉贝儿·加吉特、希德·蒙扎、高安·莱因福德；术语表定名随之改写，旧写法列入弃用 |
| サラ・コダマ | 沿用 2026-08-28 的“莎拉·古塔玛”，改名表（覆盖确认页上的 A） |
| ブロンコ | 人名、机体ブロンコⅡ、ブロンコ隊统一改为音译：扎奇·布隆科、布隆科II、布隆科队 |
| マルチナ・レーン | 保持“玛尔蒂娜·雷恩”，只有辛西亚改为“琳” |
| SP 战斗鉴赏 9 个士兵标签槽仅 16 字节，“联邦军士兵（1）”放不下 | 去掉括号：奇拉姆士兵1、联邦军士兵1、革命军士兵1、扎夫特士兵1 等；DC士兵（1）、身份不明士兵（1）的槽位够大，保留括号 |

两条按原文作了调整：

- **d02 盾牌防御说明**：SP 原文与本篇不同（SP 是「敵攻撃命中時に」，本篇是「「反撃」選択時にも」）。前两行改用本篇措辞，第三行保留 SP 原文的意思：“被敌方攻击命中时也有一定几率发动同样效果。”
- **t06 EX 困难**：只改 SP 的两条改造／培养限制说明，SP 挑战模式本身的 EX-HARD 标签不变。

同一日文由多人共用时，只改决定涉及的人，其余用单条覆盖保留：

- クライン：拉克丝、西格尔及克莱茵派改为“克莱茵”，GRAVION 的克莱因·桑德曼保持“克莱因”。
- エイジ：ポゥ・エイジ的姓改为“艾吉”，红英司保持“英司”。
- ゲイン：ミハエル・ゲイン的姓改为“格恩”，该隐·比琼的“该隐”不变。
- レーン：辛西亚改为“琳”，玛尔蒂娜保持“雷恩”。

## 改动

**本篇／BEST 与 SP 语料**：`tools/editorial_review/apply_name_unification_20261017.py` 在 67 个语料文件中按规则替换 398 处（剧情、战斗字幕、图鉴、菜单、SP 剧情／挑战／战斗台词／系统文字／图鉴），逐条报告见 `work/review/main-best-sp-consistency-20261016/apply-report.json`。

**图鉴生效覆盖**：本篇图鉴实际显示的是 `config/library/v0.2-editorial-overrides.json` 的覆盖译文，其中仍有新帕尔萨班、阳光号、桑布鲁、贝鲁那尔、克莱因派、机械战士等旧名（16 日的审计只查了语料，漏了这一层）。同一脚本第二轮在该文件替换 64 处（`apply-report-2.json`），并加入“机械战士→装甲怪兽”。脚本可重复执行，第三次运行无任何改动。

**连带改动**：ブロンコⅡ 改为“布隆科II”后，SP 的机体名及战斗鉴赏副本也一并改写；マードック 的说话人译名改为“玛多克”后，SP 机师名表同步。SP 攻略 Q&A 第 070 页的颜色排版契约（`qa-layout.json`）同步“盖塔小队”并重算译文哈希。

**机师名表**：`remaining-ui.json` 的共用映射改了 33 个键，另加 6 条单人覆盖（`pilot_name_overrides`）。

**术语表**：8 个定名改写，旧写法保留在弃用列表：希德·蒙扎、高安·莱因福德、米姆·米德加尔德、特泰丝·哈雷、梅莉贝儿·加吉特、布隆科II、布隆科队、玛多克。

**排版**：剧情不可拆分词表重新生成，2 条对白按新名字重排（`config/editorial/story-layout-name-unification-20261017.json`）。

**SP 盘**：SP 的 COMPDATA 名称来自冻结的本篇快照（9-17 构建与 9-29 名称参考），本篇改名不会自动带过去。本轮没有整体换快照，以免把无关的本篇改动一并带入，而是新增定点写入器：

- `tools/special_disc/writeback/name_unification.py`，契约 `config/products/special-disc/name-unification-20261017.json`：115 个槽位，其中 29 个指针字符串（武器 8、机体 9 及战斗鉴赏副本 4、布隆科II 2、节子路线副标题 1、士兵标签 5），86 个机师名字段。每个槽位锁定原文字节、前一步写入后的字节、指针位置和容量（与 `write_system_text` 相同，至多补到 8 字节边界），写后回读；`verify_full_text.py` 在最终 ISO 上独立复核。契约记录决定文件的路径、SHA-256 和决定 ID，构建时不读取 `config/editorial/`（SP 依赖清单只允许 `work/` 与 `config/editorial/special-disc/`）。契约生成脚本：`work/review/main-best-sp-consistency-20261016/make_sp_contract.py`。
- `shared-name-reference.json` 同步更新 47 个键，SP 全名表校验以新名为准。
- 另外 9 个士兵标签由 `system-text.json` 直接写入。

**构建依赖锁**：

- `stage-default-formations.json` 改动后，用 `refreeze_stage_default_formation_inventory.py` 刷新默认小队名契约。
- 契约的新 SHA 同步到三处：`zh-release-font-assignments.json`、`zh-release-font.json`（分配表 SHA）、`full-story-components.json`。
- SP 共享字库按新分配表重建（`build_text_candidate.py`），字形 `font.bin` 不变，`config/editions/sp/inputs.json` 更新了 profile／proposal／manifest 三项。
- 重建字库时会顺带改写 `text-canary` 冻结基线。该基线由构建器以 `BASE_SHA` 锁定，必须保持冻结，所以已从此前的 SP 构建工作区按原哈希恢复（APFS 克隆）。
- 本地 `work/writeback/zh-release-codebook-proposal.json` 从最新本篇构建工作区同步：只有分配表哈希和 UI 选择锁两处不同。

## 验证

- `python3 tools/build_editions.py --editions original,best,sp` 通过，批次 `work/editions/136d4431…/original-best-sp.json`，状态 `requested_editions_static_validated_runtime_pending`：
  - Original `build/iso/zh-release-original/current-original.iso`，SHA-256 `ee9269f7bbcdd01bede29e59835fd87f1a91a407161ad9331bb4a4600ab0ae7c`
  - BEST `build/iso/zh-release-best/current-best.iso`，SHA-256 `ced9f43ae1edea5fdf9b172373556a43ef461a53a04ff95868a345a55fe7b155`（含同日修复的盾牌防御说明槽，见审计报告第 1 节）
  - SP `build/iso/special-disc/sp-current.iso`，SHA-256 `10dd95aa99553d1fb850c145d618417af599a7821db25bbdd32835b7de20603a`
- `python3 -m unittest discover -s tests`：771 项，OK（跳过 6）。
- 剧情排版检查 `check_story_dialogue_layout.py`：全部为最终排版。
- 用审计脚本按日文逐槽复查三张新盘的 COMPDATA：
  - 本篇与 BEST 只剩一处无害的子串指针（`连射）`）。
  - SP 与本篇的机师名字段差异为 0。
  - 决定涉及的旧写法在 SP 盘里只剩“雷恩”1 处（玛尔蒂娜，按决定保留）。
  - 其余差异是已知、有意保留的：本篇 BGM 表一带的日文字串、SP 的“机师”、SP 自己审定的 4 条说明措辞。
- 未做模拟器运行验收，未提交 git。

## 不在本轮范围、仍待决定

审计报告第 4.2 节中未上确认页的本篇旧译：艾黛尔（6 处）、双重飞碟（零件说明）、总统一阁、STAR 3、强攻魅影／巨剑魅影（机体名）、荷粒子炮／低反动炮与武器术语表的分歧。
