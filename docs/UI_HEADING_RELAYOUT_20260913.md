# 阵型／说明标题 1:1 重排与界面对齐修正

2026-09-13。用户提供四张截图反馈：

| 图 | 现象 | 处理 |
| --- | --- | --- |
| 图 2 | “选择阵型”“选择排列”“阵型”贴图模糊、笔画粗糙 | 标题字块按屏幕像素 1:1 重新栅格化并重排绘制记录 |
| 图 3 | “按键 说明”“数据 说明”模糊，且两词之间有空隙；“数据说明”文案生硬 | 同上；DATA HELP 改为“项目说明” |
| 图 4 | 选项画面“资料库”“系统设置”标签未居中 | 通过渲染控制前缀调整字距 |
| 图 1 | 机体指令菜单中“阵型”与其他项不对齐 | 见文末“待定项” |

## 原因

`KURODATA/KVPDATA.BIN` 的 34 字节绘制记录以屏幕像素为 x 单位、半像素为 y 单位。
2026-09-10 的字块只有 28×16／27×17 纹素，却被拉伸到 34–42×20–24 像素显示，
放大 1.2–1.5 倍后经双线性过滤自然发虚；两字块之间的透明边距在放大后又形成明显空隙。

## 新字块布局

只有第 2、4 页的 CLUT 第 0 组是标题多边形采样的灰阶渐变，其余页颜色不同；
第 0–9 页由 `FUN_00396f20` 作为一组常驻载入，第 11 页按需载入，因此新字块只能放在
第 2、4 页。全部字块按显示尺寸 1:1 绘制：

| 字块 | 页 | 矩形 | 用途 | 来源区域 |
| --- | ---: | --- | --- | --- |
| 选择 | 2 | (2,56,40,16) | SELECT-FORMATION／SELECT-SORT 首词 | 原 SORT 字样，仅第 177 段引用 |
| 阵型 | 2 | (160,56,38,16) | 标题次词、小队预览标签 | FORMATION 中无人引用的 ORM |
| 排列 | 4 | (46,80,40,16) | SELECT-SORT 次词 | 原 FORMATION 矩形 |
| 按键 | 4 | (0,80,46,20) | Key Help | 原 FORMATION 矩形＋指令菜单空白 |
| 说明 | 4 | (0,100,46,20) | Key Help、DATA HELP 共用 | 指令菜单矩形左侧空白 |
| 其他 | 4 | (120,98,46,20) | OTHERS COMMAND 首行 | 指令菜单矩形右侧空白 |
| 指令 | 4 | (44,234,46,20) | OTHERS COMMAND 次行 | 仅第 204 段引用的 OTHERS 字母 |
| 项目 | 4 | (156,234,46,20) | DATA HELP | 仅第 204 段引用的 COMMAND 字母 |

标题字块 15pt（描边 1.25、填充加粗 0.85，对应日版粗斜体），说明字块 19pt（描边 1.1、
填充加粗 0.5），HarmonyOS Sans SC Regular，4 倍超采样后面积平均缩回；索引仍为
0 透明、1–7 描边、8–15 填充。被第 143 段等其他标题按字母采样的 E／R／C／A 等字母原样保留。
现有“指令菜单”字块与其绘制记录不变。

斜体处理：日版把直立字母画进带 4px 错切的平行四边形，GS 逐扫描线取样会让汉字竖笔
出现台阶状“弯折”。现在把 12° 右斜按整行位移烘进 4 倍分辨率光栅再缩回（与幕间图集
相同），多边形改为矩形，取样严格 1:1。

绘制记录改动共 79 条，记录集合与上一版相同：标题四类保持原 16px 高度，说明类为
10 个半像素单位（20px）；相邻字块的位置由渲染后墨迹边界推算，填充间距 1px（加描边后与字内间距一致）。
按日版对照左对齐：“选择”从原 SELECT- 起点开始，“阵型／排列”跨绘制段紧随其后
（两段原点差 79px，按日版截图实测），小队预览的“阵型”从原 FORMATION 起点开始；
“按键说明”以原 Key Help 中心对齐；DATA HELP 两层各保留两块，其余六个字母图元维持零面积。

`tools/srwz/ui_headings.py` 改为按页写入：`texture_chunks` 列出各页锁定区间，
每个字块声明 `page`；页之间不得重叠，字块不得指向未登记的页。
配方与预览：`work/review/ui-heading-relayout-20260913/`（`author.py`、`render_cells.py`、
`localized-page{2,4}.png`）。

| 成员 | 字节数 | SHA-256 |
| --- | ---: | --- |
| KVMDATA.BIN | 3,335,408 | `e341d2e5cf26a37988e0bb646f57333cbbc4ef17c2c867fe8f447b6070790884` |
| KVPDATA.BIN | 239,664 | `b62d05b76032b153590dc8b2aad78d2d06786c2b861be875e45a4634b65e1cd9` |

## 文案

`corpus/zh/ui-atlas/formation-help-headings.json`：DATA HELP 由“数据说明”改为“项目说明”，
与顶栏“选择项目”的既有用法一致，指对当前光标项目的说明。
教学第 8 页同步：“会显示数据帮助” → “会显示项目说明”。

## 选项画面标签

用原盘运行核对：日文“システム設定”“ライブラリー”与中文标签的起始列完全相同
（302 / 465），说明该表面按固定 x 左对齐绘制，默认字距 20px、字宽 24px，
六个假名恰好撑到居中，中文四字／三字则整体偏左 7–9px，且相邻汉字互相重叠 2px。

`corpus/zh/menu/remaining-ui.json` 的 `compdata_render_control_prefixes_by_offset`
新增 `0x7FB70: <space:18>`（24px 字距）和 `0x7FB80: <space:1B>`（27px 字距）；
前缀只接受控制标记，不能放可见的全角空格。

## 验证

- `tests/test_ui_headings.py` 改为校验页归属、UV 与多边形 1:1、允许区域；
  完整单元测试 303 项通过。
- `build_ui_headings.py --refresh-manifest` 静态回读通过；
  `rebuild_zh_font.py --skip-fetch --refresh-manifests` 与
  `build_iso.py --refresh-output-locks` 重建当前 Original 工作镜像。
- LRPS2 运行证据见下节。

## 机体指令菜单“阵型”偏移与条件宽度区间

LRPS2 放大核对：无论是否被选中，“阵型”都比“移动／攻击／精神／能力”右移约 4px；
地图指令菜单的“批量设置阵型”偏 6px、“搜索”“作战目标”偏 2–3px。

根因（Ghidra 反编译 `SLPS_258.87`）：

- `FUN_00139d50` 设置字距对 A（0x46E36C）／B（0x46E374）和五个子区间开关
  0x46E37B–0x46E37F（拉丁大写、小写、假名 a、假名 b、宽区间）；风格预设 `FUN_003aa8e0`
  （920 处调用，表 `DAT_0042f540`）把五个开关全部打开，常用预设 4／8／12 的 B 比 A 窄 4–6px。
- 绘制函数 `FUN_0013a290` 在宽区间开关下只把 0x8140–0x829E 变窄；
  测量函数 `FUN_00139b00`（69 个居中渲染入口、125 处调用）和 `FUN_00261650`
  却以 0x889F 为上界。项目策略禁止汉字使用 0x8140–0x8491，因此当前语料引用的
  370 个区间内汉字全部落在 0x8492–0x889E：绘制正常、测量偏窄，凡由测量结果居中的
  标签每含一个这样的字就右移 (A−B)/2 px。左对齐正文、机体／驾驶员名（审计保证不含区间字）
  不受影响，这正是此前“剧情里出现无妨”结论成立的原因。日版同样存在该不一致，
  只是原版字库在 0x8492–0x889E 只有制表符。

处理：`tools/srwz/text_measure_range.py` 把两个测量函数里的 `ori at, zero, 0x889F`
改为 `0x829F`，使测量与绘制判定一致；契约在 `config/full-story-components.json`
的 `text_measurement_range`（Original VA 0x139CC0／0x2617EC，文件偏移 0x3B740／0x16326C），
Best 版通过 `config/editions/best/source-layout.json` 新增的两组 `elf_spans`／`elf_instructions`
搬到 `SLPS_732.70` 的 0x3B740／0x16362C（两版指令序列逐条相同）。
测试：`tests/test_text_measure_range.py`。此前临时为 阵／给／离／载 追加的字库别名已撤回，
字库分配表与 v0.4.1 保持一致。区间字引用清单：
`work/review/ui-heading-relayout-20260913/conditional-width-usage.json`。

## 运行证据

当前 Original 工作镜像 `build/iso/zh-release-full-story/current-original.iso`
SHA-256 `8f7b149ce8e600aba892a0c8797ee7616ef8e209707b2b55a9f18c76d09f2110`
（含标题重排、选项标签前缀、教学文案与测量上界补丁）。

LRPS2（software 渲染，Original 当前工作镜像），与日版原盘同路线截图并排对照：

| 画面 | 结果 | 截图 |
| --- | --- | --- |
| 单队阵型（图 2） | “选择阵型”“选择排列”粗斜体、左对齐、词间无空隙；“阵型 TRI”从原 FORMATION 起点开始 | `work/runtime/lrps2/headings-v7-unit-menu-20260914/frames/03840-squad-formation.png` |
| 批量阵型 | 同一字块 | `work/runtime/lrps2/headings-v6-map-20260914/frames/05004-bulk-formation.png` |
| 小队编成 SELECT 说明（图 3） | “项目说明”“按键说明”斜体平滑、无弯折、无空隙 | `work/runtime/lrps2/headings-v7-intermission-20260914/frames/03600-organization-help.png` |
| 选项标签（图 4） | “系统设置”中心 349.0／标签 349.5，“资料库”501.5／503.5 | `work/runtime/lrps2/headings-v3-options-20260913/frames/03536-intermission-options-open.png` |
| 机体指令菜单（图 1） | 测量上界补丁后，“阵型”（主映射码 0x886D）未选中／选中的墨迹范围 545–581 与其他四项一致（补丁前 549–585） | `work/runtime/lrps2/measure-range-20260914/frames/02975-unit-menu-0.png`、`03125-unit-menu-2.png` |
| 地图指令菜单 | 八个标签中心全部落在 526.5–528（补丁前含区间字的“搜索”529.5、“作战目标”530、“战况报告”530.5、“批量设置阵型”533） | `work/runtime/lrps2/measure-range-20260914/frames/02600-map-command.png` |

日版对照截图：`work/runtime/lrps2/original-unit-menu-20260914/`、`original-intermission-20260914/`，
并排图 `work/review/ui-heading-relayout-20260913/compare-*-orig-v7.png`。
原盘对照：`work/runtime/lrps2/probe-original-options-20260913/`。

Best 当前工作镜像 `build/iso/zh-release-best/current-best.iso`（`81d26c96…8b054a`）用同样三条
LRPS2 路线复验（ISO 契约 `work/review/ui-heading-relayout-20260913/best-iso-contract.json`）：

| 画面 | 结果 | 截图 |
| --- | --- | --- |
| 地图指令菜单 | 八个标签中心 526.5–528，与 Original 逐项相同 | `work/runtime/lrps2/best-measure-range-20260914/frames/02600-map-command.png` |
| 机体指令菜单 | “阵型”未选中／选中墨迹 545–581，与其他四项一致 | `…/02975-unit-menu-0.png`、`03125-unit-menu-2.png` |
| 单队阵型 | “选择阵型”“选择排列”“阵型 TRI”与 Original 相同 | `…/03615-squad-formation.png` |
| 小队编成 SELECT 说明 | “项目说明”“按键说明”与 Original 相同 | `work/runtime/lrps2/best-intermission-20260914/frames/03600-organization-help.png` |
| 选项标签 | “系统设置”中心 349.0／标签 349.5，“资料库”501.5／503.5 | `work/runtime/lrps2/best-options-20260914/frames/03536-intermission-options-open.png`、`03688-…png` |

配方与度量脚本：`work/review/ui-heading-relayout-20260913/`。

## 待定项

- “其他指令”（OTHERS COMMAND）已完成静态修改与回读，本轮仍未进入显示该标题的说明画面；
  按键说明一览（`03116-roster-key-list` 类画面）与地图指令说明只显示底部单行提示。
- 双版本已用 `build_editions.py --editions original,best` 从同一冻结输入重建：
  Original `8f7b149ce8e600aba892a0c8797ee7616ef8e209707b2b55a9f18c76d09f2110`，
  Best `81d26c96a24aff16b9e6d823f12aa6fc819fda636315f573d0348ed4ea8b054a`
  （批次 `work/editions/362385ab…/original-best.json`）。两版镜像内的 ELF 在
  0x3B740 与 0x16326C／0x16362C 均读回 `9F820134`，两版均已完成 LRPS2 运行复验。
- LRPS2 截图为 640×448 软件渲染；本轮不做 PCSX2 人工验收。
