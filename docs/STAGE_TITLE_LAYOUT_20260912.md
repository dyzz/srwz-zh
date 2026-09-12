# 关卡标题：Stage Name 整块重排与贴图英文比例排版

> 2026-09-12 实施记录。本文覆盖两项实现和一项运行证据：COMPDATA `Stage Name`
> 文本的整块重排、VT1 进关标题贴图的拉丁字比例排版，以及“场间底部跑马灯显示的
> 是 VT1 标题贴图而不是 COMPDATA 文本”的 LRPS2 证明。初次排版实验未改标题措辞；
> 同日后续完成的 16 项译名修改见第 6 节，最终生产状态以第 7、8 节为准。

## 1. 标题的三条显示链

| 显示位置 | 数据来源 | 本次结论 |
| --- | --- | --- |
| 进关大标题、场间底部跑马灯「第xx話「…」已通关!」 | `DATA/VT1.BIN` group 8 的 107 张 512×64 贴图 | 完全由本项目渲染；跑马灯横向滚动，长度只影响滚动时间 |
| 剧情流程底栏、存档详情、9 条路线选择文案、6 条内部记录 | `DATA/COMPDATA.BN` `Stage Name` 122 条文本 | 由 204 条场景记录的标题指针引用；现在整块重排 |
| 「第」「話」、引号、数字、「已通关!」 | KVMDATA / 数字精灵 | 未改动 |

跑马灯来源的证据：在隔离 canary ISO 中只改 `menu/Compdata/03/0035` 的文本时，
跑马灯仍显示旧标题；只改该标题的 VT1 贴图后，跑马灯随之变化。见第 4 节。

## 2. Stage Name 整块重排

实现：`tools/srwz/writers.py::repack_menu_texts_in_block()`，由
`tools/build_full_story_components.py::_apply_full_stage_titles` 调用；配置为
`config/full-story-components.json` → `full_stage_titles.encoding.block_repack`。
原先的“固定槽 + 尾部 104 字节搬迁池（4 条）”写法已移除，尾部池回到全零。

| 项目 | 值 |
| --- | ---: |
| 区块 | decoded COMPDATA `[0x72DA0, 0x73840)`，2,720 字节 |
| 条目 | 122 条，全部只被 204 条场景记录 `+0x00` 指针引用 |
| 原日文占用 | 1,854 字节 |
| 最终中文占用 | 2,207 字节（含英文宽度控制码，8 字节对齐，121 条位置变化），余量 513 字节 |
| 最终压缩后 COMPDATA | 141,046 字节，硬门 145,408 |

写回契约（全部 fail closed）：区块内除 122 条以 NUL 结束的源字符串外必须全零；
被选条目不得拥有区块外目标，未选条目不得指向区块；每个引用必须是能核对前像的
32 位指针或登记的 MIPS HI/LO 对，内联 `T` 记录拒绝；按原顺序、8 字节对齐重新
分配，溢出即失败，不截断；区块外只改指针字节；写回后逐条重读文本与指针。
单元测试：`tests/test_menu_block_repack.py`。

各条标题现在共享区块容量，仍须同时满足对齐、压缩容量与显示约束；例如“绯红之路”
（9 字节，原槽 8）、“你的身影，我的身影”（19 字节，原槽 16）已不再受单条
原槽限制。标题文本不写入存档；读档详情会按场景记录读取 COMPDATA 标题，
跑马灯则使用 VT1 贴图。已验证的旧存档副本范围见第 4b、4c 节。

## 3. 贴图拉丁字比例排版

实现：`tools/srwz/stage_title_graphics.py::LatinLayout` 与 `layout_title_cells()`；
配置为 `full_stage_titles.graphics.raster.latin_layout`：

```json
{"mode": "proportional_stock_glyphs", "letter_gap": 2, "space_width": 8}
```

规则：ASCII 范围字符仍使用原版 24×24 字形位图，但按各自墨迹列宽推进，字母间距
2 px、空格 8 px（24 px 域，写入贴图时与其他列一样横向加倍）；汉字仍为 48 px 单元、
步进 50。不含 ASCII 的标题输出与此前逐字节相同（已对 6 张贴图核对）。ASCII 标点
（如 `.`）在原 ASCII 字形槽为空白，改为使用发布账本绑定的字形；字母和数字继续
使用原版字形。

首批受影响的 7 张贴图（自然宽度均小于 512，不再压缩；第 6 节改动后再加 4 张英文歌名）：

| ordinal | 标题 | 单元 | 拉丁单元 | 自然宽度 | 压缩 / 槽位 |
| ---: | --- | ---: | ---: | ---: | ---: |
| 46 | Z的脉动 | 4 | 1 | 184 | 1,035 / 1,344 |
| 58 | 第15年的亡灵 | 7 | 2 | 300 | 1,240 / 1,424 |
| 59 | 灵魂的Cosplayer | 12 | 9 | 386 | 1,927 / 2,032 |
| 61 | Acperience | 10 | 10 | 268 | 850 / 1,456 |
| 69 | Over Battle | 11 | 11 | 280 | 989 / 1,248 |
| 91 | 我是D.O.M.E.…… | 12 | 8 | 388 | 1,207 / 1,792 |
| 93 | Gain Over | 9 | 9 | 236 | 942 / 1,328 |

离线试算（同一渲染器）：`Blue Sky Fish` 322、`Into the Nature` 366、
`Morning Glory` 330、`Start It Up` 262，均可 16 级量化装回对应槽位。
单元测试：`tests/test_stage_title_graphics.py`。

## 4. 运行证据（LRPS2）

隔离 canary 只用于本节，不进入生产组件或发布；产物位于
`build/iso/stage-title-ticker-canary/`（被 Git 忽略）。三次运行均加载
`work/analysis/overcoat-runtime-20260907/Mcd001-overcoat-stage38.ps2` 的第 6 槽并停留在
场间画面：

| 运行目录（`work/runtime/lrps2/`） | 修改 | 跑马灯观察 |
| --- | --- | --- |
| `stage-title-ticker-latin-canary-20260912` | 仅 COMPDATA 0035 文本改为「Blue Sky蓝天」 | 仍显示「只属于自己的大逃亡」 |
| `stage-title-texture-latin-canary-20260912` | VT1 0035 贴图改为等格「Blue Sky蓝天」 | 显示「B l u e   S k y 蓝天」，字母各占一整格 |
| `stage-title-proportional-latin-canary-20260912` | VT1 0035 贴图改为比例排版「Blue Sky Fish」 | 显示比例间距的「Blue Sky Fish」 |

贴图在跑马灯里按约 0.5 倍横向缩放显示，与进关标题相同；进关标题画面本身未在
本次序列中出现（该存档进入第 38 话后先播放开场对白），仍待 PCSX2 手工验收。

## 4b. 文本链运行证据（读档详情、剧情流程）

COMPDATA 文本链的两个显示面也用 LRPS2 实机核对过。方法沿用 overcoat 探针：复制
`work/analysis/overcoat-runtime-20260907/Mcd001-before.ps2`，只改第 6 槽存档
`/BISLPS-25887S5/BISLPS-25887S5` 的三个 u16 字段并重算校验和（`0x04` 下一关 STAGE 块号、
`0x06` 已通关 STAGE 块号、`0x08` 同值；校验和为前 `0xF598` 字节的 u16 和，写在 `0xF59A`）。
产物在 `work/analysis/stage-title-text-20260912/`（Git 忽略）：

| 记忆卡 | 已通关块号 → 标题 | 运行目录（`work/runtime/lrps2/`） | 观察 |
| --- | --- | --- | --- |
| `Mcd001-blue-sky-fish.ps2` | 25（`stg_021`，共通 12） | `stage-title-text-blue-sky-fish-20260912` | 读档详情显示「第１２话为止已通关 ～「Ｂｌｕｅ　Ｓｋｙ　Ｆｉｓｈ」」，概要同步为第 12 话 |
| `Mcd001-into-the-nature.ps2` | 73（`stg_058a`，兰德 26） | `stage-title-text-into-the-nature-20260912` | 15 格英文加引号共 18 格，一行放下，无裁切 |
| `Mcd001-blue-sky-fish.ps2` | — | `stage-title-text-scenario-chart-20260912` | 资料库“剧情流程”上下移动 36 个节点，底栏逐一显示第 10–32 话标题，含 Blue Sky Fish、Into the Nature、灵魂的Cosplayer、Acperience、为了做我自己及路线选择文案 |

结论：文本链的英文按项目策略存为全角双字节，两个界面都按等宽格显示（字母之间有明显
空隙），没有触发原版条件宽度的收窄；最长的 Into the Nature 也没有溢出。要让文本链的
英文按逐字墨迹宽度推进仍需另外实现；随后第 4c 节采用现有控制码统一收窄英文，
已接入生产。此处记录的是加入控制码之前的观察。

## 4c. 文本链收窄英文的可行方案：原版 `<width>`／`<space>` 控制码（canary 验证）

原版文本表登记了 4 个内联控制码：`0x31 color`、`0x32 width`、`0x33 height`、`0x34 space`，
菜单语料里已有 `<width:12><height:0C><space:12>` 这类前缀。用 canary ISO（只改 COMPDATA
标题区块，6 条内部／调试标题临时缩短以腾出压缩余量）在两个文本界面验证：

| 写法 | 读档详情 | 剧情流程底栏 | 结论 |
| --- | --- | --- | --- |
| `<width:0C>Blue Sky Fish` | 字形压窄，格距不变 | 同左 | `width` 只改字形渲染宽度，字距反而显得更大 |
| `<width:0C><space:0C>Blue Sky Fish` | 半格间距，正常英文观感 | 同左 | `space` 是推进宽度；后续字符串不受影响（各界面每次绘制前会重设） |
| `<width:0E><space:0C>Into the Nature<width:16><space:16>` | — | 字形略粗于 0C/0C，更易读 | 末尾恢复后格式串里的收尾「」不再被压窄 |

实测默认推进宽度：读档详情 18 px（`0x12`），剧情流程 22 px（`0x16`）；恢复值只影响
标题之后的收尾引号，两者差异肉眼不明显。canary 产物：
`work/runtime/lrps2/stage-title-textwidth{,2,3}-{load,chart}-20260912/`，配方
`work/analysis/stage-title-text-20260912/textwidth-canary-v{2,3}.json`。
同日已接入生产：`full_stage_titles.encoding.latin_text_width`（`trailing_latin_run`，
`width 0E`、`space 0C`，末尾恢复 `12/12`）由 `_apply_full_stage_titles` 在写 COMPDATA 时自动
给“末尾英文段”加标签（`tools/srwz/text.py::wrap_trailing_latin_run`），语料与 VT1 贴图链
保持纯文本；原始 ASCII 扫描已认识带参数的控制码。当前命中 8 条：0020、0057、0059、0061、
0066、0069、0073、0093。Z的脉动、第15年的亡灵、我是D.O.M.E.……的英文后面还有汉字，
不加标签，维持全角。单元测试 `tests/test_stage_title_text_width.py`。

生产 ISO `4995c0b0…c5a241` 的读档详情验收：为 8 条标题各做一张只改已通关块号的记忆卡
（`work/analysis/stage-title-text-20260912/Mcd001-*.ps2`，配方 `textwidth-prod-cards.json`），
运行目录 `work/runtime/lrps2/stage-title-textwidth-prod-*-20260912/`；8 条均显示为半格
英文，收尾「」为正常宽度，标题下方的概要文字不受影响。剧情流程未再重复验收。

影响面盘点：COMPDATA 标题文本的运行时消费者只有原版文字渲染器，已确认的显示面为
读档详情（`～「%s」`，18 px）、资料库剧情流程底栏与章节概要标题（`「%s」`，22 px）、
战斗中“战况报告”的 `～第%s话『%s』`（`menu/SLPS/04/0030`，与读档详情同字号；
`work/runtime/lrps2/stage-title-textwidth-battle-suspend-probe-20260912/`）。中断保存
确认框不打印标题。标题文本不写入存档，旧存档不受影响；`Get_String_Len` 系列例程把
`0x31–0x34` 当作 2 字节控制码处理，居中与测宽不受影响；每次绘制前界面会重设尺寸，
标签不会泄漏到后续字符串。唯一可见差异是剧情流程里收尾「」按 18 px 而非 22 px 渲染。
BEST 版尚未按本轮输入重建。

## 5. 量化等级阶梯

贴图槽位由原日文贴图决定，最小的只有 832 字节。原先只允许 `[16, 8]` 两级；
2026-09-12 改为递减阶梯 `[16, 8, 7, 6, 5, 4]`，构建按顺序取第一个能装回槽位的等级，
并把结果锁进 `expected.full_precision_count` 与 `expected.reduced_precision_ordinals`。
当前只有 3 张降级：67「致远方的友人」7 级（1,209 / 1,264）、70「被昭示的明天」8 级、
92「绯红之路」8 级（965 / 1,040）；97「你的身影，我的身影」改字后反而回到 16 级。
期望值漂移时构建会直接报出实际计数与逐张等级。

## 6. 已写入语料的标题改动

2026-09-12 按用户审校清单写回 `corpus/zh/menu/stage-names.json`，`notes` 记录了理由；
`editorial_status` 按状态单向规则保持不变。术语表 `corpus/glossary/stage-titles-v1.json`
中 `title/bluesky-fish`、`title/morning-glory` 同步改为英文原名，旧译进入
`deprecated_translations`。

| 条目 | 旧 | 新 | 纯文本字节数（含 NUL，不含控制码） | 贴图 |
| --- | --- | --- | ---: | --- |
| 0020 共通12 | 飞鱼 | Blue Sky Fish | 27 B | 322 px，16 级 |
| 0057 兰德26 | 投身自然 | Into the Nature | 31 B | 366 px，16 级 |
| 0063 兰德32 | 为了成为我自己 | 为了做我自己 | 13 B | 16 级 |
| 0066 兰德35 | 牵牛花 | Morning Glory | 27 B | 330 px，16 级 |
| 0067 兰德33 | 远方挚友 | 致远方的友人 | 13 B | 7 级 |
| 0073 兰德39 | 启动一切 | Start It Up | 23 B | 262 px，16 级 |
| 0092 通常51 | 绯红路 | 绯红之路 | 9 B | 8 级 |
| 0097 隐藏56 | 你与我的身影 | 你的身影，我的身影 | 19 B | 16 级 |
| 0101 共通58 | 回忆 | 记忆 | 5 B | 16 级 |

四条英文歌名按用户偏好保留《交响诗篇》原名；中文备选（蓝天之鱼、走进自然、晨光、
就此启动）记录在 `notes` 与术语表的 `deprecated_translations`。

同日第二批按剧情语料核对后写回的“可选润色”与“先不直接替换”项：

| 条目 | 旧 | 新 | 依据 |
| --- | --- | --- | --- |
| 0040 节子27 | 初生的裂痕 | 浮现的裂痕 | 本关结尾对白“给我们留下了无法忽视的裂痕”，指关系裂痕显露 |
| 0054 节子38 | 舞动噩梦 | 起舞的噩梦 | 原为适配固定字槽省略“的”，整块重排后恢复 |
| 0072 兰德38 | 被安排的决战 | 被设计的决战 | 本关概要“众人得知自己与同伴一直遭到某人利用”，满足清单要求的阴谋语境；构建脚本 4 处第 38 话标题锁同步改为新字 |
| 0086 隐藏51 | 决别 | 诀别 | 本关塔丽亚留下临别之言、雷随密涅瓦离去，对白称“分道扬镳”；取告别义并改为规范写法，“决裂”作备选 |

同日第三批，对照 107 项考证总表的“可选润色”由用户点名改动：

| 条目 | 旧 | 新 | 说明 |
| --- | --- | --- | --- |
| 0078 共通44 | 降临的太阳 | 从天而降的太阳 | 「舞い降りる」＝从天而降；本关攻击人工太阳 |
| 0104 兰德59 | 被涂抹的明天 | 被抹去的明天 | 中文更自然，接受少掉“覆盖”画面感 |
| 0106 特殊最终话 | 迈向无尽战争之环 | 走向无尽战斗的轮回 | 「環」取循环义；关内对白仍是“争斗之环／战争循环”，属用户决定的解释性译法 |

保持不变并给出理由：0059「魂のコスプレイヤー」经用户确认保留“灵魂的Cosplayer”，全中文写法
“灵魂角色扮演者”仅作备选；总表其余“可选润色”（被留下的人、羁绊孕育之物、地狱接力赛、
混乱中的正义、乐园的放逐者、幻想都市）经用户确认保留；0038「闇の住処」与 0071「粛清の嵐」
已用原盘 COMPDATA 解析出的日文字符串核对，现译成立，外部表格异文不采用。
`docs/STAGE_ROUTE_MAP.md` 已同步。

## 7. 本次生产构建

```bash
python3 -m unittest tests.test_menu_block_repack tests.test_stage_title_graphics
python3 tools/rebuild_zh_font.py --skip-fetch --refresh-manifests
python3 tools/build_iso.py --config config/iso/zh-release-current-build.json --refresh-output-locks
python3 tools/verify_full_story_iso_content.py --refresh-manifest --force
```

294 项 Python 测试通过；三批标题改动（共 16 条）加文本链英文收窄后的当前工作 ISO SHA-256 为
`4995c0b078195c67be2c9c287d2fa2adaae46255f1185cd66f279b5248c5a241`（前几版依次为
`3ca92e77…54a48f`、`bc8a58fb…851a122`、`6e6f34fb…7781e4`，改动前为 `2148de87…07a386`），全盘语义回读
通过（170 STAGE、93,071 条翻译），122 条标题已从 ISO 的 COMPDATA 逐条读回，改动贴图
逐张回读。与 107 项考证总表的逐条对照见
[`STAGE_TITLE_REVIEW_RECONCILIATION_20260912.md`](STAGE_TITLE_REVIEW_RECONCILIATION_20260912.md)。

`build_text_update_iso.py --refresh-manifests` 以及 `rebuild_zh_font.py` 的组件复用路径
都会因既有的 `config/stage-default-formation-inventory.json` 与
`corpus/zh/menu/stage-default-formations.json` 哈希不一致（HEAD `283db7a` 改了编队名语料
但未重冻结清单）而在文本锁审计阶段停止；这不是本次改动引入的。本次以
`rebuild_zh_font.py --skip-fetch --force-rebuild --refresh-manifests` 走完整路径完成，
该清单应由 `refreeze_stage_default_formation_inventory.py` 另行审核后重冻结。BEST 版尚未按本次输入重建；COMPDATA 的投影只改变
区块内文本和场景记录指针（`+0x800` 基址规则已覆盖），需在下一次双版本构建时确认。

## 8. 提交前复核（2026-09-12）

对本轮最终工作区另行复核，结果记录在
[`stage-title-completion-review-20260912.json`](../manifests/stage-title-completion-review-20260912.json)。

- 107 行审校对照表的现译与正式语料前 107 项完全对应；122 项源文身份保持不变，
  其中 16 项译名有修改。保留译名也有处理结论，`editorial_status` 沿用既有状态。
- 当前 Original ISO 的 SHA-256 为第 7 节所列 `4995c0b0…c5a241`。
  强制全盘语义回读重新通过（170 STAGE、93,071 条翻译），既有验证 manifest 无漂移。
- 额外直接读取该 ISO 的 COMPDATA、VT1：122 项标题连同宽度控制码逐项匹配语料，
  107 张贴图的解码索引哈希逐张匹配组件清单，文本目标均位于登记区块内。
- 两份完整组件清单分别有 83、95 个输入文件身份记录，逐个复核无缺失或哈希漂移。
- 294 项 Python 测试、原盘身份验证、工具编译、ISO／发布入口帮助及 diff 空白检查通过。
- 复看 `work/runtime/lrps2/stage-title-textwidth-prod-*-20260912/` 的 8 张英文标题
  读档详情截图，标题未截断、收尾引号和概要正常；截图哈希及 receipt 中的 ISO 哈希
  均核对一致。可提交摘要保留相对路径和哈希，图片、记忆卡、canary ISO 留在 `work/`。
  本次是复核既有 LRPS2 证据，没有新运行模拟器。

当前生产 ISO 的剧情流程界面未重复验收，进关标题与 PCSX2 人工验收仍待完成，
Best 未按本轮输入重建；不能把 canary 或其他旧 ISO 的运行结果算作这些项目通过。
默认编队清单与语料的旧锁不一致也已复核存在，保留为独立构建维护事项。
