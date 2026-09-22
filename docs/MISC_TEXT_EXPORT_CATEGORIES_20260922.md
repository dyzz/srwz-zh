# 本篇 Original / The Best 零散文本分类

盘点日期：2026-09-22。下文保留初始分类盘点，最终导出范围以本段更新为准。

用户最终限定为三组：菜单、系统与说明（2,714 条），教程正文与标题（124 条），图片文字（194 条），本篇与 BEST 各 3,032 条。BGM 曲名、小队名、地形名、独立人物／机体／武器／演示／作品名称表和地图地点名称表均不进入最终交付；世界地图标题图片保留在图片文字组，音乐选择、编成和地形属性的操作说明仍保留。

最终交付目录：`work/exports/menu-tutorial-images-20260922/`，旁附同名 ZIP。三个分组文件分别为 `menu-system-help.json`、`tutorial.json`、`image-text.json`。使用 `tools/select_misc_text_export.py` 从下述已校验的冻结导出筛选，保留原文、译文和两版定位，不刷新当前工作区语料。保留 5 条版本原文差异；已验证筛选一致性、全部 29 个文件哈希、离线页面数据及 ZIP 的 30 个文件内容。

初始结构化导出入口：`tools/export_misc_text.py`。冻结来源目录：`work/exports/misc-text-20260922/`，旁附同名 ZIP。包含两版原文、导出时的中文、分类文件、原生位置、版本差异、共用源字节的不同用途记录及哈希清单。两版原盘分别校验完整 SHA-256；中文取自导出时的语料，图片标签使用资源标注／原生贴图转写，不代表中文 ISO 回读或运行时验收。启发式分类另列上下文复核队列。

导出额外发现：教程第 8 页的旧标题备注是“技能等级”，两版原盘实际标题与固定槽译文均为“选择帮助”。导出采用实际标题并记录备注差异，没有修改原语料。

## 范围

本轮把“非剧情、战斗、图鉴、Q&A”解释为排除剧情对白、战斗台词、机体／人物／术语事典正文及攻略 Q&A。与战斗有关的菜单、能力说明、系统提示仍属于零散文本；它们在后续导出中保留独立类别，便于整类筛除。特别盘 SP 不在范围内。

Original 与 The Best 使用相同的分类目录，分别保存原文和定位信息。版本身份以当前 `config/editions/original/edition.json`、`config/editions/best/edition.json` 为准：`rom/original.iso` / `SLPS_258.87`，以及 `rom/best.iso` / `SLPS_732.70`。不能把 Original 的可执行文件偏移直接套用到 BEST。

## 建议的 14 个字符串类别

下面是面向阅读／校对的类别，并非现有文件的一对一改名。同一类可能同时来自可执行文件和 COMPDATA；同一语料文件也可能需要拆入多个类别。

| 编号 | 类别 | 收录内容和例子 | 当前主要定位入口 |
| --- | --- | --- | --- |
| 01 | 系统、设置与存读档 | 开始／继续／读取，系统选项、确认／取消，存储卡检查、格式化、容量不足、覆盖和读取失败提示 | `remaining-ui.json` 的 SLPS / COMPDATA 固定槽，`system-ui-command-menu.json`；标题菜单的图片部分另记 |
| 02 | 开局选择与命名 | 主人公选择、生日／血型、姓／名／昵称、日式／西式读法、部队命名；开局路线标题及人物简介 | `system-ui-character-setup.json`、`system-ui-name-screen.json`、`opening-protagonist-profile.json` |
| 03 | 整备与养成操作 | 中场休息、驾驶员培养、机体／武器改造、换乘、装备，相关操作说明与限制提示 | `remaining-ui.json`、`unclassified.json`、`system-ui-command-menu.json` |
| 04 | 小队编成与搜索 | 建立／解散小队、队长／队员、后备区、排序、阵型选择、搜索条件、自动命名说明 | `system-ui-search.json`、`system-ui-search-menu.json`、`remaining-ui.json`；小队名称建议另作名称附表 |
| 05 | 地图与战术指令 | 移动、攻击、待机、修理、补给、回合结束、出击／搭载、援护选择、作战目标界面的通用标签 | `system-ui-command-menu.json`、`system-ui-tactical.json`、`system-ui-battle-conditions.json`、`unclassified.json` |
| 06 | 能力、属性与状态字段 | 驾驶员／机体／武器性能字段，HP／EN／SP／PP、气力、命中、射程、地形适应、移动类型、异常状态及解释 | `system-ui-unit-mech-pilot-weapons.json`、`system-ui-map-data.json`、`remaining-ui.json`；动态组合标签也需登记 |
| 07 | 精神指令 | 精神名称、简称、效果说明、目标选择和使用条件 | `system-ui-spirit-commands.json`、`system-ui-spirit-acronyms.json`、`remaining-ui.json` |
| 08 | 特殊技能、特殊能力与武器效果 | 驾驶员技能、机体能力、发动条件、等级／数值说明，屏障贯通、无视体型修正等武器效果 | `system-ui-skills.json`、`system-ui-special-abilities.json`、`weapon-special-effect-2.json`、`remaining-ui.json` |
| 09 | 队长效果与小队奖励 | 经验／资金加成、射程／移动力／命中回避加成、小队修理／补给等效果 | `system-ui-leadership.json`、`remaining-ui.json` 的 `leadership_effect_by_offset` 及上下文帮助 |
| 10 | 强化零件 | 零件名称、效果、装备／卸下及相关限制说明 | `system-ui-parts.json`、`remaining-ui.json` |
| 11 | 交易所与商品介绍 | 购买／出售／价格／持有量、交易提示，以及商品背景介绍等短文 | SLPS 固定槽、`remaining-ui.json`、`unclassified.json`；交易所标题图片另记 |
| 12 | 结算、奖励与成长通知 | 获得资金／BS／零件／机体、升级、技能习得、击坠与奖励提示 | `system-ui-results.json`、`remaining-ui.json`；STAGE CLEAR 等图片另记 |
| 13 | 按键帮助与共通提示 | 确定、返回、切换、翻页、搜索、操作帮助、页签、选择框和格式化提示模板 | `system-ui-buttons.json`、`remaining-ui.json`；场景图的通用按键提示不能因位于 STAGE 就整体漏掉 |
| 14 | 音乐选择与作品标题 | BGM 曲名、音乐选择操作提示、参战作品标题、收录率等菜单文字 | COMPDATA 音乐标题表、`tools/srwz/sound_select.py`、`remaining-ui.json` 的作品标题引用；不含图鉴正文 |

“战斗条件”文件名不能作为整类排除依据：其中有通用 UI 字段。各关具体胜利／失败／SR 条件属于关卡脚本，暂不进入以上主表。

## 名称、教程和图片的独立附表

这些内容也属于非对白，但不宜与系统提示和帮助正文混为一张表。

| 附表 | 已发现的范围 | 处理方式 |
| --- | --- | --- |
| 名称表 | 人物／机体／武器显示名、母舰名、小队名称建议、剧情默认小队名 | 单独导出；菜单中的名称不等于图鉴介绍。现有 `weapons.json` 有 711 条语料，`ui-name-tables.json` 有 104 条小队名建议；它们不是去重后的全游戏名称总数 |
| 地名与地形 | `MAP/MAPNAME.BIN` 的具名地图记录、MAPMODEL 地形／地点名、世界地图标题 | `ui-name-tables.json` 有 73 条具名地图记录，`mapmodel-terrain-names.json` 有 84 个译文条目。MAPNAME 的玩家界面调用仍未确认；地图名与地形名不能合并计数 |
| 教程 | `nisv-tutorial-pages.json` 的 10 页、114 条正文记录及页标题 | 与 Q&A 分开登记；本轮主表暂不混入整页教程。教程关卡对白仍属于剧情 |
| 图片文字 | 标题菜单、中场休息、交易所、编成、按键帮助、结算、资料库导航等贴图标题／标签 | 另列图片标签清单，保存原文、译文、成员／块／TIM2／矩形定位。来源含 VT1、KVMDATA／KVPDATA、NISVDATA；不能用字符串提取结果声称覆盖图片 |
| 战斗画面图片标签 | 跳过动画提示、援攻／援防、暴击、屏障等固定效果文字 | 属于战斗 UI，与战斗台词分开；默认作为可独立排除的附表，来源含 AIDDATA、TRICMN 等 |
| 待机演示名称 | OP*.BIN / OP*.SEG 中的固定名称字段 | 由 `tools/srwz/auto_demo.py` 定位，作为名称附表的独立来源，不能仅检查 COMPDATA 名称表 |

世界史、关卡标题、STAGE／HSFC 剧情概要、Z 报告、关卡具体条件虽然不都是对白，但与剧情内容直接相连，本轮仍排除。片尾职员表／版权文字的独立来源和完整覆盖尚未在本次盘点中核实，不计入已确认类别数量。

## 现有导出能复用什么

工作区已有 `tools/export_explanatory_text.py` 及 `work/exports/explanatory-text-20260922/`。本次读取其 manifest，并重新核对其中登记的输入文件 SHA-256，均与当前文件一致；没有重新对两张完整 ISO 做哈希或提取。

- 现有导出每版 7,673 条：其中图鉴字段 4,921 条，非图鉴 `menu/*` 候选 2,752 条。
- 2,752 条候选中的 5 条日文存在版本差异：技能说明、两条特殊能力说明、交易所纳豆介绍的错字、小队顺序操作说明的重字。这个数量只适用于现有导出范围。
- `menu/Unknown` 仍有 381 条，内容跨越指令、属性、整备和存读档等类别；“Unknown”是旧提取器的分组，不能作为交付给校对者的最终分类。
- `remaining-ui.json` 的直接偏移分组同样跨多个语义类别；需要逐条归类，并保留原始技术分组作为来源字段。
- `release-v0.3.json` 是发布选择和覆盖层，不能作为额外类别累加。`remaining-ui.json` 与旧指针表也有重叠，需按目标位置和语义记录区分覆盖关系。
- 现有导出未完整覆盖名称附表、音乐曲名表、教程、图片标签等来源。因此 2,752 是可复用的候选记录数，不是本次零散文本的最终总量。
- 已有导出中的中文来自当前工作区语料，不是分别从 Original／BEST 中文成品 ISO 解码得到的文本。

## 后续导出的记录约定

先按上面的类别归并已有字符串，再补齐独立表。每条至少保留稳定 ID、语义类别／子类、Original 日文、BEST 日文、各版本位置、当前中文及语料来源、版本差异标记。位置要注明是文件偏移、解压后偏移、表记录或图片区域。共享翻译不应伪装成分别从两版成品读取的两份中文。

同文不同位置保留所有引用；同一位置被不同语料覆盖时记录最终选择及覆盖来源。保留控制标记、占位符、换行、Latin／缩写和数字，不按文字长度、是否含假名或所在资源文件名判断是否收录。

最终数量在两版原盘分别提取、按语义归类和去重规则落实后给出。这份文档只完成分类盘点，不代表新的运行时验收。

## 核查入口

- `corpus/zh/menu/*.json`、`corpus/zh/display-names/*.json`、`corpus/zh/ui-atlas/*.json`
- `vendor/upstream-python/project/menu_files.json`
- `config/editions/{original,best}/edition.json`、`config/editions/best/source-layout.json`
- `config/assets/title-menu-zh.json`、`config/assets/ui-headings-zh.json`
- `tools/export_explanatory_text.py`、`tools/srwz/ui_name_tables.py`、`tools/srwz/sound_select.py`、`tools/srwz/auto_demo.py`
- `docs/UI_OMISSIONS_FIX_20260909.md`、`docs/UI_ATLAS_REMAINING_20260920.md`、`docs/BUILD_EDITIONS.md`

本轮只新增此分类文档，未改动已有语料、导出脚本、ISO 或构建锁。
