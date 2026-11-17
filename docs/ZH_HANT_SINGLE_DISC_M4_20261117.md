# 简繁一张碟：M4（贴图与其余文字路径）实施记录

2026-11-17。接 [M3 记录](ZH_HANT_SINGLE_DISC_M3_20261116.md) §10 的平行方案。目标：本篇 Original 在功能上完备，只差语料（人工繁体稿）和术语。

最新测试盘与 SHA-256 见 §7。原 M4 测试盘为 `b3d9c79b…`，当时另有装载音乐播放器的 `zh-hant-dual-music-original.iso`。

一条命令（要有装了 opencc 和 Pillow 的 Python；ImageMagick 版本须为 7.1.2-27，和简体管线相同）：

```bash
python3 tools/zh_hant/build_dual.py
```

## 1. 结论

繁体模式下，玩家能看到的中文都是繁体，包括所有贴图类文字。原 M4 的简体基线为 `c6754f75…`。设定面板更新后的基线见 §8，本次手工贴图重建的逐字节比较见 §7。

| 位置 | 内容 | 繁体做法 |
| --- | --- | --- |
| VT1 第 6 块 | 标题菜单按钮（开始/读取/继续/资料库） | 新画四张 128×32 灰度掩码；组盘把整块放进 DMY，并改读取指令 |
| VT1 第 8 组 | 107 张进关标题 | 用繁体构建自己的字库字形渲染；按原槽位压缩，6 张降到 8 级灰度 |
| KVMDATA | 6 个界面图集、标题格、帮助标题、战斗 SELECT 字块 | 图集实时渲染并冻结；后续环节按繁体重算（§3） |
| MAPMODEL | 78 个世界地图地名 | 实时渲染并冻结；繁体与日文原文写法相同的地名保留原图（§4） |
| MTV_PROP | 两条章节间幕 | 渲染哈希写入平行语料 |
| VEFF2DX | 教学标题、剧情/模式选择标签与 SELECT 标题、剧情字幕 | 配置段的繁体版（§2） |
| AIDDATA、TRICMN | 援护提示 10 条、战斗叠加层 51 条 | 用工具自带的重新冻结流程；「單體攻擊」字距自动收紧 1 px |
| NISVDATA、HSFC | 资料库菜单、音乐选择标题、剧情流程标题 | 实时渲染并冻结 |
| 可执行文件 | 武器类别「格鬥」 | 用繁体码表重编 LUI/ORI 立即数 |

字体仍是 HarmonyOS Sans SC，它覆盖了繁体语料用到的全部 3,972 个汉字，字形按大陆规范。

## 2. 繁体资产放在哪里

| 位置 | 内容 |
| --- | --- |
| `config/zh-hant/sections.json` | 配置文件里整段的繁体值，键为 `文件#段名`。每段记录它起草时对应的简体段哈希和状态，规则同平行语料。<br>本次有 13 段：`full-story-components.json` 的教学标题、世界地图、剧情/模式选择、kvmdata/kvpdata 锁；`library/v0.2.0.json` 的三处菜单；两份剧情字幕的 `captions`。 |
| `config/zh-hant/overlay/<路径>` | 整份替换的文件：冻结快照、图集与组件配置、对应的 `manifests/*-validation.json`。 |
| `config/zh-hant/render-adjustments.json` | 繁体专用的渲染微调（目前只有「單體攻擊」字距 7 → 6）。 |
| `config/zh-hant/stage-title-graphics-indexed-snapshot.json` | 繁体进关标题快照。 |
| `config/zh-hant/hand-drawn/original.json` | Original 五类手工贴图的固定像素输入。每格记录文案、尺寸、来源、参数和索引 SHA-256。 |
| `config/zh-hant/author-fingerprint.json` | 这些资产生成时的输入指纹，包括用到的每个简繁字串对。 |

`build_dual.py` 准备繁体克隆时，先套用段和覆盖文件，再刷新所有指向改动文件的 `{"path","size","sha256"}` 锁（`tools/zh_hant/locks.py`，只扫 `config/`，反复刷新直到稳定）。

## 3. 生成工具

`tools/zh_hant/author_textures.py [STEP ...]` 在准备好的繁体克隆里运行；不带参数时跑全部步骤并写指纹。`build_dual.py` 发现指纹过期会自动重跑，然后换一份新克隆再构建。

| 步骤 | 做法 |
| --- | --- |
| tutorial | 教学标题：用 `render_locks.relocking()` 渲染，把新哈希写回配置段。 |
| world_map | 世界地图：`live_render` 加快照输出。「已翻译」计数随文本变化，写进段的 `expected`。 |
| library | 资料库三处菜单：实时渲染，冻结快照。 |
| aid、tricmn | 运行工具自己的 `--live-render`，把报告里的 `expected` 写回配置，再 `--refreeze-snapshot`，最后跑一遍冻结构建核对。标签碰到矩形边界时，字距每次减 1 px 重试。 |
| atlases | 6 个 KVMDATA 图集逐个实时渲染并冻结，用管线自己的 ratchet 更新输出锁，再更新图集套件的锁。 |
| kvm_chain | 按 `ui_headings.py` 的顺序在繁体图集上重放后续环节（菜单还原、清晰化、帮助标题、支援/指令标题、战斗 SELECT），重算每一步的前后哈希。重放结果必须和真跑 `build_ui_headings.py` 一致。<br>重绘的有：清晰化格子 5 个（選擇、陣型、按鍵、說明、項目）、帮助标题两条（按鍵說明、項目說明）、战斗 SELECT 字块 8 个（選擇陣隊員機體師）。支援/精神/指令/其他/排序 简繁同形，不重绘。<br>阵型帮助标题格的语料和快照仍用简体：可见的每个格子之后都会被清晰化格或帮助标题覆盖。 |
| title_menu | 标题按钮掩码。 |
| select_headings | 选择剧情/选择模式标题的普通和粗体两条。 |
| event_subtitles | 剧情字幕只换 `chinese_draft`，其他字段保持简体文件原样。 |

**五类手工贴图**由 `tools/zh_hant/paint_hand_drawn.py` 单独绘制，采用 HarmonyOS Sans SC。构建读取 `config/zh-hant/hand-drawn/original.json`，逐格核对文案、尺寸、索引范围和哈希。该文件参与指纹检查，改图后重新冻结配置与输出锁。

| 资产 | 简体原流程与繁体做法 |
| --- | --- |
| 标题菜单 | 查过 Git、2026-07-26 至 07-30 提交、Codex 和 Claude 会话及本地工作目录，找到冻结掩码和写回工具，未找到原绘制脚本。按冻结掩码校准 ImageMagick 渲染，四张保留 128×32、16 级灰度。「繼續」使用较细描边保持字腔。 |
| 清晰化格 | Codex 会话 `01a1bbc2-eb8a-79e2-a85b-375f36a09c73` 的 `render_cells.py`。4 倍采样、#505050 描边、白字、就近映射原第 2 页调色板的整数灰度。简体六格逐索引复现。排序沿用原字块。 |
| 帮助标题 | Codex 会话 `01a1bbd7-4fdf-7351-9741-bfbbdee4ab36` 的 `build_review.py`。复用扩大画布、分别绘制字面与描边、4-bpp 分层量化、裁边居中的流程。会话中的脚本有截断，描边、加粗和字面阈值按冻结结果与繁体槽位调整。 |
| 战斗 SELECT | 同一会话的 `build_aligned_titles.py` 18 pt 版本。用 108×36 画布整行画，取同一基线上的 18 行和每字 19 列，映射原第 2 页 CLUT。原参数逐索引复现简体 11 格。繁体略宽的笔画在量化前按面积平均缩进现有字槽。 |
| 剧情／模式选择 | 同一会话的 `build_opening.py`，简体冻结于 `71e2a66c`。88×24 画布、17 pt、字距 1 px、左移 4 px，普通／粗体描边 0／2.5 px。简体四条逐索引复现。繁体沿用参数和同一写入边界。 |

校对图在 `build/zh-hant/hand-drawn-review/`，三列依次为简体、旧繁体、新繁体。保留该目录的基线配置、原简体镜像及 `zh-hant-dual-before-hand-drawn.iso` 和收据时，可运行 `python3 tools/zh_hant/paint_hand_drawn.py --compare` 复现对照。

另外几项：
- 章节间幕：`build_dual` 每次自动重跑 `author_intertitles.py`。
- 进关标题字形取自繁体构建自己的字库。字库变了，`build_dual` 会重新生成快照，然后再构建一次。

## 4. 公用构建工具的改动（简体产物不变）

- `srwz/render_locks.py`（新）：只在 `relocking()` 里生效。渲染输出锁不符时写回合同、不报错；正常构建从不进入这个模式。
- 接入 `relocking` 的地方：`mtv_prop_intertitles`（`relock` 参数）、`veff_tutorial_titles`、`ui_menu_restore` 的输出身份校验。
- 原来写死的验收值改为读配置，简体值不变：
  - 世界地图「已翻译」计数（70/101）；
  - 标题菜单改动像素数（12514）；
  - 武器类别、音乐选择、剧情流程的字面量（经 `build_language.expected_literal`）。
- `weapon_category_labels`：其他语言的构建里，只校验改动的是 LUI/ORI 立即数。
- `tricmn_battle_overlay`：渲染出错时报出标签名。

## 5. 组盘（assemble_dual.py）

- VT1 第 6 块（标题菜单）不同时，整块放进 DMY。
  - 标题画面在 `0x154C8C`–`0x154CA8` 读这一块：原来是半字表 `0x3F8668` → VT1 表 → `0x139620`。
  - 繁体补丁把这 6 条指令改成立即数的 DMY 偏移和结束位置，做法同字库读取。
  - 只有这一处读第 6 块。
- DMY 用量 109.9 MB / 122.6 MB。复制进去的成员：AIDDATA、TRICMN、KVMDATA、MTV_PROP、VEFF2DX（含字幕）、MAPMODEL 等 18 个，加字库、标题菜单、进关标题组和补丁。KVPDATA 简繁相同，不复制。
- 补丁 7 个扇区：18 行对照表，743 条记录。

## 6. 实机验证（ARMSX2 runner，`work/analysis/zh-hant-m3-20261116/` 的 `x-*` 目录）

| 项目 | 结果 |
| --- | --- |
| 简体模式 | 和简体构建盘在 15 个画面上逐像素相同。 |
| 繁体开机路径 | 743/743 条补丁记录生效；堆顶、字库缓冲大小字、临时区和此前相同；第 3 话剧情块等于繁体构建。 |
| 标题 | 开始/读取/继续/资料库按钮显示为繁体，说明第 6 块从 DMY 读取正常。标题确认框为繁体。 |
| 中场休息 | 标题、六个菜单项、下个地图、SR 点数、资金、第 2 话/9 回合、已通关！全部繁体。 |
| 世界地图 | 「西伯利亞」。 |
| 资料库 | 機體圖鑑…攻略問答；音乐选择标题「音樂選擇」、作品名「魔神Z」。 |
| 剧情 | 第 3 话开场 40 多段对白全为繁体，没有缺字。 |
| 标题待机演示 | 战斗台词为繁体（SRVC/OP1/OP2 从 DMY 读取）。 |
| 中断存档 | 简体存、繁体读，以及繁体存、简体读，地图和敌方回合都正常。 |
| 音乐 | 繁体模式下播放器播放 97 号曲，无断流、无错误。 |

实机没有看到的项目：
- 战斗叠加层、援护提示、阵型 SELECT 标题、帮助标题、章节间幕、教学标题、剧情字幕：需要实际战斗、教学或事件影片。
- 剧情流程标题：音乐选择里没能退出，没走到这一页。

这些内容都经过构建自身的逐像素锁和回读校验，读取走的是已验证过的同一套 VMAP 重定向。

## 7. 手工贴图验收与剩余工作

最终双语盘为 `build/iso/test/zh-hant-dual-original.iso`，SHA-256 为 `1da64962eaeea67393745f9f1c8b99fccbeb38503862bfce722d26e7889d28d9`。先完整构建，再以 `--skip-sc` 从同一份简体产物重建繁体并重新组盘，两份双语 ISO 通过 `cmp`。重新构建的简体单语言 ISO 与封存基线也通过 `cmp`，SHA-256 为 `7917b9cece204f2d0e49a192a99ade7ca90cf59adb20bb316c0958ff176fb12e`。详见 [哈希](../build/zh-hant/hand-drawn-review/final.sha256) 和 [逐字节比较](../build/zh-hant/hand-drawn-review/byte-comparison.txt)。

静态 ISO 回读检查了繁体 VT1 菜单掩码输出、KVMDATA 的索引和 CLUT、VEFF2DX 两块的普通／粗体掩码。KVMDATA、VEFF2DX 的矩形外像素和 CLUT 与旧繁体盘逐值相同，KVPDATA 保持逐字节相同。清晰化链中的旧「選擇」格在后续由原生 SELECT 恢复覆盖，「按鍵／說明／項目」旧格由整条帮助标题替换。见 [回读日志](../build/zh-hant/hand-drawn-review/iso-readback.log)。

ARMSX2 Metal 4× 静音冷启动，运行时语言值为 1。以下均来自最终 ISO。模式选择通过读取第 30 格通关档进入。

| 类别 | 简体／旧繁体／新繁体贴图 | ARMSX2 截图 |
| --- | --- | --- |
| 标题菜单 | [掩码](../build/zh-hant/hand-drawn-review/title-menu.png) | [标题画面](../build/zh-hant/hand-drawn-review/final/opening/title.png) |
| 清晰化格 | [索引格](../build/zh-hant/hand-drawn-review/clarity.png) | [战场阵型画面的青色陣型标签](../build/zh-hant/hand-drawn-review/final/battle-select/formation.png) |
| 帮助标题 | [索引格](../build/zh-hant/hand-drawn-review/help.png) | [项目说明](../build/zh-hant/hand-drawn-review/final/intermission/help.png)、[按键说明](../build/zh-hant/hand-drawn-review/final/intermission/key-help.png) |
| 战斗 SELECT | [字块](../build/zh-hant/hand-drawn-review/battle-select.png) | [阵型和排列队员](../build/zh-hant/hand-drawn-review/final/battle-select/formation.png)、[机体](../build/zh-hant/hand-drawn-review/final/battle-select/robo.png)、[机师](../build/zh-hant/hand-drawn-review/final/pilot/pilot.png) |
| 开场 SELECT | [四条掩码](../build/zh-hant/hand-drawn-review/opening.png) | [剧情](../build/zh-hant/hand-drawn-review/final/opening/scenario.png)、[模式](../build/zh-hant/hand-drawn-review/final/clear-save/mode.png) |

本轮改动均未提交。新增绘制工具和固定输入，修改 `tools/zh_hant/author_textures.py`、`config/zh-hant/author-fingerprint.json`、`config/zh-hant/sections.json` 及本记录。重生成的覆盖文件位于 `config/zh-hant/overlay/`，包括：

- `config/assets/` 下的 `title-menu-zh.json`、`ui-battle-select-titles-zh.json`、`ui-headings-zh.json`、`ui-help-titles-zh.json`、`ui-select-native.json`、`ui-text-clarity.json`。
- `manifests/ui-headings-zh-validation.json`。

剩余工作

- 人工繁体稿和术语表：现在全是机器稿，留到以后再做（用户 2026-11-17）。攻略问答部分按用户要求不处理。
- 标题菜单仍采用按简体成品校准的画法，帮助标题的部分数值按原图回调。评审可对照 §3 的三列图。
- 实机还没看到：战斗叠加层、援护提示、章节间幕、教学标题、剧情影片字幕、剧情流程标题。
- 带音乐播放器的双语盘要用最终盘重新做。
- BEST（M5）。

用户决定不做的（2026-11-17）：
- 改名画面的选字表：繁体模式下不处理。
- 换台湾规范字体：不换，继续用 HarmonyOS Sans SC，它本身带繁体字。

## 8. 设定面板：语言、数字 0、对话引号（2026-11-17）

用户要求：在标题菜单按 SELECT 打开设定，和简繁切换放在一起；新增「数字 0 有点/没点」「对话引号 中文“”/日文「」」。

### 8.1 玩家看到的

- 标题菜单按 SELECT，弹出游戏自带的信息框，共四行：
  ```
  ⇒游戏语言：简体中文
  　数字样式：0
  　对话引号：中文“”
  　　(○)保存　　(×)取消
  ```
- 操作：上下选行，左右改值，○ 保存，× 或 △ 关闭。
- 提示行的 ○ / × 是游戏自己的按键图标（和资料库「剧情流程」底栏同一套），不是字库里的字。
- 光标是原字库的 ⇒（0x81CB），固定在最左一列。
- 排版：信息框按字码个数把每行居中（`0x139B00`，字体 6 每个字码都算 16 px，全角空格也算）。所以三行都补成 10 个字码：标签都是 5 个字码（用户定名：游戏语言、数字样式、对话引号），值右补空格到 4 个。三行左对齐，冒号对齐。`assemble_dual.py` 里有断言检查行宽。
- 数字零一行直接显示两种 0：拉丁字库的有点 0（0x8440，slot 0）和没点 0（0x844A，slot 10）。信息框按码位直接取这两个字形。
- 繁体模式下面板文字用繁体码表（遊戲語言 / 數字樣式 / 對話引號）。
- 生效时机：
  - 保存后提示「设定已保存。（语言在重新启动游戏后生效）」。
  - 数字 0 和引号立即生效。
  - 语言要重新启动才生效。
- 默认值和以前相同（有点、中文“”），两种语言都有这两个选项。

### 8.2 实现

**字形**（`srwz/latin_bank.py`、`config/fonts/zh-latin-bank.json` 的 `extras`）：拉丁字库里加了三个字形，原有字形的哈希不变。
- slot 10（数字与大写字母之间的空格位）：没点的 0。
- slot 80、81（两个备用位）：窄版「」。取 HarmonyOS 的「」，平移到窄引号“”的墨迹位置（16 px 步进）。换引号样式时排版一个像素都不变。

**绘制**（`srwz/proportional_hooks.glyph_bank_hook` 的 `options` 参数；`tag_free_integrated` 只对 original/best 启用）：
- 比例场景的绘字钩子读一个选项字。地址在负载里，前面有 `SRWZOPT1` 标记，本篇是 `0x78AFD0`。
  - bit 0：0 改画 slot 10，仍走逐个绘制的路径。
  - bit 1：“（0x9141/0x8167）和 ”（0x8FE7/0x8168）改画 slot 80/81，只限对话场景（场景表前两项：剧情对话框、地图对话框）。
- 存储的仍是 “” 码位，所以名字颜色、backlog、换行都不用改。
- 选项字为 0 时，画面和以前完全相同。

**设定**（`tools/zh_hant/lang_hook.S`）：
- `LANG.BIN` 升为版本 2：值 = 语言 | 没点 << 8 | 日文引号 << 16，另存一份按位取反做校验。版本 1 的文件照常读。
- 开机时两种语言都读卡。打完补丁后，把两个显示选项写进选项字。
- 面板用信息框（style 2，4 行）。
- 两处信息框机制：
  - 信息框会忽略设置成当前同一个 id 的消息，所以每次更新在 id 22 和 21 之间轮换。
  - 面板打开时，每帧在按键沿清零的窗口里调用一次 `0x36BC30`，信息框才会读入新文字。
- 文字片段按显示语言分组，每种语言 16 个，表里存半字偏移。

**按键图标**：
- 信息框文字里的 `<N>` 是名字替换（`<0>` 打出「兰德」），不能用来显示图标。资料库底栏的图标是精灵。
- 精灵由 KVP style 引擎画：`0x36B330(包, style, x, y, 0, 128, 128)`，返回新的包指针。style → KVPDATA 块的表在 VA `0x42C350`。
- 按键 style（亮 / 暗）：○ 45、47（小）/ 46、48；× 37、39（小）/ 38、40；□ 43、41；△ 49、51；L1 53。面板用小号 47 / 39。
- 只在面板状态（dlg_state 1）画，在信息框之后。提示文字是「　　保存　　　取消」（9 个字码），图标画在第 2 和第 7 格的空格上。多出的开头空格让整行右移半格（8 px），落在上面三行的中间（用户要求往右一点）。
- 坐标（`lang_hook.S` 的 `ICON_*`）：y = −12，○ x = −63，× x = 17（比格子中心偏左 3 px，离字近一点）。换算：图标中心屏幕 x ≈ x + 334，屏幕 y ≈ 2y + 226（448 行）；面板行的中心在屏幕 x ≈ 322。

**空间**：
- 钩子映像按 64 字节取整报 3,712 / 3,712，实际末尾在 `0x78C488`，离洞口末尾 `0x78C4C0` 还有 56 字节。两个图标共用一个 `draw_icon` 小函数，数据段的 16 字节对齐改成 4 字节。
- 面板文字 82 字节：3 行 ×（10 个字码 + 换行）+ 提示行 9 个字码 + 结尾 0；缓冲区 84 字节。
- 读卡缓冲和面板文字共用 80 字节。
- 文字片段表存半字偏移。

### 8.3 构建与验证

- **构建**：
  - 简体单语言构建的新基线是 `7917b9ce…`（多了三个字形和钩子代码），两次构建相同。
  - 双语盘 `114b3505…`；加按键图标、对齐排版、改标签、提示行右移后重新组盘为 `5fca5a77…`。
  - BEST、SP 照常构建。SP 的问答排版需要 `qa_typography.ATOMIC`，已保留这个名字。
- **测试**：`test_glyph_bank_hook` 新增 4 项，用 MIPS 解释器验证。解释器补了 `andi` 指令。
- **实机（`work/analysis/zh-hant-m3-20261116/` 的 `y-*` 目录）**：
  - 面板：简繁两种模式都正确显示、切换、保存，卡上值为 3。
  - 按键图标和排版：简繁面板三行冒号对齐，图标在「保存」「取消」左边、和文字垂直居中；保存后的结果框不画图标。简繁两种模式都跑完整套设定测试，选项字为 3，第 3 话对话是「」（`z-lay*`、`z-final*` 目录）。
  - 引号：之后进入第 3 话，对话显示「」，名字颜色和续行缩进正常。
  - 数字 0：在 RAM 里把一句对白改成「00了？」，开选项时是没点的 0 加「」，默认时是有点的 0 加 “”。
  - 简体模式：和新的简体构建在 15 个画面上逐像素相同。
