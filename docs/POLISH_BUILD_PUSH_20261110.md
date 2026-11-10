# 润色定稿：本篇与 SP 构建交付

2026-11-10 使用最新构建入口执行：

```sh
python3.13 tools/build_editions.py --editions original,sp
```

两版均通过构建与独立回读，总墙钟耗时 96.177 秒；本篇 94.744 秒，SP 93.489 秒，二者并行。本轮没有重建 Best。

| 版本 | 当前 ISO | SHA-256 |
|---|---|---|
| 本篇 Original | `build/iso/zh-release-original/current-original.iso` | `061443c5aafc95cdb2f5c5dd3e6690f7e74bde0b940a1aa51cc1abd30eef1ed6` |
| SP | `build/iso/special-disc/sp-current.iso` | `af82f520a45ecca170ceb1c93c6e0af73af96db2a224c0de3d3c2584f4d30463` |

版本标记保持 v0.5.0-rc。已确认的 1,588 个最终文本条目均在语料；84 条仅因地图宽度重排。包含三处原始战斗触发对象修复、SP 名场面集合的地图验宽，以及当前构建所需的 SP 项目说明字形修复。原审阅／确认记录保留。

## ARMSX2 抽查

使用本轮输出 ISO，Metal 4×，从冷启动操作，不注入文本、不加载旧即时存档：

- 本篇：开始新游戏、选择兰德、进入开场中文剧情并推进对话。
- SP：进入战斗鉴赏、启动战斗，看到实际战斗动画和字幕。

截图在 `docs/issue-assets/polish-build-final-20261110/`，命令与运行记录在 `work/review/polish-build-final-20261110/`。这属于 ARMSX2 运行抽查，与构建／独立回读证据分开；不代表全部剧情、读档 STAGE 路径或全部名场面已逐项实机验收。

## 输入与提交

冻结输入摘要：`27eed9e560c7ab5891490add2356caa0fcde21e33e8a3a2f1d15f6e66a29c0a9`。构建开始后才拆分提交，因此自动回执中的 source_head 是构建开始时的 HEAD；905 个输入文件在提交后重新核对，全部仍匹配冻结快照。详情见同目录资产中的 `receipt.json`。

润色、触发修复、名场面验宽、SP 字形及交付回执分别提交。ISO 本体不加入 Git；无关视频、实验材料及文档改动留在原工作区。

## 测试

`python3.13 -m unittest discover -s tests`：986 项，978 项通过、8 项跳过，无失败，耗时 198.069 秒。两版最终 ISO 另行重算 SHA-256，均与回执一致。
