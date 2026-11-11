# 《超级机器人大战 Z》简体中文版 v0.5.0

v0.5.0 首次正式加入 SP 特别盘汉化。本篇继续支持 Original（初版）与 The Best（廉价版）。

## 本次更新

- **SP 特别盘**加入中文剧情、挑战、图鉴及鉴赏内容。名场面集可按 ○ 观看演出，或按 △ 连同对白观看。战斗鉴赏可关闭 BGM，保留语音与音效。
- **本篇**为部分原关卡事件演出补上中文字幕，并修订开场滚动文字与剧情梗概。图鉴和梗概按原版进度解锁，两组可选全开金手指可以独立启用。 [金手指说明](LIBRARY_UNLOCK_TEST_CHEATS_20261106.md)
- **三版**同步经审阅的战斗台词及术语，调整对白、菜单和图鉴排版。战斗动画中按住方块键（□），可跳到演出的下一个阶段。

感谢参与试用、报告问题、核对原文和提交译文的玩家。贡献者名单与审阅入口见[项目说明](../README.md#致谢)。

## 选择补丁与校验

根据自己持有的**未修改日文原盘 ISO**，从 [v0.5.0 GitHub Release](https://github.com/dyzz/srwz-zh/releases/tag/v0.5.0) 下载一份 `.xdelta`。

| 日文原盘 | 补丁 |
| --- | --- |
| Original 初版，SLPS-25887 / 1.04 | `srwz-zh-v0.5.0-original.xdelta` |
| The Best 廉价版，SLPS-73270 / 2.00 | `srwz-zh-v0.5.0-best.xdelta` |
| SP 特别盘，SLPS-25920 / 1.01 | `srwz-zh-v0.5.0-sp.xdelta` |

持有 The Best 日文原盘的玩家可用以下命令生成中文镜像。

```sh
xdelta3 -d -s "best.iso" "srwz-zh-v0.5.0-best.xdelta" "srwz-zh-v0.5.0-best.iso"
```

请先备份原盘和普通记忆卡存档，换用新镜像后从普通存档读取进度。依赖 Original（初版）金手指的玩家可继续选择 Original 补丁。

附件 `SHA256SUMS.txt` 用于校验补丁，`release-manifest.json` 记录各版原盘及还原成品的 SHA-256。

三份补丁均已从各自的日文原盘还原验证。 [构建与验证记录](RELEASE_BUILD_V0.5.0.md)
