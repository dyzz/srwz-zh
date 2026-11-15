# 真正关闭 hinting 后的游戏画面（2026-11-15）

用户要求：关闭 hinting，游戏里看效果。本次使用 `-set type:hinting off` 生成汉字位图，在 ARMSX2 runner Metal 4× 中完成五个场景、四个方案共 20 张整屏截图，均已通过对比图目视检查。未修改正式配置/栅格器，未提交或重建 ISO。

## 四个对照

| 标记 | 字号 | Hinting | 字底下移 |
| --- | --- | --- | --- |
| current | 22px | 当前调用实际开启 | 保留 |
| off22drop | 22px | 关闭 | 保留，按新的无 hinting 墨迹重新判定 |
| off22 | 22px | 关闭 | 撤销 |
| off24 | 24px | 关闭 | 撤销 |

本次仅改变汉字栅格，英文数字字库、字号、基线、字宽、步进和行距均维持当前游戏设置，不叠加前次 H 的基线调整。24px 是额外的实验分支，不是正式字号变更。

## 图像

| 场景 | 四方案对比 | 24px 无 hinting 整屏 |
| --- | --- | --- |
| 第 136 话地图目标 | [对比](issue-assets/font-nohint-20261115/stage136-comparison.png) | [整屏](issue-assets/font-nohint-20261115/stage136-off24.png) |
| 地图中英混排 | [对比](issue-assets/font-nohint-20261115/mixed-map-comparison.png) | [整屏](issue-assets/font-nohint-20261115/mixed-map-off24.png) |
| 第 13 话自然剧情对白 | [对比](issue-assets/font-nohint-20261115/story-natural-comparison.png) | [整屏](issue-assets/font-nohint-20261115/story-natural-off24.png) |
| 剧情框中英混排 | [对比](issue-assets/font-nohint-20261115/mixed-story-comparison.png) | [整屏](issue-assets/font-nohint-20261115/mixed-story-off24.png) |
| 剧情框三行各 21 字 | [对比](issue-assets/font-nohint-20261115/full21-comparison.png) | [整屏](issue-assets/font-nohint-20261115/full21-off24.png) |

## 本轮观察

- 只关闭 hinting、继续保留按字底下移，不足以消除短字下坠；新的无 hinting 位图还会改变触发下移规则的字符集合。
- 22px 关闭 hinting 并撤销下移，短字位置更自然；原始字形结构导致的高矮差异仍在。
- 24px 关闭 hinting 并撤销下移，汉字更饱满，目标句视觉更连贯。剧情满行的字间空白变少，密度更高，这是字号变化的取舍。
- 现有英文在 24px 汉字旁显得更小、偏高；本轮没有调整它，因此不能宣称中英混排已完成。
- 五组画面未见文字被对话框截断。满行样例探针记录仍为每行 21 字，x=-240..201。

## 静态与运行时证据边界

全字库生成 3,402 个无 hinting 汉字。另用 32×32 参考画布复核 24px 的位图，中央 24×24 与实际字库完全相同，外部无非零 4bpp 墨迹：本次未发现量化墨迹被字框裁掉。许多字已经接近边缘，不能据此保证其他字号/偏移也不会裁切。

运行时复用此前保存的当前 Original 场景，替换前断言 RAM 整个解压字库与前次 ISO 回读字体副本一致。地图目标通过此前记录的节指针实验到达；混排和满行是显示缓冲里的受控文本。这里是 **ARMSX2 内存注入实验**，不是新候选 ISO 冷启动验收，也没有新增 SP/Best 运行时证明。

[收据及 20 张截图 hash](issue-assets/font-nohint-20261115/receipt.json) · [全字库字顶/字底分布](issue-assets/font-nohint-20261115/nohint-statistics.json)

复现脚本位于 `work/review/font-height-20261115/`：`build_nohint.py`、`nohint_runtime.py`、`native24_nohint.py`。原始运行输出为 `nohint-runtime/`。上述是方案选择前的 RAM 实验。后续用户已选定 **22px、真正关闭 hinting、撤销字底下移**；正式构建及剧情／梗概／滚动多文本验收见 [最终方案验收](FONT_22PX_NOHINT_ACCEPTANCE_20261115.md)。
