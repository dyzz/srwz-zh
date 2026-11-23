# 22px 无 hinting、不下移：正式构建与三场景验收

用户选定：22px、真正关闭 hinting、取消按墨迹底边下移。画布仍为 24×24，共享画布基线偏移 `y_offset=1` 保留；“不下移”指撤销 `cjk_bottom_row_drop`，不是重置字体的共同基线。

## 实现与静态证明

- ImageMagick 使用 `-set type:hinting off`；此前的 `-define type:hinting=false` 未实际关闭 hinting。增加实际像素回归测试，要求开关的渲染结果不同。
- 删除正式配置中的 `cjk_bottom_row_drop`。不做逐字缩放、逐字偏移或字形包围盒归一化。
- 保留已确定的 Latin bank 渲染方式：82 个字槽与修改前逐字节相同。英文的 g/j/p/q/y 保留正常下伸部，不能把所有字母最底部强行拉到同一条线。
- 正式组件的 3,402 个汉字逐像素匹配之前 `off22` 实验。
- 新字库也用于少数拼接标题纹理。“特殊模式”左半块水平右移 1px，恢复整句视觉中心；其他标题中心不变。没有修改汉字垂直位置。

## 实际截图方法

使用 ARMSX2 runner、Metal 4×。从本轮重建 ISO 冷启动，经正常按键进入剧情、梗概、滚动场景；只在同一次启动生成的状态间切换。

每个场景保留自然文本截图，再在游戏文本缓冲区写入多组测试句。字库及绘制几何均来自 ISO，不在 RAM 替换字库。测试句不会写回语料或存档。原始截图和 trace 行坐标一并保存，便于区分字号、字形和场景缩放。

测试内容包括：纯汉字高低结构、中英文缩写和机体编号、数字、小写下伸部、标点，以及剧情 21 列满行。

## 三场景截图

**换行对齐更正**：下列旧样例中，梗概删除开引号后残留续行空格，滚动误用了剧情的专用缩进，不能作为行首对齐通过的证据。已修正测试文本生成方式并冷启动复测，最新结果见 `换行缩进复测`（已删除，原文见提交 eb9c1f90）。

[全部 21 张完整截图与样例文本](issue-assets/font22-final-20261115/index.html)

| 场景 | 截图数 | 裁切总览 | 代表混排原图 |
| --- | ---: | --- | --- |
| 剧情 | 10 | [总览](issue-assets/font22-final-20261115/story-overview.png) | [原图](issue-assets/font22-final-20261115/story-mixed.png) |
| 梗概 | 5 | [总览](issue-assets/font22-final-20261115/flow-overview.png) | [原图](issue-assets/font22-final-20261115/flow-mixed.png) |
| 滚动 | 6 | [总览](issue-assets/font22-final-20261115/scroll-overview.png) | [原图](issue-assets/font22-final-20261115/scroll-mixed.png) |

三组均为 Best 新镜像的 ARMSX2 runner 画面。共 3 张自然文本、18 张测试文本，完整原图均为 2560×1792。已查看各组总览及混排原图；剧情 21 列三行完整显示，未发现字框裁切、行间挤压或缺字。汉字固有高矮差仍存在，不能解释为所有字的最下墨迹像素完全一致。滚动区下缘遮挡正在进入画面的后续行是游戏的滚动窗口裁切，不是字库裁切。

追踪的主文本绘制尺寸：剧情 21×12、梗概 16×10、滚动 24×12；三者使用同一 22px 字库，但游戏场景各有缩放。绘制行、代码和位置见 [运行记录](issue-assets/font22-final-20261115/runtime-report.json)。空格的绘制记录可能与相邻字具有相同 x，排序后的 trace 文本并非原始字符串；样例原文与截图一并保留。

## 三版读回

Original、Best、SP 分别从最终 ISO 解压字库，均对 3,402 汉字逐像素核对通过。三版完整解压字库 SHA-256 相同：

`0f7d4620cc6f8c57536054230cb8b8d368136e5cdfbe6018ce0081bfab332ad7`

[ISO 读回记录](issue-assets/font22-final-20261115/readback.json)、[正式组件与已选方案比对](issue-assets/font22-final-20261115/component-check.json)。

SP 新字体超过旧槽，构建器仅从已验证全零的前方填充区借空间，将紧邻音频块整体前移，保持音频字节、归档大小和后续块偏移；构建回执记录具体借用量。新增测试同时核对音频保持不变、后续块不变，并拒绝非零填充区。


SP 实际借用 11,232 字节，详见 [扩容回执](issue-assets/font22-final-20261115/sp-font-relocation.json)。新 SP 镜像已冷启动进入[战斗](issue-assets/font22-final-20261115/sp-battle-natural.png)和[剧情滚动](issue-assets/font22-final-20261115/sp-scroll-natural.png)，ARMSX2 截图及绘制 trace 均成功；[运行记录](issue-assets/font22-final-20261115/sp-report.json)。音频块逐字节保持不变是静态证据，本轮未做音频听感验收，也不声称 PCSX2 手工验收。

复现脚本与构建日志：`work/review/font22-final-20261115/`。以上记录为提交前验收结果。


## 最终测试

`PYTHONPATH=work/test-deps/unicorn-2.1.4 work/analysis/opening-overflow-review-20261110/venv/bin/python -m unittest discover -s tests`：**1,070 项通过，0 失败、0 跳过**，含 Unicorn；耗时 194.842 秒。日志位于 `work/review/font22-final-20261115/tests-final.log`。`git diff --check` 通过。

证据层次：三版 ISO 字库读回及音频字节保持是静态证明；Best 三场景与 SP 战斗／剧情滚动属于 ARMSX2 runner 实际画面证明；本轮没有 PCSX2 手工验收。
