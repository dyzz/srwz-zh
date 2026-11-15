# 构建后自然文本运行验证（2026-11-15）

使用本次构建的 current ISO，分别以 ARMSX2 runner Metal 4× 冷启动。启动前完整计算 ISO SHA-256，与当前三版构建回执逐一核对通过。只重放控制器按键，未写入测试句、替换字库或修改绘制几何；仅使用当次会话生成的状态。记忆卡由 runner 复制。

[全部 7 张游戏画面](issue-assets/font22-build-runtime-20261115/index.html) · [总览](issue-assets/font22-build-runtime-20261115/overview.png) · [ISO 哈希及实际绘制行记录](issue-assets/font22-build-runtime-20261115/reports.json)

| 版本 | 实际进入场景 | 结果 |
| --- | --- | --- |
| Original | 剧情、滚动 | 截图和绘制 trace 成功 |
| Best | 剧情、梗概、滚动 | 截图和绘制 trace 成功 |
| SP | 战斗、剧情滚动 | 截图和绘制 trace 成功 |

另保留每版冷启动标题截图。完整截图均为 2560×1792。已查看七个画面及剧情、梗概文字裁切，本次观察范围未发现缺字、字形裁切或行间挤压。剧情的续行对齐开引号后的正文；梗概、滚动保留语料本身的段首缩进，与同段自动换行的左边界有意不同。滚动区底边遮住正在入场的后续行，是游戏窗口裁切。

本轮是当前 ISO 的自然文本运行证明，不代替此前的三场景人工混排样例验收，也不声称所有语料和所有关卡均已验证。这是 ARMSX2 runner 证据，不是 PS2 硬件或 PCSX2 手工验收。

复现脚本及会话日志：`work/review/font22-build-runtime-20261115/`。
