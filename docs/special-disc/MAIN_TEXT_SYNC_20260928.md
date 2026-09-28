# SP 对齐本篇／BEST 最新文本（2026-09-28）

以当前本篇／BEST 共用语料为来源，检查上一份已验证 SP 输入快照之后的变更。

## 文本同步

- 刷新 `stage-context-reuse.json` 中 18 条明确绑定本篇位置、且对应本篇记录在旧 SP 快照之后发生变化的译文。全部位于 SP STAGE 023。
- 每条写回均核对 SP 原文 SHA-256、本篇语料路径及本篇原生 ID。保留既有绑定位置与原文，不按同源字符串的任意首项选译文。
- 同步更新 `config/editions/sp/inputs.json` 的绑定配置大小与 SHA-256。
- 本篇战斗字幕由 SP 的 SRVC 写入器直接读取。“我来夺回”和两条“苦痛咆哮”在 SP 中各有 4 个原生位置，12 处最终 ISO 字幕均与本篇最新语料一致。本篇 `battle:20163` 的完整“三重魔神剑！！”日文台词不在 SP SRVC 中，不计为同步成功项。
- 解码旧 SP 当前盘确认武器名已为“三重魔神剑”，无需增加重复覆盖。本轮构建同时消费已确认的 SP“恶薙之剑”语料。
- SP 独立审定文本与本篇的其他历史措辞差异保留；教程、Q&A、图片及图鉴不做无依据的整篇替换。

逐条前后文本、本篇来源及旧 SP 回执见
[`main-sync-20260928.json`](../../config/editorial/special-disc/main-sync-20260928.json)。

## 验证

STAGE 写回专项 16 项测试通过。三版使用同一输入批次重新构建，耗时 199.681 秒；SP 组件阶段为 53.644 秒。

- 三版静态内容回读及 `verify_editions.py` 批次验证通过。
- SP 完整独立回读通过，覆盖 42 个 STAGE 块与 10,464 个剧情／阵型绑定；未消费目标和未分配显示字符均为 0。
- 对比旧 SP 组件，译文发生变化的剧情绑定恰好为上述 18 条，其他剧情绑定变化为 0；逐条检查新译文及实际排版输出。
- 从最终 ISO 独立解析 SRVC，验证上述 12 个字幕位置；解码 COMPDATA 核对两个武器名。
- 三版当前盘及 `build/iso/daily-test/current-{original,best,sp}-skip.iso` 均已更新，日常副本身份及 skip 回读通过。

| 版本 | 当前 ISO SHA-256 |
| --- | --- |
| Original | `4af4b17c673509595f171333b907eb69dfbd5e795fc4446f92e92985196c8245` |
| BEST | `bd90e036f7de18804c1173c200f198fa0e0dff87bd775ba4af75f71b12498c90` |
| SP | `30abf27210a72ab424cc7ae5d7ce15fccfa62cc67f4cd9836059e888882a387f` |

输入摘要为 `ab48af8c777c5b3687766ac3e99d669c2f8733fd75c94e2ffb74b22e45a9b72d`。
批次回执位于 `work/editions/<输入摘要>/original-best-sp.json`；各版当前回执位于
`manifests/editions/{original,best,sp}/current.json`。逐项验证结果另写入上述编辑记录的 `validation` 字段。

新镜像的运行验收独立记账；静态写回、构建及回读不构成 PCSX2 人工验收。
