# 2026-09-29 晚间社区投稿发布记录

## 确认与写回

- 原批次39条：33条投稿原样采纳，6条分歧均由用户确认。
- 构建期间新增1条，删除“君の太陽”现译中无直接原文依据的“超重神”，投稿原样采纳。
- 合计40条：36条直接采纳，4条按用户确认的最终方案处理；没有自动拒绝投稿。
- 丹泽尔和奎因斯坦采用本轮用户确认的自定义译文，覆盖先前推荐。
- “恶薙之剑”保留；下列用户批准的回复已发布且核对只有一次。
- 原样采纳的阿克艾里昂三形态及作品名同步关联名称与自动演示标题。
- 两条第113话对白仅调整换行，保持“阿美利亚”大陆名完整；文字内容不变。

> 原文仅作片假名「アクナギノツルギ」，官方汉字表记未确认。日文机战Wiki推测为「悪薙の剣」；从「クサナギノツルギ（草薙之剑）」的命名结构及XAN-斩-的忍者／武者设计来看，「悪薙」较有依据，因此译作“恶薙之剑”。

语料及审阅站提交：`6e66a1c2364da04c73098e53934a3e05a8dc4a0a`。

投稿写回记录：

- `config/editorial/community-20260929-night.json`
- `config/editorial/community-20260929-late-sun.json`
- `config/editorial/community-layout-20260929.json`

## ISO与验证

输入摘要：`ac115af2d8c6115d3c7f90112eb5c1bb910ec696ef957a03b764c1f9182965ab`。

| 版本 | 本地当前ISO | SHA-256 |
| --- | --- | --- |
| original | `build/iso/zh-release-original/current-original.iso` | `530f349a616938ecda3f705095df614bf2035cb2c475b414754ff6c80a9665a3` |
| best | `build/iso/zh-release-best/current-best.iso` | `ba851a0222dbecf7e3430cef7d1979a688871722992c069529dfca3b816a0900` |
| sp | `build/iso/special-disc/sp-current.iso` | `5036dfc7218d131c9bca4b58b13aa0b89c19884739bbd24bddf1c524dcf68e52` |

三版均完成构建、独立回读与发布后复验；日常测试副本及跳过动画补丁读回按各版receipt核对。ISO只保留在本地。

- 审阅站相关导出与SP绑定检查44项通过。
- 已确认40条线上当前译文与选定译文一致，普通公开site-index已为上述语料提交。
- 核对时线上待处理为0；既有「アゲハ隊」仍在“有疑问”，后续定稿。
- 按用户要求未运行全量测试。
- 本轮未做PCSX2或人工运行验证；runtime仍为`not_tested`。

构建及发布证据：`manifests/editions/community-20260929-night.json`及其引用的三版receipt、batch manifest与独立回读记录。
本地审阅原始快照和6项用户确认记录保存在`srwz-community-web/work/pending-review-20260929-230013/`。
