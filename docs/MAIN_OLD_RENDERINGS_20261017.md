# 本篇旧译统一（2026-10-17）

承接 [译名统一](NAME_UNIFICATION_20261017.md) 后的余项。本篇（Original 与 BEST 共用同一份中文）中，同一日文有两种写法的 18 处，在[本篇旧译确认页](https://claude.ai/artifact/YVMGpoC63Ej5pfxZMa3S1S)中立并列，由用户逐条选择。决定见 `config/editorial/main-old-renderings-20261017.json`。SP 盘继承了同一段文字的，一并同步。

## 决定

| # | 日文 | 统一为 | 说明 |
| --- | --- | --- | --- |
| m01 | エーデル・ベルナル | 艾黛尔 | 全部 1,070 处由“艾岱尔”改为“艾黛尔”，含极·艾黛尔、机师名表、说话人、术语表、SP |
| m02 | 総統 | 总帅 | “总统一阁”→“总帅”（用户在对话中补选） |
| m03 | 上級大尉 | 上级上尉 | 战斗台词 1 |
| m04 | ボス（跟班喊波士） | 老大 | 只限努克对波士本人喊「ボス」：剧情 5 句、战斗字幕 battle:16920 1 句。按审阅站关卡数据的日文与说话人逐句定位；其他人对波士仍用“波士” |
| m05 | スター３／スター１ | 星3号／星1号 | 战斗台词 2 |
| m06 | フォースシルエット | 强攻魅影 | 正文、图鉴、SP 中的“强攻型魅影”随之改为“强攻魅影”；零件术语表改写 |
| m07 | ソードシルエット | 剑装魅影 | 机体名表 |
| m08 | ブラック | 黑方 | 机体名“盖纳B（黑方）”、图鉴 |
| m09 | 荷粒子砲 | 荷粒子炮（保持） | 武器名表槽位只能放 4 个汉字，“荷电粒子炮”放不下；术语表随之改为“荷粒子炮” |
| m10 | 低反動砲 | 低后坐炮 | 同为容量所限：低后坐炮、Mk39低后坐炮、低后坐炮（连射）、Mk39低后坐炮（连射） |
| m11 | ＸＭ４７トリスタン | XM47特里斯坦 | 术语表随之改写 |
| m12 | ビッグオー・ファイナルステージ | BigO·FinalStage | 容量所限去掉两个空格；剧情台词中的“Final Stage”不变 |
| m13 | ゴッドシグマ | 巨神Σ | 作品名改为“宇宙大帝巨神Σ” |
| m14 | 魂の凱歌 | 魂之凯歌 | 关卡名及第 95 张关卡标题贴图 |
| m15 | 魂のコスプレイヤー | 灵魂的Cosplayer | 图鉴中的“灵魂角色扮演者”随之改写；术语表改写 |
| m16 | カートリッジ | 弹匣 | 零件名、说明、攻略 Q&A、SP；术语表改写 |
| m17 | ダブルスペイザー | 双重斯派扎 | 零件说明、交易所商品介绍 |
| m18 | 味方フェイズ | 我方阶段 | 本篇 3 处；SP 也改（取代 2026-09-22 SP 保留“回合”的决定） |

## 改动

- **语料与图鉴覆盖**：`tools/editorial_review/apply_main_old_renderings_20261017.py`，规则替换覆盖 `corpus/zh`（本篇与 SP）和 `config/library/v0.2-editorial-overrides.json`；m04 按记录 ID 定点修改；术语表改写 14 个定名，旧写法列入弃用。脚本跳过 SP 说明覆盖的 `baseline_translation`（这是 SP 盘写入前的原文校验值），可重复执行，重跑无改动。
- **关卡标题第 95 张**：用 SP 盘共享字库的字形，按快照的栅格参数和构建器的压缩参数单独重画。用旧文字“灵魂凯歌”重画能逐字节复现原冻结图，以此确认字形来源可靠。快照 `config/assets/stage-title-graphics-indexed-snapshot.json` 只改了这一张及组哈希，另附一条显式改图记录，其余 106 张不变。对比图：`work/review/main-old-renderings-20261017/title95-old-new.png`。
- **SP 盘**：共享名称写入器的契约 `config/products/special-disc/name-unification-20261017.json` 改为可挂多份决定记录，新增 SP 继承的 24 个槽位，共 139 个。新增槽位包括战斗台词、零件说明、武器名、机体名、队长效果，以及 10 个艾黛尔机师名字段。作品名由 SP 作品名池写入器直接读取已改好的共享语料；其余 7 处由 SP 语料写入。`shared-name-reference.json` 同步 4 个键。
- **SP 攻略 Q&A**：第 053 页和关键词摘要第 052 条是与本篇共用的页面，“弹匣”改动已在 `config/editorial/special-disc/qa-shared-updates.json` 登记批准。`qa_native.py` 的报错信息现在会带出前后哈希。
- **构建依赖锁**（与上一轮相同的链）：
  - 默认小队名契约与三处 SHA。
  - 字库配置。
  - SP 共享字库重建（字形不变），`text-canary` 冻结基线已按原哈希恢复。
  - SP 依赖清单。
  - 本地码表同步。

## 验证

- `python3 tools/build_editions.py --editions original,best,sp` 通过，批次 `work/editions/005ed4be…/original-best-sp.json`：
  - Original SHA-256 `604887eedb3cae9579c751ca1309c41854c17a83e6e8e8a77ddb51db47e1ddda`
  - BEST SHA-256 `83fe07d46c8d8916e6b57d7d4c7ae9a2deae18552988692bd56fd752fe531cb1`
  - SP SHA-256 `c316274d2743d5dfad153c7beebf842059215ec0c1ecb547a18e6a5f257b8c04`
- `python3 -m unittest discover -s tests`：771 项 OK（跳过 6）。两项测试的硬编码预期已随决定更新：剧情词表测试中的艾黛尔·贝尔纳尔，以及 SP Q&A 第 53 页的“弹匣”。
- 复查三张新盘的 COMPDATA：上表各旧写法在 Original、BEST、SP 中均为 0。跨版对照与上一轮相同，只剩已知、有意保留的差异。
- 剧情排版检查全部为最终排版。
- 未做模拟器运行验收；第 95 张标题的画面只看过静态对比图。
