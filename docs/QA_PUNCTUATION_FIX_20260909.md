# Q&A 红色 SR 点数提示与句号修复

2026-09-09，关联 AL-E 反馈和 [issue #22](https://github.com/dyzz/srwz-zh/issues/22)。
状态：源码修复、完整双版构建、ISO 回读及两版目标页面 LRPS2 验收通过。

## 修复行为

“什么是 SR 点数？”中，红色 `“SR点数获得不可”` 与后面的普通色句号现在一起决定
是否换行。完整红色提示移到下一行，左右引号均显示，句号紧随其后且保持普通色。
没有删字、缩写、取消颜色，也没有把句号改成红色。

排版器在同一段落内跨过空记录，识别紧随正文的纯闭合标点记录；前文与标点合在
一行放得下时，预留它们的总宽度。各条记录仍分别输出，原样式和文本保持不变。
固定表格列、段落边界及放不下的长记录不适用此规则。

## 改动与验证

完整扫描与双版 ISO 逐条回读确认：102 页、2609 条记录中只改变 3 页的 6 条坐标。
将这 6 条坐标恢复为旧值后，解压的整个 Q&A 块与 v0.4.0 逐字节一致，证明所有文本、
颜色、记录数量、目录、贴图和其他非坐标内容均保留。

| 页面 | 正文记录的新坐标 | 句号的新坐标 |
| --- | --- | --- |
| 031，机体减伤 | `record/013`：`(19,58)` | `record/014`：`(57,58)` |
| 051，修理说明 | `record/018`：`(19,113)` | `record/019`：`(171,113)` |
| 093，SR 点数 | `record/013`：`(19,91)` | `record/014`：`(209,91)` |

4 个回归测试覆盖实际 SR 点数记录、空记录衔接、段落边界和固定表格列；完整测试
263 项通过。双版完整构建及 `verify_editions.py` 的输入／回读／实际 ISO 绑定检查通过。

两版分别冷启动 LRPS2，进入“其他 → 关于 SR 点数 → 什么是 SR 点数？”，第 3900 帧
及滚动返回顶部后的第 4500 帧均已查看：红色两端引号完整、句号同一行、颜色正确。
答案滚动和逐层返回资料库正常；源记忆卡哈希未变。按照用户确认的标准，LRPS2
通过即视为验收通过，无需 PCSX2 补验。031／051 页本轮是全量静态回读覆盖，未单独
运行其答案页面。

| 当前镜像 | SHA-256 |
| --- | --- |
| Original | `7ee310d80d6167a85ab4a4fe4ea373df45817e02b0ebd1838f4506e1fdcea6e6` |
| Best | `d7a92841d3981ef0fb59d67f1f794692103b00730d6936fdec767a216ab6af9c` |

两版 Q&A 块 SHA-256 均为
`8f92e516a961b483108f794ba636f6112b878d0f51b1f1f180ec600491646ef9`。
Original 也已按生产配置无刷新锁重建到 `build/iso/zh-release-full-story/current-original.iso`，
与隔离构建输出哈希完全一致；Best 保存在 `build/iso/zh-release-best/current-best.iso`。
v0.4.0 冻结发行镜像不变。

## 剩余候选与凭据

之前的 47 处行首标点候选中有 3 处由本次规则修正，剩余 30 页、44 处候选仍需
分别核查，转入 [issue #24](https://github.com/dyzz/srwz-zh/issues/24)。包括
`page/030/record/018`、`page/064/record/052`、`page/100/record/029`
三个纯句号行，涉及固定列或超长正文，不能当作本次已经修复或验收通过。

- 机器记录：`manifests/qa-punctuation-fix-20260909.json`。
- 双版构建凭据：`work/editions/3e738e23a2b3dc3962b06bf07ea4406d0179acef242034fe7e1bace6f24f6746/original-best.json`。
- LRPS2 截图及 receipt：`work/runtime/lrps2/qa-punctuation-fix-20260909/{original,best}/`。
- 静态坐标对比、回读脚本与构建日志：`work/analysis/qa-punctuation-fix-20260909/`。

构建本身的 receipt 继续保留 `runtime=not_tested`；本文件及独立运行凭据记录后续的
LRPS2 验收，避免将静态检查冒充运行检查。

验收后按六个 ISO 槽位契约清理了本批的 5 份已核对哈希的重复镜像，清单为
`work/analysis/qa-punctuation-fix-20260909/iso-cleanup.json`。运行记录中的 Original
隔离输出路径作为历史凭据保留；长期镜像为上述 `zh-release-full-story/current-original.iso`。
重放历史双版批次验证前，可按相同哈希临时复制回隔离输出路径，验证后再移除副本。
