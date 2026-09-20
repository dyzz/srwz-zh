# Special Disc 当前镜像

唯一日常输出是 `build/iso/special-disc/sp-current.iso`，同名 JSON 记录其身份和验证范围。
2026-09-20 从开场标题修复候选提升后，追加 7 个共享字形并修复沿用本篇的世界地图标题。
当前 SHA-256：`d8c91e60993a4fb104632dfb1581a7750c72686389235ffd08bd25c8e6dee21e`。

- `build_full_text.py` 原子更新 current；标题修补器默认同一路径，已有正确标题时只验证。
- `update_current_font.py --previous-proposal <旧码表>` 只允许追加映射和新字槽像素，验证音频
  搬移内容、旧字形及 ISO 非目标字节不变后原子更新 current。
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

静态验证：原有 3518 条主映射、48 条别名、36 条兼容映射及旧字形像素不变；13 张地图标题
（10 张继承、3 张 SP 新增）均从 current 解压回读并与冻结中文图片一致。
ISO 大小和 LBA 不变，10 个记录成员的哈希与当前 manifest 一致。
最终镜像 LRPS2 回归已看到纽瓦克世界地图中文标题、司令室地点字幕、“发令”关卡标题
及战术地图；源记忆卡未改写。其他地图标题仅完成静态／ISO 回读，PCSX2 人工验收待做。
详细回执见 `work/analysis/sp-font-mapnames-20260920/` 和
`work/verification/sp-current-font-20260920/`、`work/verification/sp-current-world-map-titles/`。
