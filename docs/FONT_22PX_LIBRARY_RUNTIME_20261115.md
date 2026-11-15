# 22px 无 hinting 字体：三版图鉴与 SP 补充实测

2026-11-15。当前 Original / Best / SP ISO 分别冷启动，以 ARMSX2 runner、Metal 4× 渲染，通过正常按键进入图鉴。使用游戏原有文本，没有注入测试文本、字体或图鉴解锁数据。启动前完整 ISO SHA-256 与各版 current 构建回执一致。

[完整截图页](issue-assets/font22-library-20261115/index.html) · [逐行文本、坐标和 ISO 记录](issue-assets/font22-library-20261115/reports.json)

## 抽查范围

每版保留 12 张：图鉴菜单 1 张、三个类别列表 3 张，以及以下 8 张详情画面：

- 机体：魔神 Z 首屏及向下滚动、戴安娜 A。
- 人物：兜甲儿首屏及向下滚动、弓沙也加。
- 术语：宇宙科学研究所、恐龙帝国。

SP 另保留战斗台词、剧情流程第 3 话「迷途」梗概、剧情滚动各 1 张。三版合计 39 张原始截图，另提供缩略总览。

## 观察结果

本次抽查页面未见缺字、字形底部异常削切或文本超出窗口。机体与人物说明的连续换行行首保持对齐，滚动后也正常；术语弹窗的正文行首保持对齐。魔神 Z、戴安娜 A、GO!、UFO、数字及单位等混排未见明显异常上下错位。汉字具体笔画外框仍随字形不同，不能将其解释为每个字的可见像素底边完全相同。

SP 战斗台词、梗概与滚动剧情均可正常显示。梗概与滚动剧情保留原文本的段首缩进，段首和续行的不同起点不属于字形错位。

这些是当前构建的 ARMSX2 runner 抽样运行证据，不代表全部图鉴条目或实体 PS2 验证。

## 版本与截图

- original: `d45b8e27d270f7ebd2317b63058186ecc04528f2f14a79afa3c8269454fe5a38`；[截图总览](issue-assets/font22-library-20261115/original-overview.png)，12 张。
- best: `a5d5ec18d34968750b6d3e13f093e5cd129a012a00683058da632bb4735f2a00`；[截图总览](issue-assets/font22-library-20261115/best-overview.png)，12 张。
- sp: `0175bffd0a3312db930f45d5058e56fc60058362c6941a26fb87ad8a91496ae9`；[截图总览](issue-assets/font22-library-20261115/sp-overview.png)，15 张。
