# 待办汇总

2026-11-23 起，所有计划、路线图和待办都只记在这里，原来分散的计划文档已删除。原文可用 `git show eb9c1f90:docs/<文件名>` 查看；未入库的计划和交接文档另有本机备份。

每条都已对照 2026-11-23 的仓库现状核过：完成或被取代的不再列出；标「待确认」的是没找到完成证据、也没法确定是否仍需要做。做完一条就删掉；需要长期保留的技术结论写进相应技术文档或 `docs/TECHNICAL_FINDINGS.md`。

## 三语版本（简体／台湾／香港）

### 三语言独立版本改造（来源：`docs/ZH_THREE_EDITIONS_PLAN_20261121.md`，2026-11-21）
- [ ] 阶段 5 收尾：SP 图像链仍按简体配置封存，最后一步才装入繁体字格（`tools/zh_hant/build_dual_sp.py` 的 `SP_KEEP_SC`、`sp_images_stay_sc`）；按繁体重新封存 7 个配置（结算标签、DATA HELP 項目、菜单还原、清晰度字格、帮助标题、覆盖区、战斗 SELECT）
- [ ] 繁体构建里仍靠 `traditional_build()` 放行的前像检查改为按本语言基线比对：`name_unification`、`terrain_names`、`qa_native`、`library_work_titles`、`instruction_overrides`
- [ ] 台湾语料残留旧名「奧布」：`corpus/zh-hant/story-speakers.json`（`story/109/speaker/035` 奧布士兵）、`corpus/zh-hant/special-disc/system-text.json`（奧布士兵（1）（2）…）、奧布保衛戰等约 14 处；`regional-names.json` 定台湾为「歐普士兵」（apply=true）。香港侧也要核对
- [ ] 上盘文字中原来经字面量映射得来的部分（SP 数据链接页、名场面菜单、移动类型/武器类别标签）是否已全部改为直接读本语言语料；`expected_literal` 仍在 `movement_type_labels.py`、`weapon_category_labels.py` 等处使用（待确认）
- [ ] 繁体 SP 仍以简体 SP 九月基线组件为起点、`sp-translated-ranges.json` 决定翻译位置；是否要按语言重跑九月基线流程（工作量大，待确认是否要做）
约束：
- 不用 OpenCC：三份语料、三份术语表均为静态文件，人工维护；构建、检查、作图都不做简→繁转换，工具只检查（`sync_corpus.py`、`port_sc_changes.py`、`preflight.py`）
- 港台共用一套繁体图片和一套繁体码表/字形表；香港 10 个图片文字文件用台湾的（`config/zh-hant/hk-uses-taiwan.json`）
- 每步完成的验收：三张盘构建、预检、读回全过，运行器里三种语言各看一遍，简体盘字节不变

### 繁体港台区分（来源：`docs/ZH_HANT_HK_TW_PLAN_20261118.md`，2026-11-18）
- [ ] 修人名音译「里」被转成「裡/裏」：台湾 弗裡克 61、弗裡德(星) 69、艾裡克 11、裡克 若干；香港 弗裏克 61、弗裏德 12、艾裏克 11（`regional-names.json` 未覆盖，需逐条区分人名与「裡/裏」本义，裡克·迪亞斯 等机体名另判）
- [ ] 约 100 条搁置的港台译名（单字名、拉丁字母名、并名等，清单在 `work/analysis/zh-hk-tw-names-20261119/apply-held.md`）待用户逐条定
- [ ] 香港模式下剧情、战斗台词实机通读
- [ ] BEST 独有关卡与战斗台词、章节间幕、教学标题、援护提示在台/港模式下实机验证
- [ ] 音乐包在本篇/BEST 三合一盘上的兼容性实测
- [ ] Windows 构建障碍：`tools/build_editions.py`、`tools/srwz/file_identity.py` 用 `fcntl`；`tools/zh_hant/sp_tc_baseline.py` 用符号链接指向答案目录；仓库 `rom` 是符号链接
- [ ] 提速：`sp_tc_baseline.return_compdata_strings` 在缓存未命中时把 COMPDATA 整份再压一遍（每语言约 64 秒）（待确认现状）
约束：
- 用词一律用自建表 `config/zh-hant/regional-terms.json`（含按日文绑定规则），不用 OpenCC s2twp 词表；香港字形只取 `hk-characters.json` 里人工挑过的 27 组
- 香港模式下贴图和地形名沿用台湾字形（盘空间：MAPMODEL、KVMDATA 不另存）；开机按住 SELECT 强制台湾版
- 译名原则（11-19 用户定）：香港高达系取香港官网写法；70–80 年代作品不用配音改名；系统用语用官方繁中机战写法（「援護攻撃」「ガード」「カウンター」保留现名）；与已定名冲突逐条确认

### SP 简繁一张碟（来源：`docs/ZH_HANT_SP_DUAL_PLAN_20261117.md`，2026-11-17）
- [ ] 繁体（台/港）模式下 SP 额外关卡、挑战篇的剧情与战斗实机走一遍
- [ ] 繁体模式下名场面集整套（22 行 △／○）内存回归（S6）
- [ ] 实机确认繁体贴图：集市、中场休息、DATA HELP、按键说明、结算提示（序章／進行中）、战斗中的 TRI 叠图和援护提示（目前只做了图集层面的核对）
- [ ] SP 三合一盘（约 4.21 GB）加音乐包后的总大小与兼容性：当初估计单层 DVD 只剩约 30 MB，需实测
约束：
- SP 语言设定单独一份 `/BISLPS-25920L/LANG.BIN`，与本篇各自设定
- 繁体模式把 `DATA/VT1.BIN` 整份重定向到盘尾的繁体 VT1（不平移偏移表，否则额外关卡黑屏）；仍需只在繁体模式加大字库缓冲并启用线性区回退
- SP 底图组件是九月冻结的，任何语言都只能在其上画字，无法从日文底图重新生成

### 三语交接遗留（来源：`HANDOFF_CODEX_THREE_EDITIONS_20261121.md` §9，2026-11-21，未入库）
- [ ] 两类简体字格还没有繁体版（本篇和 SP 都有）：第 4 页斜体「按键」（`config/assets/ui-headings-zh.json` 的 `key` 格，page 4 rect [0,80,46,20]，HarmonyOS Regular 19pt、shear 12、stroke 1.1／fill 0.5），以及挤在一起的「菜单」标题格（本篇第 3 页左上，SP 第 6 页「指令」后）。这些格平时被盖住，但用户要求凡简体画过的都要有繁体版；画法用 `tools/zh_hant/kvm_text.py` 的 `fit` + `render`
- [ ] SP 其他贴图文件（VEFF2DX、AIDDATA、TRICMN）按「简体画了字、繁体与简体相同」的思路逐区域核对；KVMDATA 已核：SP 74 处中 34 处相同（其中 32 处简繁同字），本篇 63 处中 27 处相同
- [ ] 全量单元测试原有 3 项失败（简体写死的断言：`test_polish_feedback_pilot` 种子、`test_release_workflow` 修复器标签、v030_043），需改为按语言取值或更新断言
约束：
- SP 资源缓存会掩盖改动：要真正重跑，先改名 `work/build/sp-multilang-resources/{tw,hk}/*/verified.json`，再用 `SRWZ_SP_STAGE_MEMO=0` 构建
- 一个简体词对应多个繁体写法时，`expected_literal` 会报错，要改用按位置的 `expected_at`

## Special Disc

### Special Disc 汉化遗留项（来源：`docs/special-disc/PLAN.md`，2026-09-17；含 `STATUS.md` 清单）
- [ ] 战斗鉴赏菜单按钮图集（VT1 块 53）「トライ」「シングル」仍是日文：先确认两键在游戏里的用途，再定译法（`images/build_kit.py` 候选 TRI／单机），去掉 `tools/special_disc/images/render_buttons.py` 的 `KEEP_JAPANESE`、重绘并冻结
- [ ] VT1 第 2 块新增音频（SShd，66.8 MB）前移 29,760 字节后，未找到实际播放场景的专项验证：定位哪些场景用到该块，用 runner 录音（`audio start/stop`）核对（待确认）
- [ ] 数据链接：用中文版本篇通关存档（含中文名字）测试 SP 读取与奖励发放；现有证据只有空白卡（待确认）
- [ ] SP 语料仍有 draft：剧情 4,604、挑战 693、战斗台词 59、系统 59、框架 4 条（均为机翻原稿，Pro 润色只给改动行标了 reviewed）。确认是否还要逐条审，还是视为已被 11-10 全量通读覆盖、批量改状态（待确认）
- [ ] 两条指代不明的初稿仍为 draft：`sd-battle:078`、`sd/story/011/dialogue/02.03/0006`，按上下文定稿（待确认）
约束：
- 游戏内统一叫“特别篇”（标题副标题条、3 条存档名已经用了）；原有英文和拉丁标识保留；`OTHERS COMMAND`、`MAP WEAPON`、`DATA HELP` 和 SD 字母库共用格子保持原字模
- 不在范围内：主 logo、设定资料图里的说明和批注、特效字和装饰字、KVMDATA 22 示例图、片尾名单、演示画面上方的作品名
- SP 跟本篇共用一套码表，只追加不挪码位（数据链接要读本篇存档）；图鉴和梗概按原生进度解锁，不做默认全开

### SP 界面运行检查缺口（来源：`docs/special-disc/UI_AUDIT_FOLLOWUP_20260922.md`，2026-09-22）
- [ ] SPCHK-01 资料库：机体和人物全部条目、长文滚动、翻页末行、Q&A 各分类（待确认）
- [ ] SPCHK-02/03 剧情流程 Z 梗概、各剧情组首尾话和分支入口；特别剧场先确认壁纸入口的开放条件，再查壁纸和幻灯片设置、影片和中断对话的播放（待确认）
- [ ] SPCHK-04 战斗鉴赏：简易模式，驾驶员、地形、命中等设置，BGM，配置的保存和读取（待确认）
- [ ] SPCHK-05–08 地图和整备：精神列表和确认、攻击预览和武器详情、援攻援防、战斗结算和关卡胜负、技能学习、部件、换乘、集市出售、帮助、搜索、快捷指令、部队改名（待确认）
- [ ] SPCHK-09 在隔离卡上新建普通存档并读回，覆盖保存、取消、重启后继续（待确认）
约束：
- 用 ARMSX2 runner 自己验证，不找用户测；源卡每次复制，不写回
- 小队名 `フリーデン` 是旧存档留下的，不算缺陷

## 文本与译名

### 机师名表统一漏网项（来源：`docs/PILOT_NAME_TABLE_CONFIRMATION_20261016.md`，2026-10-16）
- [ ] 简体、台湾、香港三份语料都还留着旧写法：`story/050/dialogue/01.02/0012` 的「伍达上尉」改成伍德（p59 选了 B），`battle:15274` 的「哈利·欧德」改成奥德，`battle:20140` 的「洛德·吉布利尔」改成罗德（文档列为“不需要确认，直接改正文”）
约束：
- 以 `config/editorial/name-unification-20261017.json` 和名表 `pilot_name_overrides` 为准；三份语料分开改，不用 OpenCC；写入就是三版同时构建转正

### 人物性格与口吻待办（来源：`docs/CHARACTER_PERSONALITY_BACKLOG_20260907.md`，2026-09-07）
- [ ] CHAR-H01 查尔斯 `story/085/dialogue/02.02/0076`（便利店饭／雷的料理）：既有暂缓决定，连同兰顿反应复核亲近与调侃程度
- [ ] MAIL-W01 `battle:19691–19692`（うますぎ）：典故出处未核实，现稿保留，找到可靠出处再定
- [ ] VOICE-08 阿斯哈姆 `story/130/dialogue/01.02/0004` 现为“多么真挚的友情啊！”，原记录认为“真挚”会削弱讽刺；若该句有线上意见保护则不动（待确认）
- [ ] 按人物的口吻专项（兰德、节子、兰顿、真、盖纳等前 10 名）是否还要做，或已被 11-07/11-10 全量复读覆盖（待确认）
约束：
- 不能凭一两个标签把某人全部台词改成同一口气；按对象、关系、阶段和情绪逐句判断

### 全角英数排版遗留（来源：`docs/COMPACT_TEXT_ADJUSTMENT_PLAN_20260928.md`，2026-09-28）
- [ ] 长武器名压住武器类型栏（固定栏目里有反例）：改名称宽度或栏目布局，不能凭 RAM 样例整批验收（待确认）
- [ ] 动态文本（2,275 条含 `$n` 或模板的记录、SP 17 个 `tm` 绑定、HP/EN/资金/命中等程序数值）还没按最长展开值测过宽（待确认）
约束：
- 不给 `%s`、`%d`、`$n`、`tm` 这些控制语法本身套可见字符标签
- 过长的闭合段只能显式在词间分段，不能截断或删字

### 0.5.0 录制中发现的游戏问题（来源：`docs/RELEASE_VIDEO_GAME_FINDINGS_20261110.md`，2026-11-10）
- [ ] 第 4 条：本篇卡克利孔独白一幕的历史记录里，丹泽尔“……代为道／歉”在词中断行；语料现已同行，需在 Back Log 实机复查，并确认 BEST 是否同样出现（待确认）
- [ ] 第 7 条：SP 攻略问答 → 战斗篇 → 阵型 Q2，标题窄体“TRI”与正文全角“ＴＲＩ攻击”“－２０％”不一致；先问用户是否保留（待确认）
约束：
- 用户 11-10 定：SP 战斗鉴赏的日文曲名、“戦闘開始”按钮、“援護攻擊／再攻擊”原贴图字形和地图“援護 2”标记保持原样

## 贴图与资源

### 本篇同类贴图文字（来源：`docs/UI_ATLAS_REMAINING_20260920.md`，2026-09-20）
- [ ] 本篇多层效果字 HIT&AWAY!、GET BONUS!／GET!、SET UP SYSTEM 是否汉化（目前仅 `config/assets/ui-atlas-candidates.json` 有离线候选，未做运行映射）（待确认）
- [ ] 本篇图鉴/资料标题 CHARACTERS SELECT、CHARACTERS REFERENCE、ROBOTS SPECIFICATIONS、PILOT DATA、MAP WEAPON、DATA UNKNOWN 是否汉化（待确认）
- [ ] 本篇 KVP 小字版「援攻／援防／再攻撃」（TRICMN 大字版已译）与固定标签「重力子臨界」核实覆盖情况（待确认）
约束：
- 数字相关不改；本篇 KVMDATA 第 2/4 页兼作拉丁字母库，改字前要先追全引用，不能直接套用 SP 块号或覆盖共享字母

### 本篇 XAN 头像资源（来源：`docs/VT1_XAN_RESOURCE_HANDOFF_20261006.md`，2026-10-06）
- [ ] Original 和 BEST 的 VT1 第 10 组追加 XAN 小头像（新 ID 1742，取自 SP 第 12 组记录 1094），第 11 组追加半身像（新 ID 2516，取自 SP 第 13 组记录 1550），同步扩展两版主程序的成员偏移表；先核对表后的填充区和加载器有没有记录数上限（待确认是否还要做）
- [ ] 绑定人物和表情映射，让完整战斗动画左下角显示 XAN 小头像（调用链见 `docs/VT1_XAN_SMALL_PORTRAIT_BINDING_20261006.md`）
- [ ] 游戏内核对 SP 原记录 1094/1550 的外观（用户怀疑导出的像素排列或调色板不对）
约束：
- 写回用完整原生记录（CLUT、swizzle 像素、半身像 16 字节尾部），不能把裁剪后的 PNG 写回
- VT1 总长、两组的外层边界、非头像组和已有记录都要逐字节不变
- SP 的人物视觉 ID 553 不能写进本篇映射（本篇 553 是薇拉）

### 旧高清材质包迁移到 PCSX2 2.x（来源：`docs/HD_TEXTURE_PACK_MIGRATION_PLAN_20261015.md`，2026-10-15）
- [ ] 第 3 步路线 B 小样本：在 `FUN_002ef830` / `FUN_002f5bc0` 挂 CLAMP 日志钩子，跑 SP 战斗鉴赏十几场，求出两类动态矩形的生成规则（精灵 UV 窗口 18/696、切入图 37/50、背景滚动裁切零头 386/1,070），写回 `twp_parts.py` / `tbg_tiles.py` 静态枚举
- [ ] 补做 `out-of-atlas` 402 条（页回绕哈希）和 `mode1-inset` 11 条（内缩/镜像 REGION_REPEAT）
- [ ] 查明 `no-such-picture` 中 371 个非占位矩形的组/picture 语义
- [ ] 第 5 步：face 中场以外画面（剧情对话等）的 region 形态，确认后批量生成 1,296 张
- [ ] ui/ui2：8 张 KvMData 页按 region 裁剪；19 张未定位图（疑为渲染目标）确认是否可用
- [ ] 第 6 步打包发布：按 BA/BAC/maps/face/ui 分目录，SLPS-25887 与 SLPS-73270 两个序列号目录同一份内容；PCSX2 2.8 与 ARMSX2 各跑战斗、剧情、中场验收替换计数和部件接缝
约束：
- 路线 A 必须最终做到纯静态全量产出；路线 B 只用来找规则，不做批量采集；路线 D（改模拟器关闭 region）已否决，目标是官方 PCSX2 2.x 直接可用
- 范围只含本篇与 BEST，`XAN-斩` 文件夹不处理
- `face-r513`（1,295 张中场头像）目录不要在磁盘清理中删除

## 工具与网页

### 网页静态金手指（来源：`docs/STATIC_CHEATS_WEB_PLAN_20261116.md`，2026-11-16）
- [ ] `/cheats/` 页每条金手指加“可写入 ISO／仅模拟器”标记（用户还没决定）
- [ ] 不能直接写入的项另找路线：4 槽（要在本 ELF 里另找代码洞）、哈啰 ×2（改 COMPDATA.BN）、资金/BS/SR 数值（改存档或打代码补丁）（待确认是否要做）
约束：
- 清单里不存 ISO 偏移，按 ISO9660 和 ELF 程序头定位，每处先核对原值，不符就停用该项；发新版本后要重新生成 `static-cheats.json` 的验证目标
- SP 的图鉴全开和梗概全开不移植（用户 2026-11-16 决定）；输出文件名后缀用 `-cheats`

## 已核对为完成或已被取代的计划

- `docs/LATIN_DIGIT_PUNCTUATION_VISUAL_PLAN_20261024.md`：`<z>` 标签已实施并提交（2fa900de、58632c0f），图鉴字母不上移（`BODY_LETTERS_RAISED=False`）；英数字形后来改由 HarmonyOS Latin 字形库（467aaaaf）负责，§6 的待定项随之失效
- `docs/DUAL_EDITION_BUILD_PLAN.md`：双版构建已实现（`build_editions.py`、`config/editions/*`），`build_release.py` 已支持 original/best/sp 分版补丁，v0.5.0/v0.5.1 已三版发布
- `docs/special-disc/TEXT_WRITEBACK_PLAN.md`：WB-01～07 已经走完，SP 全量文本写回接入统一构建，随 v0.5.x 发布（`srwz-zh-v0.5.1-sp.xdelta`）
- `docs/SETSUKO_ROUTE_POLISH_PLAN_20260927.md`：被尼禄字幕吸收轮（2a011381、b0783847）和 11-07/11-10 的全量剧情复审取代
- `docs/BEST_MIGRATION_PLAN.md`：alpha1 只是历史实验；BEST 已正式接入源码构建并发布
- `docs/LIBRARY_V02_SCOPE.md`：v0.2 的历史范围，剧情流程和 Q&A 已在 v0.3.0 及之后补完
- `docs/SP_EVENT_COMPLETENESS_BACKLOG_20261013.md`：按 `SP_EVENT_FIDELITY_20261014.md` 处理完，后续鉴赏改成 22 场按事件影片顺序排列；随玩家操作变动的位置按设计用固定锚点

- `docs/special-disc/STATUS.md`（2026-09-19）：SP 剧情写回、正式构建、发布验收已完成（SP 随 v0.5.0／v0.5.1 发布）；所列文本问题均已处理（14 个缺字已入码表，Orange／Keep On Movin'／银莲花等条目已 reviewed）
- `docs/special-disc/UI_ATLAS_CROSS_PAGE_PLAN_20260920.md`（2026-09-20）：用户定只做 DATA HELP →「项目说明」，其余标题撤回，见 `TITLE_ATLAS_IMPLEMENTATION_20260920.md`；后续 SP 指令标题另在 `7ebe8eae` 完成
- `docs/special-disc/TITLE_ATLAS_PLAN_20260920.md`（2026-09-20）：跨页像素＋原调色板方案已实现并收窄到 DATA HELP（`title-atlas.json` 只剩块 1198）
- `docs/POST_V030_POLISH_PLAN_20260907.md`（2026-09-07）：20 条待处理意见和 3 处“天使机械天使”均已写入语料（现为“阿克艾里昂天使”等），图鉴全量复核另有报告
- `docs/SETSUKO_AUTHORIZED_REFERENCE_ASSESSMENT_20260928.md`（2026-09-28）：被尼禄文本采纳（2026-10-28，2,273 处，见 `NERO_CLAUDE_ADOPTION_20261028.md`）和 11-10 剧情全量复读取代；文中样例句已按建议改好
- `docs/video-v0.5.0/EDIT_PLAN.md`（约 2026-11-09）：0.5.0 已发布，发布视频工作转到 0.5.1 视频，剪辑安排不再适用
- `docs/RELEASE_VIDEO_GAME_FINDINGS_20261110.md` 第 1–3、6 条：地图对白出界、ZEUTH 拆行、名场面集标题被 ○ 压住、简报室波浪号已在 `62643bd8` 修复；“4分钟／4回合”与日文原文一致，不是错误
