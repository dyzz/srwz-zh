# 《超级机器人大战 Z》简体中文版 v0.4.1

v0.4.1 是针对 v0.4.0 严重黑屏问题的修复版，继续提供 Original（初版）与 The Best（廉价版）两个补丁。**使用 v0.4.0 The Best 的玩家请升级。**

## 本次修复

- **The Best 剧情流程黑屏卡死**：修复从“资料库 → 剧情流程”进入后黑屏、按键无响应的问题。现在可以进入流程图、打开章节概要并返回资料库。感谢 **AL-E** 提供反馈。[问题 #21](https://github.com/dyzz/srwz-zh/issues/21)
- **两版搜索说明漏译**：补齐小队奖励中“EN 补给”“干扰功能”的效果说明。感谢 **蒙古王者风行烈** 提供反馈。[问题 #23](https://github.com/dyzz/srwz-zh/issues/23)
- **两版 Q&A 排版**：修正“什么是 SR 点数？”中红色提示的引号与句号换行，保留完整文字和原有颜色；同时修正另外两页的同类坐标问题。感谢 **AL-E** 提供反馈。[问题 #22](https://github.com/dyzz/srwz-zh/issues/22)
- 补齐“充能／回合”贴图、部分菜单帮助，以及小队名称建议表和地图名称表中的中文。地图名称表的普通玩家界面调用位置仍待确认。

v0.4.0 的其他内容继续保留，两版补丁均包含本版适用的全部更新。

## 安装与校验

从 [v0.4.1 GitHub Release](https://github.com/dyzz/srwz-zh/releases/tag/v0.4.1) 下载与自己日文原盘对应的 **一个** `.xdelta`。
请从日文原盘重新应用补丁，不能直接给 v0.4.0 汉化 ISO 打补丁，也不能叠加两版补丁。升级前备份普通记忆卡存档；跨版本即时存档不作兼容承诺。

| 日文原盘 | 下载文件 | 原盘及生成镜像大小 |
| --- | --- | ---: |
| Original，SLPS-25887 / 1.04 | `srwz-zh-v0.4.1-original.xdelta` | 3,758,358,528 字节 |
| The Best，SLPS-73270 / 2.00 | `srwz-zh-v0.4.1-best.xdelta` | 3,755,081,728 字节 |

Original：

```bash
xdelta3 -d -s "original.iso" "srwz-zh-v0.4.1-original.xdelta" "srwz-zh-v0.4.1-original.iso"
```

The Best：

```bash
xdelta3 -d -s "best.iso" "srwz-zh-v0.4.1-best.xdelta" "srwz-zh-v0.4.1-best.iso"
```

| 文件 | SHA-256 |
| --- | --- |
| Original 日文原盘 | `ddbedefc0061213c50928fb213a7fb277c0345f01dab7386adc0383638a78cd2` |
| Original v0.4.1 中文镜像 | `7ee310d80d6167a85ab4a4fe4ea373df45817e02b0ebd1838f4506e1fdcea6e6` |
| The Best 日文原盘 | `950e2759d0d7482387d97d6df31325d9e352097a23e0bb4724073d1538d8cf77` |
| The Best v0.4.1 中文镜像 | `d7a92841d3981ef0fb59d67f1f794692103b00730d6936fdec767a216ab6af9c` |

本项目只分发补丁，不提供游戏 ISO。补丁大小、SHA-256 及实际还原结果见 [补丁清单](https://github.com/dyzz/srwz-zh/blob/v0.4.1/manifests/releases/v0.4.1/patches.json)。

## 验证范围

两版均完成同批源码构建、最终 ISO 静态内容回读及 xdelta 实际还原校验。最终 Best 发布镜像通过 LRPS2 剧情流程回归：进入、返回、再次进入、打开与关闭章节概要、再次返回资料库。两版最终镜像的 SR 点数 Q&A 页面也已有 LRPS2 验收记录。

搜索说明已在此前修复镜像上完成两版 LRPS2 验证；新增菜单帮助、名称表及充能贴图目前完成静态回读，未逐项运行验收。剩余 Q&A 标点排版候选继续在 [问题 #24](https://github.com/dyzz/srwz-zh/issues/24) 跟进。全路线、全部分支及所有存档兼容未作保证；本次未执行 PCSX2。

构建、运行凭据及精确制品身份见 [v0.4.1 构建与发布记录](https://github.com/dyzz/srwz-zh/blob/v0.4.1/docs/RELEASE_BUILD_V0.4.1.md)。
