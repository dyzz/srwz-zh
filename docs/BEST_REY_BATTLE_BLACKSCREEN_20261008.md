# Best 女主线第 3 话雷进入战斗演出时黑屏反馈

2026-10-08。反馈人：**埃尔03**。关联 [V042-010](V0.4.2_POST_RELEASE_ISSUES.md#v042-010)。

**当前结论：玩家录像已确认持续黑屏，本地及 Seeker 尚未复现。** 视频实际路线是雷原地用**光束突击枪**攻击奥尔的深渊高达（HP 165），演出 ON、开启加速；Best 在点“开始战斗”后直接黑屏，尚未出现演出或结算。按该武器／位置／目标补测的 10 月 6 日 Best 在 LRPS2 和 **Seeker／Android 16／AetherSX2 v1.5-3668** 均完成结算及事件，并恢复可操作地图；Seeker 也开启了加速，但未测得与玩家相同的精确速度。没有定位根因、修改游戏代码或宣称修复。

## 反馈与待确认信息

- 原反馈：“女主线第三关用雷来战斗结束会黑屏。”
- 补充：“任意的战斗都会，不过只是 best 会，另一个不会。”这是玩家描述的范围，本轮没有完成任意战斗的穷举。
- 用户先推测“应该是 0.4.2”，后补充也可能为 current-best，并要求测试方块。
- 玩家后续明确：“安卓蓝以太 3668”，“10 月 6 号发的 chd 文件夹里的测试版”；另一版可以正常玩。由此将重点从稳定 v0.4.2／10 月 8 日 current-best 转到 10 月 6 日批次。
- 用户随后根据视频提出火蜂、补充原地攻击；逐帧核对后确认火蜂只是曾被高亮，最终选择的是光束突击枪。具体视频证据和补测见下节。
- 玩家手机型号、实际 CHD 哈希、渲染器和其他设置、启动前是否恢复过即时存档，仍未确认。录像内可见从标题“继续”恢复战场。Seeker 是用户连接的本次测试手机，不能代替反馈者手机的硬件与设置。

## 玩家录像核对与原地攻击补测

输入录像：`/Users/nate/Downloads/Screenrecorder-2026-10-08-17-16-56-391.mp4`，时长 73.839 秒、27,797,523 字节，SHA-256 `0722cc32e620dd1e83007182183cb89f2cfa11b156716cdb5910610fdb3452d7`。以下时间为录像时间，模拟器帧率与录屏帧率分开记录。

| 时间 | 可见操作／结果 |
| --- | --- |
| 约 11.2 秒 | 武器列表高亮“火蜂” |
| 约 11.4 秒 | 选择往上移到“光束突击枪” |
| 12.6 秒 | [战前确认](issue-assets/setsuko-stage3-rey-20261008/player-video-12.6-rifle-confirm.png)：雷 Lv7、HP 8250、EN 258、气力 116，光束突击枪；目标奥尔 Lv8、深渊高达 HP 165、EN 144；演出 ON。雷未先移动 |
| 约 13 秒起 | 点开始战斗后直接黑屏，没有可见战斗演出或资金结算 |
| 22 秒 | [仍黑屏](issue-assets/setsuko-stage3-rey-20261008/player-video-22-black.png)，保留触屏控件、加速标记及 V119.89；不是只凭单张过场黑屏判定 |
| 约 25 秒 | 暂停页识别 `srwz-zh-v0.4.2-best-20261006.chd (SLPS-73270 / 53B9FBC8)`，随后退出 |
| 后半段换另一版 | 约 63 秒出现光束突击枪演出，69 秒 [资金 6000](issue-assets/setsuko-stage3-rey-20261008/player-video-69-other-funds.png)，71 秒奥尔对白，73 秒返回地图。玩家称该版为 Original；未获得该手机文件的整盘哈希 |

两段都有加速标记，模拟器显示约 120 帧。前段没有可见方块跳过操作，但触屏画面不是输入日志，不能证明没有任何输入。录像能确认持续黑屏，不能单凭画面判定 CPU 死锁、渲染故障或具体补丁根因。

按视频修正路线，均用保留的 10 月 6 日 Best、同一原生中断档冷启动恢复，**原地光束突击枪 → 奥尔／深渊高达 HP 165，演出 ON，不按方块**：

- LRPS2：完整演出后返回“一击脱离”菜单，选待机，资金 6000、EXP 429／PP 24、Lv7→Lv8，继续尼奥／奥尔事件后能打开 [地图菜单](issue-assets/setsuko-stage3-rey-20261008/oct6-local-stationary-map-menu.png)。请求计数为 0，抽样补丁执行代码未变。
- Seeker／3668：战前使用 Toggle Frame Limiter 开启加速，录像可见加速标记及 [攻击命中](issue-assets/setsuko-stage3-rey-20261008/seeker-stationary-fast-animation.png)，完成一击脱离、[资金 6000](issue-assets/setsuko-stage3-rey-20261008/seeker-stationary-fast-funds.png)、升级、尼奥／奥尔事件，恢复 [地图菜单](issue-assets/setsuko-stage3-rey-20261008/seeker-stationary-map-menu.png)。没有测量 Seeker 的实际加速帧率，不能将其登记为精确 2 倍速复现。

视频核对前另做过移动后火蜂攻击斯汀的补测：LRPS2 完整演出及 +300 帧方块长按 780 帧两轮均通过（请求计数分别为 0、1），斯汀余 HP 511、反击、EXP 42／PP 0 后恢复地图；Seeker 完整火蜂演出也走到 EXP 42 和地图菜单。这些是其他路线覆盖，不是玩家视频路线的复现。

本地原地会话目录历史命名为 `firebee-stationary-full`；实际开始战斗前取消了火蜂选择，改为视频里的光束突击枪，**该会话只执行了一场光束突击枪战斗**。前面的灰色 TRI 武器误选也在开始战斗前退出，不计为战斗测试。完整命令保留，避免把目录名当成武器证据。

补测结束已退出手机游戏，将槽 1 恢复为原 `Mcd001.ps2`；原两卡和独立测试卡哈希均未变，加速在结算前切回。原录像和两段手机录像留在忽略目录；视频元数据、时间线、三轮新增本地测试、手机测试及恢复证据绑定于 [视频核对补充回执](issue-assets/setsuko-stage3-rey-20261008/player-video-followup-receipt.json)。旧回执保留为历史记录。

## 记忆卡保全

输入：`/Users/nate/Downloads/Mcd001.ps2`，69,206,016 字节，为 64 MiB 数据加 ECC 的 PS2 卡镜像。

SHA-256：`07bd1372638abe2dc9502d4128d62ed585bef280d8deb6995964c7079e9db799`。

只读解析使用 `mymcplusplus.ps2mc`，卡文件以 `rb` 打开。保全副本、提取的本作文件及运行卡均留在忽略目录，原件未改写。卡还包含其他游戏，本调查只登记本作文件，不上传整卡或其他游戏存档。

| 本作文件 | 大小 | 检查 |
| --- | ---: | --- |
| `/BISLPS-25887Q/BISLPS-25887Q` | 142,800 | 由各测试 ISO 冷启动选择“继续”，自然恢复战场 |
| `/BISLPS-25887S0/BISLPS-25887S0` | 62,880 | 普通存档校验和计算值／存储值均为 20299 |
| `/BISLPS-25887S1/BISLPS-25887S1` | 62,880 | 普通存档校验和计算值／存储值均为 37430 |

运行中地图字段为 STAGE 4、回合 2；实际能力页确认驾驶员雷 Lv7、瞬发型扎古幻影。样本显示武器高改造及多项技能，保留玩家样本原状；没有用脚本修改技能、数值、位置或事件。

## 镜像与运行条件

v0.4.2 测试盘由保留的发布 xdelta 和对应日文原盘还原；整盘哈希与锁定发布记录核对。current-best 单独绑定本轮读取的实际文件，不把它当成玩家镜像。

| 镜像 | SHA-256 |
| --- | --- |
| v0.4.2 Original，无 skip | `6a72307c36ec6b2f7f0af9e6f31d1a88cdb092af7d1b64377341c2e4b7e0e50c` |
| v0.4.2 Best，无 skip | `081b4ce998b9c71ba17f84f5e410e6bfa0b99b9d4582711f2d72d60defa6cc1a` |
| v0.4.2 Best，带 skip | `c87442d9d8f2cb8c4399292ed135e9682f45e0f0e7c6461988fbb6e3557a15cb` |
| 本轮 current-best | `3a2ddb299cd5deb985a8214dfcb15961a6fa3b6e6ff26f85e80dbcce1536ecea` |

LRPS2 `v2.0.0-16e520b`，x86_64 Python 3.12.14／libretro.py 0.8.3，Software (SW) renderer，关闭金手指、共享记忆卡。核心 SHA-256 为 `e0aa4d6c1b68fca49f9088acacb2a8dddaa6d9d62f21a14766f8023b0217fdf4`。

每轮独立进程冷启动、复制并挂载保全卡、在标题选择“继续”；没有恢复模拟器即时存档，没有 RAM poke。RAM dump 仅用于只读取证。操作由仓库既有 LRPS2 驱动记录于 `commands.jsonl`。

## 指定自然战斗与方块对照

从中断档恢复后，选择雷，向上移动四格，使用“光束突击枪”攻击斯汀驾驶的混沌高达，动画 ON。两版采用相同单位、移动和攻击路线；启动／探索等待帧略有差异，不把随机伤害或字幕时序视为逐帧相同。

| 测试 | 方块操作 | 观察结果 |
| --- | --- | --- |
| v0.4.2 Best 无 skip | 不按 | 完整演出后资金 6000、雷 Lv7→Lv8、斯汀战后对白；随后恢复地图，可打开指令菜单 |
| v0.4.2 Original 无 skip | 不按 | 同样完成结算、升级和战后事件，恢复地图菜单 |
| v0.4.2 Best 带 skip | 战斗开始后 300 帧，雷头像切入时开始按住 780 帧 | 跳过请求计数为 1；回到资金结算并继续升级、事件，恢复地图菜单 |
| current-best | 同上 | 跳过请求计数为 1；完成同样的结算、升级、事件及地图菜单 |
| current-best，另一次独立冷启动 | 战斗开始后 600 帧，在敌机伤害／爆炸阶段开始发出十次 3 帧方块脉冲，每次随后空闲 32 帧 | 跳过请求计数为 1；继续通过资金、升级和战后事件，恢复地图菜单 |

v0.4.2 Best 带 skip 和 current-best 的机器码及三个 hook 站点均匹配当前 native-tail-r5 契约；两者该补丁范围逐字节一致。两轮 RAM 中，跳过状态块 `0x3F6600 + 8` 的请求计数为 1，执行代码区域 `[0x3F6000, 0x3F6600)` 与战前 dump 一致。它们证明这次方块请求实际触发及抽样代码未变，不证明所有对象生命周期或平台安全。

首次带 skip 探索把方块提前按在战前确认菜单，实际打开精神菜单，导致后续画面与原定命名错位。该会话 `v042-best-skip-run1` 保留为无效路线记录，**不计入上述通过项**；有效方块路线是重新冷启动的 `v042-best-skip-run2`。

## 10 月 6 日 CHD 批次与 Seeker 补测

从保留的清理归档复制恢复 `srwz-zh-v0.4.2-best-20261006.chd`，没有重新构建或用最新 current-best 代替。与 `build/chd/test-20261006/manifest.json` 核对：版本 `v0.4.2+20261006`，批次源提交 `51569b200d9abf5b92c7c754015852bdf8daa1b6`，带方块 skip。

| 对象 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| 恢复的 Best CHD、复制到手机的 CHD | 2,557,267,925 | `0f5e5f8bd7b44465bb0ef7641b4b15ceb79627fb8a6e3ebf4a480624d3e06a2e` |
| chdman 0.289 extractraw 解出的 ISO | 3,755,081,728 | `28e7a3d04225e6e01e0580d112a6ec95e4ed0878f093204876aad6f487aed6a1` |

**本地补测**：`best-20261006-square` 独立 LRPS2 冷启动，使用相同保全卡及前述四格移动路线，在动画开始后 300 帧按住方块 780 帧。请求计数为 1，抽样执行代码未变；资金、升级、斯汀对白与地图菜单均通过。原批次 manifest 的 `runtime: not_tested` 保留为当日历史状态，本次证据另存补充回执。

**手机补测**：ADB 核实设备 Seeker、Android 16，包 `xyz.aethersx2.android` 为 `v1.5-3668`／versionCode 13930。直接运行 CHD，暂停页识别为 `SLPS-73270 / 53B9FBC8`，标题版本角标为 `v0.4.2+20261006`。从标题“继续”恢复原生中断档，没有恢复即时存档。

保留手机原有 OpenGL、1x Native、EE 100%、EE Skip 0、Multi-Threaded VU1／Instant VU1 开启等设置，不启用补丁码。将保全卡复制为独立 `El03-Rey-20261008.ps2` 后挂载槽 1。雷移动后使用光束突击枪攻击斯汀／混沌高达，动画 ON；战斗开始约 5 秒后截到雷射击前画面，随后发送 1500 ms 方块触屏长按。手机摇杆操作的落点与本地四格路线不同（最终位于蓝色友机左侧），本次只认定为同武器／目标的移动后攻击，不能称为逐格相同回放。

手机录像中可见射击、敌机 HP 0／爆炸、资金 6000、雷升级、斯汀战后对白，随后恢复地图并能打开阶段结束确认框，未黑屏。手机没有读取 skip 请求计数，**只能证明发送了方块输入并成功返回，不能将其登记为已核实 hook 接受请求**。

退出游戏后已将槽 1 恢复为原 `Mcd001.ps2`；原两张记忆卡的前后 SHA-256 一致，反馈原卡及独立测试卡也未变。测试 CHD 和独立卡仍保留在手机专用测试路径。一次误选旧 `current-best-skip-20261001.iso` 的开机探索在标题前结束，未参与有效战斗，排除在结果之外。

补测的镜像、卡、命令、录像、截图与恢复检查绑定在 [10 月 6 日批次／手机补充回执](issue-assets/setsuko-stage3-rey-20261008/oct6-seeker-receipt.json)。手机 [资金结算](issue-assets/setsuko-stage3-rey-20261008/seeker-funds.png)、[雷升级](issue-assets/setsuko-stage3-rey-20261008/seeker-levelup.png)、[战后对白](issue-assets/setsuko-stage3-rey-20261008/seeker-post-battle-event.png)、[返回地图菜单](issue-assets/setsuko-stage3-rey-20261008/seeker-map-menu.png) 已选存；完整 74 秒录像在忽略目录 `work/analysis/setsuko-stage3-rey-20261008/phone/rey-phone-square.mp4`。

## 证据位置与边界

- 忽略的输入与分析：`work/analysis/setsuko-stage3-rey-20261008/`。
- 忽略的逐帧命令、核心日志、隔离卡、截图和 RAM：`work/runtime/lrps2/setsuko-stage3-rey-20261008/`。
- 可入库摘要和选定截图：`docs/issue-assets/setsuko-stage3-rey-20261008/`。

[初轮运行摘要](issue-assets/setsuko-stage3-rey-20261008/receipt.json) 绑定五次有效会话、卡／ISO／核心哈希、逐帧命令与全部截图哈希；其中模拟器未知的字段是后续补充前的历史状态，以本页及补充回执为准。[方块补丁静态回读](issue-assets/setsuko-stage3-rey-20261008/square-hook-static.json) 单独记录 ELF 检查，不混同运行结果。
current-best 的 [方块前头像切入](issue-assets/setsuko-stage3-rey-20261008/current-best-run1-animation-before-square.png)、[方块后资金结算](issue-assets/setsuko-stage3-rey-20261008/current-best-run1-held-square-780.png)、[最终地图菜单](issue-assets/setsuko-stage3-rey-20261008/current-best-run1-map-menu.png)，以及另一次 [伤害阶段方块前画面](issue-assets/setsuko-stage3-rey-20261008/current-best-run2-effect-before-square.png) 和 [连续方块后地图菜单](issue-assets/setsuko-stage3-rey-20261008/current-best-run2-map-menu.png) 已归档。

初轮结果只覆盖“先移动再攻击、光束突击枪、击破斯汀”；新增证据另覆盖移动后火蜂／斯汀和视频里的原地光束突击枪／奥尔路线。敌方回合反击、动画 OFF、其他方块时机及反馈者手机的具体环境不能由这些指定路线推定。Seeker 已有直接 Android AetherSX2 运行证据，没有新增 PCSX2／ArmsX2 人工证据，也未做全关卡通关验收。

下一次定位应优先绑定反馈者 CHD 校验值、手机型号与全局／单游戏设置；可在反馈者原环境对照关闭加速、软件渲染及干净单游戏设置，分别记录结果。它们是待检验条件，不是已判定原因。继续保留“玩家录像已确认，本地尚未复现”状态，不能据 Seeker 通过断言 3668 或 Best 在所有条件下正常。
