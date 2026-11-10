# 战斗撇号收尾与排版核验（2026-11-10）

已写回本地语料，保留原审阅与确认记录；未处理线上审阅。

## 本次处理

| 条目 | 去标签后的定稿 |
| --- | --- |
| battle:19705 | “冲啊，达令！Let's Go！！” |
| battle:21251 | “It's Showtime！！” |
| battle:21270 | “It's Grand Finale！\n　（终幕到了！）” |

保留英文大小写、撇号、词间空格和换行。撇号在字母或数字之间使用 4px 推进；对应扩展字码 E6C3。度量表增至 81 项、324 字节，残差偏移同步更新；SP 使用共用选择器以满足代码空间限制。

战斗沿用 U+3000 全角续行空格，开引号和续行缩进均为 22px。剧情按已批准方案在构建时转换为专用续行字码 0x93FD，与 16px 开引号对齐。没有将战斗续行替换成剧情的新空格。

## ARMSX2 运行核验

使用新构建的 Best ISO 冷启动，Metal 4×，进入真实战斗后在字幕缓冲区注入七条代表文本，再采集实际绘制的逐字坐标、宽高与截图。七条全部与排版引擎一致：19705、21251、21270、24719（10%／20%）、24510（SWITCH ON）、08057（Thank you very much）、02089（BIG-O）。

这是实际游戏渲染器的受控字幕验证，不代表逐条自然触发了这些角色的语音事件；原版和 SP 本轮证据为构建及回读，未将其标记为完成运行验证。

已人工查看撇号、百分号、大写英文、多词英文及双行截图：百分号未裁切，英文词间距可辨，续行正文对齐。英文绘制高度 12px，词间推进 5px；百分号维持原有 22px 宽度。

- [逐字运行对照与 ISO 哈希](issue-assets/battle-apostrophe-20261110/result.json)
- [可复现探针](issue-assets/battle-apostrophe-20261110/runtime_probe.py)
- [撇号与双行](issue-assets/battle-apostrophe-20261110/battle-21270.png)
- [百分号](issue-assets/battle-apostrophe-20261110/battle-24719.png)
- [英文词间距](issue-assets/battle-apostrophe-20261110/battle-08057.png)

## 润色、字库与构建

一并提交已定稿的本篇、SP、君／酱及战斗润色语料与原审阅记录。补齐新语料所需的“窒”字，刷新 SP 共享字库基线，并将 SP 事件画廊的 18 处引用同步为当前已定稿剧情。历史审阅记录不随当前语料重新计算输入锁；后续脚本只刷新活动构建输入。

Python 完整测试：975 项，8 项按条件跳过，其余通过。Node 排版测试：54 项通过。原版、Best、SP 均完成构建与独立回读，最终产物和来源见各版 current.json；这些静态记录与上述 ARMSX2 证据分别保留。

- [原版构建记录](../manifests/editions/original/current.json)
- [Best 构建记录](../manifests/editions/best/current.json)
- [SP 构建记录](../manifests/editions/sp/current.json)
- [三条写回记录](../config/editorial/battle-apostrophe-20261110.json)
