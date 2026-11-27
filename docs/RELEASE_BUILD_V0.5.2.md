# v0.5.2 三语合盘构建记录

冻结源码为 `44d22c66b959ba8289d63908b1d1efdf02b7f7a3`。初版、The Best、SP 的简体、台湾及香港输入均与源码提交一致。[九份输入回执](../manifests/releases/v0.5.2/source-head.json)

| 版本 | 冻结 ISO 字节 | xdelta 字节 | 子 CHD 字节 | ISO SHA-256 |
| --- | ---: | ---: | ---: | --- |
| original | 3,863,324,672 | 107,261,353 | 142,345,437 | `499620c6965788c206efc84a93726b02b93b21a6fb8e273fa0a8c8b92f75dc08` |
| best | 3,860,060,160 | 106,585,910 | 116,894,024 | `3d578a4bf289c043765d5bed43362516e5ca5eb9550440d8e38f7ab30b13bf4c` |
| sp | 4,459,114,496 | 606,760,934 | 438,371,815 | `6240ad79f2fcc4ed8289ad1b9428524006b7c5bf4e4bb0f550dccda6b287fa1a` |

三份 xdelta 均从各自的日文原盘还原。三份子 CHD 均与对应日文父 CHD 解出完整镜像。两种方式的整盘 SHA-256 均与冻结值一致。[补丁清单](../manifests/releases/v0.5.2/patches.json) · [CHD 清单](../manifests/releases/v0.5.2/chd.json)

全量单元测试通过 1144 项，零跳过。[测试记录](../manifests/releases/v0.5.2/tests.json)

ARMSX2 从每张冻结盘冷启动，验证标题语言与画面比例的保存、重启和 SELECT 临时启动。三版分别从地图和整备打开七项内置金手指，核对菜单选择、游戏数值与原生结算指令。三个地区均用手柄触发战斗演出快进。SP 另测资料库、名场面集和港台额外关卡。四曲音乐包沿用同 SHA-256 候选盘的浏览器与本地安装结果及音乐室实测。[运行证据](../manifests/releases/v0.5.2/runtime.json)

本地 Node 解码器和 Chrome 补丁页各还原三份完整镜像。SP 浏览器用时 37.69 秒，每秒采样的 Chrome 进程树 RSS 峰值合计 1,632,796,672 字节，共享页可能重复计入。[浏览器记录](../manifests/releases/v0.5.2/browser.json)

构建入口为 `tools/build_editions.py --release-version 0.5.2 --out-dir build/iso/test/v052-three-final`。随后用 `tools/freeze_release.py --multilang-dir build/iso/test/v052-three-final --version 0.5.2` 冻结。xdelta 和 CHD 工具均使用 `config/release/v0.5.2.json`。
