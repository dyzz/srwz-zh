# Special Disc 当前镜像

唯一日常输出是 `build/iso/special-disc/sp-current.iso`，同名 JSON 记录其身份和验证范围。

2026-09-20 已集成方块 skip，完整构建默认安装，现有镜像可用
`update_current_skip.py` 原子更新。保持原生清理、伤害显示和资源等待；
[适配与验证记录](SQUARE_SKIP.md) 分别记录静态／ISO 回读与 LRPS2 覆盖范围。
2026-09-20 从开场标题修复候选提升后，追加 7 个共享字形并修复沿用本篇的世界地图标题。
随后保留 Q&A 排版更新，将两种汉化点号换为日版原始字形。
点号更新及编号运行验证时 SHA-256：`f44d0bdabfe15f8b8cd0ce8fdea053fc4dd13ed365aa44445a2d86c723174bc1`。
其后并行进行的标题更新保留了相同点号字库；最新整体镜像身份以同名 JSON 为准。

- `build_full_text.py` 原子更新 current；标题修补器默认同一路径，已有正确标题时只验证。
- `update_current_font.py --previous-proposal <旧码表>` 只允许追加映射和新字槽像素，验证音频
  搬移内容、旧字形及 ISO 非目标字节不变后原子更新 current。
- `update_period_glyphs.py` 专门将 `.` / `．` 的两个汉化字槽复制为日版 `8144` 像素，
  不改编码、字宽或文字；完整共享字库构建也采用相同规则。
- `update_current_map_titles.py` 修复 10 张沿用本篇的地图标题；完整覆盖冻结的标题像素，
  避免按零散差异段迁移时漏掉日文字形或残留笔画。完整构建也消费同一图片绑定。
- `build_preview.py` 与 `build_text_candidate.py` 仅更新中间差分基线，不再保留可选 ISO。
- 基线位于 `work/build/special-disc/baselines/{preview,text-canary}.{json,xdelta}`。
  `baselines.py` 校验原盘、差分及还原结果哈希，只在进程私有临时目录还原，正常退出清除。
  原盘仍从 `config/products/special-disc/disc-inventory.json` 读取，不属于可清理候选。
- 截图、旧运行回执和历史 manifest 不改写成新的运行证据。旧路径的迁移记录见
  `work/cleanup/sp-current-20260920/receipt.json`；9 份旧镜像已可恢复地移入废纸篓。
- 当前 SP 语料缺字扫描为零；全量审阅语料重建仍有 3 条流程图摘要和 1 页旁白的行数超限。
  字库和图片的增量更新没有改写这些句子，历史组件回执也不代表全量语料已重新写入。

字体追加及地图标题修复时的静态验证：原有 3518 条主映射、48 条别名、36 条兼容映射及旧字形像素不变；13 张地图标题
（10 张继承、3 张 SP 新增）均从 current 解压回读并与冻结中文图片一致。
ISO 大小和 LBA 不变，10 个记录成员的哈希与当前 manifest 一致。
该轮镜像 LRPS2 回归已看到纽瓦克世界地图中文标题、司令室地点字幕、“发令”关卡标题
及战术地图；源记忆卡未改写。其他地图标题仅完成静态／ISO 回读，PCSX2 人工验收待做。
详细回执见 `work/analysis/sp-font-mapnames-20260920/` 和
`work/verification/sp-current-font-20260920/`、`work/verification/sp-current-world-map-titles/`。

本轮点号更新仅改变字槽 2836（`8FD4`）及 4467（`9873`），字形与日版原始 `8144`
逐字节一致。完整共享字库重建和 SP 增量更新的解压字体完全相同；ISO 字体压缩区之外的
3,791,154,992 字节不变，EXE、音频、其他图片与文本不变。静态回执见
`work/verification/native-period-sp/readback.json`，共享组件验证见
`work/build/native-period-20260920/manifest.json`。本篇 Original／Best 既有镜像未在本轮重建。
更新后 LRPS2 已复跑 SP 第一话胜败条件：点号向左约 6 个画面像素，数字及其后的中文
像素完全不变，源记忆卡不变。截图与度量见 `work/verification/native-period-sp/`，
运行回执见 `work/runtime/lrps2/sp-native-period-20260920/run/receipt.json`。
其他使用页面未逐页运行验收，PCSX2 人工验收仍待做。
