# 汉字行高与中西文基线：三轮实验报告（2026-11-15）

> 后续核对修正（2026-11-15）：此前把配置 `hinting: false` 当作已生效是不准确的。本机 ImageMagick 7.1.2-27 下，当前 `-define type:hinting=false` 与默认渲染逐像素一致；`-set type:hinting off` 才改变为无 hinting。22px/24px 各 18 个样字已做四组参数对照。24px 的“天/说”字底由第 21 行变为第 22 行，与“有/离”一致，说明部分一行差异由 hinting/栅格覆盖造成。此前 H 推荐暂缓，不应先用位移规则补偿一个尚未正确控制的栅格化过程。原有图片与数据仍是当前调用方式的有效观测，但不能标作纯无 hinting 原始字体结果。证据见 `work/review/font-height-20261115/native24/hinting-report.json`、`outline-report.json`、`hinting-comparison.png`。本次未修改正式栅格器或配置。


本报告回应 [调查任务](FONT_HEIGHT_ROW_DROP_20261115.md)。结论：当前按字底下移的规则确实新增了垂直错位，但汉字本身的高矮差异不是它制造的。建议采用候选 **H：收紧汉字下移条件，同时独立校准拉丁字母和数字基线**。这是待定案的实验方案，尚未落入正式配置，也不能据此关闭三版全界面的字体问题。

## 直接查看结果

| 场景 | 现状 / H 对比 | H 的原始整屏 |
| --- | --- | --- |
| 第 136 话迪安娜地图对话 | [前后对比](issue-assets/font-height-20261115-review/stage136-before-after.png) | [2560×1792](issue-assets/font-height-20261115-review/stage136-H-full.png) |
| 地图混排：THE CRUSHER说、Side 3距离1.5km | [前后对比](issue-assets/font-height-20261115-review/mixed-map-before-after.png) | [2560×1792](issue-assets/font-height-20261115-review/mixed-map-H-full.png) |
| 剧情框同一组混排 | [前后对比](issue-assets/font-height-20261115-review/mixed-story-before-after.png) | [2560×1792](issue-assets/font-height-20261115-review/mixed-story-H-full.png) |
| 剧情框三行各 21 字压力样例 | [前后对比](issue-assets/font-height-20261115-review/full21-before-after.png) | [2560×1792](issue-assets/font-height-20261115-review/full21-H-full.png) |

图片来自 **ARMSX2 runner，Metal 4×**。对比图只裁切、排列和加标签，不重画文字。所有候选画面均经对比图目视检查；最终 H 同时提供原始整屏供复核。预渲染 UI 贴图不在本次栅格器实验范围。

## 原因与全字库统计

以当前 proposal 的全部 **3,402 个汉字**为总体，使用锁定的 HarmonyOS Sans SC Regular、22px、24×24 画布重栅格化。汉字的当前 ISO 像素与现行规则结果 **3,402/3,402 完全匹配**。因此不是只挑报告中的十几个字推断。

- 墨迹边界采用 4bpp 灰度 ≥8，行号从 0 开始。
- 包围盒中心为 `(top + bottom) / 2`；另行统计全部非零灰度像素的加权重心，不能把两者混为一谈。
- 原始字形的字底：第 11 行 1 字、第 19 行 4 字、第 20 行 1,485 字、第 21 行 1,912 字。
- 当前规则移动其中 1,485 字，最终第 21 行有 3,397 字。原任务记录的 3,201 是旧总体，不是本次结果。
- 字高分布在全部平移候选中完全不变：2 行 1 字、16 行 1 字、17 行 2 字、18 行 162 字、19 行 915 字、20 行 1,835 字、21 行 486 字。未发生墨迹裁切。
- 原始字顶分布：1 行 1,024 字、2 行 2,085 字、3 行 290 字、4 行 2 字、10 行 1 字。
- 当前字顶分布：1 行 488 字、2 行 1,835 字、3 行 914 字、4 行 163 字、5 行 1 字、10 行 1 字。

| 方案 | 字顶标准差 | 字底标准差 | 字高标准差 | 包围盒中心标准差 | 灰度重心标准差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 当前字底下移 | 0.758 | 0.185 | 0.809 | 0.375 | 0.653 |
| A 原始统一基线 | 0.602 | 0.525 | 0.809 | 0.394 | 0.442 |
| B 最近整数中心对齐 | 0.554 | 0.527 | 0.809 | 0.358 | 0.490 |
| C 中心偏上才下移 | 0.501 | 0.475 | 0.809 | 0.273 | 0.544 |
| H 收紧 C | **0.497** | 0.482 | 0.809 | 0.275 | **0.543** |

单位均为字库行。A 的灰度重心最集中，H 的字顶更集中；不能只凭其中一个数值决定视觉优劣。当前规则改善了字底一致性，却放大了字顶与灰度重心离散。原字形高矮仍然存在，撤销规则不会让所有字变成相同高度。

完整直方图（包括字顶、字底、字高、两个中心）见 [A–D 及当前统计](issue-assets/font-height-20261115-review/statistics.json)、[H 统计](issue-assets/font-height-20261115-review/statistics-H.json)。

## SP 核对

直接读取当前 Original 与 SP ISO 的 EXE/VT1，解压后整个字库 SHA-256 均为：

`446f97ddef48f36c60549443e78045b0e21fb9d375325fe260205d71c1fb9ea1`

SP 当前镜像已包含这条下移规则；不是 11-12 当时未刷新的状态。`config/editions/sp/inputs.json` 中 font manifest/profile/proposal 与 sp-font/font.bin/report.json 共五项锁均与磁盘一致。`build_text_candidate.py` 的刷新路径仍然经过共享字体 prepare/build/verify 和 install_font。

注意 SP 保存的旧安装报告记作 chunk 2，而当前 `install_font.py` 定义的 SP 字库是 chunk 3。本次以当前 ISO 的实际表项及成功解压后的完整 hash 为准，没有把旧报告的 chunk 编号当成当前读盘位置。

## 三轮实验及取舍

第一轮固定拉丁设置，只改变汉字，四个方案均用同一字体来源与字号：

| 方案 | 全字库统一规则 | 观察与取舍 |
| --- | --- | --- |
| A | 去掉 bottom-row-drop | 消除新引入的下坠，保留字体原始形状；当前拉丁仍偏高。只等价于撤销该规则，不声称整包等同 v0.5.0。 |
| B | 包围盒中心向中位数 11 靠拢，只取最近整数位移；恰好半行时保持原位 | 上移 128 字，下移 2 字。统计改善有限，仍需独立处理混排。 |
| C | 原始包围盒中心 <11 时下移一行 | 移动 539 字。目标行更整齐，但也移动“一”和两个底部在 19 行的字，条件过宽。 |
| D | 所有汉字统一下移一行 | 相对参差不变，还把英文显得更高；不推荐。 |

[第 136 话 A/B/C/D](issue-assets/font-height-20261115-review/stage136-round1.png) · [地图混排 A/B/C/D](issue-assets/font-height-20261115-review/mixed-map-round1.png) · [自然剧情对白 A/B/C/D](issue-assets/font-height-20261115-review/story21-round1.png)

第二轮校准混排：E=A+拉丁基线 12/16，F=C+12/16，G=C+16/16。这里的 12/16、16/16 是 GS 坐标残差；当前 4×捕获中分别下移约 6、8 个像素，不是移动 12 或 16 行字库。使用既有 baseline sidecar 平移绘制四边形，避免重新采样字形产生模糊。字母与数字一致平移，保留 g 等下降部。

[地图目标](issue-assets/font-height-20261115-review/stage136-round2.png) · [地图混排](issue-assets/font-height-20261115-review/mixed-map-round2.png) · [剧情混排](issue-assets/font-height-20261115-review/mixed-story-round2.png) · [21 列压力样例](issue-assets/font-height-20261115-review/full21-round2.png)

第三轮 H 收紧汉字规则，并比较场景尺寸对应的拉丁基线。H 与 F 在目标地图场景的汉字结果相同；H 对“一”等边界样例更保守。G 下移更大，某些相邻短字会显得英文偏低，因此推荐 H。

[地图第三轮](issue-assets/font-height-20261115-review/stage136-round3.png) · [地图混排第三轮](issue-assets/font-height-20261115-review/mixed-map-round3.png) · [剧情混排第三轮](issue-assets/font-height-20261115-review/mixed-story-round3.png) · [满行第三轮](issue-assets/font-height-20261115-review/full21-round3.png)

## 推荐 H 的精确定义

先按原始统一基线栅格化，再对每个汉字应用相同判定：

```python
# 4bpp threshold = 8; all row indices zero-based
if ink_bottom == 20 and (ink_top + ink_bottom) / 2 < 11:
    shift_down_one_row()
```

条件使用锁定的阈值 11，不随以后增加字符重新计算中位数，避免扩充字库时旧字突然移动。没有逐字名单、缩放、裁边、换字号或改变字宽。

- 相对 A，移动 536 字；相对现状，撤回 949 字的下移。
- 保留“天、历、吗、距”等短字的原始垂直位置；“一”保持原位。
- 当前地图 `sp_story_map` 的字母/数字残差建议都为 `+12`；剧情 `story` 都为 `+14`。字高、字宽、步进、行距不变。
- 其他场景需要按其尺寸校准，不能直接把这两个常数套到战斗、图鉴、梗概和武器列表。

## ARMSX2 证据与验收边界

使用当前 Original ISO，复用本日实验存档。在第 136 话加载后，把 block-1 的 118 个节指针临时指向 01.09，使游戏自己的地图事件解释器显示该节；目标文字和字形绘制路径来自游戏。自然剧情对白是 `story/013/dialogue/02.01/0012`。混排和满行样例只在 RAM 中替换显示文本。

每个场景替换字形前均找到 RAM 中的解压字体，并断言**整个字体副本与本次当前 ISO 回读一致**。候选只替换显示汉字的对应字库槽；变更内容由全字库规则预先生成。英文基线修改前检查了当前几何记录的原始字节。

这属于 **ARMSX2 内存干预实验**，不是候选 ISO 冷启动验收，也不是 PCSX2/manual 或 LRPS2 证据。

截图像素测量采用灰度 <60 的主墨迹和探针给出的字位置；抗锯齿、笔画形状、相邻字边缘会使值与字体 ≥8 的边界不完全相同，不能将像素量测当成亚像素精确的排版基线。

- 第 136 话第三行：字顶跨度由 **7 个 4×像素降至 4 个**。原来“历、吗”偏低的情况改善。字底从约一条线回到字体自然的两档，绝不能写成顶底都绝对齐平。
- 地图混排：英文平底大写/数字的底部中位数从 76 到 82；相同行高下汉字底部中位数由 83 到 80.5。
- 剧情混排：英文平底大写/数字底部中位数从 82 到 88；汉字由 90 到 88。
- 上述中位数均为相对该行绘制起点的 4×像素，不是整屏 Y。相邻字仍存在约一个原生像素量级的轮廓差异，H 是视觉协调方案，**没有证明所有中英相邻字符的墨迹底部完全相等**。
- 三行满行样例均经探针确认 21 字，`x=-240..201`，Y 为 61/75/89；没有新增换行、丢字或横向溢出。测试故意包含“一二三、上下、口日月田由甲申中”等形状差异。
- 所有候选均没有字库墨迹质量损失；没有改变 24×24 画布或 22px 字号。

详细测量见 [逐字屏幕数据](issue-assets/font-height-20261115-review/screen-metrics-round3.json)。输入 ISO/config hash、图片 hash 和满行坐标见 [实验收据](issue-assets/font-height-20261115-review/receipt.json)。

要把“整齐且混排协调”提升到发布保证，仍须在选定方案后：正式实现并强制重栅格化，刷新 SP 锁，重建三版，验证读回像素，然后在三版的地图、剧情、战斗、图鉴、梗概及武器列表各自完成基线验收，并运行完整测试（含 Unicorn，0 跳过）。本次未改正式配置、未提交、未重建三版，也没有把这一步写成已完成。

## 复现材料与排除项

实验目录：`work/review/font-height-20261115/`。

- `analyze.py`：全字库栅格化、原始/候选分布、Original/SP ISO 回读。
- `capture.py`：第一轮；`round2.py`：混排基线；`round3.py`：收紧条件及最终候选。
- `measure_round3.py`：截图主墨迹测量；`package.py`：整理图与 hash 收据。
- Python 使用本机已有的 `work/analysis/opening-overflow-review-20261110/venv/bin/python`，包含 Pillow；ARMSX2 需要主机共享内存权限。
- 第一轮 `mixed-story` 曾只改到源文本而未改显示缓冲，已由目视和探针发现，该组截图不作混排证据、不在交付图中；有效剧情混排来自第二、三轮，均断言显示出 CRUSHER。
- 复用的 `go.py` 对 136 目标行出现 corpus 行匹配告警（引号/缩进形式），但探针和截图均确认实际三行就是本任务指定文本；不据该告警宣称字幕验收已通过。
