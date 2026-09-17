# 《超级机器人大战 Z》简体中文版 v0.4.2

v0.4.2 是 The Best 版地图事件故障的紧急修复版本。**正在使用旧版 The Best 汉化的玩家请升级，尤其是即将进入第 47 话的玩家。**

修复第 47 话“我们的去向”在标题后黑屏，以及“我的未来，你的未来”相关关卡段落进入地图后缺少机体和开场事件的问题。原因是 Best 构建迁移时错误覆盖了两处地图事件函数表；现已分别恢复全部事件目标，并修正程序读取表的位置。

感谢用户“贴吧用户_a6bM8ty”反馈本次黑屏问题。

此次发布同时收录 v0.4.1 之后已经合入的社区译文修订、术语统一、图鉴姓名及改名显示修复，以及关卡标题、阵型／说明标题和文字宽度相关调整。

## 选择补丁

从 [v0.4.2 GitHub Release](https://github.com/dyzz/srwz-zh/releases/tag/v0.4.2) 下载与自己的日文原盘对应的 **一份** `.xdelta`。

**默认推荐不带方块 skip 的版本。** 带 `-skip` 的可选版本额外启用战斗演出跳过；是否使用该功能与本次关卡修复无关，四个版本均包含修复。

带 skip 版的效果类似《破界篇》引入的快进：战斗动画中**按住方块键（□）**，跳到战斗动画的下一个阶段。

| 日文原盘 | 不带方块 skip（默认推荐） | 带方块 skip（可选） |
| --- | --- | --- |
| Original，SLPS-25887 / 1.04 | `srwz-zh-v0.4.2-original.xdelta` | `srwz-zh-v0.4.2-original-skip.xdelta` |
| The Best，SLPS-73270 / 2.00 | `srwz-zh-v0.4.2-best.xdelta` | `srwz-zh-v0.4.2-best-skip.xdelta` |

四份补丁都直接用于对应的**未修改日文原盘 ISO**。不要在旧汉化 ISO 上打补丁，也不要先打普通版再叠加 skip 版。

例如，使用日文 Best 原盘生成推荐版本：

```sh
xdelta3 -d -s "best.iso" "srwz-zh-v0.4.2-best.xdelta" "srwz-zh-v0.4.2-best.iso"
```

使用 Original 原盘生成可选 skip 版本：

```sh
xdelta3 -d -s "original.iso" "srwz-zh-v0.4.2-original-skip.xdelta" "srwz-zh-v0.4.2-original-skip.iso"
```

原盘身份及生成镜像的 SHA-256 见 [发布配置](https://github.com/dyzz/srwz-zh/blob/v0.4.2/config/release/v0.4.2.json)，补丁身份及实际还原结果见 [补丁清单](https://github.com/dyzz/srwz-zh/blob/v0.4.2/manifests/releases/v0.4.2/patches.json)。本项目只分发补丁，不提供日文原盘或完整 ISO。

## 存档与验证范围

请先备份普通记忆卡存档，换用新镜像后从普通存档进入关卡。即时存档可能保留旧版已经载入的程序和关卡数据，不适合用来判断修复效果。

本次对全部 205 个 STAGE 块执行静态检查，其中 182 个块的 184 张已识别地图事件表与原生 Best 对照。两处故障已使用 LRPS2 进行运行对照；具体最终镜像、运行检查点及打包验证见 [v0.4.2 构建与发布记录](https://github.com/dyzz/srwz-zh/blob/v0.4.2/docs/RELEASE_BUILD_V0.4.2.md)。这不代表两关完整通关或全路线运行验收；本轮没有重新执行 PCSX2 手动验收。

## 本地 CHD

本地构建工具准备两个日文原盘父 CHD，以及 Original／Best 各自不带 skip、带 skip 的四个中文子 CHD。子 CHD 需要匹配的日文父 CHD 放在同一目录；四个子 CHD 都直接依赖日文父盘，不互相依赖。父盘仅在本地准备，不作为 GitHub Release 附件发布。
