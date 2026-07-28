# 语料约定

`ja/` 保存从固定原版提取并经哈希确认的日文基准；不得人工改写。

`zh/` 保存中文译文。每条译文至少记录稳定 ID、日文原文哈希、中文、编辑
状态、术语引用和备注；来源文件、分区、指针及日文正文只从本地固定日文语料
连接，不在 Git 中重复保存。

`glossary/` 独立保存日文术语、简体中文 canonical 译名、分类、审核状态和
适用域。正式译文通过 `glossary_refs` 显式引用词条，避免只靠全文搜索推测
使用了哪项术语决策。若分片文本因中日语序不同，术语只能落在运行时拼接的
另一片段，可用 `glossary_exceptions` 显式登记；审核器仍要求该术语确实出现
于原文，并把例外单列到人工审核表，不能用来静默跳过术语决定。
词条默认按 `substring` 匹配；精神指令等短词可用 `token`，只匹配整条原文
或日文引号中的完整名称，避免“愛”误命中“愛称”一类复合词。

专有名词按“官方简中译名、可靠中文社区共识、自然中文本地化”的顺序取证。
若没有官方译名或稳定社区共识，字面直译又会让人物、地点或设施名看起来像
术语、错字或说明文字，则优先采用易读、可辨认且尽量贴近原音的专名音译；
字面原义、外文拼写、检索到的社区写法和无共识边界必须保留在词条备注中。
这类候选不得仅凭机器检索冒充定名，应进入人工复核；人工确认后再统一正文、
简称、词表与测试。后续翻译遇到同类歧义时可以暂停自动定名，由人工给出最终
用字。

`fixtures/` 只保存验证 writer、字体和运行路径的技术文本，不属于翻译语料；
`releases/` 固定一个语料版本选择的译文文件、术语文件和日文基准聚合哈希。

`reference/` 保存用户指定的外部名称基准快照及其哈希锁。当前
`gundam-roster-names.tsv` 来自相邻 `sdgundam` 工作区此前依据 Biligame
高达资料整理的名单，只适用于高达系人物和机体，不覆盖《古连泰沙》、
《赞波特3》等参战作品或《机战Z》原创角色／机体。该表默认只用于核对和生成
人工审核项，不会凭日文短串自动改写译文；`ネオ`、`シン`、`カオス` 等歧义
名称必须先确认角色或机体身份。

旧 TSV 不是 Biligame 全站名单。完整补抓从 Biligame“分类:人物”入口进入，
覆盖 SRWZ 的《Z 高达》《SEED》《SEED DESTINY》《高达 X》和《∀高达》
5 张人物页、全机体索引及当前前五关所需详情页；原始 Markdown 只保存在
`work/review/sources/biligame/`，页面 URL、数量和聚合哈希固定在
`reference/biligame-srwz-gundam.lock.json`。离线重建结构化审核索引：

```bash
python3 tools/build_biligame_gundam_reference.py
```

当前索引含 344 个唯一人物页面和 3,023 个有效机体页面链接。Biligame 是社区
WIKI 而非官方资料，且已发现“伊恩·李”外文字段误填、盖亚／盖娅字段内部不一致；
因此页面标题、日文名、作品归属和正文身份必须分层核对，不能整页无条件采信。

当前日文基准通过：

```bash
python3 tools/export_srwz_corpus.py --force
```

导出到被 Git 忽略的 `work/corpus/srwz-corpus.jsonl`。它包含 94,189 条日文
原文，不进入 Git；`manifests/corpus-export.json` 只保存计数和聚合哈希。
`corpus/zh/` 后续只提交中文、稳定 ID、source text SHA-256、状态和备注，不重复
提交提取的日文正文。导出过程还会严格序列化并重新解码全部条目，当前结果为
94,189/94,189。

v1 当前已有八个完整首译批次，另有五个 UI 图片标签切片；剧情正文批次已开始
逐关推进：

- `zh/ui-atlas/info-v1.json`：信息页图集首个受审标签 `SHIP → 机体`。它以
  图集定位串的哈希为源前像，并引用既有菜单语义记录；具体字体、mask、调色板
  和输出锁由 `config/assets/ui-info-atlas-zh.json` 所有。静态候选不等于
  已证明运行场景归属。
- `zh/ui-atlas/core-menus-v1.json`：战场、商店、幕间和编成图集的四个受审
  标签，分别由四个 `config/assets/ui-*-atlas-zh.json` profile 锁定字体、
  mask、调色板和输出。语料只拥有翻译决定，旧擦除 canary 仍拥有定位前像；
  四张静态候选同样不等于已证明运行场景归属。
- `zh/summary.json`：28/28 条世界历史摘要；
- `zh/menu/system-ui-*.json`：903/903 条菜单与系统 UI；
- `zh/menu/stage-names.json`：122/122 条关卡标题、路线标签和内部测试标题；
- `zh/menu/weapons.json`：711/711 条武器名称，每条均引用
  `glossary/weapons-v1.json` 中独立、可审批的 canonical 译名；
- `zh/menu/unclassified.json`：382/382 条原上游未分类菜单文本，其中 314 条
  翻译、68 条控制／占位片段显式 `preserve`。
- `zh/menu/battle-lines.json`：297/297 条战斗退场台词；逐条保持原换行数量，
  人名、舰名、组织和作品专有称呼另见 `glossary/battle-lines-v1.json`。
- `zh/story-conditions.json`：558/558 条胜利、败北和 SR 条件，来自 241 个
  唯一原文模板；重复模板保持同译，相关规则词、人物、机体和组织另见
  `glossary/story-conditions-v1.json`。24 条 `？？？` 和 3 条动态冒号占位
  均显式保留并附审核备注。
- `zh/story-speakers.json`：8,469/8,469 条剧情说话人记录，覆盖 425 个唯一
  显示串；7,931 条人物／身份名称完成首译，538 条空白、全角空格、玩家名
  `$n` 或 `？？？` 槽位按原样显式保留。既有 80 个精确人物术语优先复用，
  其余 340 个名称和身份标签独立登记在
  `glossary/story-speakers-v1.json`，其中同名 `ジュン` 等歧义项已列为
  人工重点复核，不把音译初稿冒充最终定名。
- `zh/story-dialogue/stage-001.json`：第 001 关 312/312 条剧情正文已逐句
  对照日文上下文完成二校并提升为 `reviewed`，覆盖 288 个唯一句；中文布局为
  207 条单行、105 条双行；`$n/$F` 玩家名、`●/●●` 原文遮蔽和 11 条纯标点演出均有自动
  门禁。23 个新增地名、组织、人物、机体和原创武装
  独立登记在 `glossary/story-dialogue-stage-001-v1.json`；其中
  “卢特提姆基地”已在核对 Lutetium 字面义、英文资料和中文社区无统一译名
  的边界后，由人工确认采用自然专名音译并提升为 `researched`，
  “加纳利·卡弗”及简称仍列为人工重点复核；Shoe Fitter、The Right
  Stuff 和 GS Combat Action 已结合试飞语境复核，其中后者由不自然的
  “GS战斗行动”修订为原文定义更明确的“GS战斗术”。整个 82,719 条正文批次仍为
  `in_progress`，不能把首关完成写成全剧情完成。
- `zh/story-dialogue/stage-002.json`：第 002 关 542/542 条剧情正文已逐句
  对照日文上下文完成二校并提升为 `reviewed`，覆盖 321 个唯一句；同一原文
  在本关内保持同一译法，中文布局为 445 条单行、96 条双行和 1 条三行选择项，
  10 次 `$n` 占位全部锁定，16 条七点省略号
  演出显式规范为中文双省略号。46 个新增场景、世界观、人物和机体术语独立登记在
  `glossary/story-dialogue-stage-002-v1.json`。本轮按设备实际为
  Silhouette Hangar 而非外置挂架，将“剪影挂架”修订为“剪影机库”；
  “公共频道”“未知机体”“星2号／星3号”和“幸运色狼”也已逐条核对使用语境，
  本关 46 项术语均标为 `researched`。
- `zh/story-dialogue/stage-003.json`：第 003 关 36/36 条剧情正文首译，
  已逐句对照日文上下文完成二校并提升为 `reviewed`；全部为唯一句，中文布局为
  29 条单行、7 条双行，唯一一条纯标点演出显式规范为中文双省略号。
  复用既有 ZAFT、密涅瓦、Extended 等 canonical 术语，并在
  `glossary/story-dialogue-stage-003-v1.json` 中新增“地球联合”短称、
  尼奥·罗安那克、Bogey One、红色警戒和亚瑟·托莱恩 5 项决定；两处
  Condition Red 均由舰桥发布并要求全员就位，已按功能统一为“红色警戒”。
- `zh/story-dialogue/stage-004.json`：第 004 关 523/523 条剧情正文已逐句
  对照日文上下文完成二校并提升为 `reviewed`，覆盖 469 个唯一句；中文布局为
  394 条单行、127 条双行和 2 条三行；`$n/$F` 玩家名结构和 30 次纯标点演出均有自动门禁。本关完成
  SEED DESTINY 与《Z 高达》世界线首次正面
  汇合，新增 19 项独立术语，包括 BLOCK WORD、轰击型剪影、胸部／腿部
  飞行器、ZAFT 红衣、白色基地、阿克西斯、格里普斯、Mk-II 短称、MA、
  短剑系和“平行世界”。审校器另显式记录 33 次跨语境例外：其中 25 次是
  “ターン”误命中“ティターンズ”的片假名子串，3 次是数值术语“伤害”
  与舰体受损叙事的区别，另有 4 次“未知机体”与未知目标／部队／整舰语境的差异及
  1 次数值“回避”与普通动词的区别，不能为了消除机器告警而破坏自然中文。
- `zh/story-dialogue/stage-005.json`：第 005 关 298/298 条剧情正文已逐句
  对照日文上下文完成二校并提升为 `reviewed`，覆盖 280 个唯一句；中文布局为
  190 条单行、107 条双行和 1 条三行；9 条纯标点／未知场景演出、`$F` 玩家名和 6 次黑屏指令均有
  自动门禁。本关汇合《古连泰沙》、
  《无敌超人赞波特3》、SEED 与《Z 高达》世界线，新增 18 项独立术语，
  包括古连泰沙、杜克·弗里德、骷髅月基地、MidiFO、蕾蒂·甘达尔、
  第二次雅金·杜威攻防战、PLANT 评议会议长、藤泽、骏河湾和多米拉。
  “古连泰沙”和“弗里德星”已依据 Level-5 官方简中联动页提升为
  `researched`；“杜克·弗里德”“骷髅月基地”“蕾蒂·甘达尔”“圆盘兽”
  “维加兽”和“多米拉”也已分别用东映、Grendizer U 与《赞波特3》一手页面
  核对原名和设定，明确标为 `researched`，同时在备注中保留“尚无直接官方
  简中全名”的边界。“托比·沃森”也已核对 Toby Watson 原名及前四关短称，
  当前仅 MidiFO 仍为 `proposed`。官方
  设定与 Gundam 简中依据记录在本关术语表，方便逐项人工复核。前五关合计
  1,711/1,711 条记录、按关内去重的 1,394 个译文决定（跨关再去重为
  1,359 段原文）均已逐句二校并提升为
  `reviewed`；整个正文批次完成 1,711/82,719 条，仍有 81,008 条正文待译。

武器词条使用原表中的精确名称作为 `token`，但不做全菜单自动强制匹配：
“格斗”“剑”“光子垫”等短武器名也会合法出现在按钮、能力说明或普通句子中，
若全局强制会产生伪命中。武器记录本身必须显式引用一条同序号
`weapon/NNNN` 词条；其中出现的新人类、百鬼、射程、变形等跨域既有术语仍
照常强制引用。

关卡标题的 `0000..0121` 稳定 ID 保留 `COMPDATA` 原表顺序，但这不等于单线
游玩顺序：`0107..0115` 是路线选择标签，`0116..0121` 包含隐藏、教学和内部
测试记录。人工整理章节路线时必须保留这一区分，不能把 122 条直接编号成
“第 1～122 话”。

生成一份包含批次 ID、日文原文、译文、状态、术语引用、显式术语例外和备注的
全量译文 TSV，一份包含 canonical 译名、审核状态、引用／例外次数和异译说明
的全量术语 TSV，一份把 8,469 条说话人按 425 个唯一显示名聚合的专项 TSV，
以及一份把当前剧情正文按唯一原文／译文决定聚合并附出现次数、首末稳定 ID
的专项 TSV。当前前五关里新增的 112 项术语另生成优先审核表：3 项
`proposed` 和 1 项有意语境异译排在最前；65 条含显式术语例外的记录则生成带说话人、
日文上下文、译文和逐条理由的独立审核表。另将官方简中
《SEED DESTINY》角色页与项目当前口径不同的 9 组前五关用名写入
`review/first-five-official-variants-v1.json`。用户指定 Biligame 为本切片
高达名称口径后，其中 4 组已显式记为保留当前口径，另 5 组仍待人工决定。
对应迁移记录见 `review/first-five-gundam-roster-variants-v1.json`；该表只
覆盖高达人物和机体，不能拿来决定其他参战作品或《机战Z》原创专名：

```bash
python3 tools/review_srwz_translations.py
python3 tools/reflow_first_five_dialogue.py --force
python3 tools/audit_first_five_language_quality.py --force
python3 tools/audit_first_five_upstream_english.py --force
```

七份审核表和统计写入被 Git 忽略的 `work/review/`。当前正文专项表为
`work/review/srwz-story-dialogue-v1.tsv`，第 001～005 关合计 1,711 次出现；
前五关术语重点表和例外表分别为
`work/review/srwz-story-dialogue-milestone-terms.tsv` 与
`work/review/srwz-story-dialogue-milestone-exceptions.tsv`；官方简中异名
选择表为 `work/review/srwz-first-five-official-variants.tsv`。日文正文
不会被提交。

前五关语言质量审计另写入
`work/review/first-five-language-quality.json` 和
`work/review/first-five-language-quality-findings.tsv`。它将假名残留、
结构占位符漂移、引号／括号不平衡、混合标点、超过 24 字符或 3 行的显示串、
标点禁则错误，以及
没有“跨关同源”说明的同源异译视为硬错误。当前 1,711 条正文硬错误为 0；
4 组语气词／省略句共 14 次语境异译均有显式说明。该机械门不替代人物口吻和
剧情连贯性的人工逐句复核。

固定上游 `001.xml`～`005.xml` 的 `EnglishText` 当前全部为空，因此不能声称
前五关已有直接英语逐句对照。英语参考审计会在全部上游剧情 XML 中按日文原文
精确查找复用句，只把命中的其他关卡译文列作语义提示；说话人、受话人、语气和
肯否仍须回到本关上下文判断，绝不自动覆盖中文。

逐关翻译前，可先导出带已译说话人、原文哈希和既有译文状态的完整上下文表：

```bash
python3 tools/export_story_dialogue_stage_review.py --stage 2
```

人工填写被忽略的 unique draft 并建立本关增量术语表后，可用确定性构建器展开
全部重复出现、自动引用强制术语并在写入前执行完整翻译审计：

```bash
python3 tools/build_story_dialogue_stage_translation.py \
  --stage 2 \
  --additional-glossary corpus/glossary/story-dialogue-stage-002-v1.json
```

构建器不会生成译文；它只把人工决策展开到稳定 ID，并拒绝唯一句缺失、
空译文、结构 token 变化、术语 canonical 缺失和未登记例外。日文原行数
不再是中文译文的约束；中文布局由独立重排和审计门负责。
该命令检查：

1. v1 固定的 94,189 条日文基准聚合哈希；
2. 每条译文的稳定 ID 和 `source_text_sha256`；
3. 日文假名残留和不规范省略号；
4. 原始字节、控制标签、`%s`、`$n/$F` 和黑圆点遮蔽等结构占位符是否原样
   保留；
5. 强制术语是否引用、是否确实出现在原文、译文是否使用 canonical 形式；
6. 显式术语例外是否有效、是否与正常引用冲突；
7. 全部译文与术语记录是否唯一；
8. 标成 `*_complete` 的批次是否恰好达到 release 中声明的目标条数。

技术 canary 由 `config/build-profiles/canary-*.json` 选择
`fixtures/*-canary.json`。可执行其生产路径 reconciliation：

```bash
python3 tools/validate_build_profile.py
```

该门会把 fixture 记录与 SurfaceSpec 的稳定 ID/source hash 对齐，并检查状态、
codebook、可编码性和定长要求。`zh/` 中出现第二份 `source_text` 会直接失败。

推荐状态：

```text
todo -> draft -> reviewed -> final
```

运行验证是独立证据，不是编辑状态；修改字体、writer 或 ISO 后不能把旧的
PCSX2 截图自动继承为新的文本审核结论。

字段和写回验证规则见 `docs/PRODUCTION_PIPELINE.md` 和
`docs/WRITEBACK_CONTRACT.md`。
