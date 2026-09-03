# STAGE 剧情文本重排清单

> 当前生产语料快照，更新于 2026-09-03。本文是人读审计索引，不参与构建；
> 机器可读的逐指针事实以
> <code>work/build/full-story-stage/components/component-validation.json</code> 为准。

## 口径

生产 writer 会以单个 STAGE 为事务，把该段全部 parser 已识别的对白和条件文本
重新放入同一段确认归属的字符串区间。因此，“发生地址变化”与“某条译文必须扩容”
不是同一个集合：前者包含由排序、共享 payload 和 16 字节对齐带来的机械搬移；
后者才是译文 payload 大于自身严格原槽、必须借用关内文本池的文字。

本文按两层记录：

1. “发生地址变化的 STAGE”列出所有至少一条主指针目标变化的关卡段；
2. “必要重排文字”逐条列出严格原槽超限的 placement，合并共享同一源地址和
   同一输出 payload 的稳定 ID。原槽与 payload 均包含说话人前缀、换行、正文和 NUL。

其余能放回自身原槽、但因全关重新分配而移动的文字不在正文重复抄录；
它们的稳定 ID、原地址、新地址和 payload 大小已经全部保存在上述机器报告的
<code>stages[].allocations[]</code>。

标题映射读取 decoded STAGE 头部的 <code>stg_NNN[a-z].bin</code>；
<code>NNN - 1</code> 是 Stage Name ordinal，同号的 <code>a/b/c</code> 共用标题。
<code>stg_400+</code> 是无 Stage Name 对应项的公共／特殊段，
<code>stg_500.bin</code> 与 <code>stg_501.bin</code> 归为“教学关卡”。

## 快照总览

| 项目 | 当前值 |
| --- | ---: |
| 生产覆盖 STAGE | 170 |
| 可重定位物理记录 | 84,338 |
| 合并后的 placement | 72,310 |
| 至少一条地址变化的 STAGE | 166 |
| 地址变化的物理记录 | 84,093 |
| 地址变化的 placement | 72,106 |
| 严格原槽超限的 STAGE | 130 |
| 严格原槽超限的物理记录 | 555 |
| 严格原槽超限的 placement | 483 |
| 严格原槽超限的唯一日文／中文文本对 | 383 |
| 没有地址变化的 STAGE | 4 |

严格原槽超限幅度分布（按 placement）：

| 超出字节 | placement 数 |
| ---: | ---: |
| +1 | 47 |
| +2 | 269 |
| +3 | 21 |
| +4 | 65 |
| +5 | 16 |
| +6 | 22 |
| +7 | 12 |
| +8 | 10 |
| +9 | 14 |
| +10 | 1 |
| +11 | 3 |
| +12 | 1 |
| +13 | 1 |
| +18 | 1 |

没有地址变化的四段为：<code>STAGE 177</code>（<code>stg_423.bin</code>）、<code>STAGE 178</code>（<code>stg_424.bin</code>）、<code>STAGE 179</code>（<code>stg_425.bin</code>）、<code>STAGE 180</code>（<code>stg_426.bin</code>）。

### 类型化同值地址契约

这些是全关重排时在 parser 主指针之外又命中旧文本地址的 9 个位置。
它们不是文本润色问题；只有明确 owner 的指针可以随 placement 重写，
已证明为非指针的字段必须保持原值。

| STAGE／资源／标题 | 候选位置 → 源文本偏移 | owner | 动作 | 命中文字 |
| --- | --- | --- | --- | --- |
| <code>STAGE 002</code><br><code>stg_002.bin</code><br>[001] 愤怒的眼眸 | <code>0x64F0</code> → <code>0xE9E8</code> | <code>runtime_keyword_pointer</code> | 随唯一 placement 重写 | 军械库一号 |
| <code>STAGE 028</code><br><code>stg_024.bin</code><br>[023] 奔向未知明天 | <code>0xB1EC</code> → <code>0x1B0C8</code> | <code>stage_formation_pointer</code> | 随唯一 placement 重写 | ？？？ |
| <code>STAGE 118</code><br><code>stg_087.bin</code><br>[086] 决别 | <code>0xCD2C</code> → <code>0x19EA8</code> | <code>stage_formation_pointer</code> | 随唯一 placement 重写 | 阿伽玛 |
| <code>STAGE 125</code><br><code>stg_091a.bin</code><br>[090] 绝望之光，希望之灯 | <code>0x403C</code> → <code>0x8360</code> | <code>stage_formation_pointer</code> | 随唯一 placement 重写 | 大天使 |
| <code>STAGE 135</code><br><code>stg_098.bin</code><br>[097] 你与我的身影 | <code>0x11BDC</code> → <code>0x25950</code> | <code>stage_formation_pointer</code> | 随唯一 placement 重写 | 大天使 |
| <code>STAGE 138</code><br><code>stg_100.bin</code><br>[099] 最后之力 | <code>0x13FAC</code> → <code>0x2A6C0</code> | <code>stage_formation_pointer</code> | 随唯一 placement 重写 | 大天使 |
| <code>STAGE 140</code><br><code>stg_102.bin</code><br>[101] 回忆 | <code>0xF720</code> → <code>0x19910</code> | <code>stage_u16_table_nonpointer</code> | 保持原 4 字节不变 | “拜托了，罗杰·谈判专家！” |
| <code>STAGE 145</code><br><code>stg_104c.bin</code><br>[103] 我的未来，大家的未来 | <code>0xFB4C</code> → <code>0x12E60</code> | <code>stage_formation_pointer</code> | 随唯一 placement 重写 | 格罗玛 |
| <code>STAGE 150</code><br><code>stg_106c.bin</code><br>[105] 我的未来，你的未来 | <code>0x104FC</code> → <code>0x14950</code> | <code>stage_formation_pointer</code> | 随唯一 placement 重写 | 格罗玛 |

## 发生地址变化的 STAGE

“移动 placement”先按同一源地址和同一输出 payload 合并；“超槽 placement”
是下面会展开文字的必要扩容项。

| STAGE | 源资源 | Stage Name 标题 | 物理记录 | 移动物理记录 | 移动 placement | 超槽 placement |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 001 | <code>stg_001.bin</code> | [000] 太空先锋 | 317 | 315 | 292 | 3 |
| 002 | <code>stg_002.bin</code> | [001] 愤怒的眼眸 | 549 | 548 | 334 | 4 |
| 003 | <code>stg_003a.bin</code> | [002] 两个世界 | 36 | 33 | 33 | 1 |
| 004 | <code>stg_003b.bin</code> | [002] 两个世界 | 530 | 528 | 488 | 2 |
| 005 | <code>stg_004.bin</code> | [003] 异星人来袭 | 303 | 303 | 289 | 1 |
| 006 | <code>stg_005.bin</code> | [004] 觉醒之日 | 451 | 450 | 428 | 7 |
| 007 | <code>stg_006.bin</code> | [005] 超重神降临 | 639 | 639 | 593 | 5 |
| 008 | <code>stg_007a.bin</code> | [006] 月光，染上怒火 | 188 | 187 | 167 | 2 |
| 009 | <code>stg_007b.bin</code> | [006] 月光，染上怒火 | 365 | 365 | 346 | 5 |
| 010 | <code>stg_008.bin</code> | [007] 世界终结之时 | 639 | 637 | 587 | 12 |
| 011 | <code>stg_009a.bin</code> | [008] 时空破坏 | 45 | 42 | 42 | 0 |
| 012 | <code>stg_009b.bin</code> | [008] 时空破坏 | 228 | 228 | 219 | 2 |
| 013 | <code>stg_010.bin</code> | [009] 流浪的修理工 | 254 | 253 | 243 | 3 |
| 014 | <code>stg_011.bin</code> | [010] 启程之日 | 381 | 380 | 353 | 0 |
| 015 | <code>stg_012.bin</code> | [011] 打破规矩的帮手们 | 487 | 485 | 447 | 4 |
| 016 | <code>stg_013.bin</code> | [012] 各自的旅途，各自的缘由 | 596 | 595 | 560 | 0 |
| 017 | <code>stg_014a.bin</code> | [013] 月之骑手 | 251 | 251 | 244 | 2 |
| 018 | <code>stg_014b.bin</code> | [013] 月之骑手 | 3 | 2 | 2 | 0 |
| 019 | <code>stg_015.bin</code> | [014] 祭典之夜 | 320 | 320 | 307 | 0 |
| 020 | <code>stg_016.bin</code> | [015] 月之女神 | 617 | 616 | 581 | 0 |
| 021 | <code>stg_017.bin</code> | [016] 天翅的记忆 | 508 | 508 | 482 | 2 |
| 022 | <code>stg_018.bin</code> | [017] 世界终结之日 | 379 | 378 | 366 | 4 |
| 023 | <code>stg_019.bin</code> | [018] 世界崩坏 | 226 | 226 | 216 | 4 |
| 024 | <code>stg_020.bin</code> | [019] 范式转移 | 889 | 886 | 623 | 4 |
| 025 | <code>stg_021.bin</code> | [020] 飞鱼 | 985 | 983 | 839 | 5 |
| 026 | <code>stg_022.bin</code> | [021] 站起来吧，宇宙战士！ | 660 | 659 | 599 | 5 |
| 027 | <code>stg_023.bin</code> | [022] 聚集的异乡人 | 702 | 701 | 628 | 4 |
| 028 | <code>stg_024.bin</code> | [023] 奔向未知明天 | 813 | 811 | 763 | 3 |
| 029 | <code>stg_025.bin</code> | [024] 交汇的决意 | 639 | 635 | 551 | 2 |
| 030 | <code>stg_026.bin</code> | [025] 蓝色流浪者 | 654 | 653 | 597 | 4 |
| 031 | <code>stg_027.bin</code> | [026] 染血的眼眸 | 676 | 675 | 616 | 2 |
| 032 | <code>stg_028a.bin</code> | [027] 复苏之翼 | 480 | 480 | 412 | 4 |
| 033 | <code>stg_028b.bin</code> | [027] 复苏之翼 | 143 | 142 | 136 | 0 |
| 034 | <code>stg_029.bin</code> | [028] 特异点 | 537 | 536 | 463 | 1 |
| 035 | <code>stg_030a.bin</code> | [029] 地狱接力赛 | 383 | 382 | 295 | 2 |
| 036 | <code>stg_030b.bin</code> | [029] 地狱接力赛 | 334 | 332 | 319 | 0 |
| 037 | <code>stg_031.bin</code> | [030] 永别了，我的朋友 | 506 | 505 | 476 | 5 |
| 038 | <code>stg_032a.bin</code> | [031] 建国的暴风雪 | 826 | 826 | 684 | 5 |
| 039 | <code>stg_032b.bin</code> | [031] 建国的暴风雪 | 221 | 220 | 207 | 0 |
| 040 | <code>stg_033.bin</code> | [032] 没有谎言的世界 | 756 | 756 | 678 | 1 |
| 041 | <code>stg_034.bin</code> | [033] 被留下的人 | 479 | 478 | 438 | 9 |
| 042 | <code>stg_035.bin</code> | [034] 父亲的回忆 | 436 | 435 | 414 | 2 |
| 043 | <code>stg_036.bin</code> | [035] 只属于自己的大逃亡 | 605 | 603 | 503 | 1 |
| 044 | <code>stg_037a.bin</code> | [036] 百鬼的挑战书 | 65 | 63 | 61 | 0 |
| 045 | <code>stg_037b.bin</code> | [036] 百鬼的挑战书 | 687 | 686 | 640 | 7 |
| 046 | <code>stg_038a.bin</code> | [037] 光子力研究所夺回作战 | 28 | 27 | 27 | 0 |
| 047 | <code>stg_038b.bin</code> | [037] 光子力研究所夺回作战 | 559 | 557 | 447 | 5 |
| 048 | <code>stg_039a.bin</code> | [038] 黑暗居所 | 823 | 822 | 765 | 8 |
| 049 | <code>stg_039b.bin</code> | [038] 黑暗居所 | 81 | 80 | 78 | 0 |
| 050 | <code>stg_040.bin</code> | [039] 香港城 | 736 | 735 | 662 | 4 |
| 051 | <code>stg_041a.bin</code> | [040] 初生的裂痕 | 7 | 6 | 6 | 0 |
| 052 | <code>stg_041b.bin</code> | [040] 初生的裂痕 | 531 | 530 | 502 | 4 |
| 053 | <code>stg_042.bin</code> | [041] 白银之牙 | 611 | 607 | 550 | 11 |
| 054 | <code>stg_043.bin</code> | [042] 灼热海原 | 569 | 567 | 502 | 5 |
| 055 | <code>stg_044.bin</code> | [043] 罪之所在 | 798 | 797 | 707 | 7 |
| 056 | <code>stg_045.bin</code> | [044] 羁绊孕育之物 | 497 | 497 | 472 | 3 |
| 057 | <code>stg_046.bin</code> | [045] 名为悲伤的力量 | 365 | 365 | 343 | 2 |
| 058 | <code>stg_047.bin</code> | [046] Z的脉动 | 519 | 518 | 441 | 7 |
| 059 | <code>stg_048a.bin</code> | [047] 虚假的女王，假面公主 | 119 | 118 | 106 | 1 |
| 060 | <code>stg_048b.bin</code> | [047] 虚假的女王，假面公主 | 673 | 673 | 642 | 4 |
| 061 | <code>stg_049.bin</code> | [048] 战斗神之影 | 561 | 561 | 513 | 3 |
| 062 | <code>stg_050.bin</code> | [049] 星光闪耀时 | 415 | 414 | 393 | 5 |
| 063 | <code>stg_051.bin</code> | [050] 这颗星球属于谁 | 473 | 472 | 445 | 5 |
| 064 | <code>stg_052a.bin</code> | [051] 悲叹的玫瑰念珠 | 335 | 332 | 312 | 3 |
| 065 | <code>stg_052b.bin</code> | [051] 悲叹的玫瑰念珠 | 342 | 342 | 329 | 2 |
| 066 | <code>stg_053.bin</code> | [052] 恸哭的星空 | 809 | 808 | 707 | 3 |
| 067 | <code>stg_054a.bin</code> | [053] 新地球联邦重组 | 98 | 97 | 93 | 1 |
| 068 | <code>stg_054b.bin</code> | [053] 新地球联邦重组 | 368 | 367 | 347 | 0 |
| 069 | <code>stg_055.bin</code> | [054] 舞动噩梦 | 1,097 | 1,096 | 1,051 | 3 |
| 070 | <code>stg_056a.bin</code> | [055] 举起旗帜 | 125 | 124 | 107 | 0 |
| 071 | <code>stg_056b.bin</code> | [055] 举起旗帜 | 220 | 220 | 209 | 2 |
| 072 | <code>stg_057.bin</code> | [056] 冲击再临 | 422 | 420 | 401 | 5 |
| 073 | <code>stg_058a.bin</code> | [057] 投身自然 | 649 | 648 | 539 | 1 |
| 074 | <code>stg_058b.bin</code> | [057] 投身自然 | 95 | 93 | 86 | 2 |
| 075 | <code>stg_059a.bin</code> | [058] 第15年的亡灵 | 489 | 488 | 453 | 3 |
| 076 | <code>stg_059b.bin</code> | [058] 第15年的亡灵 | 496 | 496 | 455 | 1 |
| 077 | <code>stg_060a.bin</code> | [059] 灵魂的Cosplayer | 303 | 303 | 278 | 1 |
| 078 | <code>stg_060b.bin</code> | [059] 灵魂的Cosplayer | 456 | 454 | 406 | 6 |
| 079 | <code>stg_061a.bin</code> | [060] 局外人 | 225 | 224 | 218 | 3 |
| 080 | <code>stg_061b.bin</code> | [060] 局外人 | 491 | 490 | 448 | 3 |
| 081 | <code>stg_062a.bin</code> | [061] Acperience | 70 | 69 | 67 | 2 |
| 082 | <code>stg_062b.bin</code> | [061] Acperience | 446 | 445 | 404 | 4 |
| 083 | <code>stg_063.bin</code> | [062] 被撕裂的过去 | 779 | 777 | 641 | 4 |
| 084 | <code>stg_064.bin</code> | [063] 为了成为我自己 | 643 | 642 | 609 | 6 |
| 085 | <code>stg_065.bin</code> | [064] 孤独逃亡者 | 457 | 456 | 436 | 0 |
| 086 | <code>stg_066a.bin</code> | [065] 奇异接触 | 219 | 218 | 205 | 0 |
| 087 | <code>stg_066b.bin</code> | [065] 奇异接触 | 293 | 293 | 288 | 1 |
| 088 | <code>stg_067a.bin</code> | [066] 牵牛花 | 622 | 621 | 557 | 2 |
| 089 | <code>stg_067b.bin</code> | [066] 牵牛花 | 81 | 80 | 76 | 1 |
| 090 | <code>stg_068.bin</code> | [067] 远方挚友 | 624 | 618 | 546 | 2 |
| 091 | <code>stg_069.bin</code> | [068] 愤怒的铁路王 | 464 | 463 | 442 | 1 |
| 092 | <code>stg_070a.bin</code> | [069] Over Battle | 305 | 304 | 287 | 0 |
| 093 | <code>stg_070b.bin</code> | [069] Over Battle | 125 | 118 | 109 | 0 |
| 094 | <code>stg_070c.bin</code> | [069] Over Battle | 56 | 55 | 53 | 1 |
| 095 | <code>stg_071.bin</code> | [070] 被昭示的明天 | 592 | 592 | 554 | 3 |
| 096 | <code>stg_072a.bin</code> | [071] 肃清风暴 | 82 | 81 | 78 | 1 |
| 097 | <code>stg_072b.bin</code> | [071] 肃清风暴 | 365 | 363 | 336 | 0 |
| 098 | <code>stg_073.bin</code> | [072] 被安排的决战 | 930 | 928 | 908 | 3 |
| 099 | <code>stg_074a.bin</code> | [073] 启动一切 | 345 | 344 | 292 | 2 |
| 100 | <code>stg_074b.bin</code> | [073] 启动一切 | 480 | 479 | 451 | 3 |
| 101 | <code>stg_075.bin</code> | [074] 崩坏序曲 | 636 | 635 | 585 | 9 |
| 102 | <code>stg_076a.bin</code> | [075] 交叉点 | 533 | 531 | 485 | 3 |
| 103 | <code>stg_076b.bin</code> | [075] 交叉点 | 473 | 472 | 438 | 2 |
| 104 | <code>stg_077.bin</code> | [076] 终章开幕 | 928 | 927 | 750 | 8 |
| 105 | <code>stg_078a.bin</code> | [077] 命运与自由 | 439 | 438 | 352 | 1 |
| 106 | <code>stg_078b.bin</code> | [077] 命运与自由 | 359 | 358 | 339 | 2 |
| 107 | <code>stg_079.bin</code> | [078] 降临的太阳 | 1,154 | 1,151 | 883 | 7 |
| 108 | <code>stg_080.bin</code> | [079] 遗产继承者 | 834 | 833 | 751 | 2 |
| 109 | <code>stg_081.bin</code> | [080] 混乱中的正义 | 1,115 | 1,114 | 867 | 10 |
| 110 | <code>stg_082.bin</code> | [081] 倒计时 | 1,091 | 1,091 | 845 | 4 |
| 111 | <code>stg_083.bin</code> | [082] 我们的去向 | 1,134 | 1,131 | 913 | 5 |
| 112 | <code>stg_084.bin</code> | [083] 乐园的放逐者 | 831 | 831 | 729 | 7 |
| 113 | <code>stg_085.bin</code> | [084] 幻想都市 | 811 | 810 | 668 | 2 |
| 114 | <code>stg_086a.bin</code> | [085] 人类之心，天翅之梦 | 49 | 46 | 44 | 0 |
| 115 | <code>stg_086b.bin</code> | [085] 人类之心，天翅之梦 | 107 | 106 | 90 | 0 |
| 116 | <code>stg_086c.bin</code> | [085] 人类之心，天翅之梦 | 242 | 241 | 166 | 1 |
| 117 | <code>stg_086d.bin</code> | [085] 人类之心，天翅之梦 | 843 | 842 | 727 | 9 |
| 118 | <code>stg_087.bin</code> | [086] 决别 | 1,003 | 1,002 | 824 | 6 |
| 119 | <code>stg_088.bin</code> | [087] 黑历史的真相 | 1,118 | 1,117 | 1,012 | 3 |
| 120 | <code>stg_089.bin</code> | [088] 月面决战 | 713 | 712 | 681 | 2 |
| 121 | <code>stg_090a.bin</code> | [089] 背叛的月光 | 11 | 10 | 10 | 0 |
| 122 | <code>stg_090b.bin</code> | [089] 背叛的月光 | 662 | 661 | 555 | 2 |
| 123 | <code>stg_090c.bin</code> | [089] 背叛的月光 | 12 | 9 | 9 | 0 |
| 124 | <code>stg_090d.bin</code> | [089] 背叛的月光 | 8 | 6 | 6 | 0 |
| 125 | <code>stg_091a.bin</code> | [090] 绝望之光，希望之灯 | 300 | 298 | 263 | 1 |
| 126 | <code>stg_091b.bin</code> | [090] 绝望之光，希望之灯 | 554 | 553 | 462 | 3 |
| 127 | <code>stg_092.bin</code> | [091] 我是D.O.M.E.…… | 1,287 | 1,285 | 1,173 | 4 |
| 128 | <code>stg_093.bin</code> | [092] 绯红路 | 936 | 935 | 831 | 10 |
| 129 | <code>stg_094a.bin</code> | [093] Gain Over | 317 | 316 | 232 | 1 |
| 130 | <code>stg_094b.bin</code> | [093] Gain Over | 635 | 633 | 552 | 4 |
| 131 | <code>stg_095.bin</code> | [094] 扭曲的裁决 | 1,118 | 1,117 | 946 | 2 |
| 132 | <code>stg_096.bin</code> | [095] 灵魂凯歌 | 670 | 670 | 571 | 5 |
| 133 | <code>stg_097a.bin</code> | [096] 永远闪耀吧，我们的星球 | 359 | 358 | 341 | 3 |
| 134 | <code>stg_097b.bin</code> | [096] 永远闪耀吧，我们的星球 | 108 | 107 | 105 | 2 |
| 135 | <code>stg_098.bin</code> | [097] 你与我的身影 | 1,259 | 1,258 | 1,066 | 6 |
| 136 | <code>stg_099a.bin</code> | [098] 终末之光 | 825 | 823 | 708 | 3 |
| 137 | <code>stg_099b.bin</code> | [098] 终末之光 | 160 | 159 | 156 | 1 |
| 138 | <code>stg_100.bin</code> | [099] 最后之力 | 1,386 | 1,385 | 1,237 | 10 |
| 139 | <code>stg_101.bin</code> | [100] 向星辰许愿 | 1,117 | 1,117 | 1,015 | 4 |
| 140 | <code>stg_102.bin</code> | [101] 回忆 | 1,133 | 1,133 | 804 | 2 |
| 141 | <code>stg_103a.bin</code> | [102] 黑色世界 | 330 | 328 | 310 | 1 |
| 142 | <code>stg_103b.bin</code> | [102] 黑色世界 | 778 | 778 | 598 | 3 |
| 143 | <code>stg_104a.bin</code> | [103] 我的未来，大家的未来 | 1,507 | 1,506 | 1,282 | 10 |
| 144 | <code>stg_104b.bin</code> | [103] 我的未来，大家的未来 | 888 | 886 | 850 | 7 |
| 145 | <code>stg_104c.bin</code> | [103] 我的未来，大家的未来 | 1,465 | 1,464 | 513 | 4 |
| 146 | <code>stg_105a.bin</code> | [104] 被涂抹的明天 | 330 | 328 | 310 | 1 |
| 147 | <code>stg_105b.bin</code> | [104] 被涂抹的明天 | 795 | 795 | 606 | 5 |
| 148 | <code>stg_106a.bin</code> | [105] 我的未来，你的未来 | 1,620 | 1,619 | 1,357 | 5 |
| 149 | <code>stg_106b.bin</code> | [105] 我的未来，你的未来 | 1,682 | 1,679 | 943 | 9 |
| 150 | <code>stg_106c.bin</code> | [105] 我的未来，你的未来 | 1,530 | 1,529 | 538 | 7 |
| 151 | <code>stg_107a.bin</code> | [106] 迈向无尽战争之环 | 303 | 302 | 288 | 1 |
| 152 | <code>stg_107b.bin</code> | [106] 迈向无尽战争之环 | 57 | 56 | 48 | 0 |
| 153 | <code>stg_107c.bin</code> | [106] 迈向无尽战争之环 | 29 | 28 | 28 | 1 |
| 154 | <code>stg_400.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 293 | 289 | 265 | 1 |
| 155 | <code>stg_401.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 27 | 23 | 21 | 0 |
| 156 | <code>stg_402.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 27 | 23 | 21 | 0 |
| 157 | <code>stg_403.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 47 | 44 | 42 | 0 |
| 160 | <code>stg_406.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 121 | 117 | 105 | 2 |
| 163 | <code>stg_409.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 39 | 35 | 33 | 0 |
| 164 | <code>stg_410.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 39 | 35 | 33 | 0 |
| 169 | <code>stg_415.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 36 | 32 | 30 | 0 |
| 170 | <code>stg_416.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 36 | 32 | 30 | 0 |
| 175 | <code>stg_421.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 36 | 32 | 30 | 0 |
| 176 | <code>stg_422.bin</code> | 非章节公共／特殊段（无 Stage Name 标题） | 36 | 32 | 30 | 0 |
| 185 | <code>stg_500.bin</code> | [117] 教学关卡 | 413 | 413 | 322 | 2 |
| 186 | <code>stg_501.bin</code> | [117] 教学关卡 | 437 | 437 | 342 | 0 |

## 必要重排文字

下表只收录 payload 大于严格原槽的 placement。“原 → 新”是 decoded STAGE 内偏移，
不是 ISO LBA；多个稳定 ID 共用同一 placement 时合并显示，但物理记录数仍单列。

### STAGE 001 · <code>stg_001.bin</code> · [000] 太空先锋

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/001/dialogue/02.01/0060</code> | 对白 | 【$n】「あ、あの…ジェリド中尉…」 | 【$n】“那、那个……捷利特中尉……” | 32 → 34 | +2 | <code>0x9360</code> → <code>0x8B40</code> |
| <code>story/001/dialogue/02.01/0113</code> | 对白 | 【$n】「…地球連邦は異星からの侵略者、<br>　ベガ星連合軍と戦い…」 | 【$n】“……地球联邦正在与来自异星的侵略者，<br>　贝加星联合军交战……” | 64 → 67 | +3 | <code>0xA110</code> → <code>0x9620</code> |
| <code>story/001/dialogue/02.01/0135</code> | 对白 | 【$n】「…はい…」 | 【$n】“……是……” | 16 → 18 | +2 | <code>0xA810</code> → <code>0x9BA0</code> |

### STAGE 002 · <code>stg_002.bin</code> · [001] 愤怒的眼眸

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/002/dialogue/01.05/0000</code> | 对白 | 【ザフト兵】「何が起きている！？」 | 【ZAFT士兵】“发生什么事了！？” | 32 → 34 | +2 | <code>0xBBA0</code> → <code>0xBB00</code> |
| <code>story/002/dialogue/01.34/0000</code> | 对白 | 【$n】「やった…！　後は脱出を…」 | 【$n】“成功了……！接下来只要撤离……” | 32 → 38 | +6 | <code>0xD730</code> → <code>0xD0B0</code> |
| <code>story/002/dialogue/02.01/0075</code> | 对白 | 【ステラ】「手…放して…胸…」 | 【史黛拉】“手……放开……胸口……” | 32 → 34 | +2 | <code>0x11BB0</code> → <code>0x10C90</code> |
| <code>story/002/dialogue/02.01/0078</code> | 对白 | 【シン】「何だったんだ、あの子…」 | 【真】“那女孩……到底怎么回事……” | 32 → 34 | +2 | <code>0x11C00</code> → <code>0x10CF0</code> |

### STAGE 003 · <code>stg_003a.bin</code> · [002] 两个世界

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/003/dialogue/01.01/0001</code> | 对白 | 【ザフト兵】「だ、駄目です、隊長！<br>　これ以上はもちません…！」 | 【ZAFT士兵】“不、不行了，队长！<br>　再这样下去我们撑不住了……！” | 64 → 67 | +3 | <code>0x1440</code> → <code>0x1440</code> |

### STAGE 004 · <code>stg_003b.bin</code> · [002] 两个世界

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/004/dialogue/01.01/0010</code> | 对白 | 【イアン】「噂では常に情緒不安定で、<br>　餌で釣るしかなかったと…」 | 【伊安】“据说上次战争中的那些人总是情绪不稳，<br>　只能拿诱饵哄着……” | 64 → 67 | +3 | <code>0x9BF0</code> → <code>0x9C60</code> |
| <code>story/004/dialogue/01.08/0002</code> | 对白 | 【アウル】「くっ…命令なら従うよ」 | 【奥尔】“唔……既然是命令，我照办” | 32 → 34 | +2 | <code>0xAC30</code> → <code>0xA8F0</code> |

### STAGE 005 · <code>stg_004.bin</code> · [003] 异星人来袭

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/005/dialogue/01.05/0016</code> | 对白 | 【$n】「では…？」 | 【$n】“那么……？” | 16 → 18 | +2 | <code>0x6680</code> → <code>0x6440</code> |

### STAGE 006 · <code>stg_005.bin</code> · [004] 觉醒之日

7 个超槽 placement，7 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/006/dialogue/01.08/0002</code> | 对白 | 【勝平】「ちょ！　冗談でしょ！」 | 【胜平】“等等！你不是在开玩笑吧！” | 32 → 34 | +2 | <code>0x7F80</code> → <code>0x7EC0</code> |
| <code>story/006/dialogue/01.18/0005</code> | 对白 | 【勝平】「香月…」 | 【胜平】“香月……” | 16 → 18 | +2 | <code>0x8BA0</code> → <code>0x88D0</code> |
| <code>story/006/dialogue/01.20/0001</code> | 对白 | 【ミチ】「勝平…」 | 【美知】“胜平……” | 16 → 18 | +2 | <code>0x8D10</code> → <code>0x8A00</code> |
| <code>story/006/dialogue/01.25/0004</code> | 对白 | 【$n】「え…！？」 | 【$n】“诶……！？” | 16 → 18 | +2 | <code>0x9660</code> → <code>0x9190</code> |
| <code>story/006/dialogue/02.01/0009</code> | 对白 | 【梅江】「おお、怖い怖い…」 | 【梅江】“哎呀，好可怕，好可怕……” | 32 → 34 | +2 | <code>0xA5C0</code> → <code>0x9E10</code> |
| <code>story/006/dialogue/02.01/0103</code> | 对白 | 【トビー】「ちっ…次の取調べかよ」 | 【托比】“啧……又要接受审讯了吗。” | 32 → 34 | +2 | <code>0xBFD0</code> → <code>0xB2D0</code> |
| <code>story/006/dialogue/02.03/0016</code> | 对白 | 【$n】「でも、自分達の機体なら！」 | 【$n】“可是，如果是我们自己的机体！” | 32 → 36 | +4 | <code>0xD660</code> → <code>0xC550</code> |

### STAGE 007 · <code>stg_006.bin</code> · [005] 超重神降临

5 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/007/dialogue/01.22/0005</code> | 对白 | 【ミヅキ】「５機目があるなんて、<br>　今まで全然…」 | 【媚月】“竟然还有第五台机体，<br>　我之前完全不知道……” | 48 → 53 | +5 | <code>0xBC10</code> → <code>0xB4B0</code> |
| <code>story/007/dialogue/02.01/0097</code> | 对白 | 【一太郎】「え…」 | 【一太郎】“诶……” | 16 → 18 | +2 | <code>0xED60</code> → <code>0xDA20</code> |
| <code>story/007/dialogue/02.01/0195</code> | 对白 | 【琉菜】「でも、ちょっと頭悪そ…」 | 【琉菜】“不过，脑子好像不太好……” | 32 → 34 | +2 | <code>0x105F0</code> → <code>0xED50</code> |
| <code>story/007/dialogue/02.01/0217</code> | 对白 | 【斗牙】「でも、肌は僕より硬そう」 | 【斗牙】“不过你的皮肉好像比我的硬。” | 32 → 36 | +4 | <code>0x10980</code> → <code>0xF000</code> |
| <code>story/007/dialogue/02.01/0227</code> | 对白 | 【斗牙】「え…？」 | 【斗牙】“诶……？” | 16 → 18 | +2 | <code>0x10B00</code> → <code>0xF170</code> |

### STAGE 008 · <code>stg_007a.bin</code> · [006] 月光，染上怒火

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/008/dialogue/02.01/0073</code> | 对白 | 【琉菜】「え…？」 | 【琉菜】“咦……？” | 16 → 18 | +2 | <code>0x38E0</code> → <code>0x3440</code> |
| <code>story/008/dialogue/02.01/0153</code> | 对白 | 【？？？】「あ…」 | 【？？？】“啊……” | 16 → 18 | +2 | <code>0x4AB0</code> → <code>0x4180</code> |

### STAGE 009 · <code>stg_007b.bin</code> · [006] 月光，染上怒火

5 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/009/dialogue/01.01/0000</code> | 对白 | 【香月】「このロボット…勝平の乗っている奴か！」 | 【香月】“这台机器人……<br>　难道是胜平驾驶的那台吗！？” | 48 → 53 | +5 | <code>0x7790</code> → <code>0x77F0</code> |
| <code>story/009/dialogue/01.22/0001</code> | 对白 | 【恵子】「そ、それが…私達にも…」 | 【惠子】“这、这个……我们也不知道……” | 32 → 38 | +6 | <code>0x8EF0</code> → <code>0x89F0</code> |
| <code>story/009/dialogue/01.23/0014</code> | 对白 | 【勝平】「でも、イチ兄ちゃん…！<br>　あいつ、これまでの奴とは…」 | 【胜平】“可是，一太郎哥哥……！<br>　那家伙和之前的那些不是一回事……” | 64 → 67 | +3 | <code>0x9210</code> → <code>0x8C60</code> |
| <code>story/009/dialogue/02.03/0023</code> | 对白 | 【勝平】「くそ…」 | 【胜平】“可恶……” | 16 → 18 | +2 | <code>0xCA10</code> → <code>0xB910</code> |
| <code>story/009/dialogue/02.03/0039</code> | 对白 | 【源五郎】「それでは嫌か、勝平？」 | 【源五郎】“光有爸爸理解你，还不够吗，胜平？” | 32 → 44 | +12 | <code>0xCE00</code> → <code>0xBC40</code> |

### STAGE 010 · <code>stg_008.bin</code> · [007] 世界终结之时

12 个超槽 placement，12 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/010/dialogue/01.03/0003</code> | 对白 | 【デュランダル】「…前大戦の傷跡は未だ癒えんか…」 | 【迪兰达尔】“……上次大战留下的伤痕，<br>　至今仍未愈合吗……” | 48 → 59 | +11 | <code>0xBBF0</code> → <code>0xBBE0</code> |
| <code>story/010/dialogue/01.09/0005</code> | 对白 | 【ブライト】「面倒な時に面倒な連中が！」 | 【布莱德】“偏偏在这种麻烦的时候，<br>　又来了一群麻烦的家伙！” | 48 → 59 | +11 | <code>0xD2B0</code> → <code>0xCE20</code> |
| <code>story/010/dialogue/01.12/0001</code> | 对白 | 【クワトロ】「戦力差に加えて、<br>　無秩序な異星人までいるのだ。<br>　苦戦は必然か…！」 | 【克瓦特罗】“不仅战力相差悬殊，还有毫无秩序的异星人。<br>　陷入苦战也是必然吗……！” | 80 → 81 | +1 | <code>0xDB80</code> → <code>0xD560</code> |
| <code>story/010/dialogue/01.14/0000</code> | 对白 | 【タリア】「連合の艦ではない！？」 | 【塔丽亚】“不是地球联合的战舰！？” | 32 → 34 | +2 | <code>0xDCE0</code> → <code>0xD690</code> |
| <code>story/010/dialogue/01.23/0009</code> | 对白 | 【サトー】「ここで無残に散った命の嘆き、忘れ…<br>　撃った者らと、なぜ偽りの世界で笑うか！？<br>　貴様らは！」 | 【佐藤】“这里惨死的生命在哀号，你们忘了吗……！<br>　为什么还要和开枪杀人的家伙，<br>　在虚假的世界里欢笑！？你们这些家伙！” | 112 → 118 | +6 | <code>0xF250</code> → <code>0xE790</code> |
| <code>story/010/dialogue/01.26/0002</code> | 对白 | 【デュランダル】「万事休すか…」 | 【迪兰达尔】“难道一切都完了吗……” | 32 → 34 | +2 | <code>0xF6C0</code> → <code>0xEB30</code> |
| <code>story/010/dialogue/02.01/0045</code> | 对白 | 【カミーユ】「陸地に落ちれば、粉塵による様々な障害…<br>　海に落ちれば、周辺への津波等…」 | 【卡缪】“如果落在陆地上，<br>　会因尘埃造成各种障碍……如果落入海中，<br>　则会在周边引发海啸等灾害……” | 96 → 98 | +2 | <code>0x11900</code> → <code>0x106A0</code> |
| <code>story/010/dialogue/02.01/0118</code> | 对白 | 【カガリ】「…！」 | 【卡嘉莉】“……！” | 16 → 18 | +2 | <code>0x12E10</code> → <code>0x117C0</code> |
| <code>story/010/dialogue/02.01/0141</code> | 对白 | 【シン】「何…？」 | 【真】“什么……？” | 16 → 18 | +2 | <code>0x132F0</code> → <code>0x11BF0</code> |
| <code>story/010/dialogue/02.01/0155</code> | 对白 | 【カガリ】「え…」 | 【卡嘉莉】“什么……” | 16 → 20 | +4 | <code>0x136C0</code> → <code>0x11F00</code> |
| <code>story/010/dialogue/02.01/0158</code> | 对白 | 【カガリ】「あ…」 | 【卡嘉莉】“啊……” | 16 → 18 | +2 | <code>0x13740</code> → <code>0x11F70</code> |
| <code>story/010/dialogue/02.02/0014</code> | 对白 | 【アレックス】「きっと自分の気持ちで一杯で…」 | 【亚历克斯】“他一定已经完全被自己的情绪淹没了……” | 48 → 50 | +2 | <code>0x14480</code> → <code>0x12A80</code> |

### STAGE 012 · <code>stg_009b.bin</code> · [008] 时空破坏

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/012/dialogue/02.01/0016</code> | 对白 | 【$n】「でも…！」 | 【$n】“但是……！” | 16 → 18 | +2 | <code>0x6B10</code> → <code>0x6470</code> |
| <code>story/012/dialogue/02.01/0023</code> | 对白 | 【$n】「…はい…」 | 【$n】“……是……” | 16 → 18 | +2 | <code>0x6C70</code> → <code>0x65B0</code> |

### STAGE 013 · <code>stg_010.bin</code> · [009] 流浪的修理工

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/013/dialogue/01.08/0000</code> | 对白 | 【ゲラバ】「な、何が修理屋だ…。<br>　お前は壊し屋…ザ・クラッシャーだ…！」 | 【格拉巴】“什、什么修理店……<br>　你明明是THE CRUSHER……<br>　THE CRUSHER……！” | 80 → 98 | +18 | <code>0x5450</code> → <code>0x5170</code> |
| <code>story/013/dialogue/02.01/0093</code> | 对白 | 【ガロード】「オッサン…何者だ？」 | 【卡洛德】“大叔……你到底是什么人？” | 32 → 36 | +4 | <code>0x7F50</code> → <code>0x7440</code> |
| <code>story/013/dialogue/02.02/0042</code> | 对白 | 【$n】「そうか…」 | 【$n】“这样啊……” | 16 → 18 | +2 | <code>0x8C40</code> → <code>0x7E40</code> |

### STAGE 015 · <code>stg_012.bin</code> · [011] 打破规矩的帮手们

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/015/dialogue/01.37/0001</code> | 对白 | 【$n】「その先を言ってみやがれ！<br>　大解体じゃすまさねえぞ！」 | 【$n】“你敢把后面的话说出来试试！<br>　我可不会只是大解体就完事的！” | 64 → 65 | +1 | <code>0xBC90</code> → <code>0xB0E0</code> |
| <code>story/015/dialogue/02.01/0004</code> | 对白 | 【サラ】「…でも、驚いたわよ」 | 【莎拉】“……不过，我真是吃了一惊。” | 32 → 36 | +4 | <code>0xC5A0</code> → <code>0xB810</code> |
| <code>story/015/dialogue/02.02/0023</code> | 对白 | 【$n】「フ…俺達流の挨拶だ」 | 【$n】“呼……这是我们之间的打招呼方式。” | 32 → 40 | +8 | <code>0xDBF0</code> → <code>0xC980</code> |
| <code>story/015/dialogue/02.02/0098</code> | 对白 | 【チル】「えへへ…『様』なんてつけられたら、<br>　照れちゃうよ」 | 【琪露】“诶嘿嘿……被加上‘大人’两个字，<br>　还真有点不好意思呢。” | 64 → 65 | +1 | <code>0xEE20</code> → <code>0xD7C0</code> |

### STAGE 017 · <code>stg_014a.bin</code> · [013] 月之骑手

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/017/dialogue/01.10/0011</code> | 对白 | 【ホランド】「…タルホ…ここの位置、つかめたか？」 | 【霍兰德】“……塔尔荷……这里的位置，能掌握了吗？” | 48 → 50 | +2 | <code>0x6030</code> → <code>0x5C80</code> |
| <code>story/017/dialogue/01.12/0004</code> | 对白 | 【ゲイン】「結局、こうなるか…！」 | 【该隐】“结果还是变成这样吗……！” | 32 → 34 | +2 | <code>0x6550</code> → <code>0x60C0</code> |

### STAGE 021 · <code>stg_017.bin</code> · [016] 天翅的记忆

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/021/dialogue/01.03/0000</code> | 对白 | 【エルチ】「な、何…この音…！？」 | 【艾露琪】“这、这是什么声音……！？” | 32 → 36 | +4 | <code>0x9F50</code> → <code>0x9D80</code> |
| <code>story/021/dialogue/01.25/0002</code> | 对白 | 【シルヴィア】「嘘…なんであいつがアクエリオンの<br>　名前を…！？」 | 【西尔维娅】“骗人……为什么那家伙会知道<br>　亚库艾里翁的名字……！？” | 64 → 67 | +3 | <code>0xB390</code> → <code>0xADF0</code> |

### STAGE 022 · <code>stg_018.bin</code> · [017] 世界终结之日

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/022/dialogue/01.19/0007</code> | 对白 | 【シリウス】「…自分の殻を破れぬ者…それは…」 | 【西利乌斯】“……无法打破自身外壳的人……那是……” | 48 → 50 | +2 | <code>0x97A0</code> → <code>0x9440</code> |
| <code>story/022/dialogue/01.28/0005</code> | 对白 | 【アポロ】「この声…頭翅か！？」 | 【阿波罗】“这个声音……是头翅吗！？” | 32 → 36 | +4 | <code>0xA210</code> → <code>0x9CB0</code> |
| <code>story/022/dialogue/01.30/0005</code> | 对白 | 【アポロ】「あ…ああ…あああ！<br>　あああーっ！　あああああーっ！」 | 【阿波罗】“啊……啊啊……啊啊啊！<br>　啊啊啊——！啊啊啊啊啊——！” | 64 → 65 | +1 | <code>0xA320</code> → <code>0x9DD0</code> |
| <code>story/022/dialogue/01.31/0001</code> | 对白 | 【アポロ】「光…」 | 【阿波罗】“光……” | 16 → 18 | +2 | <code>0xA390</code> → <code>0x9E50</code> |

### STAGE 023 · <code>stg_019.bin</code> · [018] 世界崩坏

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/023/dialogue/01.06/0002</code> | 对白 | 【チラム兵】「特異点反応は、あの機体からか…」 | 【奇拉姆士兵】“特异点反应是从那台机体发出的吗……” | 48 → 50 | +2 | <code>0x5280</code> → <code>0x5040</code> |
| <code>story/023/dialogue/01.08/0007</code> | 对白 | 【桂】「…やだね」 | 【桂】“……不要。” | 16 → 18 | +2 | <code>0x59C0</code> → <code>0x5600</code> |
| <code>story/023/dialogue/01.09/0000</code> | 对白 | 【チラム兵】「何だと、貴様！？」 | 【奇拉姆士兵】“你说什么，你这家伙！？” | 32 → 38 | +6 | <code>0x59D0</code> → <code>0x5620</code> |
| <code>story/023/dialogue/02.02/0041</code> | 对白 | 【桂】「多元世界…それが今の地球の姿…」 | 【桂】“多元世界……这就是现在地球的样子……” | 40 → 44 | +4 | <code>0x7D30</code> → <code>0x70B0</code> |

### STAGE 024 · <code>stg_020.bin</code> · [019] 范式转移

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/024/dialogue/01.21/0006</code> | 对白 | 【$n】「でも…！」 | 【$n】“但是……！” | 16 → 18 | +2 | <code>0xD560</code> → <code>0xD1C0</code> |
| <code>story/024/dialogue/02.01/0023</code> | 对白 | 【$n】「私は$F…」 | 【$n】“我是$F……” | 16 → 18 | +2 | <code>0xFF90</code> → <code>0xF320</code> |
| <code>story/024/dialogue/02.01/0049</code> | 对白 | 【$n】「その４０年前の何かとは？」 | 【$n】“那40年前的某件事是什么？” | 32 → 34 | +2 | <code>0x10530</code> → <code>0xF7A0</code> |
| <code>story/024/dialogue/02.02/0017</code> | 对白 | 【$n】「え…！？」 | 【$n】“诶……！？” | 16 → 18 | +2 | <code>0x11C00</code> → <code>0x10950</code> |

### STAGE 025 · <code>stg_021.bin</code> · [020] 飞鱼

5 个超槽 placement，6 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/025/dialogue/01.11/0001</code> | 对白 | 【ホランド】「お前…修理屋のザ・ヒートか！」 | 【霍兰德】“你……就是那个修理工THE HEAT！” | 48 → 50 | +2 | <code>0xFE90</code> → <code>0xFB50</code> |
| <code>story/025/dialogue/01.24/0004</code> | 对白 | 【カミーユ】「嫌な気配はあいつからか…！」 | 【卡缪】“那股讨厌的气息是从那<br>　家伙身上来的吗……！” | 48 → 53 | +5 | <code>0x11B10</code> → <code>0x11160</code> |
| <code>story/025/dialogue/02.01/0106</code> | 对白 | 【$n】「何の音？」 | 【$n】“什么声音？” | 16 → 18 | +2 | <code>0x15E70</code> → <code>0x149D0</code> |
| <code>story/025/dialogue/02.01/0118</code> | 对白 | 【$n】「詳しいのね、レントン君」 | 【$n】“你知道得很清楚嘛，兰顿君。” | 32 → 34 | +2 | <code>0x161F0</code> → <code>0x14C50</code> |
| <code>story/025/dialogue/02.01/0144</code><br><code>story/025/dialogue/02.01/0285</code> | 对白 | 【アクセル】「だがな…現実を見ろ」 | 【阿克塞尔】“但是……你得看清现实。” | 32 → 36 | +4 | <code>0x16880</code> → <code>0x15140</code> |

### STAGE 026 · <code>stg_022.bin</code> · [021] 站起来吧，宇宙战士！

5 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/026/dialogue/01.30/0005</code> | 对白 | 【恵子】「勝平…」 | 【惠子】“胜平……” | 16 → 18 | +2 | <code>0xD980</code> → <code>0xD040</code> |
| <code>story/026/dialogue/02.01/0078</code> | 对白 | 【闘志也】「前の世界で俺達と一緒に戦った仲間だ」 | 【斗志也】“是以前的世界里和我们一起战斗过的同伴。” | 48 → 50 | +2 | <code>0xFCE0</code> → <code>0xEAA0</code> |
| <code>story/026/dialogue/02.01/0104</code> | 对白 | 【$n】「では、相克界を突破して地球へ…！？」 | 【$n】“这么说，你是突破相克界<br>　来到地球的……！？” | 48 → 51 | +3 | <code>0x10420</code> → <code>0xF030</code> |
| <code>story/026/dialogue/02.01/0178</code> | 对白 | 【$n】「…マジ？」 | 【$n】“……真的？” | 16 → 18 | +2 | <code>0x11600</code> → <code>0xFE10</code> |
| <code>story/026/dialogue/02.01/0236</code> | 对白 | 【キラケン】「ワシは吉良謙作、通称キラケン。<br>　イオの時からの闘志也のダチじゃ」 | 【吉良谦】“我是吉良谦作，大家都叫我吉良谦。<br>　从木卫一时期起，我就是斗志也的朋友。” | 80 → 83 | +3 | <code>0x12380</code> → <code>0x108E0</code> |

### STAGE 027 · <code>stg_023.bin</code> · [022] 聚集的异乡人

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/027/dialogue/02.01/0163</code> | 对白 | 【$n】「$Fだ。<br>　ザ・ヒートと呼んでくれ」 | 【$n】“我是$F。<br>　叫我‘THE HEAT’就行。” | 48 → 49 | +1 | <code>0x13460</code> → <code>0x11600</code> |
| <code>story/027/dialogue/02.01/0204</code> | 对白 | 【エニル】「よくわからない説明ね」 | 【艾妮尔】“这解释真让人摸不着头脑。” | 32 → 36 | +4 | <code>0x13CA0</code> → <code>0x11C90</code> |
| <code>story/027/dialogue/02.02/0009</code> | 对白 | 【フィル】「では、攻撃の命令を？」 | 【菲尔】“那么，要下达攻击命令吗？” | 32 → 34 | +2 | <code>0x14090</code> → <code>0x11F90</code> |
| <code>story/027/dialogue/02.02/0072</code> | 对白 | 【サラ】「え…？」 | 【莎拉】“诶……？” | 16 → 18 | +2 | <code>0x15180</code> → <code>0x12C10</code> |

### STAGE 028 · <code>stg_024.bin</code> · [023] 奔向未知明天

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/028/dialogue/01.44/0008</code> | 对白 | 【アサキム】「ザ・ヒートだろう？<br>　メールから何度も聞いている。<br>　熱い男…だとな」 | 【阿萨基姆】“是‘THE HEAT’吧？从梅尔那里<br>　听过很多次了。说是……热血的男人。” | 80 → 87 | +7 | <code>0x14260</code> → <code>0x131C0</code> |
| <code>story/028/dialogue/02.01/0007</code> | 对白 | 【桂】「詳しいんだな、ミムジィ」 | 【桂】“你知道得真详细啊，蜜姆晶。” | 32 → 34 | +2 | <code>0x171F0</code> → <code>0x15620</code> |
| <code>story/028/dialogue/02.01/0102</code> | 对白 | 【桂】「何って…人助けだけど…」 | 【桂】“干什么……就是帮人而已……” | 32 → 34 | +2 | <code>0x18C40</code> → <code>0x16A80</code> |

### STAGE 029 · <code>stg_025.bin</code> · [024] 交汇的决意

2 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/029/dialogue/01.03/0000</code> | 对白 | 【ホランド】「あの艦、ザフトか！」 | 【霍兰德】“那艘舰，是ZAFT吗！” | 32 → 34 | +2 | <code>0xAED0</code> → <code>0xAE30</code> |
| <code>story/029/dialogue/02.01/0109</code><br><code>story/029/dialogue/02.02/0141</code> | 对白 | 【　】　　　〜月光号　購買『ボン・マルシェ』〜 | 【　】——月光号小卖部‘Bon <br>　Marché’—— | 48 → 51 | +3 | <code>0xFF20</code> → <code>0xEAD0</code> |

### STAGE 030 · <code>stg_026.bin</code> · [025] 蓝色流浪者

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/030/dialogue/01.04/0003</code> | 对白 | 【キラケン】「何じゃい！<br>　出迎えに差があるぞ！」 | 【吉良谦】“搞什么啊！这迎接的待遇差别也太大了吧！” | 48 → 50 | +2 | <code>0xC310</code> → <code>0xC260</code> |
| <code>story/030/dialogue/02.01/0124</code> | 对白 | 【大介】「それで…彼は今、何を？」 | 【大介】“那么……他现在在做什么？” | 32 → 34 | +2 | <code>0x11FB0</code> → <code>0x10B80</code> |
| <code>story/030/dialogue/02.02/0013</code> | 对白 | 【マリン】「何…」 | 【马林】“什么……” | 16 → 18 | +2 | <code>0x13A20</code> → <code>0x12080</code> |
| <code>story/030/dialogue/02.03/0098</code> | 对白 | 【ハップ】「…その…何と言うか…」 | 【哈普】“……那个……怎么说呢……” | 32 → 34 | +2 | <code>0x15940</code> → <code>0x13880</code> |

### STAGE 031 · <code>stg_027.bin</code> · [026] 染血的眼眸

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/031/dialogue/01.08/0008</code> | 对白 | 【ババ】「それでは議会の決定に…」 | 【马场】“那样的话就违背了议会的决定……” | 32 → 40 | +8 | <code>0xD340</code> → <code>0xD0E0</code> |
| <code>story/031/dialogue/02.01/0037</code> | 对白 | 【カガリ】「あ…」 | 【卡嘉莉】“啊……” | 16 → 18 | +2 | <code>0x10860</code> → <code>0xFA20</code> |

### STAGE 032 · <code>stg_028a.bin</code> · [027] 复苏之翼

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/032/dialogue/01.04/0002</code> | 对白 | 【キラ】「僕は…守ってみせる…！」 | 【基拉】“我……一定会保护给你们看……！” | 32 → 40 | +8 | <code>0x8980</code> → <code>0x89C0</code> |
| <code>story/032/dialogue/01.17/0019</code> | 对白 | 【$n】「む…カチンと来る言い方…」 | 【$n】“唔……这说法真让人火大……” | 32 → 34 | +2 | <code>0x9F90</code> → <code>0x9B10</code> |
| <code>story/032/dialogue/02.01/0066</code> | 对白 | 【カガリ】「…！」 | 【卡嘉莉】“……！” | 16 → 18 | +2 | <code>0xBFC0</code> → <code>0xB500</code> |
| <code>story/032/dialogue/02.01/0069</code> | 对白 | 【ユウナ】「カガリ・ユラ・アスハ…<br>　オーブ連合首長国代表首長たる<br>　今の君の立場の側にはね」 | 【尤纳】“卡嘉莉·尤拉·阿斯哈……<br>　作为奥布联合首长国代表首长的你<br>　现在的立场，不能有他们在身边。” | 96 → 100 | +4 | <code>0xC090</code> → <code>0xB5B0</code> |

### STAGE 034 · <code>stg_029.bin</code> · [028] 特异点

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/034/dialogue/01.13/0003</code> | 对白 | 【ＤＣ兵】「は、放せ！　こいつ！」 | 【DC士兵】“放、放开我！你这家伙！” | 32 → 36 | +4 | <code>0xAB60</code> → <code>0xA6B0</code> |

### STAGE 035 · <code>stg_030a.bin</code> · [029] 地狱接力赛

2 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/035/dialogue/02.01/0069</code><br><code>story/035/dialogue/02.01/0085</code> | 对白 | 【ガウリ】「ここでも…とは？」 | 【高富利】“这里也……是什么意思？” | 32 → 34 | +2 | <code>0x69C0</code> → <code>0x62D0</code> |
| <code>story/035/dialogue/02.02/0228</code> | 对白 | 【ガウリ】「全く説得力がない…！」 | 【高富利】“一点说服力都没有……！” | 32 → 34 | +2 | <code>0x9CE0</code> → <code>0x89F0</code> |

### STAGE 037 · <code>stg_031.bin</code> · [030] 永别了，我的朋友

5 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/037/dialogue/01.09/0003</code> | 对白 | 【勝平】「…俺が…俺達が負けたら<br>　アキやミチや香月が…」 | 【胜平】“……如果我……如果我们输了，<br>　亚纪、美知和香月他们就会……” | 64 → 69 | +5 | <code>0xB240</code> → <code>0xB050</code> |
| <code>story/037/dialogue/01.09/0004</code> | 对白 | 【恵子】「勝平…」 | 【惠子】“胜平……” | 16 → 18 | +2 | <code>0xB280</code> → <code>0xB0A0</code> |
| <code>story/037/dialogue/02.01/0127</code> | 对白 | 【勝平】「香月…」 | 【胜平】“香月……” | 16 → 18 | +2 | <code>0xF780</code> → <code>0xE550</code> |
| <code>story/037/dialogue/02.01/0155</code> | 对白 | 【ミチ】「勝平…」 | 【美知】“胜平……” | 16 → 18 | +2 | <code>0x100A0</code> → <code>0xEC30</code> |
| <code>story/037/dialogue/02.02/0027</code> | 对白 | 【アキ】「勝平…」 | 【亚纪】“胜平……” | 16 → 18 | +2 | <code>0x10F90</code> → <code>0xF780</code> |

### STAGE 038 · <code>stg_032a.bin</code> · [031] 建国的暴风雪

5 个超槽 placement，7 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/038/dialogue/01.12/0023</code> | 对白 | 【ディアナ】「同じ人類だからです」 | 【迪安娜】“因为我们是同样的人类。” | 32 → 34 | +2 | <code>0xF230</code> → <code>0xEA40</code> |
| <code>story/038/dialogue/01.19/0000</code> | 对白 | 【エルチ】「何、あの金ピカ！？」 | 【艾露琪】“那金光闪闪的是什么！？” | 32 → 34 | +2 | <code>0xFE80</code> → <code>0xF3A0</code> |
| <code>story/038/dialogue/01.48/0000</code> | 对白 | 【ゲラバ】「行くぜ、ザ・クラッシャー！」 | 【格拉巴】“上吧，THE CRUSHER！” | 40 → 42 | +2 | <code>0x121D0</code> → <code>0x10EC0</code> |
| <code>story/038/dialogue/02.01/0180</code><br><code>story/038/dialogue/02.01/0287</code> | 对白 | 【？？？】「え…」 | 【？？？】“呃……” | 16 → 18 | +2 | <code>0x158C0</code> → <code>0x138C0</code> |
| <code>story/038/dialogue/02.01/0257</code><br><code>story/038/dialogue/02.01/0363</code> | 对白 | 【ソシエ】「無事よね、お姉様！？」 | 【苏茜亚】“你没事吧，姐姐大人！？” | 32 → 34 | +2 | <code>0x16B70</code> → <code>0x14820</code> |

### STAGE 040 · <code>stg_033.bin</code> · [032] 没有谎言的世界

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/040/dialogue/01.21/0002</code> | 对白 | 【エウレカ】「何、これ…？<br>　凄い力を感じる…！」 | 【优莱卡】“这是什么……？<br>　感觉到一股强大的力量……！” | 48 → 55 | +7 | <code>0x103D0</code> → <code>0xF850</code> |

### STAGE 041 · <code>stg_034.bin</code> · [033] 被留下的人

9 个超槽 placement，11 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/041/dialogue/01.02/0003</code> | 对白 | 【トビー】「奴ら…やる気か…！」 | 【托比】“他们……是认真的吗……！” | 32 → 34 | +2 | <code>0x9340</code> → <code>0x93A0</code> |
| <code>story/041/dialogue/01.09/0002</code> | 对白 | 【アサキム】「全ては太極への道…」 | 【阿萨基姆】“一切都是通往太极之路……” | 32 → 38 | +6 | <code>0x9C90</code> → <code>0x9B50</code> |
| <code>story/041/dialogue/01.19/0000</code> | 对白 | 【トビー】「す…まねえ…チーフ…$n…」 | 【托比】“对……对不起……<br>　队长……$n……” | 40 → 43 | +3 | <code>0xA2D0</code> → <code>0xA0A0</code> |
| <code>story/041/dialogue/01.22/0000</code> | 对白 | 【アサキム】「…邪魔が入ったか」 | 【阿萨基姆】“……有碍事的家伙来了。” | 32 → 36 | +4 | <code>0xA410</code> → <code>0xA1D0</code> |
| <code>story/041/dialogue/02.02/0012</code> | 对白 | 【アサキム】「これで残るは君一人だね、<br>　$F…」 | 【阿萨基姆】“这样剩下的就只有你一个人了，<br>　$F……” | 48 → 51 | +3 | <code>0xD7B0</code> → <code>0xC9C0</code> |
| <code>story/041/dialogue/02.03/0011</code> | 对白 | 【$n】「…はい…」 | 【$n】“……是……” | 16 → 18 | +2 | <code>0xDCB0</code> → <code>0xCDF0</code> |
| <code>story/041/dialogue/02.03/0015</code> | 对白 | 【$n】「…うう…う…。<br>　なぜ、私が…うう…」 | 【$n】“……呜呜……呜……<br>　为什么是我……呜呜……” | 48 → 51 | +3 | <code>0xDD70</code> → <code>0xCEA0</code> |
| <code>story/041/dialogue/02.03/0090</code><br><code>story/041/dialogue/02.03/0091</code><br><code>story/041/dialogue/02.03/0092</code> | 对白 | 戦場跡 | 战场遗迹 | 8 → 9 | +1 | <code>0xF488</code> → <code>0xE060</code> |
| <code>story/041/dialogue/02.03/0095</code> | 对白 | 【アムロ】「$n…」 | 【阿姆罗】“$n……” | 16 → 18 | +2 | <code>0xF4B0</code> → <code>0xE090</code> |

### STAGE 042 · <code>stg_035.bin</code> · [034] 父亲的回忆

2 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/042/dialogue/01.13/0007</code> | 对白 | 【アサキム】（仲間…か。甘美な響きだね。<br>　昔の事を思い出すよ） | 【阿萨基姆】（伙伴……吗。真是甜美的字眼。<br>　让我想起了过去的事。） | 64 → 65 | +1 | <code>0x8A80</code> → <code>0x8770</code> |
| <code>story/042/dialogue/02.02/0069</code><br><code>story/042/dialogue/02.02/0070</code><br><code>story/042/dialogue/02.02/0071</code> | 对白 | 戦場跡 | 战场遗迹 | 8 → 9 | +1 | <code>0xD978</code> → <code>0xC440</code> |

### STAGE 043 · <code>stg_036.bin</code> · [035] 只属于自己的大逃亡

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/043/dialogue/01.06/0012</code> | 对白 | 【サラ】「嘘…！　嘘でしょ…！？」 | 【莎拉】“骗人……！骗人的吧……！？” | 32 → 36 | +4 | <code>0xD570</code> → <code>0xD2E0</code> |

### STAGE 045 · <code>stg_037b.bin</code> · [036] 百鬼的挑战书

7 个超槽 placement，9 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/045/dialogue/01.03/0013</code> | 对白 | 【不動】「甘い！」 | 【不动】“太天真了！” | 16 → 20 | +4 | <code>0xDA50</code> → <code>0xD990</code> |
| <code>story/045/dialogue/01.06/0008</code> | 对白 | 【シリウス】「やめろ、アポロ…！」 | 【西利乌斯】“别说了，阿波罗……！” | 32 → 34 | +2 | <code>0xE310</code> → <code>0xE0B0</code> |
| <code>story/045/dialogue/01.09/0004</code><br><code>story/045/dialogue/01.13/0011</code> | 对白 | 【麗花】「でも…」 | 【丽花】“但是……” | 16 → 18 | +2 | <code>0xE6E0</code> → <code>0xE3D0</code> |
| <code>story/045/dialogue/01.17/0001</code><br><code>story/045/dialogue/01.18/0001</code> | 对白 | 【竜馬】「無事か、ミチルさん！<br>　アポロ達も！」 | 【龙马】“美智留小姐，你没事吧！<br>　阿波罗，你们也没事吧！” | 48 → 57 | +9 | <code>0xF590</code> → <code>0xEFE0</code> |
| <code>story/045/dialogue/02.01/0062</code> | 对白 | 【源五郎】「噂？」 | 【源五郎】“传闻？” | 16 → 18 | +2 | <code>0x12630</code> → <code>0x115E0</code> |
| <code>story/045/dialogue/02.01/0074</code> | 对白 | 【源五郎】「百鬼…不吉な名前だ」 | 【源五郎】“百鬼……不吉利的名字。” | 32 → 34 | +2 | <code>0x12990</code> → <code>0x118A0</code> |
| <code>story/045/dialogue/02.03/0150</code> | 对白 | 【竜馬】「あの人は不動ＧＥＮ。<br>　予想通り、ディーバの司令官だ」 | 【龙马】“那个人是不动GEN。<br>　正如所料，是DEAVA的司令官。” | 64 → 65 | +1 | <code>0x170A0</code> → <code>0x14FC0</code> |

### STAGE 047 · <code>stg_038b.bin</code> · [037] 光子力研究所夺回作战

5 个超槽 placement，6 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/047/dialogue/01.01/0000</code> | 对白 | 【ヒドラー】「来たか、$cめ！<br>　懲りない奴らよ！」 | 【希德拉】“终于来了啊，$c！<br>　真是一群不知悔改的家伙！” | 48 → 55 | +7 | <code>0xB210</code> → <code>0xB2A0</code> |
| <code>story/047/dialogue/01.11/0002</code><br><code>story/047/dialogue/01.12/0003</code> | 对白 | 【マリア】「まだなの、甲児…！？」 | 【玛丽亚】“还没好吗，甲儿……！？” | 32 → 34 | +2 | <code>0xBEC0</code> → <code>0xBCD0</code> |
| <code>story/047/dialogue/01.33/0000</code> | 对白 | 【鉄甲鬼】「この女…弓の娘か！」 | 【铁甲鬼】“这女人……是弓的女儿吗！” | 32 → 36 | +4 | <code>0xE040</code> → <code>0xD6D0</code> |
| <code>story/047/dialogue/02.01/0163</code> | 对白 | 【鉄甲鬼】「フン…ありがとう…か」 | 【铁甲鬼】“哼……是在说‘谢谢’吗……” | 32 → 38 | +6 | <code>0x102D0</code> → <code>0xF0F0</code> |
| <code>story/047/dialogue/02.01/0165</code> | 对白 | 【さやか】「え…」 | 【沙也加】“诶……” | 16 → 18 | +2 | <code>0x10350</code> → <code>0xF160</code> |

### STAGE 048 · <code>stg_039a.bin</code> · [038] 黑暗居所

8 个超槽 placement，8 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/048/dialogue/01.01/0000</code> | 对白 | 【独眼鬼】「正面から来たか、$c。<br>　愚鈍な奴らよ」 | 【独眼鬼】“从正面来了吗，$c。<br>　一群愚钝的家伙。” | 48 → 49 | +1 | <code>0xD890</code> → <code>0xD960</code> |
| <code>story/048/dialogue/01.10/0001</code> | 对白 | 【シリウス】「そんな…この私が…」 | 【西利乌斯】“怎么会……我居然……” | 32 → 34 | +2 | <code>0xEC40</code> → <code>0xE960</code> |
| <code>story/048/dialogue/01.34/0003</code> | 对白 | 【隼人】「早乙女博士が生涯を懸けた<br>　ゲッター線研究の結晶だ！」 | 【隼人】“它是早乙女博士倾注毕生心血，<br>　研究盖塔射线所得的结晶！” | 64 → 65 | +1 | <code>0x110D0</code> → <code>0x10790</code> |
| <code>story/048/dialogue/01.38/0003</code> | 对白 | 【アムロ】「何…」 | 【阿姆罗】“什么……” | 16 → 20 | +4 | <code>0x118F0</code> → <code>0x10E60</code> |
| <code>story/048/dialogue/01.38/0005</code> | 对白 | 【源五郎】「日本の独立も<br>　百鬼帝国の仕業と考えれば、<br>　元に戻るだけですしね」 | 【源五郎】“况且，如果日本独立也是百鬼帝国一手策划，<br>　那么现在不过是恢复原状而已。” | 80 → 83 | +3 | <code>0x11950</code> → <code>0x10EC0</code> |
| <code>story/048/dialogue/01.44/0000</code> | 对白 | 【鉄甲鬼】「ゲッターロボ！<br>　宣言通り、ここで決着をつける！」 | 【铁甲鬼】“盖塔机器人！正如我所宣告的，<br>　今天就在这里做个了断！” | 64 → 65 | +1 | <code>0x12100</code> → <code>0x11520</code> |
| <code>story/048/dialogue/02.01/0020</code> | 对白 | 【頭翅】「御意…」 | 【头翅】“遵命……” | 16 → 18 | +2 | <code>0x13670</code> → <code>0x12510</code> |
| <code>story/048/dialogue/02.01/0212</code> | 对白 | 【シリウス】「ああ…アリシア王家の力を<br>　鬼共と野良犬に見せてやろう」 | 【西利乌斯】“啊……就让那些恶鬼和野狗见识一下，<br>　阿莉西亚王家的力量吧。” | 72 → 73 | +1 | <code>0x16760</code> → <code>0x14C30</code> |

### STAGE 050 · <code>stg_040.bin</code> · [039] 香港城

4 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/050/dialogue/02.01/0061</code><br><code>story/050/dialogue/02.01/0085</code> | 对白 | 【アムロ】「え…」 | 【阿姆罗】“呃……” | 16 → 18 | +2 | <code>0x101D0</code> → <code>0xF220</code> |
| <code>story/050/dialogue/02.02/0011</code> | 对白 | 【エィナ】「斗牙様…エイジ様…」 | 【爱娜】“斗牙大人……英司大人……” | 32 → 34 | +2 | <code>0x144A0</code> → <code>0x12580</code> |
| <code>story/050/dialogue/02.02/0016</code> | 对白 | 【斗牙】「え…？」 | 【斗牙】“诶……？” | 16 → 18 | +2 | <code>0x145A0</code> → <code>0x12680</code> |
| <code>story/050/dialogue/02.02/0138</code> | 对白 | 【タリア】「…では開封します…」 | 【塔丽亚】“……那么，我开封了……” | 32 → 34 | +2 | <code>0x16140</code> → <code>0x13C50</code> |

### STAGE 052 · <code>stg_041b.bin</code> · [040] 初生的裂痕

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/052/dialogue/01.07/0000</code> | 对白 | 【鉄也】「あれが例の砲台か…！」 | 【铁也】“那就是传说中的炮台吗……！” | 32 → 36 | +4 | <code>0xBA60</code> → <code>0xB780</code> |
| <code>story/052/dialogue/02.01/0046</code> | 对白 | 【アムロ】「何がだ、ソシエ？」 | 【阿姆罗】“什么不可思议，苏茜亚？” | 32 → 34 | +2 | <code>0xEBE0</code> → <code>0xDF10</code> |
| <code>story/052/dialogue/02.01/0142</code> | 对白 | 【源五郎】「世界も最後には女性の下へ還る。<br>　戦いではなく、豊かな実りを求めてな」 | 【源五郎】“世界最终也会回到女性的怀抱。<br>　不是为了战斗，而是为了追求丰饶的果实。” | 80 → 81 | +1 | <code>0x10340</code> → <code>0xF1E0</code> |
| <code>story/052/dialogue/02.02/0065</code> | 对白 | 【ロラン】「この命に代えましても」 | 【罗兰】“即使豁出性命也在所不惜。” | 32 → 34 | +2 | <code>0x117E0</code> → <code>0x10290</code> |

### STAGE 053 · <code>stg_042.bin</code> · [041] 白银之牙

11 个超槽 placement，13 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/053/dialogue/01.01/0002</code> | 对白 | 【ジュリィ】「捜したぜ、家出少年」 | 【杰利】“找到你了，离家出走的少年。” | 32 → 36 | +4 | <code>0xBCE0</code> → <code>0xBDC0</code> |
| <code>story/053/dialogue/01.05/0011</code><br><code>story/053/dialogue/01.06/0011</code> | 对白 | 【アスラン】「これでも俺は君を買っている。<br>　…それに俺も未熟だ」 | 【阿斯兰】“即便如此，我还是看好你的。……<br>　而且，我也还不成熟。” | 64 → 65 | +1 | <code>0xC9F0</code> → <code>0xC810</code> |
| <code>story/053/dialogue/01.07/0003</code> | 对白 | 【琉菜】「斗牙…」 | 【琉菜】“斗牙……” | 16 → 18 | +2 | <code>0xCD30</code> → <code>0xCAC0</code> |
| <code>story/053/dialogue/01.24/0002</code> | 对白 | 【斗牙】「奴が敵戦力の中核か！」 | 【斗牙】“那家伙是敌方战力的核心吗！” | 32 → 36 | +4 | <code>0xEBA0</code> → <code>0xE300</code> |
| <code>story/053/dialogue/01.30/0004</code> | 对白 | 【琉菜】「え…？」 | 【琉菜】“诶……？” | 16 → 18 | +2 | <code>0xF4C0</code> → <code>0xEA20</code> |
| <code>story/053/dialogue/01.36/0002</code><br><code>story/053/dialogue/01.37/0002</code> | 对白 | 【兵左衛門】「ガイゾックめ…。<br>　人間を集めて、何をする気だ…？」 | 【兵左卫门】“盖佐克那混蛋……抓走这么多人，<br>　究竟想干什么……？” | 64 → 65 | +1 | <code>0xFE60</code> → <code>0xF200</code> |
| <code>story/053/dialogue/02.01/0127</code> | 对白 | 【闘志也】「$n…」 | 【斗志也】“$n……” | 16 → 18 | +2 | <code>0x12360</code> → <code>0x10F50</code> |
| <code>story/053/dialogue/02.02/0032</code> | 对白 | 【テラル】「…！」 | 【迪拉尔】“……！” | 16 → 18 | +2 | <code>0x13100</code> → <code>0x11A00</code> |
| <code>story/053/dialogue/02.02/0048</code> | 对白 | 【テラル】（それは私の心が…女なるゆえか…） | 【迪拉尔】（那是因为我的心中……<br>　仍留着女人的一面吗……） | 48 → 57 | +9 | <code>0x134F0</code> → <code>0x11D20</code> |
| <code>story/053/dialogue/02.02/0054</code> | 对白 | 【テラル】（身体はテラル…心は私。<br>　リラの意識、記憶、性格は全て…<br>　テラルの身体と共にある…） | 【迪拉尔】（身体是迪拉尔……心是我。<br>　莉拉的意识、记忆、性格全都……<br>　存在于迪拉尔的身体之中……） | 96 → 98 | +2 | <code>0x136A0</code> → <code>0x11EB0</code> |
| <code>story/053/dialogue/02.02/0063</code> | 对白 | 【バレター】「さあ入れ、お前ら！」 | 【巴雷塔】“快进去，你们这些家伙！” | 32 → 34 | +2 | <code>0x138B0</code> → <code>0x120A0</code> |

### STAGE 054 · <code>stg_043.bin</code> · [042] 灼热海原

5 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/054/dialogue/01.02/0003</code> | 对白 | 【斗牙】「でも…」 | 【斗牙】“但是……” | 16 → 18 | +2 | <code>0xEB20</code> → <code>0xEAC0</code> |
| <code>story/054/dialogue/01.10/0001</code> | 对白 | 【キラ】「カガリ…もう駄目だ…」 | 【基拉】“卡嘉莉……已经不行了……” | 32 → 34 | +2 | <code>0xFE00</code> → <code>0xF9B0</code> |
| <code>story/054/dialogue/01.10/0002</code> | 对白 | 【カガリ】「え…」 | 【卡嘉莉】“诶……” | 16 → 18 | +2 | <code>0xFE20</code> → <code>0xF9E0</code> |
| <code>story/054/dialogue/01.52/0000</code> | 对白 | 【闘志也】「残るはあっちの女だ！」 | 【斗志也】“剩下的就是那个女人了！” | 32 → 34 | +2 | <code>0x11950</code> → <code>0x10FC0</code> |
| <code>story/054/dialogue/02.01/0056</code> | 对白 | 【ネオ】「では…」 | 【尼奥】“那么……” | 16 → 18 | +2 | <code>0x145B0</code> → <code>0x132A0</code> |

### STAGE 055 · <code>stg_044.bin</code> · [043] 罪之所在

7 个超槽 placement，11 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/055/dialogue/01.20/0002</code><br><code>story/055/dialogue/01.47/0002</code> | 对白 | 【ババ】「く…！」 | 【马场】“唔……！” | 16 → 18 | +2 | <code>0x10F60</code> → <code>0x107C0</code> |
| <code>story/055/dialogue/01.20/0006</code><br><code>story/055/dialogue/01.47/0006</code><br><code>story/055/dialogue/02.01/0125</code> | 对白 | 【カガリ】「…！」 | 【卡嘉莉】“……！” | 16 → 18 | +2 | <code>0x11050</code> → <code>0x108B0</code> |
| <code>story/055/dialogue/01.23/0007</code> | 对白 | 【キラ】「なら、僕は…君を討つ！」 | 【基拉】“那么，我……就要讨伐你！” | 32 → 34 | +2 | <code>0x11660</code> → <code>0x10E00</code> |
| <code>story/055/dialogue/01.50/0007</code> | 对白 | 【キラ】「なら、僕は…君を討つ！」 | 【基拉】“那么，我……就要打倒你！” | 32 → 34 | +2 | <code>0x11660</code> → <code>0x11DA0</code> |
| <code>story/055/dialogue/01.25/0003</code><br><code>story/055/dialogue/01.52/0003</code> | 对白 | 【鉄也】「何なんだ、あいつは…！」 | 【铁也】“那家伙到底是什么人……！” | 32 → 34 | +2 | <code>0x11760</code> → <code>0x10EE0</code> |
| <code>story/055/dialogue/01.74/0000</code> | 对白 | 【クワトロ】「中途半端な戦い方は<br>　自分の腕への自信からか…！」 | 【克瓦特罗】“这种半吊子的战斗方式，<br>　是因为对自己的技术有自信吗……！” | 64 → 71 | +7 | <code>0x13490</code> → <code>0x12820</code> |
| <code>story/055/dialogue/01.81/0001</code> | 对白 | 【$n】「…上手く言えないけど…<br>　私の戦い方に…似ている…？」 | 【$n】“……说不太清楚……但……<br>　和我的战斗方式……有点像……？” | 64 → 65 | +1 | <code>0x13BF0</code> → <code>0x12DF0</code> |

### STAGE 056 · <code>stg_045.bin</code> · [044] 羁绊孕育之物

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/056/dialogue/01.14/0000</code> | 对白 | 【$n】「まさか、アサキムは…<br>　そのためにチーフとトビーを…」 | 【$n】“难道说，阿萨基姆他……<br>　就是为了这个才杀了队长和托比……” | 64 → 65 | +1 | <code>0x9690</code> → <code>0x9490</code> |
| <code>story/056/dialogue/02.01/0006</code> | 对白 | 【ステラ】「ネオ…ネオ、どこ…？<br>　怖い…ステラ…怖い…」 | 【史黛拉】“尼奥……尼奥，在哪里……？<br>　好可怕……史黛拉……好可怕……” | 64 → 71 | +7 | <code>0xB340</code> → <code>0xAB50</code> |
| <code>story/056/dialogue/02.01/0008</code> | 对白 | 【ステラ】「…いや…いやぁ…！」 | 【史黛拉】“……不要……不要啊……！” | 32 → 36 | +4 | <code>0xB3C0</code> → <code>0xABD0</code> |

### STAGE 057 · <code>stg_046.bin</code> · [045] 名为悲伤的力量

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/057/dialogue/01.11/0000</code> | 对白 | 【$n】「ああ…！」 | 【$n】“啊啊……！” | 16 → 18 | +2 | <code>0x87F0</code> → <code>0x86F0</code> |
| <code>story/057/dialogue/01.16/0000</code> | 对白 | 【$n】「トビー…何を…！？」 | 【$n】“托比……你在做什么……！？” | 32 → 34 | +2 | <code>0x8B20</code> → <code>0x8960</code> |

### STAGE 058 · <code>stg_047.bin</code> · [046] Z的脉动

7 个超槽 placement，7 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/058/dialogue/01.20/0007</code> | 对白 | 【アムロ】「嫌な気を感じる…。<br>　何かが来るぞ…」 | 【阿姆罗】“我感觉到一股不好的气息……<br>　有什么要来了……” | 48 → 57 | +9 | <code>0xB580</code> → <code>0xB0A0</code> |
| <code>story/058/dialogue/01.29/0002</code> | 对白 | 【アムロ】「あの男…何者なんだ？」 | 【阿姆罗】“那个男人……到底是什么人？” | 32 → 38 | +6 | <code>0xBEC0</code> → <code>0xB840</code> |
| <code>story/058/dialogue/01.39/0001</code> | 对白 | 【レコア】「え…」 | 【蕾柯亚】“诶……” | 16 → 18 | +2 | <code>0xC330</code> → <code>0xBC00</code> |
| <code>story/058/dialogue/02.01/0069</code> | 对白 | 【クワトロ】「パプテマス・シロッコ…。<br>　噂の木星帰りの男か…」 | 【克瓦特罗】“帕普提马斯·西罗克……<br>　传闻中那个从木星回来的男人吗……” | 64 → 71 | +7 | <code>0xE4F0</code> → <code>0xD5E0</code> |
| <code>story/058/dialogue/02.02/0020</code> | 对白 | 【ルナマリア】「カミーユの幼馴染かぁ。<br>　昔の話が楽しめそうだね」 | 【露娜玛丽亚】“卡缪的青梅竹马啊。<br>　看来能听到不少过去的故事了。” | 64 → 65 | +1 | <code>0xED10</code> → <code>0xDC70</code> |
| <code>story/058/dialogue/02.02/0030</code> | 对白 | 【レコア】「必要とされる命…ね…」 | 【蕾柯亚】“被需要的生命……吗……” | 32 → 34 | +2 | <code>0xEF90</code> → <code>0xDEA0</code> |
| <code>story/058/dialogue/02.02/0034</code> | 对白 | 【レコア】「あの…クワトロ大尉…」 | 【蕾柯亚】“那个……克瓦特罗上尉……” | 32 → 36 | +4 | <code>0xF060</code> → <code>0xDF60</code> |

### STAGE 059 · <code>stg_048a.bin</code> · [047] 虚假的女王，假面公主

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/059/dialogue/01.01/0029</code> | 对白 | 【ジャミトフ】「口を慎め、エーデル・ベルナル…！」 | 【加米托夫】“注意你的言辞，艾岱尔·贝尔纳尔……！” | 48 → 50 | +2 | <code>0x2AA0</code> → <code>0x2770</code> |

### STAGE 060 · <code>stg_048b.bin</code> · [047] 虚假的女王，假面公主

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/060/dialogue/01.18/0002</code> | 对白 | 【ソシエ】「え…」 | 【苏茜亚】“诶……” | 16 → 18 | +2 | <code>0xD150</code> → <code>0xCC90</code> |
| <code>story/060/dialogue/02.02/0041</code> | 对白 | 【テテス】「あ…」 | 【特泰丝】“啊……” | 16 → 18 | +2 | <code>0x13450</code> → <code>0x117B0</code> |
| <code>story/060/dialogue/02.02/0051</code> | 对白 | 【サラ】「…サラ・ザビアロフ…」 | 【莎拉】“……莎拉·扎比亚罗夫……” | 32 → 34 | +2 | <code>0x13670</code> → <code>0x11980</code> |
| <code>story/060/dialogue/02.04/0070</code> | 对白 | 【シン】「…何だよ、あの態度…！」 | 【真】“……搞什么啊，那副态度……！” | 32 → 36 | +4 | <code>0x153A0</code> → <code>0x130E0</code> |

### STAGE 061 · <code>stg_049.bin</code> · [048] 战斗神之影

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/061/dialogue/01.15/0000</code> | 对白 | 【ロラン】「そんな…ディアナ様…」 | 【罗兰】“怎么会……迪安娜大人……” | 32 → 34 | +2 | <code>0xAA20</code> → <code>0xA6B0</code> |
| <code>story/061/dialogue/01.27/0000</code> | 对白 | 【カツ】「サラ…」 | 【卡兹】“莎拉……” | 16 → 18 | +2 | <code>0xBA30</code> → <code>0xB370</code> |
| <code>story/061/dialogue/02.02/0018</code> | 对白 | 【キラ】「でも…」 | 【基拉】“但是……” | 16 → 18 | +2 | <code>0x10BA0</code> → <code>0xF300</code> |

### STAGE 062 · <code>stg_050.bin</code> · [049] 星光闪耀时

5 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/062/dialogue/01.14/0006</code> | 对白 | 【浜本】「勝平…」 | 【滨本】“胜平……” | 16 → 18 | +2 | <code>0x87D0</code> → <code>0x8410</code> |
| <code>story/062/dialogue/01.18/0000</code> | 对白 | 【浜本】「あ…！」 | 【滨本】“啊……！” | 16 → 18 | +2 | <code>0x8E30</code> → <code>0x8950</code> |
| <code>story/062/dialogue/02.02/0031</code> | 对白 | 【勝平】「浜本…」 | 【胜平】“滨本……” | 16 → 18 | +2 | <code>0xCF70</code> → <code>0xBD10</code> |
| <code>story/062/dialogue/02.02/0037</code> | 对白 | 【斗牙】「…僕達は…無力だ…」 | 【斗牙】“……我们……无能为力……” | 32 → 34 | +2 | <code>0xD0B0</code> → <code>0xBE50</code> |
| <code>story/062/dialogue/02.02/0055</code> | 对白 | 【市民】「…でもね…お母さんはずっと一緒よ…。<br>　だから…何も怖くない…からね…」 | 【市民】“……但是啊……妈妈会一直陪着你……<br>　所以……什么都不用怕……知道吗……” | 80 → 81 | +1 | <code>0xD400</code> → <code>0xC150</code> |

### STAGE 063 · <code>stg_051.bin</code> · [050] 这颗星球属于谁

5 个超槽 placement，7 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/063/dialogue/01.19/0000</code> | 对白 | 【闘志也】「あの戦艦、テラルか！」 | 【斗志也】“那艘战舰……是迪拉尔的！” | 32 → 36 | +4 | <code>0x9D10</code> → <code>0x9790</code> |
| <code>story/063/dialogue/01.20/0000</code> | 对白 | 【闘志也】「テラル、貴様ーっ！」 | 【斗志也】“迪拉尔，你这家伙——！” | 32 → 34 | +2 | <code>0x9E00</code> → <code>0x9880</code> |
| <code>story/063/dialogue/02.01/0015</code> | 对白 | 【大介】「え…？」 | 【大介】“呃……？” | 16 → 18 | +2 | <code>0xBA30</code> → <code>0xAE30</code> |
| <code>story/063/dialogue/02.01/0126</code> | 对白 | 【理恵】「博士…」 | 【理惠】“博士……” | 16 → 18 | +2 | <code>0xD780</code> → <code>0xC5A0</code> |
| <code>story/063/dialogue/02.02/0104</code><br><code>story/063/dialogue/02.02/0105</code><br><code>story/063/dialogue/02.02/0106</code> | 对白 | 風見博士　私室 | 风见博士私人房间 | 16 → 17 | +1 | <code>0xF640</code> → <code>0xDE30</code> |

### STAGE 064 · <code>stg_052a.bin</code> · [051] 悲叹的玫瑰念珠

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/064/dialogue/01.01/0002</code> | 对白 | 【$n】「まさか、時空転移…！？」 | 【$n】“难道说，是时空转移……！？” | 32 → 34 | +2 | <code>0x5170</code> → <code>0x5170</code> |
| <code>story/064/dialogue/01.03/0004</code> | 对白 | 【甲児】「罪…？」 | 【甲儿】“罪孽……？” | 16 → 20 | +4 | <code>0x5530</code> → <code>0x5490</code> |
| <code>story/064/dialogue/02.02/0136</code> | 对白 | 【一太郎】「え…」 | 【一太郎】“诶……” | 16 → 18 | +2 | <code>0xA5A0</code> → <code>0x93C0</code> |

### STAGE 065 · <code>stg_052b.bin</code> · [051] 悲叹的玫瑰念珠

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/065/dialogue/01.20/0002</code> | 对白 | 【斗牙】「ない」 | 【斗牙】“不认识。” | 16 → 18 | +2 | <code>0xA260</code> → <code>0x9A60</code> |
| <code>story/065/dialogue/02.01/0040</code> | 对白 | 【$n】「勝平君…」 | 【$n】“胜平君……” | 16 → 18 | +2 | <code>0xB4E0</code> → <code>0xA7D0</code> |

### STAGE 066 · <code>stg_053.bin</code> · [052] 恸哭的星空

3 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/066/dialogue/01.05/0006</code> | 对白 | 【レイ】「敵の中枢…<br>　つまり、あの黒いマシンか」 | 【雷】“敌人的中枢……<br>　也就是说，那台黑色机器吗。” | 48 → 51 | +3 | <code>0x10090</code> → <code>0xFFD0</code> |
| <code>story/066/dialogue/01.35/0000</code><br><code>story/066/dialogue/01.46/0000</code> | 对白 | 【ステラ】「あ…」 | 【史黛拉】“啊……” | 16 → 18 | +2 | <code>0x128F0</code> → <code>0x12020</code> |
| <code>story/066/dialogue/01.75/0000</code> | 对白 | 【マリン】「連邦軍もザフトも自分達以外の人間は<br>　地球人も異星人も容赦無しだ！」 | 【马林】“联邦军也好ZAFT也好，除了自己以外的<br>　人，不管是地球人还是外星人都毫不留情！” | 80 → 89 | +9 | <code>0x14070</code> → <code>0x132D0</code> |

### STAGE 067 · <code>stg_054a.bin</code> · [053] 新地球联邦重组

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/067/dialogue/01.06/0002</code> | 对白 | 【アテナ】「え…」 | 【雅典娜】“诶……” | 16 → 18 | +2 | <code>0x2AF0</code> → <code>0x2960</code> |

### STAGE 069 · <code>stg_055.bin</code> · [054] 舞动噩梦

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/069/dialogue/01.15/0000</code> | 对白 | 【カガリ】「う、嘘だろ…キラ…」 | 【卡嘉莉】“骗、骗人的吧……基拉……” | 32 → 36 | +4 | <code>0x16C50</code> → <code>0x19820</code> |
| <code>story/069/dialogue/01.54/0000</code> | 对白 | 【闘志也】「相手はゲッターロボか…！<br>　分離合体の隙はやらねえ！」 | 【斗志也】“对手是盖塔机器人吗……！<br>　不会给你们分离合体的机会！” | 64 → 65 | +1 | <code>0x1A7B0</code> → <code>0x1DD20</code> |
| <code>story/069/dialogue/01.84/0002</code> | 对白 | 【琉菜】「斗牙…」 | 【琉菜】“斗牙……” | 16 → 18 | +2 | <code>0x1D010</code> → <code>0x1FBC0</code> |

### STAGE 071 · <code>stg_056b.bin</code> · [055] 举起旗帜

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/071/dialogue/02.01/0032</code> | 对白 | 【甲児】「だから、俺に振るなよ！」 | 【甲儿】“所以说，别把问题抛给我啊！” | 32 → 36 | +4 | <code>0x9BF0</code> → <code>0x9290</code> |
| <code>story/071/dialogue/02.01/0070</code> | 对白 | 【？？？】「…救世の戦士…太極への旅人…法の守護騎士…<br>　因果律の番人…呪われし放浪者…。<br>　何でも構いませんが…」 | 【？？？】“……救世的战士……太极的旅人……<br>　法则的守护骑士……因果律的看守……<br>　被诅咒的流浪者……叫什么都可以……” | 112 → 118 | +6 | <code>0xA570</code> → <code>0x99E0</code> |

### STAGE 072 · <code>stg_057.bin</code> · [056] 冲击再临

5 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/072/dialogue/01.19/0012</code> | 对白 | 【黒のカリスマ】「黒のカリスマ…」 | 【黑之卡里斯马】“黑之卡里斯马……” | 32 → 34 | +2 | <code>0xCBA0</code> → <code>0xC310</code> |
| <code>story/072/dialogue/02.01/0009</code> | 对白 | 【カガリ】「え…」 | 【卡嘉莉】“呃……” | 16 → 18 | +2 | <code>0xDCF0</code> → <code>0xD050</code> |
| <code>story/072/dialogue/02.01/0068</code> | 对白 | 【ネオ】（ムウ・ラ・フラガ…か…） | 【尼奥】（穆·拉·弗拉加……吗……） | 32 → 34 | +2 | <code>0xEA80</code> → <code>0xDB50</code> |
| <code>story/072/dialogue/02.01/0083</code> | 对白 | 【総裁】「何…？」 | 【总裁】“什么……？” | 16 → 20 | +4 | <code>0xED80</code> → <code>0xDDE0</code> |
| <code>story/072/dialogue/02.01/0167</code> | 对白 | 【一太郎】「新連邦…時空制御装置…実験…。<br>　２日後…１８：００…Ｘ１３Ｙ２４…<br>　危険…危険…危険…」 | 【一太郎】“新联邦……时空控制装置……实验……<br>　两天后……18:00……X13Y24……<br>　危险……危险……危险……” | 112 → 116 | +4 | <code>0x10460</code> → <code>0xEF30</code> |

### STAGE 073 · <code>stg_058a.bin</code> · [057] 投身自然

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/073/dialogue/02.02/0129</code> | 对白 | 【アネモネ】「もうおりますぅ！」 | 【阿尼莫奈】“人家已经在这里啦～！” | 32 → 34 | +2 | <code>0x11A10</code> → <code>0xFAC0</code> |

### STAGE 074 · <code>stg_058b.bin</code> · [057] 投身自然

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/074/dialogue/00.01/0000</code> | 对白 | 【シャイア】「みんな…無事…？」 | 【夏伊亚】“大家……都平安吗……？” | 32 → 34 | +2 | <code>0x2090</code> → <code>0x2090</code> |
| <code>story/074/dialogue/01.03/0019</code> | 对白 | 【$n】「ＯＫ…保管は任せるぜ、桂」 | 【$n】“OK……保管就交给你了，桂” | 32 → 34 | +2 | <code>0x3800</code> → <code>0x32F0</code> |

### STAGE 075 · <code>stg_059a.bin</code> · [058] 第15年的亡灵

3 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/075/dialogue/02.01/0128</code> | 对白 | 【ドミニク】「バイクの礼だ…」 | 【多米尼克】“算是修摩托车的谢礼……” | 32 → 36 | +4 | <code>0x9B00</code> → <code>0x8DD0</code> |
| <code>story/075/dialogue/02.01/0149</code> | 对白 | 【ドミニク】（う、受けてる…！？） | 【多米尼克】（她、她居然笑了……！？） | 32 → 36 | +4 | <code>0xA0B0</code> → <code>0x9250</code> |
| <code>story/075/dialogue/02.01/0160</code><br><code>story/075/dialogue/02.01/0166</code><br><code>story/075/dialogue/02.01/0193</code> | 对白 | 【エニル】「え…」 | 【艾妮尔】“诶……” | 16 → 18 | +2 | <code>0xA300</code> → <code>0x9420</code> |

### STAGE 076 · <code>stg_059b.bin</code> · [058] 第15年的亡灵

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/076/dialogue/02.03/0040</code> | 对白 | 【カトック】「こんな滅茶苦茶な…世の中だ…。<br>　好きに…生きろ…」 | 【卡托克】“这么乱七八糟的……世界……<br>　随自己心意……活下去……” | 64 → 65 | +1 | <code>0xF880</code> → <code>0xE870</code> |

### STAGE 077 · <code>stg_060a.bin</code> · [059] 灵魂的Cosplayer

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/077/dialogue/02.02/0194</code> | 对白 | 【アポロ】「…？」 | 【阿波罗】“……？” | 16 → 18 | +2 | <code>0x8950</code> → <code>0x7920</code> |

### STAGE 078 · <code>stg_060b.bin</code> · [059] 灵魂的Cosplayer

6 个超槽 placement，6 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/078/dialogue/01.04/0004</code> | 对白 | 【竜馬】「だが…」 | 【龙马】“但是……” | 16 → 18 | +2 | <code>0x93A0</code> → <code>0x92C0</code> |
| <code>story/078/dialogue/01.14/0017</code> | 对白 | 【テクス】「なるほど…。<br>　習うより慣れろ、と？」 | 【泰克斯】“原来如此……<br>　与其说教不如让他亲身体会，是吗？” | 48 → 59 | +11 | <code>0x9EC0</code> → <code>0x9BD0</code> |
| <code>story/078/dialogue/01.31/0002</code> | 对白 | 【竜馬】「戦うだけの生き方…。<br>　それしか無い限り、俺達と鬼の<br>　戦いは続く…」 | 【龙马】“只知战斗的活法……只要鬼仍坚持这种活法，<br>　我们与他们的战斗就不会结束……” | 80 → 83 | +3 | <code>0xC5B0</code> → <code>0xBC90</code> |
| <code>story/078/dialogue/02.01/0077</code> | 对白 | 【サラ】「ある意味、男らしい！」 | 【莎拉】“某种意义上，很有男子气概！” | 32 → 36 | +4 | <code>0xDEA0</code> → <code>0xD060</code> |
| <code>story/078/dialogue/02.01/0078</code> | 对白 | 【不動】「代わりに言葉を送る」 | 【不动】“代替金钱，我送你们一句话。” | 32 → 36 | +4 | <code>0xDEC0</code> → <code>0xD090</code> |
| <code>story/078/dialogue/02.03/0010</code> | 对白 | 【アポロ】「う…」 | 【阿波罗】“呃……” | 16 → 18 | +2 | <code>0xED80</code> → <code>0xDBB0</code> |

### STAGE 079 · <code>stg_061a.bin</code> · [060] 局外人

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/079/dialogue/02.01/0006</code> | 对白 | 【シリウス】「つまり多元世界の先住民と言えるな」 | 【西利乌斯】“也就是说，可以算是多元世界的原住民了。” | 48 → 52 | +4 | <code>0x4160</code> → <code>0x3F80</code> |
| <code>story/079/dialogue/02.01/0092</code> | 对白 | 【桂】「俺…か」 | 【桂】“我……吗。” | 16 → 18 | +2 | <code>0x59B0</code> → <code>0x5260</code> |
| <code>story/079/dialogue/02.01/0155</code> | 对白 | 【隼人】「万事休すって奴だな」 | 【隼人】“这就是所谓的万事休矣吧。” | 32 → 34 | +2 | <code>0x6AD0</code> → <code>0x5E90</code> |

### STAGE 080 · <code>stg_061b.bin</code> · [060] 局外人

3 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/080/dialogue/01.11/0004</code> | 对白 | 【オルソン】（だが、例の装置が完成すれば<br>　特異点は不要となる…） | 【奥尔森】（不过，如果那个装置完成的话，<br>　特异点就不再需要了……） | 64 → 65 | +1 | <code>0xC0B0</code> → <code>0xBB30</code> |
| <code>story/080/dialogue/01.25/0001</code><br><code>story/080/dialogue/01.31/0001</code> | 对白 | 【シャイア】「スレイ…何て事を…」 | 【夏伊亚】“斯雷……你都干了些什么……” | 32 → 38 | +6 | <code>0xD100</code> → <code>0xC8B0</code> |
| <code>story/080/dialogue/02.04/0017</code> | 对白 | 【桂】「まあね…」 | 【桂】“还好吧……” | 16 → 18 | +2 | <code>0x11730</code> → <code>0xFEF0</code> |

### STAGE 081 · <code>stg_062a.bin</code> · [061] Acperience

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/081/dialogue/01.01/0041</code> | 对白 | 【ジャミトフ】「口を慎め、エーデル・ベルナル…！」 | 【加米托夫】“注意你的言辞，艾岱尔·贝尔纳尔……！” | 48 → 50 | +2 | <code>0x2370</code> → <code>0x1F50</code> |
| <code>story/081/dialogue/01.01/0045</code> | 对白 | 【ジブリール】（フ…ロゴスの経済力を後ろ盾にした<br>　賢人会議など、所詮は飾りだ…） | 【吉布利尔】（哼……以LOGOS的经济实力为后盾<br>　的贤人会议，终究只是个摆设……） | 80 → 81 | +1 | <code>0x2490</code> → <code>0x2050</code> |

### STAGE 082 · <code>stg_062b.bin</code> · [061] Acperience

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/082/dialogue/02.01/0116</code> | 对白 | 【桂】「怖い…？」 | 【桂】“害怕……？” | 16 → 18 | +2 | <code>0xF0E0</code> → <code>0xE1A0</code> |
| <code>story/082/dialogue/02.01/0125</code> | 对白 | 【マリン】「その何かとは何だ？」 | 【马林】“那个‘什么东西’是什么？” | 32 → 34 | +2 | <code>0xF3B0</code> → <code>0xE3B0</code> |
| <code>story/082/dialogue/02.03/0009</code> | 对白 | 【エニル】「噂？」 | 【艾妮尔】“传闻？” | 16 → 18 | +2 | <code>0x10190</code> → <code>0xEEF0</code> |
| <code>story/082/dialogue/02.03/0030</code> | 对白 | 【キラ】「はい…」 | 【基拉】“是的……” | 16 → 18 | +2 | <code>0x10780</code> → <code>0xF3B0</code> |

### STAGE 083 · <code>stg_063.bin</code> · [062] 被撕裂的过去

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/083/dialogue/01.18/0015</code> | 对白 | 【アサキム】「…待て。何かが来る」 | 【阿萨基姆】“……等等。有什么东西来了。” | 32 → 40 | +8 | <code>0xE4A0</code> → <code>0xDEA0</code> |
| <code>story/083/dialogue/01.24/0000</code> | 对白 | 【セツコ】「わ、私…何て事を…」 | 【节子】“我、我……都做了什么……” | 32 → 34 | +2 | <code>0xE740</code> → <code>0xE0F0</code> |
| <code>story/083/dialogue/02.01/0264</code> | 对白 | 【ジュン】「奴らって…アポロ君…」 | 【纯】“那些家伙是指……阿波罗君……” | 32 → 36 | +4 | <code>0x13D00</code> → <code>0x12350</code> |
| <code>story/083/dialogue/02.03/0067</code> | 对白 | 【$n】「それが俺の…ザ・ヒートのスタイルだ」 | 【$n】“这就是我的……<br>　‘THE HEAT’的风格。” | 48 → 53 | +5 | <code>0x167A0</code> → <code>0x14320</code> |

### STAGE 084 · <code>stg_064.bin</code> · [063] 为了成为我自己

6 个超槽 placement，6 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/084/dialogue/01.01/0002</code> | 对白 | 【アサキム】「頼みの綱のザ・ヒートも<br>　間に合わなかったようだね」 | 【阿萨基姆】“看来你的救命稻草<br>　‘THE HEAT’也没赶上啊。” | 64 → 65 | +1 | <code>0xA8F0</code> → <code>0xA940</code> |
| <code>story/084/dialogue/01.15/0007</code> | 对白 | 【$n】「ザ・ヒートのやり方だ！！」 | 【$n】“THE HEAT的做法！！” | 32 → 34 | +2 | <code>0xC210</code> → <code>0xBCF0</code> |
| <code>story/084/dialogue/01.29/0002</code> | 对白 | 【アサキム】「悠久の時を彷徨えば、君にもわかるさ」 | 【阿萨基姆】“在悠久的时空中彷徨的话，你也会明白的。” | 48 → 52 | +4 | <code>0xD680</code> → <code>0xCD40</code> |
| <code>story/084/dialogue/01.37/0003</code> | 对白 | 【アサキム】「君は僕の想像以上だ、ザ・ヒート」 | 【阿萨基姆】“你超出了我的想象，THE HEAT。” | 48 → 50 | +2 | <code>0xDFC0</code> → <code>0xD4A0</code> |
| <code>story/084/dialogue/02.01/0119</code> | 对白 | 【サラ】「え…？」 | 【莎拉】“诶……？” | 16 → 18 | +2 | <code>0x101A0</code> → <code>0xEDC0</code> |
| <code>story/084/dialogue/02.01/0170</code> | 对白 | 【ジエー】「サンキュー・ベリーマッチョ！」 | 【极艾】“THANK YOU <br>　VERY MUCHO！” | 48 → 55 | +7 | <code>0x10F70</code> → <code>0xF800</code> |

### STAGE 087 · <code>stg_066b.bin</code> · [065] 奇异接触

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/087/dialogue/01.46/0004</code> | 对白 | 【レントン】「感じて…乗る…」 | 【兰顿】“去感受……然后乘上去……” | 32 → 34 | +2 | <code>0xC610</code> → <code>0xB5E0</code> |

### STAGE 088 · <code>stg_067a.bin</code> · [066] 牵牛花

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/088/dialogue/01.05/0004</code> | 对白 | 【タルホ】「あの馬鹿！　戦場をノコノコと！」 | 【塔尔荷】“那个笨蛋！居然大摇大摆地跑到战场上来！” | 48 → 50 | +2 | <code>0xAA10</code> → <code>0xA8B0</code> |
| <code>story/088/dialogue/01.11/0013</code> | 对白 | 【レントン】「…自然に出た…。<br>　俺…ニルヴァーシュの気持ちが…」 | 【兰顿】“……自然而然就说出来了……我……<br>　能感受到尼尔瓦修的心情了……” | 64 → 73 | +9 | <code>0xB630</code> → <code>0xB240</code> |

### STAGE 089 · <code>stg_067b.bin</code> · [066] 牵牛花

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/089/dialogue/01.05/0000</code> | 对白 | 【カシマル】「あ…ああ…寒い…凍える…。<br>　ああ…私の…ダイヤが…凍る…」 | 【卡西马尔】“啊……啊啊……好冷……冻僵了……啊啊……<br>　我的……列车运行图……冻住了……” | 80 → 89 | +9 | <code>0x2AE0</code> → <code>0x29E0</code> |

### STAGE 090 · <code>stg_068.bin</code> · [067] 远方挚友

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/090/dialogue/02.01/0179</code> | 对白 | 【リーナ】「恋ね」 | 【莉娜】“是恋爱。” | 16 → 18 | +2 | <code>0x10730</code> → <code>0xF430</code> |
| <code>story/090/dialogue/02.02/0051</code> | 对白 | 【大介】「ベガ大王の娘…僕の幼馴染のルビーナだ」 | 【大介】“贝加大王的女儿……<br>　我的青梅竹马，露比娜。” | 48 → 53 | +5 | <code>0x12F80</code> → <code>0x112D0</code> |

### STAGE 091 · <code>stg_069.bin</code> · [068] 愤怒的铁路王

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/091/dialogue/01.07/0014</code> | 对白 | 【シンシア】「友達なら遊んでよ！」 | 【辛西亚】“既然是朋友，那就陪我玩啊！” | 32 → 38 | +6 | <code>0xAE50</code> → <code>0xABA0</code> |

### STAGE 094 · <code>stg_070c.bin</code> · [069] Over Battle

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/094/dialogue/01.05/0000</code> | 对白 | 【カシマル】「あ…ああ…寒い…凍える…。<br>　ああ…私の…ダイヤが…凍る…」 | 【卡西马尔】“啊……啊啊……好冷……冻僵了……啊啊……<br>　我的……列车运行图……冻住了……” | 80 → 89 | +9 | <code>0x2860</code> → <code>0x2780</code> |

### STAGE 095 · <code>stg_071.bin</code> · [070] 被昭示的明天

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/095/dialogue/01.04/0001</code> | 对白 | 【$n】「ひでえ…！<br>　街が滅茶苦茶じゃねえか！」 | 【$n】“这也太惨了……！<br>　整座城市都被毁得不成样了！” | 48 → 53 | +5 | <code>0xC370</code> → <code>0xC2A0</code> |
| <code>story/095/dialogue/01.18/0000</code> | 对白 | 【ステラ】「あ…」 | 【史黛拉】“啊……” | 16 → 18 | +2 | <code>0xE620</code> → <code>0xDF00</code> |
| <code>story/095/dialogue/01.18/0004</code> | 对白 | 【ステラ】「シン…ステラ…守る…う…って…」 | 【史黛拉】“真……史黛拉……保护……<br>　你……说……过……” | 48 → 57 | +9 | <code>0xE6A0</code> → <code>0xDF90</code> |

### STAGE 096 · <code>stg_072a.bin</code> · [071] 肃清风暴

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/096/dialogue/01.06/0002</code> | 对白 | 【アテナ】「え…」 | 【雅典娜】“诶……” | 16 → 18 | +2 | <code>0x2980</code> → <code>0x27D0</code> |

### STAGE 098 · <code>stg_073.bin</code> · [072] 被安排的决战

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/098/dialogue/01.06/0009</code> | 对白 | 【$n】「心配するな、メール。<br>　俺はザ・クラッシャーじゃなく<br>　ザ・ヒートだ！」 | 【$n】“别担心，梅尔。我现在不是<br>　THE CRUSHER，<br>　而是THE HEAT！” | 80 → 84 | +4 | <code>0x13E60</code> → <code>0x13930</code> |
| <code>story/098/dialogue/01.14/0000</code> | 对白 | 【カガリ】「う、嘘だろ…キラ…」 | 【卡嘉莉】“骗、骗人的吧……基拉……” | 32 → 36 | +4 | <code>0x141E0</code> → <code>0x16350</code> |
| <code>story/098/dialogue/02.01/0030</code> | 对白 | 【桂】「え…！？」 | 【桂】“诶……！？” | 16 → 18 | +2 | <code>0x21D70</code> → <code>0x1E480</code> |

### STAGE 099 · <code>stg_074a.bin</code> · [073] 启动一切

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/099/dialogue/02.02/0046</code> | 对白 | 【タルホ】「え…」 | 【塔尔荷】“呃……” | 16 → 18 | +2 | <code>0x82A0</code> → <code>0x7860</code> |
| <code>story/099/dialogue/02.02/0153</code> | 对白 | 【ジョブス】「な、何だと！？<br>　この罰当たりが！」 | 【乔布斯】“什、什么！？你这个不知天高地厚的家伙！” | 48 → 50 | +2 | <code>0x9EA0</code> → <code>0x8E40</code> |

### STAGE 100 · <code>stg_074b.bin</code> · [073] 启动一切

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/100/dialogue/01.13/0003</code> | 对白 | 【タルホ】「…！」 | 【塔尔荷】“……！” | 16 → 18 | +2 | <code>0xB720</code> → <code>0xB440</code> |
| <code>story/100/dialogue/01.26/0009</code> | 对白 | 【エウレカ】「手を…手を握って…」 | 【优莱卡】“握住……握住我的手……” | 32 → 34 | +2 | <code>0xCA00</code> → <code>0xC330</code> |
| <code>story/100/dialogue/02.01/0235</code> | 对白 | 【？？？】「…救世の戦士…太極への旅人…法の守護騎士…<br>　因果律の番人…呪われし放浪者…。<br>　何でも構いませんが…」 | 【？？？】“……救世的战士……太极的旅人……<br>　法则的守护骑士……因果律的看守人……<br>　被诅咒的流浪者……叫什么都可以……” | 112 → 120 | +8 | <code>0x11610</code> → <code>0xFF10</code> |

### STAGE 101 · <code>stg_075.bin</code> · [074] 崩坏序曲

9 个超槽 placement，9 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/101/dialogue/01.07/0006</code> | 对白 | 【？？？】（フフフ…フフフフフ…） | 【？？？】（哼哼哼……哼哼哼哼……） | 32 → 34 | +2 | <code>0xD370</code> → <code>0xD020</code> |
| <code>story/101/dialogue/01.18/0012</code> | 对白 | 【黒のカリスマ】「黒のカリスマ…」 | 【黑之卡里斯马】“黑之卡里斯马……” | 32 → 34 | +2 | <code>0xF550</code> → <code>0xEAA0</code> |
| <code>story/101/dialogue/01.38/0000</code> | 对白 | 【頭翅】「一万二千年前のあの日…」 | 【头翅】“一万两千年前的那一天……” | 32 → 34 | +2 | <code>0x10830</code> → <code>0xF970</code> |
| <code>story/101/dialogue/02.01/0009</code> | 对白 | 【カガリ】「え…」 | 【卡嘉莉】“呃……” | 16 → 18 | +2 | <code>0x11230</code> → <code>0x10160</code> |
| <code>story/101/dialogue/02.01/0069</code> | 对白 | 【ネオ】（ムウ・ラ・フラガ…か…） | 【尼奥】（穆·拉·弗拉格……吗……） | 32 → 34 | +2 | <code>0x12020</code> → <code>0x10CD0</code> |
| <code>story/101/dialogue/02.01/0084</code> | 对白 | 【総裁】「何…？」 | 【总裁】“什么……？” | 16 → 20 | +4 | <code>0x12320</code> → <code>0x10F50</code> |
| <code>story/101/dialogue/02.01/0243</code> | 对白 | 【桂】（子供か…） | 【桂】（还是个小鬼啊……） | 16 → 24 | +8 | <code>0x14B90</code> → <code>0x12F70</code> |
| <code>story/101/dialogue/02.02/0018</code> | 对白 | 【頭翅】「フフ…こやつらの正体を知った上でもか？」 | 【头翅】“呵呵……就算知道了他们的<br>　真实身份也还是这么说吗？” | 48 → 61 | +13 | <code>0x151B0</code> → <code>0x134B0</code> |
| <code>story/101/dialogue/02.02/0024</code> | 对白 | 【頭翅】「そう…我らと同じ翅を受け継ぐ者達だ」 | 【头翅】“没错……<br>　他们是继承了和我们相同翅膀的人。” | 48 → 53 | +5 | <code>0x152D0</code> → <code>0x135B0</code> |

### STAGE 102 · <code>stg_076a.bin</code> · [075] 交叉点

3 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/102/dialogue/01.01/0312</code><br><code>story/102/dialogue/01.01/0326</code> | 对白 | 【大介】「$c…。<br>　正しき力の集う場としたいな」 | 【大介】“$c……<br>　希望它能成为正义力量汇聚之地。” | 48 → 49 | +1 | <code>0xB550</code> → <code>0xA020</code> |
| <code>story/102/dialogue/01.01/0491</code> | 对白 | 【トニヤ】「やだ…敵が来たの！？」 | 【托妮娅】“讨厌……敌人来了吗！？” | 32 → 34 | +2 | <code>0xE500</code> → <code>0xC500</code> |
| <code>story/102/dialogue/01.01/0505</code> | 对白 | 【シリウス】「…我らの翅の事…<br>　口外すれば、お前を…斬る」 | 【西利乌斯】“……关于我们翅膀的事……<br>　要是说出去，我就……斩了你。” | 64 → 69 | +5 | <code>0xE8B0</code> → <code>0xC7F0</code> |

### STAGE 103 · <code>stg_076b.bin</code> · [075] 交叉点

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/103/dialogue/02.01/0024</code> | 对白 | 【シャイア】「私は何事にも純粋に情熱を傾ける彼らに<br>　賭けている…」 | 【夏伊亚】“我愿意把希望寄托在他们身上……<br>　他们无论做什么，都会倾注纯粹的热情。” | 80 → 81 | +1 | <code>0xFEF0</code> → <code>0xEC70</code> |
| <code>story/103/dialogue/02.01/0071</code> | 对白 | 【シャイア】「私達全員が特異点…」 | 【夏伊亚】“我们全员都是特异点……” | 32 → 34 | +2 | <code>0x10B50</code> → <code>0xF620</code> |

### STAGE 104 · <code>stg_077.bin</code> · [076] 终章开幕

8 个超槽 placement，16 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/104/dialogue/01.11/0015</code> | 对白 | 【$n】「勝平君…」 | 【$n】“胜平君……” | 16 → 18 | +2 | <code>0x10660</code> → <code>0x10210</code> |
| <code>story/104/dialogue/01.17/0001</code><br><code>story/104/dialogue/01.18/0001</code> | 对白 | 【恵子】「勝平…」 | 【惠子】“胜平……” | 16 → 18 | +2 | <code>0x10EF0</code> → <code>0x108C0</code> |
| <code>story/104/dialogue/01.34/0001</code> | 对白 | 【斗牙】「空っぽだ…」 | 【斗牙】“心里已经什么都不剩了……” | 32 → 34 | +2 | <code>0x126D0</code> → <code>0x11B90</code> |
| <code>story/104/dialogue/02.01/0023</code> | 对白 | 【太一郎】「何…」 | 【太一郎】“什么……” | 16 → 20 | +4 | <code>0x14340</code> → <code>0x130D0</code> |
| <code>story/104/dialogue/02.01/0050</code> | 对白 | 【テラル】「アフロディア殿…。<br>　無理を聞いてもらう礼というわけではないが、<br>　一つ話をしよう」 | 【迪拉尔】“阿芙罗蒂亚阁下……这算不上你<br>　答应我这个强人所难的请求的谢礼，<br>　不过，我还是给你讲一件事吧。” | 96 → 106 | +10 | <code>0x14AE0</code> → <code>0x13700</code> |
| <code>story/104/dialogue/02.01/0293</code><br><code>story/104/dialogue/02.01/0349</code><br><code>story/104/dialogue/02.01/0368</code><br><code>story/104/dialogue/02.01/0391</code><br><code>story/104/dialogue/02.01/0397</code> | 对白 | 【アキ】「勝平…」 | 【亚纪】“胜平……” | 16 → 18 | +2 | <code>0x191B0</code> → <code>0x16E20</code> |
| <code>story/104/dialogue/02.01/0294</code><br><code>story/104/dialogue/02.01/0350</code> | 对白 | 【勝平】「アキ…アキなのか…！？」 | 【胜平】“亚纪……是亚纪吗……！？” | 32 → 34 | +2 | <code>0x191C0</code> → <code>0x16E40</code> |
| <code>story/104/dialogue/02.01/0365</code><br><code>story/104/dialogue/02.01/0379</code><br><code>story/104/dialogue/02.02/0010</code> | 对白 | 【勝平】「アキ…」 | 【胜平】“亚纪……” | 16 → 18 | +2 | <code>0x19590</code> → <code>0x17140</code> |

### STAGE 105 · <code>stg_078a.bin</code> · [077] 命运与自由

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/105/dialogue/02.02/0004</code> | 对白 | 【タリア】「…！」 | 【塔丽亚】“……！” | 16 → 18 | +2 | <code>0xB340</code> → <code>0x9F70</code> |

### STAGE 106 · <code>stg_078b.bin</code> · [077] 命运与自由

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/106/dialogue/02.02/0040</code> | 对白 | 【ハリー】「助けてもらった身で不躾だが、聞かせてもらう。<br>　君はあの時の戦闘も今日も<br>　不自然な戦い方をしていた…」 | 【哈利】“虽然是被你救的人，说这话可能有些冒昧，<br>　但我还是想问。你在那天的战斗和今天，<br>　都用了不自然的战斗方式……” | 112 → 116 | +4 | <code>0xB660</code> → <code>0xABE0</code> |
| <code>story/106/dialogue/02.02/0117</code> | 对白 | 【ベガ大王】「地球洪水作戦…！？」 | 【贝加大王】“地球洪水作战……！？” | 32 → 34 | +2 | <code>0xCB10</code> → <code>0xBC50</code> |

### STAGE 107 · <code>stg_079.bin</code> · [078] 降临的太阳

7 个超槽 placement，8 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/107/dialogue/01.20/0001</code> | 对白 | 【つぐみ】「で、でも…あの姿…！」 | 【鸫】“可、可是……那个样子……！” | 32 → 34 | +2 | <code>0x18E00</code> → <code>0x18E50</code> |
| <code>story/107/dialogue/01.35/0003</code> | 对白 | 【琉菜】「上空から何か来るよ！」 | 【琉菜】“天上有什么东西飞过来了！” | 32 → 34 | +2 | <code>0x19E00</code> → <code>0x19B60</code> |
| <code>story/107/dialogue/01.41/0016</code> | 对白 | 【斗牙】「リィル…君の力も貸して」 | 【斗牙】“莉露……也借给我你的力量。” | 32 → 36 | +4 | <code>0x1A950</code> → <code>0x1A490</code> |
| <code>story/107/dialogue/02.01/0313</code> | 对白 | 【$n】「シン君…ルナマリアさん…」 | 【$n】“真君……露娜玛丽亚小姐……” | 32 → 34 | +2 | <code>0x229E0</code> → <code>0x1FFC0</code> |
| <code>story/107/dialogue/02.03/0038</code> | 对白 | 【ルビーナ】「…最後にお願い…。<br>　お父様を…ベガ大王を止めて…」 | 【露比娜】“……最后还有一个请求……<br>　请阻止父亲……贝加大王……” | 64 → 65 | +1 | <code>0x245C0</code> → <code>0x21550</code> |
| <code>story/107/dialogue/02.03/0052</code><br><code>story/107/dialogue/02.03/0089</code> | 对白 | 【勝平】「香月…」 | 【胜平】“香月……” | 16 → 18 | +2 | <code>0x24920</code> → <code>0x21830</code> |
| <code>story/107/dialogue/02.03/0053</code> | 对白 | 【香月】「勝平…俺は異星人に追われて捕まって<br>　色んな人間が死んでいくのを見た」 | 【香月】“胜平……胜平……我被外星人追杀，落到了他们手里，<br>眼睁睁看着好多人死掉” | 80 → 81 | +1 | <code>0x24930</code> → <code>0x21850</code> |

### STAGE 108 · <code>stg_080.bin</code> · [079] 遗产继承者

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/108/dialogue/02.01/0013</code> | 对白 | 【テラル】「なぜ、それを…！？」 | 【迪拉尔】“为什么你会知道……！？” | 32 → 34 | +2 | <code>0x13100</code> → <code>0x11DA0</code> |
| <code>story/108/dialogue/02.03/0051</code> | 对白 | 【月影】「では…」 | 【月影】“那么……” | 16 → 18 | +2 | <code>0x1A840</code> → <code>0x181B0</code> |

### STAGE 109 · <code>stg_081.bin</code> · [080] 混乱中的正义

10 个超槽 placement，10 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/109/dialogue/01.18/0000</code> | 对白 | 【エマ】「ロゴスも撤退していく…」 | 【爱玛】“LOGOS的部队也在撤退……” | 32 → 38 | +6 | <code>0x15AA0</code> → <code>0x153D0</code> |
| <code>story/109/dialogue/01.53/0015</code> | 对白 | 【クワトロ】（デュランダル議長…<br>　ロゴスがほぼ壊滅した今、<br>　強攻策に出るか…！） | 【克瓦特罗】（迪兰达尔议长……在‘LOGOS’几乎<br>　覆灭的现在，要采取强硬手段吗……！） | 80 → 87 | +7 | <code>0x180E0</code> → <code>0x17300</code> |
| <code>story/109/dialogue/01.53/0020</code> | 对白 | 【ザフト艦長】「何だと…！？」 | 【ZAFT舰长】“你说什么……！？” | 32 → 34 | +2 | <code>0x18270</code> → <code>0x17450</code> |
| <code>story/109/dialogue/01.58/0001</code> | 对白 | 【万丈】「侍と言うよりお殿様だな」 | 【万丈】“与其说是武士，倒更像个大名。” | 32 → 38 | +6 | <code>0x185C0</code> → <code>0x17700</code> |
| <code>story/109/dialogue/01.60/0001</code> | 对白 | 【ルナマリア】「あの黄色いムラサメ…凄い気迫ね」 | 【露娜玛丽亚】“那台黄色的村雨……好惊人的气势啊。” | 48 → 50 | +2 | <code>0x18730</code> → <code>0x17840</code> |
| <code>story/109/dialogue/01.75/0000</code> | 对白 | 【アムロ】「荒削りな分、動きが読みづらい！<br>　この男…何者だ！？」 | 【阿姆罗】“因为粗糙，所以动作难以预测！<br>　这个男人……到底是什么人！？” | 64 → 71 | +7 | <code>0x19B30</code> → <code>0x18820</code> |
| <code>story/109/dialogue/01.89/0005</code> | 对白 | 【$n】「その胸の傷程度じゃ済まさねえぞ！<br>　てめえは大解体だ！」 | 【$n】“可不会让你只留下胸口那道伤疤就完事！<br>　我要把你大卸八块！” | 64 → 65 | +1 | <code>0x1B040</code> → <code>0x19860</code> |
| <code>story/109/dialogue/02.02/0007</code> | 对白 | 【ネオ】「今はフラガ少佐でいい！」 | 【尼奥】“现在叫弗拉加少校就行了！” | 32 → 34 | +2 | <code>0x1F380</code> → <code>0x1CEC0</code> |
| <code>story/109/dialogue/02.03/0082</code> | 对白 | 【ミーア】「え…え…わ、私は…」 | 【米娅】“诶……诶……我、我是……” | 32 → 34 | +2 | <code>0x20AB0</code> → <code>0x1E1B0</code> |
| <code>story/109/dialogue/02.03/0087</code> | 对白 | 【シン】「…そんな…馬鹿な…」 | 【真】“……怎么会……怎么可能……” | 32 → 34 | +2 | <code>0x20BF0</code> → <code>0x1E2D0</code> |

### STAGE 110 · <code>stg_082.bin</code> · [081] 倒计时

4 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/110/dialogue/01.06/0001</code> | 对白 | 【$n】「…はい…」 | 【$n】“……是……” | 16 → 18 | +2 | <code>0x11380</code> → <code>0x10F90</code> |
| <code>story/110/dialogue/01.14/0007</code> | 对白 | 【$n】「そんな…」 | 【$n】“怎么会……” | 16 → 18 | +2 | <code>0x11A30</code> → <code>0x11510</code> |
| <code>story/110/dialogue/02.01/0124</code> | 对白 | 【$n】「敵…ね…」 | 【$n】“敌人……吗……” | 16 → 22 | +6 | <code>0x18CA0</code> → <code>0x16C60</code> |
| <code>story/110/dialogue/02.02/0077</code><br><code>story/110/dialogue/02.02/0194</code> | 对白 | 【タリア】「…！」 | 【塔丽亚】“……！” | 16 → 18 | +2 | <code>0x1ADF0</code> → <code>0x18560</code> |

### STAGE 111 · <code>stg_083.bin</code> · [082] 我们的去向

5 个超槽 placement，6 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/111/dialogue/01.03/0000</code> | 对白 | 【連邦軍兵】「何者だ、奴は！？」 | 【联邦军士兵】“那家伙是什么人！？” | 32 → 34 | +2 | <code>0x10B00</code> → <code>0x10B80</code> |
| <code>story/111/dialogue/02.01/0136</code> | 对白 | 【ホランド】「顔も知らない誰かの作った商売に<br>　乗る気はねえよ」 | 【霍兰德】“我可没兴趣上赶着买那些连脸<br>　都不认识的家伙搞出来的东西。” | 64 → 69 | +5 | <code>0x19360</code> → <code>0x173C0</code> |
| <code>story/111/dialogue/02.01/0143</code> | 对白 | 【ゲイン】「せっかくだから見物だ」 | 【该隐】“难得的机会，就看看热闹。” | 32 → 34 | +2 | <code>0x19560</code> → <code>0x17550</code> |
| <code>story/111/dialogue/02.01/0281</code> | 对白 | 【連邦軍兵】「何だ、お前は…！？」 | 【联邦军士兵】“你是什么人……！？” | 32 → 34 | +2 | <code>0x1B630</code> → <code>0x18E40</code> |
| <code>story/111/dialogue/02.02/0094</code><br><code>story/111/dialogue/02.02/0215</code> | 对白 | 【タリア】「…！」 | 【塔丽亚】“……！” | 16 → 18 | +2 | <code>0x1D7A0</code> → <code>0x1A7A0</code> |

### STAGE 112 · <code>stg_084.bin</code> · [083] 乐园的放逐者

7 个超槽 placement，9 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/112/dialogue/01.02/0001</code> | 对白 | 【両翅】「それに先程から感じる不快感…！<br>　奴ら、まさか…！」 | 【双翅】“而且从刚才起就感到的那股不快感……！<br>　他们，难道……！” | 64 → 65 | +1 | <code>0x10EB0</code> → <code>0x10F80</code> |
| <code>story/112/dialogue/01.34/0001</code> | 对白 | 【麗花】「あ…！」 | 【丽花】“啊……！” | 16 → 18 | +2 | <code>0x13F50</code> → <code>0x136A0</code> |
| <code>story/112/dialogue/01.59/0004</code> | 对白 | 【レントン】「ドミニク…あんた…」 | 【兰顿】“多米尼克……你这家伙……” | 32 → 34 | +2 | <code>0x15340</code> → <code>0x146B0</code> |
| <code>story/112/dialogue/01.75/0002</code> | 对白 | 【シリウス】「グレン…<br>　君も悪しき力の犠牲に…」 | 【西利乌斯】“格伦……你也成了邪恶力量的牺牲品……” | 48 → 50 | +2 | <code>0x16870</code> → <code>0x15790</code> |
| <code>story/112/dialogue/02.01/0000</code><br><code>story/112/dialogue/02.01/0001</code><br><code>story/112/dialogue/02.01/0002</code> | 对白 | ディーバ司令室 | DEAVA司令室 | 16 → 17 | +1 | <code>0x16A40</code> → <code>0x158F0</code> |
| <code>story/112/dialogue/02.01/0111</code> | 对白 | 【ノルブ】「いや…話はここまでだ」 | 【诺尔布】“不……话就到此为止了。” | 32 → 34 | +2 | <code>0x185C0</code> → <code>0x16DF0</code> |
| <code>story/112/dialogue/02.02/0010</code> | 对白 | 【ノルブ】「ただいま、サクヤ様…」 | 【诺尔布】“我回来了，咲夜大人……” | 32 → 34 | +2 | <code>0x19960</code> → <code>0x17E20</code> |

### STAGE 113 · <code>stg_085.bin</code> · [084] 幻想都市

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/113/dialogue/01.21/0005</code> | 对白 | 【ロジャー】「誰かに与えられた力に喜ぶお前達に<br>　我々の強さを教えてやろう！」 | 【罗杰】“你们这些为别人赐予的力量而沾沾自喜的<br>　家伙，让我来教教你们什么是真正的强大！” | 80 → 87 | +7 | <code>0x11A50</code> → <code>0x11510</code> |
| <code>story/113/dialogue/02.01/0094</code> | 对白 | 【竜馬】「お、おい…アポロ…！？」 | 【龙马】“喂、喂……阿波罗……！？” | 32 → 34 | +2 | <code>0x17850</code> → <code>0x15E50</code> |

### STAGE 116 · <code>stg_086c.bin</code> · [085] 人类之心，天翅之梦

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/116/dialogue/02.01/0087</code> | 对白 | 【$n】「納得…」 | 【$n】“明白了……” | 16 → 18 | +2 | <code>0x6820</code> → <code>0x5E60</code> |

### STAGE 117 · <code>stg_086d.bin</code> · [085] 人类之心，天翅之梦

9 个超槽 placement，10 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/117/dialogue/01.03/0002</code> | 对白 | 【ガウリ】「御意」 | 【高富利】“遵命。” | 16 → 18 | +2 | <code>0x13C00</code> → <code>0x13C90</code> |
| <code>story/117/dialogue/01.05/0021</code><br><code>story/117/dialogue/01.06/0022</code> | 对白 | 【アポロ】「この声…シリウスか！」 | 【阿波罗】“这个声音……是西利乌斯吗！” | 32 → 38 | +6 | <code>0x14690</code> → <code>0x14490</code> |
| <code>story/117/dialogue/01.17/0002</code> | 对白 | 【詩翅】「麗花…」 | 【诗翅】“丽花……” | 16 → 18 | +2 | <code>0x15850</code> → <code>0x179A0</code> |
| <code>story/117/dialogue/01.18/0000</code> | 对白 | 【リーナ】「麗花の叫び…届いた…」 | 【莉娜】“丽花的呼喊……传到了……” | 32 → 34 | +2 | <code>0x15B50</code> → <code>0x17C20</code> |
| <code>story/117/dialogue/01.101/0028</code> | 对白 | 【シルヴィア】「…今、わかった…」 | 【西尔维娅】“……我现在明白了……” | 32 → 34 | +2 | <code>0x1AC50</code> → <code>0x156D0</code> |
| <code>story/117/dialogue/01.117/0000</code> | 对白 | 【両翅】「生命の樹の受粉は近い…」 | 【双翅】“生命之树的授粉临近了……” | 32 → 34 | +2 | <code>0x1C250</code> → <code>0x16930</code> |
| <code>story/117/dialogue/01.124/0000</code> | 对白 | 【$n】「来いや、化け物！<br>　お前が氷の悪魔なら、<br>　俺はザ・ヒート…炎の天使だ！！」 | 【$n】“来吧，怪物！如果你是冰之恶魔，那我就<br>　是THE HEAT……火焰的天使！！” | 80 → 83 | +3 | <code>0x1C7F0</code> → <code>0x16E00</code> |
| <code>story/117/dialogue/01.131/0001</code> | 对白 | 【アナ】「キ〜ング、キ〜ング、キングゲイナー♪」 | 【安娜】“King~King~<br>　King Gainer♪” | 48 → 57 | +9 | <code>0x1D360</code> → <code>0x177A0</code> |
| <code>story/117/dialogue/02.01/0025</code> | 对白 | 【アスハム】「え…あ…ああ…」 | 【阿斯哈姆】“呃……啊……啊啊……” | 32 → 34 | +2 | <code>0x1D980</code> → <code>0x1B8D0</code> |

### STAGE 118 · <code>stg_087.bin</code> · [086] 决别

6 个超槽 placement，9 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/118/dialogue/01.25/0011</code> | 对白 | 【タリア】（では、今…ザフトは…） | 【塔丽亚】（那么，现在……ZAFT……） | 32 → 38 | +6 | <code>0x14100</code> → <code>0x137A0</code> |
| <code>story/118/dialogue/02.01/0041</code> | 对白 | 【テラル】「負けだ、アフロディア。<br>　力ではなく心に我々は負けた」 | 【迪拉尔】“我们输了，阿芙罗蒂亚。<br>　我们不是输给了力量，而是输给了心灵。” | 64 → 73 | +9 | <code>0x18C00</code> → <code>0x16CF0</code> |
| <code>story/118/dialogue/02.01/0061</code> | 对白 | 【ジブリール】「シロッコ…貴様っ！<br>　よくもぬけぬけと私の前に！」 | 【吉布利尔】“西罗克……你这混蛋！<br>　竟敢厚颜无耻地出现在我面前！” | 64 → 65 | +1 | <code>0x18F50</code> → <code>0x16F80</code> |
| <code>story/118/dialogue/02.02/0092</code> | 对白 | 【ブライト】（レコア少尉の事か…） | 【布莱德】（是说蕾柯亚少尉的事吧……） | 32 → 36 | +4 | <code>0x1D050</code> → <code>0x1A960</code> |
| <code>story/118/dialogue/02.02/0169</code><br><code>story/118/dialogue/02.02/0312</code> | 对白 | 【アムロ】「人はわかりあえる…」 | 【阿姆罗】“人是可以相互理解的……” | 32 → 34 | +2 | <code>0x1E480</code> → <code>0x1B9C0</code> |
| <code>story/118/dialogue/02.02/0216</code><br><code>story/118/dialogue/02.02/0255</code><br><code>story/118/dialogue/02.02/0330</code> | 对白 | 【ネオ】「坊主…」 | 【尼奥】“小子……” | 16 → 18 | +2 | <code>0x1F0E0</code> → <code>0x1C3C0</code> |

### STAGE 119 · <code>stg_088.bin</code> · [087] 黑历史的真相

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/119/dialogue/02.01/0039</code> | 对白 | 【シロッコ】「より良き未来を迎えるためには<br>　民の選別と、それを成す力も必要です」 | 【西罗克】“为了迎接更美好的未来，对民众进行筛<br>　选以及实现这一目标的力量也是必要的。” | 80 → 85 | +5 | <code>0x1D500</code> → <code>0x1B300</code> |
| <code>story/119/dialogue/02.02/0140</code> | 对白 | 【勝平】「じゃあ、さっきの声が…」 | 【胜平】“那么，刚才的声音就是……” | 32 → 34 | +2 | <code>0x209E0</code> → <code>0x1DDF0</code> |
| <code>story/119/dialogue/02.03/0062</code> | 对白 | 【理恵】「でも…」 | 【理惠】“但是……” | 16 → 18 | +2 | <code>0x24AA0</code> → <code>0x213A0</code> |

### STAGE 120 · <code>stg_089.bin</code> · [088] 月面决战

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/120/dialogue/01.17/0002</code> | 对白 | 【太一郎】「尊い犠牲を払って得た勝利だ…！<br>　後は頼むぞ、$c！」 | 【太一郎】“这是付出宝贵牺牲换来的胜利……！<br>　接下来拜托了，$c！” | 64 → 65 | +1 | <code>0x10F60</code> → <code>0x105B0</code> |
| <code>story/120/dialogue/02.05/0016</code> | 对白 | 【少女】「あの…」 | 【少女】“那个……” | 16 → 18 | +2 | <code>0x199C0</code> → <code>0x170E0</code> |

### STAGE 122 · <code>stg_090b.bin</code> · [089] 背叛的月光

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/122/dialogue/02.02/0005</code> | 对白 | 【クワトロ】「新連邦とプラント…」 | 【克瓦特罗】“新联邦和PLANT……” | 32 → 36 | +4 | <code>0x135C0</code> → <code>0x11F00</code> |
| <code>story/122/dialogue/02.02/0175</code> | 对白 | 【理恵】「でも…」 | 【理惠】“但是……” | 16 → 18 | +2 | <code>0x16210</code> → <code>0x142C0</code> |

### STAGE 125 · <code>stg_091a.bin</code> · [090] 绝望之光，希望之灯

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/125/dialogue/02.01/0127</code> | 对白 | 【アポリー】「あのキラっての…、<br>　何て言うか…悟りきった奴だな」 | 【阿波利】“那个叫基拉的……怎么说呢……<br>　真是个看透了的家伙啊。” | 64 → 65 | +1 | <code>0x8030</code> → <code>0x7710</code> |

### STAGE 126 · <code>stg_091b.bin</code> · [090] 绝望之光，希望之灯

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/126/dialogue/02.01/0117</code> | 对白 | 【ジブリール】「シロッコ…貴様っ！<br>　よくもぬけぬけと私の前に！」 | 【吉布利尔】“西罗克……你这混蛋！<br>　竟敢厚颜无耻地出现在我面前！” | 64 → 65 | +1 | <code>0x12B70</code> → <code>0x11610</code> |
| <code>story/126/dialogue/02.02/0022</code> | 对白 | 【少女】「あの…」 | 【少女】“那个……” | 16 → 18 | +2 | <code>0x146E0</code> → <code>0x12AF0</code> |
| <code>story/126/dialogue/02.02/0043</code> | 对白 | 【ヘンケン】「ま…その…買い物だ」 | 【亨肯】“呃……那个……来买东西。” | 32 → 34 | +2 | <code>0x14BC0</code> → <code>0x12EA0</code> |

### STAGE 127 · <code>stg_092.bin</code> · [091] 我是D.O.M.E.……

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/127/dialogue/01.57/0001</code> | 对白 | 【麗花】「あ…！」 | 【丽花】“啊……！” | 16 → 18 | +2 | <code>0x1CBE0</code> → <code>0x1CC30</code> |
| <code>story/127/dialogue/01.112/0002</code> | 对白 | 【シリウス】「グレン…<br>　君も悪しき力の犠牲に…」 | 【西利乌斯】“格伦……你也成了邪恶力量的牺牲品……” | 48 → 50 | +2 | <code>0x21330</code> → <code>0x18310</code> |
| <code>story/127/dialogue/02.01/0018</code> | 对白 | 【麗花】「夢…？」 | 【丽花】“梦……？” | 16 → 18 | +2 | <code>0x22040</code> → <code>0x1F8A0</code> |
| <code>story/127/dialogue/02.01/0040</code> | 对白 | 【アポロ】「何だ、ありゃ…？」 | 【阿波罗】“搞什么啊，那家伙……？” | 32 → 34 | +2 | <code>0x225B0</code> → <code>0x1FD50</code> |

### STAGE 128 · <code>stg_093.bin</code> · [092] 绯红路

10 个超槽 placement，10 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/128/dialogue/01.50/0002</code> | 对白 | 【詩翅】「麗花…」 | 【诗翅】“丽花……” | 16 → 18 | +2 | <code>0x15230</code> → <code>0x145E0</code> |
| <code>story/128/dialogue/01.51/0000</code> | 对白 | 【リーナ】「麗花の叫び…届いた…」 | 【莉娜】“丽花的呼喊……传到了……” | 32 → 34 | +2 | <code>0x15400</code> → <code>0x14770</code> |
| <code>story/128/dialogue/01.55/0028</code> | 对白 | 【シルヴィア】「…今、わかった…」 | 【西尔维娅】“……现在，我明白了……” | 32 → 36 | +4 | <code>0x15F30</code> → <code>0x150C0</code> |
| <code>story/128/dialogue/01.55/0031</code> | 对白 | 【シルヴィア】「人と…大切な人と結ぶために<br>　あるのよ！！」 | 【西尔维娅】“是为了和人们……<br>　和重要的人联结在一起而存在的！！” | 64 → 65 | +1 | <code>0x15FB0</code> → <code>0x15140</code> |
| <code>story/128/dialogue/01.76/0000</code> | 对白 | 【両翅】「生命の樹の受粉は近い…」 | 【双翅】“生命之树的授粉临近了……” | 32 → 34 | +2 | <code>0x17670</code> → <code>0x164A0</code> |
| <code>story/128/dialogue/02.01/0090</code> | 对白 | 【テラル】「負けだ、アフロディア。<br>　力ではなく心に我々は負けた」 | 【迪拉尔】“我们输了，阿芙罗蒂亚。<br>　我们不是输给了力量，而是输给了心灵。” | 64 → 73 | +9 | <code>0x18EB0</code> → <code>0x178E0</code> |
| <code>story/128/dialogue/02.01/0155</code> | 对白 | 【竜馬】「お、おい…アポロ…！？」 | 【龙马】“喂、喂……阿波罗……！？” | 32 → 34 | +2 | <code>0x19DF0</code> → <code>0x18510</code> |
| <code>story/128/dialogue/02.01/0204</code> | 对白 | 【ノルブ】「いや…話はここまでだ」 | 【诺尔布】“不……话就到此为止了。” | 32 → 34 | +2 | <code>0x1AB10</code> → <code>0x18FF0</code> |
| <code>story/128/dialogue/02.02/0010</code> | 对白 | 【ノルブ】「ただいま、サクヤ様…」 | 【诺尔布】“我回来了，咲夜大人……” | 32 → 34 | +2 | <code>0x1B560</code> → <code>0x19880</code> |
| <code>story/128/dialogue/02.05/0018</code> | 对白 | 【ピエール】（やれやれ…不器用な奴だぜ、アポロ…） | 【皮耶尔】（哎呀呀……<br>　真是个不坦率的家伙啊，阿波罗……） | 48 → 57 | +9 | <code>0x1E550</code> → <code>0x1BFF0</code> |

### STAGE 129 · <code>stg_094a.bin</code> · [093] Gain Over

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/129/dialogue/02.02/0095</code> | 对白 | 【$n】「納得…」 | 【$n】“明白了……” | 16 → 18 | +2 | <code>0x8430</code> → <code>0x7630</code> |

### STAGE 130 · <code>stg_094b.bin</code> · [093] Gain Over

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/130/dialogue/01.03/0002</code> | 对白 | 【ガウリ】「御意」 | 【高富利】“遵命。” | 16 → 18 | +2 | <code>0x11380</code> → <code>0x114E0</code> |
| <code>story/130/dialogue/01.98/0000</code> | 对白 | 【$n】「来いや、化け物！<br>　お前が氷の悪魔なら、<br>　俺はザ・ヒート…炎の天使だ！！」 | 【$n】“来吧，怪物！如果你是冰之恶魔，那我就<br>　是THE HEAT……火焰的天使！！” | 80 → 83 | +3 | <code>0x16D40</code> → <code>0x15E70</code> |
| <code>story/130/dialogue/02.01/0025</code> | 对白 | 【アスハム】「え…あ…ああ…」 | 【阿斯哈姆】“呃……啊……啊啊……” | 32 → 34 | +2 | <code>0x17AC0</code> → <code>0x16560</code> |
| <code>story/130/dialogue/02.01/0054</code> | 对白 | 【$n】「ふふ…二度目の大胆告白ね」 | 【$n】“呵呵……第二次大胆告白呢。” | 32 → 34 | +2 | <code>0x181C0</code> → <code>0x16AC0</code> |

### STAGE 131 · <code>stg_095.bin</code> · [094] 扭曲的裁决

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/131/dialogue/01.09/0018</code> | 对白 | 【闘志也】「く…」 | 【斗志也】“唔……” | 16 → 18 | +2 | <code>0x17A30</code> → <code>0x17450</code> |
| <code>story/131/dialogue/01.31/0018</code> | 对白 | 【黒のカリスマ】「その前に全てを…。<br>　さあ始まりの地へ、我々を」 | 【黑之卡里斯马】“在那之前把一切……<br>　好了，带我们去起始之地吧。” | 64 → 65 | +1 | <code>0x1AE50</code> → <code>0x1A210</code> |

### STAGE 132 · <code>stg_096.bin</code> · [095] 灵魂凯歌

5 个超槽 placement，6 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/132/dialogue/01.07/0000</code> | 对白 | 【一太郎】「敵部隊の壊滅を確認！」 | 【一太郎】“确认敌方部队已被歼灭！” | 32 → 34 | +2 | <code>0x14450</code> → <code>0x13F90</code> |
| <code>story/132/dialogue/01.11/0004</code> | 对白 | 【竜馬】「後はグランナイツか！」 | 【龙马】“剩下的就是格兰骑士团了吗！” | 32 → 36 | +4 | <code>0x14900</code> → <code>0x14350</code> |
| <code>story/132/dialogue/01.15/0006</code> | 对白 | 【香月】「勝平…」 | 【香月】“胜平……” | 16 → 18 | +2 | <code>0x15450</code> → <code>0x14BD0</code> |
| <code>story/132/dialogue/02.01/0084</code> | 对白 | 【ルナマリア】「$nさん…身体は…」 | 【露娜玛丽亚】“$n小姐……身体……” | 32 → 34 | +2 | <code>0x18FF0</code> → <code>0x17940</code> |
| <code>story/132/dialogue/02.01/0100</code><br><code>story/132/dialogue/02.01/0184</code> | 对白 | 【ガロード】「見せてくれよ、ザ・クラッシャー」 | 【卡洛德】“让我们见识见识吧，<br>　THE CRUSHER。” | 48 → 57 | +9 | <code>0x193C0</code> → <code>0x17C50</code> |

### STAGE 133 · <code>stg_097a.bin</code> · [096] 永远闪耀吧，我们的星球

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/133/dialogue/01.23/0013</code> | 对白 | 【ミーア】（私の歌…届いて…） | 【米娅】（我的歌声……传达过去吧……） | 32 → 36 | +4 | <code>0xEBE0</code> → <code>0xE5A0</code> |
| <code>story/133/dialogue/01.26/0006</code> | 对白 | 【ミーア】「私の歌が…届いた…」 | 【米娅】“我的歌声……传达过去了……” | 32 → 36 | +4 | <code>0xEE50</code> → <code>0xE7B0</code> |
| <code>story/133/dialogue/02.03/0033</code> | 对白 | 【勝平】「そんな勝手な理屈で<br>　貴様は戦ってきたのかよ！？」 | 【胜平】“你就是凭着这种自说自话的歪理，<br>　一直战斗到现在的吗！？” | 64 → 65 | +1 | <code>0x11A60</code> → <code>0x10B30</code> |

### STAGE 134 · <code>stg_097b.bin</code> · [096] 永远闪耀吧，我们的星球

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/134/dialogue/01.04/0000</code> | 对白 | 【勝平】「う…うう…やめろ…。<br>　やめてくれ…。<br>　怖い…怖いよ…」 | 【胜平】“呜……呜呜……住手……<br>　快住手……好可怕……好可怕啊……” | 64 → 67 | +3 | <code>0x3320</code> → <code>0x3320</code> |
| <code>story/134/dialogue/01.06/0005</code> | 对白 | 【勝平】「こわ…い…怖いよ…」 | 【胜平】“好害……怕……好可怕啊……” | 32 → 36 | +4 | <code>0x3740</code> → <code>0x36A0</code> |

### STAGE 135 · <code>stg_098.bin</code> · [097] 你与我的身影

6 个超槽 placement，9 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/135/dialogue/01.02/0005</code> | 对白 | 【ネオ】「ああ、ここまで来たらな」 | 【尼奥】“啊，既然都走到这一步了。” | 32 → 34 | +2 | <code>0x1BA90</code> → <code>0x1B920</code> |
| <code>story/135/dialogue/01.70/0004</code><br><code>story/135/dialogue/01.72/0005</code> | 对白 | 【レイ】「ならば、俺の敵だ…！<br>　容赦はしない！」 | 【雷】“那你们就是我的敌人……！<br>　我不会手下留情的！” | 48 → 53 | +5 | <code>0x20A90</code> → <code>0x219B0</code> |
| <code>story/135/dialogue/01.114/0014</code> | 对白 | 【キラ】「命は何にだって一つだ！」 | 【基拉】“生命对任何事物来说都只有一个！” | 32 → 40 | +8 | <code>0x24A70</code> → <code>0x1E690</code> |
| <code>story/135/dialogue/02.01/0326</code> | 对白 | 【アムロ】「え…」 | 【阿姆罗】“诶……” | 16 → 18 | +2 | <code>0x2B6B0</code> → <code>0x27E50</code> |
| <code>story/135/dialogue/02.02/0089</code><br><code>story/135/dialogue/02.02/0163</code><br><code>story/135/dialogue/02.02/0186</code> | 对白 | 【キラ】「はい…」 | 【基拉】“是的……” | 16 → 18 | +2 | <code>0x2D180</code> → <code>0x29400</code> |
| <code>story/135/dialogue/02.03/0025</code> | 对白 | 【黒のカリスマ】「フフ…フフフ…」 | 【黑之卡里斯马】“呵呵……呵呵呵……” | 32 → 36 | +4 | <code>0x2DF20</code> → <code>0x29F90</code> |

### STAGE 136 · <code>stg_099a.bin</code> · [098] 终末之光

3 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/136/dialogue/01.08/0014</code> | 对白 | 【マリン】「全てが敵という事か！」 | 【马林】“也就是说，所有人都是敌人吗！” | 32 → 38 | +6 | <code>0x161F0</code> → <code>0x15F30</code> |
| <code>story/136/dialogue/02.01/0046</code> | 对白 | 【シン】（俺…必ず守ってみせる。<br>　仲間達と一緒に、この世界を…） | 【真】（我……一定会守护给你们看。<br>　和伙伴们一起，守护这个世界……） | 64 → 67 | +3 | <code>0x1E310</code> → <code>0x1C700</code> |
| <code>story/136/dialogue/02.02/0010</code> | 对白 | 【アゲハ隊】「大佐、ご武運を…！」 | 【阿盖哈队】“上校，祝您武运昌隆……！” | 32 → 38 | +6 | <code>0x1F420</code> → <code>0x1D540</code> |

### STAGE 137 · <code>stg_099b.bin</code> · [098] 终末之光

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/137/dialogue/01.11/0016</code> | 对白 | 【智翅】「今こそ、生命の樹へ！」 | 【智翅】“就是现在，前往生命之树！” | 32 → 34 | +2 | <code>0x5540</code> → <code>0x5350</code> |

### STAGE 138 · <code>stg_100.bin</code> · [099] 最后之力

10 个超槽 placement，11 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/138/dialogue/01.02/0004</code> | 对白 | 【ネオ】「ああ、ここまで来たらな」 | 【尼奥】“啊，既然都走到这一步了。” | 32 → 34 | +2 | <code>0x1ED50</code> → <code>0x1EB50</code> |
| <code>story/138/dialogue/01.09/0029</code> | 对白 | 【シン】「俺の望む世界…それは…」 | 【真】“我所期望的世界……那是……” | 32 → 34 | +2 | <code>0x203F0</code> → <code>0x1FD90</code> |
| <code>story/138/dialogue/01.72/0000</code> | 对白 | 【闘志也】「熱いな、あいつ…！」 | 【斗志也】“那家伙，真热血啊……！” | 32 → 34 | +2 | <code>0x23AE0</code> → <code>0x26ED0</code> |
| <code>story/138/dialogue/01.72/0001</code> | 对白 | 【甲児】「意外に熱血タイプかもな」 | 【甲儿】“说不定是个意外的热血类型呢” | 32 → 36 | +4 | <code>0x23B00</code> → <code>0x26F00</code> |
| <code>story/138/dialogue/01.137/0014</code><br><code>story/138/dialogue/01.91/0015</code> | 对白 | 【キラ】「命は何にだって一つだ！」 | 【基拉】“生命对任何事物来说都只有一个！” | 32 → 40 | +8 | <code>0x24B80</code> → <code>0x22BD0</code> |
| <code>story/138/dialogue/02.01/0360</code> | 对白 | 【アムロ】「え…」 | 【阿姆罗】“诶……” | 16 → 18 | +2 | <code>0x30AF0</code> → <code>0x2CC40</code> |
| <code>story/138/dialogue/02.02/0061</code> | 对白 | 【キラ】「でも…」 | 【基拉】“但是……” | 16 → 18 | +2 | <code>0x324C0</code> → <code>0x2E0F0</code> |
| <code>story/138/dialogue/02.02/0070</code> | 对白 | 【タリア】「しようのない人ね」 | 【塔丽亚】“真是个拿你没办法的人呢。” | 32 → 36 | +4 | <code>0x325E0</code> → <code>0x2E220</code> |
| <code>story/138/dialogue/02.02/0084</code> | 对白 | 【シン】「…う…うう…あああ…」 | 【真】“……呜……呜呜……啊啊啊……” | 32 → 36 | +4 | <code>0x327F0</code> → <code>0x2E400</code> |
| <code>story/138/dialogue/02.03/0023</code> | 对白 | 【黒のカリスマ】「フフ…フフフ…」 | 【黑之卡里斯马】“呵……呵呵呵……” | 32 → 34 | +2 | <code>0x33480</code> → <code>0x2EE20</code> |

### STAGE 139 · <code>stg_101.bin</code> · [100] 向星辰许愿

4 个超槽 placement，4 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/139/dialogue/01.27/0002</code> | 对白 | 【アネモネ】（…もし、誰も傷つけずに生きていいと<br>　言われたら…） | 【阿尼莫奈】（……如果，<br>　有人告诉我可以不伤害任何人地活下去……） | 64 → 65 | +1 | <code>0x1B0E0</code> → <code>0x1C140</code> |
| <code>story/139/dialogue/01.36/0012</code> | 对白 | 【智翅】「今こそ、生命の樹へ！」 | 【智翅】“就是现在，前往生命之树！” | 32 → 34 | +2 | <code>0x1B9D0</code> → <code>0x1C8B0</code> |
| <code>story/139/dialogue/02.01/0092</code> | 对白 | 【アムロ】「人はわかりあえる…」 | 【阿姆罗】“人是可以互相理解的……” | 32 → 34 | +2 | <code>0x23720</code> → <code>0x21430</code> |
| <code>story/139/dialogue/02.02/0010</code> | 对白 | 【アゲハ隊】「大佐、ご武運を…！」 | 【阿盖哈队】“上校，祝您武运昌隆……！” | 32 → 38 | +6 | <code>0x26230</code> → <code>0x23660</code> |

### STAGE 140 · <code>stg_102.bin</code> · [101] 回忆

2 个超槽 placement，3 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/140/dialogue/01.30/0006</code><br><code>story/140/dialogue/01.38/0006</code> | 对白 | 【アサキム】「源理の力…<br>　オリジン・ロー…」 | 【阿萨基姆】“源理之力……Origin Law……” | 48 → 50 | +2 | <code>0x16220</code> → <code>0x152C0</code> |
| <code>story/140/dialogue/01.30/0007</code> | 对白 | 【$n】「黒のカリスマとアサキム…」 | 【$n】“黑之卡里斯马和阿萨基姆……” | 32 → 34 | +2 | <code>0x16250</code> → <code>0x15300</code> |

### STAGE 141 · <code>stg_103a.bin</code> · [102] 黑色世界

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/141/dialogue/02.01/0251</code> | 对白 | 【シュラン】「熱い男だな、君は」 | 【休兰】“真是个热血的男人啊，你。” | 32 → 34 | +2 | <code>0x9370</code> → <code>0x8290</code> |

### STAGE 142 · <code>stg_103b.bin</code> · [102] 黑色世界

3 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/142/dialogue/01.01/0016</code> | 对白 | 【ツィーネ】（もう…戻れない所まで来ている…。<br>　世界も私も…） | 【兹妮】（已经……走到无法回头的地步了……<br>　无论是世界还是我……） | 64 → 65 | +1 | <code>0xECF0</code> → <code>0xEC00</code> |
| <code>story/142/dialogue/01.17/0008</code><br><code>story/142/dialogue/01.28/0008</code><br><code>story/142/dialogue/01.37/0008</code> | 对白 | 【$n】「違う…！」 | 【$n】“不对……！” | 16 → 18 | +2 | <code>0x11750</code> → <code>0x10DB0</code> |
| <code>story/142/dialogue/01.43/0001</code> | 对白 | 【シリウス】「あの女…全てに絶望して、<br>　可能性と己を殺したか…」 | 【西利乌斯】“那个女人……对一切绝望，<br>　扼杀了可能性和自己吗……” | 64 → 65 | +1 | <code>0x13500</code> → <code>0x12500</code> |

### STAGE 143 · <code>stg_104a.bin</code> · [103] 我的未来，大家的未来

10 个超槽 placement，14 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/143/dialogue/01.07/0002</code> | 对白 | 【$n】「来る…！」 | 【$n】“来了……！” | 16 → 18 | +2 | <code>0x174B0</code> → <code>0x16E00</code> |
| <code>story/143/dialogue/01.16/0012</code> | 对白 | 【桂】「大尉…！」 | 【桂】“上尉……！” | 16 → 18 | +2 | <code>0x18240</code> → <code>0x17960</code> |
| <code>story/143/dialogue/01.23/0003</code> | 对白 | 【ケジナン】「あ〜あ…伯父バカ一直線…」 | 【凯吉南】“啊~啊……真是个彻头彻尾的笨蛋伯父……” | 48 → 50 | +2 | <code>0x19230</code> → <code>0x18600</code> |
| <code>story/143/dialogue/01.34/0009</code> | 对白 | 【アスハム】「フ…シンシア嬢もな」 | 【阿斯哈姆】“哼……辛西亚小姐也是。” | 32 → 36 | +4 | <code>0x1A840</code> → <code>0x197E0</code> |
| <code>story/143/dialogue/01.35/0003</code> | 对白 | 【アネモネ】「えへへ…そうだよね」 | 【阿尼莫奈】“诶嘿嘿……说得也是呢。” | 32 → 36 | +4 | <code>0x1AA80</code> → <code>0x199D0</code> |
| <code>story/143/dialogue/01.57/0004</code> | 对白 | 【クワトロ】「御し難いエゴイズム…！<br>　お前こそが戦いの元凶か！」 | 【克瓦特罗】“难以驾驭的自我中心主义……！<br>　你才是战斗的元凶吗！” | 64 → 65 | +1 | <code>0x1CAB0</code> → <code>0x1B390</code> |
| <code>story/143/dialogue/02.01/0136</code><br><code>story/143/dialogue/02.01/0222</code> | 对白 | 【シャイア】「凄い兵器みたいね」 | 【夏伊亚】“看来是很厉害的兵器呢。” | 32 → 34 | +2 | <code>0x21690</code> → <code>0x1EEE0</code> |
| <code>story/143/dialogue/02.01/0354</code><br><code>story/143/dialogue/02.01/0398</code> | 对白 | 【甲児】「まあ…その…あれだよ…」 | 【甲儿】“嘛……那个……是那个啦……” | 32 → 36 | +4 | <code>0x236A0</code> → <code>0x20820</code> |
| <code>story/143/dialogue/02.01/0663</code><br><code>story/143/dialogue/02.01/0686</code> | 对白 | 【竜馬】「最近、感じるんだ…。<br>　俺以外の俺を…」 | 【龙马】“最近，我感觉得到……<br>　除了我之外的另一个我……” | 48 → 57 | +9 | <code>0x277D0</code> → <code>0x23D70</code> |
| <code>story/143/dialogue/02.01/0768</code><br><code>story/143/dialogue/02.01/0774</code> | 对白 | 【キラ】「でも…」 | 【基拉】“可是……” | 16 → 18 | +2 | <code>0x28BE0</code> → <code>0x24D80</code> |

### STAGE 144 · <code>stg_104b.bin</code> · [103] 我的未来，大家的未来

7 个超槽 placement，7 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/144/dialogue/01.13/0003</code> | 对白 | 【？？？】「…救世の戦士…太極への旅人…<br>　法の守護騎士…因果律の番人…<br>　呪われし放浪者…」 | 【？？？】“……救世的战士……太极的旅人……<br>　法的守护骑士……因果律的看守人……<br>　被诅咒的流浪者……” | 96 → 102 | +6 | <code>0x17D50</code> → <code>0x17940</code> |
| <code>story/144/dialogue/01.29/0000</code> | 对白 | 【$n】「駄目…！」 | 【$n】“不行……！” | 16 → 18 | +2 | <code>0x1CFB0</code> → <code>0x1BB90</code> |
| <code>story/144/dialogue/01.38/0004</code> | 对白 | 【アポロ】「そうか…アポロニアス…。<br>　このアクエリオンの匂い…<br>　堕天翅と…頭翅の奴らと同じ…」 | 【阿波罗】“原来如此……阿波罗尼亚斯……<br>　这个亚库艾里翁的气味……<br>　和堕天翅……还有头翅他们一样……” | 96 → 102 | +6 | <code>0x1D4C0</code> → <code>0x1BFF0</code> |
| <code>story/144/dialogue/01.39/0011</code> | 对白 | 【竜馬】「堕天翅と人の間も…か？」 | 【龙马】“堕天翅和人之间……也是吗？” | 32 → 36 | +4 | <code>0x1DAB0</code> → <code>0x1C540</code> |
| <code>story/144/dialogue/01.43/0003</code> | 对白 | 【シリウス】「今のアクエリオンなら…<br>　真の太陽の翼なら出来る！」 | 【西利乌斯】“现在的亚库艾里翁的话……<br>　真正的太阳之翼的话就能做到！” | 64 → 69 | +5 | <code>0x1E440</code> → <code>0x1CDB0</code> |
| <code>story/144/dialogue/02.01/0012</code> | 对白 | 【エウレカ】「でも…失敗したら…」 | 【优莱卡】“但是……如果失败了……” | 32 → 34 | +2 | <code>0x24E70</code> → <code>0x21DD0</code> |
| <code>story/144/dialogue/02.02/0015</code> | 对白 | 【レントン】「うん…俺達の星に…」 | 【兰顿】“嗯……回到我们的星球……” | 32 → 34 | +2 | <code>0x25710</code> → <code>0x224F0</code> |

### STAGE 145 · <code>stg_104c.bin</code> · [103] 我的未来，大家的未来

4 个超槽 placement，5 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/145/dialogue/01.09/0001</code> | 对白 | 【$n】「私の願う未来…それは…」 | 【$n】“我所期望的未来……那就是……” | 32 → 36 | +4 | <code>0x11AA0</code> → <code>0x116B0</code> |
| <code>story/145/dialogue/02.01/1296</code> | 对白 | 【勝平】「香月…」 | 【胜平】“香月……” | 16 → 18 | +2 | <code>0x181C0</code> → <code>0x16910</code> |
| <code>story/145/dialogue/02.01/1317</code> | 对白 | 【勝平】（アキ…俺達、戦ってくよ。<br>　本当の平和が訪れる日まで…） | 【胜平】（亚纪……我们会继续战斗下去。<br>　直到真正的和平到来那天……） | 64 → 67 | +3 | <code>0x18680</code> → <code>0x16D30</code> |
| <code>story/145/dialogue/02.01/1373</code><br><code>story/145/dialogue/02.01/1382</code> | 对白 | 【$n】（これが…私の望んだ世界…） | 【$n】（这就是……我所期望的世界……） | 32 → 36 | +4 | <code>0x18B50</code> → <code>0x17150</code> |

### STAGE 146 · <code>stg_105a.bin</code> · [104] 被涂抹的明天

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/146/dialogue/02.01/0251</code> | 对白 | 【シュラン】「熱い男だな、君は」 | 【休兰】“真是个热血的男人啊，你。” | 32 → 34 | +2 | <code>0x8D00</code> → <code>0x7BF0</code> |

### STAGE 147 · <code>stg_105b.bin</code> · [104] 被涂抹的明天

5 个超槽 placement，8 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/147/dialogue/01.01/0016</code> | 对白 | 【ツィーネ】（もう…戻れない所まで来ている…。<br>　世界も私も…） | 【兹妮】（已经……走到无法回头的地步了……<br>　世界也好，我也好……） | 64 → 65 | +1 | <code>0xF4F0</code> → <code>0xF400</code> |
| <code>story/147/dialogue/01.06/0000</code> | 对白 | 【$n】「頼むぜ、ジイさん…。<br>　こうなりゃ皿ごと毒も食うまでだ」 | 【$n】“拜托了，老爷子……既然这样，<br>　就算是毒药也得连盘子一起吞下去。” | 64 → 71 | +7 | <code>0x110E0</code> → <code>0x10A00</code> |
| <code>story/147/dialogue/01.07/0010</code> | 对白 | 【$n】「姐さん…」 | 【$n】“大姐头……” | 16 → 18 | +2 | <code>0x11380</code> → <code>0x10C20</code> |
| <code>story/147/dialogue/01.11/0001</code><br><code>story/147/dialogue/01.12/0001</code><br><code>story/147/dialogue/01.13/0011</code><br><code>story/147/dialogue/01.15/0001</code> | 对白 | 【$n】（ま…どうなろうと俺は修理屋だ。<br>　どんな世界になろうと、物を直して<br>　生きてくだけだ） | 【$n】（嘛……不管变成什么样，<br>　我都是个修理工。无论世界变成什么样，<br>　我只要修东西活下去就行了。） | 96 → 98 | +2 | <code>0x11B50</code> → <code>0x11250</code> |
| <code>story/147/dialogue/01.43/0001</code> | 对白 | 【シリウス】「あの女…全てに絶望して、<br>　可能性と己を殺したか…」 | 【西利乌斯】“那个女人……对一切绝望，<br>　扼杀了可能性和自己吗……” | 64 → 65 | +1 | <code>0x13E90</code> → <code>0x12E10</code> |

### STAGE 148 · <code>stg_106a.bin</code> · [105] 我的未来，你的未来

5 个超槽 placement，7 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/148/dialogue/01.16/0012</code> | 对白 | 【桂】「大尉…！」 | 【桂】“上尉……！” | 16 → 18 | +2 | <code>0x19DB0</code> → <code>0x19300</code> |
| <code>story/148/dialogue/01.37/0009</code> | 对白 | 【アスハム】「フ…シンシア嬢もな」 | 【阿斯哈姆】“哼……辛西亚小姐也是。” | 32 → 36 | +4 | <code>0x1CA20</code> → <code>0x1B6A0</code> |
| <code>story/148/dialogue/01.40/0003</code> | 对白 | 【アネモネ】「えへへ…そうだよね」 | 【阿尼莫奈】“诶嘿嘿……说得也是呢。” | 32 → 36 | +4 | <code>0x1CDA0</code> → <code>0x1B970</code> |
| <code>story/148/dialogue/02.01/0136</code><br><code>story/148/dialogue/02.01/0225</code> | 对白 | 【シャイア】「凄い兵器みたいね」 | 【夏伊亚】“看来是很厉害的兵器呢。” | 32 → 34 | +2 | <code>0x23A50</code> → <code>0x20D70</code> |
| <code>story/148/dialogue/02.01/0775</code><br><code>story/148/dialogue/02.01/0784</code> | 对白 | 【キラ】「でも…」 | 【基拉】“但是……” | 16 → 18 | +2 | <code>0x2B350</code> → <code>0x26C00</code> |

### STAGE 149 · <code>stg_106b.bin</code> · [105] 我的未来，你的未来

9 个超槽 placement，9 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/149/dialogue/01.10/0003</code> | 对白 | 【？？？】「…救世の戦士…太極への旅人…<br>　法の守護騎士…因果律の番人…<br>　呪われし放浪者…」 | 【？？？】“……救世的战士……太极的旅人……<br>　法则的守护骑士……因果律的看守……<br>　被诅咒的流浪者……” | 96 → 102 | +6 | <code>0x1F880</code> → <code>0x1F460</code> |
| <code>story/149/dialogue/01.28/0000</code> | 对白 | 【ジ・エーデル】「さすがはボク！<br>　サンキュー・ベリーマッチョ！」 | 【极·艾岱尔】“不愧是我！Thank <br>　you very much！” | 64 → 69 | +5 | <code>0x236B0</code> → <code>0x27000</code> |
| <code>story/149/dialogue/01.49/0004</code> | 对白 | 【アポロ】「そうか…アポロニアス…。<br>　このアクエリオンの匂い…<br>　堕天翅と…頭翅の奴らと同じ…」 | 【阿波罗】“原来如此……阿波罗尼亚斯……<br>　这台亚库艾里翁的气味……<br>　和堕天翅……头翅那些家伙一样……” | 96 → 102 | +6 | <code>0x26400</code> → <code>0x29420</code> |
| <code>story/149/dialogue/01.50/0011</code> | 对白 | 【竜馬】「堕天翅と人の間も…か？」 | 【龙马】“堕天翅和人之间……也是吗？” | 32 → 36 | +4 | <code>0x26A00</code> → <code>0x29960</code> |
| <code>story/149/dialogue/01.51/0027</code> | 对白 | 【アポロ】「全ての命の痛みも…」 | 【阿波罗】“所有生命的痛苦也是……” | 32 → 34 | +2 | <code>0x27220</code> → <code>0x2A070</code> |
| <code>story/149/dialogue/01.54/0003</code> | 对白 | 【シリウス】「今のアクエリオンなら…<br>　真の太陽の翼なら出来る！」 | 【西利乌斯】“现在的亚库艾里翁的话……<br>　真正的太阳之翼的话就能做到！” | 64 → 69 | +5 | <code>0x27390</code> → <code>0x2A1B0</code> |
| <code>story/149/dialogue/01.65/0001</code> | 对白 | 【アサキム】「…別れの時が来た、ツィーネ。<br>　そして、ザ・ヒート」 | 【阿萨基姆】“……离别的时候到了，兹妮。<br>　还有，THE HEAT。” | 64 → 67 | +3 | <code>0x27EC0</code> → <code>0x2AAB0</code> |
| <code>story/149/dialogue/02.01/0012</code> | 对白 | 【エウレカ】「でも…失敗したら…」 | 【优莱卡】“但是……要是失败的话……” | 32 → 36 | +4 | <code>0x2E650</code> → <code>0x2AE90</code> |
| <code>story/149/dialogue/02.02/0015</code> | 对白 | 【レントン】「うん…俺達の星に…」 | 【兰顿】“嗯……回到我们的星球……” | 32 → 34 | +2 | <code>0x2EED0</code> → <code>0x2B5E0</code> |

### STAGE 150 · <code>stg_106c.bin</code> · [105] 我的未来，你的未来

7 个超槽 placement，18 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/150/dialogue/02.01/0068</code><br><code>story/150/dialogue/02.01/0093</code><br><code>story/150/dialogue/02.01/0451</code><br><code>story/150/dialogue/02.01/0477</code><br><code>story/150/dialogue/02.01/0856</code><br><code>story/150/dialogue/02.01/0882</code> | 对白 | 【アスラン】「言わないのか？<br>　綺麗事はアスハのお家芸だな…って」 | 【阿斯兰】“你不说吗？‘说漂亮话是阿斯哈<br>　家的拿手好戏’什么的……” | 64 → 67 | +3 | <code>0x13730</code> → <code>0x130C0</code> |
| <code>story/150/dialogue/02.01/0366</code><br><code>story/150/dialogue/02.01/0757</code><br><code>story/150/dialogue/02.01/1150</code><br><code>story/150/dialogue/02.01/1422</code><br><code>story/150/dialogue/02.01/1441</code> | 对白 | 【ゲイン】「気張れよ、ザ・ヒート」 | 【该隐】“加油啊，THE HEAT。” | 32 → 36 | +4 | <code>0x16DB0</code> → <code>0x15C70</code> |
| <code>story/150/dialogue/02.01/0380</code><br><code>story/150/dialogue/02.01/0771</code><br><code>story/150/dialogue/02.01/1164</code> | 对白 | 【$n】「か…か…」 | 【$n】“根……根……” | 16 → 20 | +4 | <code>0x170F0</code> → <code>0x15F60</code> |
| <code>story/150/dialogue/02.01/0788</code> | 对白 | 【闘志也】「多元世界の状態で世界は固まったのか…」 | 【斗志也】“世界是以多元世界的状态固定下来的吗……” | 48 → 50 | +2 | <code>0x17D80</code> → <code>0x169D0</code> |
| <code>story/150/dialogue/02.01/1199</code> | 对白 | 【甲児】「大介さん…また会える日を祈ってるぜ」 | 【甲儿】“大介先生……<br>　我祈祷着能再见到你的那一天。” | 48 → 53 | +5 | <code>0x187F0</code> → <code>0x17290</code> |
| <code>story/150/dialogue/02.01/1269</code> | 对白 | 【勝平】「香月…」 | 【胜平】“香月……” | 16 → 18 | +2 | <code>0x18CE0</code> → <code>0x176D0</code> |
| <code>story/150/dialogue/02.01/1290</code> | 对白 | 【勝平】（アキ…俺達、戦ってくよ。<br>　本当の平和が訪れる日まで…） | 【胜平】（亚纪……我们会继续战斗下去。<br>　直到真正的和平降临的那一天……） | 64 → 71 | +7 | <code>0x191A0</code> → <code>0x17AF0</code> |

### STAGE 151 · <code>stg_107a.bin</code> · [106] 迈向无尽战争之环

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/151/dialogue/01.07/0002</code> | 对白 | 【$n】「来る…！」 | 【$n】“来了……！” | 16 → 18 | +2 | <code>0xA000</code> → <code>0x9AA0</code> |

### STAGE 153 · <code>stg_107c.bin</code> · [106] 迈向无尽战争之环

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/153/dialogue/01.05/0001</code> | 对白 | 【アムロ】「今の俺達では…もう…」 | 【阿姆罗】“以我们现在的力量……已经……” | 32 → 40 | +8 | <code>0x3230</code> → <code>0x30F0</code> |

### STAGE 154 · <code>stg_400.bin</code> · 非章节公共／特殊段（无 Stage Name 标题）

1 个超槽 placement，1 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/154/dialogue/00.01/0288</code> | 对白 | 【不動】「時に早乙女研究所は？」 | 【不动】“对了，早乙女研究所那边怎么样？” | 32 → 40 | +8 | <code>0x8150</code> → <code>0x7120</code> |

### STAGE 160 · <code>stg_406.bin</code> · 非章节公共／特殊段（无 Stage Name 标题）

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/160/dialogue/00.01/0007</code> | 对白 | 【タルホ】「ったく！<br>　あのガキ…どこまで面倒かけてくれるのよ！」 | 【塔尔荷】“真是的！那小子……<br>　到底要给我们添多少麻烦才甘心啊！” | 64 → 65 | +1 | <code>0x19E0</code> → <code>0x19B0</code> |
| <code>story/160/dialogue/00.01/0101</code> | 对白 | 【デューイ】「それでも嫌か？」 | 【杜威】“即便如此，你也不愿意吗？” | 32 → 34 | +2 | <code>0x3120</code> → <code>0x2C00</code> |

### STAGE 185 · <code>stg_500.bin</code> · [117] 教学关卡

2 个超槽 placement，2 个物理记录。

| 稳定 ID | 类型 | 日文原文 | 当前中文 | 原槽 → payload | 超出 | 原地址 → 新地址 |
| --- | --- | --- | --- | ---: | ---: | --- |
| <code>story/185/dialogue/01.28/0007</code> | 对白 | 【$n】「セレクト…これですね」 | 【$n】“SELECT……是这个吧。” | 32 → 34 | +2 | <code>0xA870</code> → <code>0x98E0</code> |
| <code>story/185/dialogue/02.01/0052</code> | 对白 | 【$n】「では…？」 | 【$n】“那么……？” | 16 → 18 | +2 | <code>0xC670</code> → <code>0xADD0</code> |

## 更新与验证边界

- 本快照绑定报告 SHA-256：<code>e4c98be95d2e70197322638e334c181d08ce23b54205b5daf1cacbdade26ed96</code>。
- 当前报告状态：<code>offline_components_validated_runtime_not_tested</code>；同值地址 ownership 完整性：<code>true</code>。
- 语料、说话人、编码分配或 writer 改动后，应重新构建并同步更新本清单；
  不能只手改统计数或地址。
- 本文证明的是静态 parser／重排／回读事实，不等于所有关卡已经完成 PCSX2
  或人工画面验收。

<!-- END GENERATED SNAPSHOT -->
