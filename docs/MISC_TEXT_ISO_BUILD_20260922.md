# 零散文本三版 ISO 构建与提交（2026-09-22）

用户授权：将本篇 Original、The Best、SP 的已审定修改写入 ISO 并 commit；不更新审阅站。本次未推送远端。

## 文本范围

- Original / BEST：104 个逻辑条目、133 处语料引用，含菜单、系统与说明、教程及“选择排序”图片。
- SP：100 项变更（97 个固定文本位置、2 个教程页面、1 个图片单元）。保留 SP 已独立审定的“边框闪烁”。
- 保留“记忆卡、回合、机师、集市”和“对自己进行一次援护攻击”。BGM 曲名、小队名、地形名及此前排除的语料未纳入本轮重新校订。
- 原审阅 JSON、组件报告保留审阅阶段的哈希和“尚未写入 ISO”状态；本文及三版 edition receipt 记录后续 ISO 交付状态。审阅站未重新渲染、未发布更新。

## 构建所需修复

1. 原提交的 `story/002/dialogue/02.01/0017` 遗漏 `《乌兹米》` 链接标记；仅补回标记，保留中文措辞。对照原盘检查全部 111 条含链接剧情，修复后无异常。
2. 原提交的 `battle:19488` 遗漏原有换行控制符；恢复为“能用好这个的\n　也就我和老把头了！”。全部 25,708 条战斗文本的换行及控制符检查通过。
3. ISO 回读器的两项硬编码预期同步已审定的“无法战斗（P系）”及兰德介绍；容量、布局与码点约束仍然保留。
4. 芜使用新增码点 `97DA`。兰德介绍的“档、经、营、个、热、过”增加默认字宽别名，保持原主码点不变。对应别名依次为 `97DB、97E4、97E8、97E9、97EC、97EF`。已有映射及字形像素不变；SP 与本篇同步字库。
5. 字库兼容校验按迁移目标码点查字，不再将一个字的多个合法码点折叠成一个；原有映射正确时通过，64 个错误目标映射变体全部拒绝。
6. 字库构建链刷新 runtime-keyword LIBRARY 清单时，同步刷新其 archive 文件锁，避免字体变化后继续使用旧哈希。SP 输入锁另补入独立教程排版文件。

7. SP Q&A 的旧字串必须用同时保留主码点与别名的完整表解码；新增别名不能导致旧码点丢失。文字、颜色、样式及元数据仍严格核对，只允许相同文字重新编码。补充原始 canary 回读、语义保持、重复写入不变及非法输入拒绝测试；不修改 Q&A 语料。

## 验证证据

- 81 项相关自动测试通过（文本、菜单、图片、字体、SP 回读及构建链）。
- 字库覆盖缺字为 0；3,532 个主映射、54 个别名。SP 与原先字库解码比较，仅 7 个声明的字形槽发生变化。
- 组件审阅证据：`work/reviews/main-misc-reviewed-20260922/`、`work/reviews/main-sp-misc-sync-20260922/`。
- 本轮构建、原盘扫描、别名反向检查、字形差量及测试日志：`work/reviews/misc-iso-commit-20260922/`。
- 静态构建与 ISO 内容回读不代表 PCSX2 游戏运行验收；本轮未运行游戏。

构建源码提交：`b1a948490b3469af3e91cf2effd326bec63ee498`。

## 最终 ISO 与回读结果

输入快照：`39aeab724a8062b376974cc8c201e49bc8c41757728bfa86ceb3a32686a9cec6`。三版最终语义回读均通过，`verify_editions.py` 已核对实际 ISO 的大小、SHA-256、输入快照和独立回读凭据。

| 版本 | ISO | 大小（字节） | SHA-256 |
| --- | --- | ---: | --- |
| original | `build/iso/zh-release-original/current-original.iso` | 3758358528 | `787a9377b14f68057d1c69e01e804a05eef48a260e8df200afb1f2b0182a04dd` |
| best | `build/iso/zh-release-best/current-best.iso` | 3755081728 | `9e7bf35284a58df7c87f7c073e33d665ed6e2a934d4189e099027cf354acc620` |
| sp | `build/iso/special-disc/sp-current.iso` | 3791781888 | `939ec7c5192a7a7c84adfcaa4984bce51e458cf25f5d5bf1582fe98f6c17e07d` |

Original / BEST 在最终源码重建后与上一轮通过回读的镜像逐哈希一致；SP 完整构建与合成预检镜像逐哈希一致。

三版汇总凭据：`manifests/editions/misc-text-20260922.json`；当前指针：`manifests/editions/{original,best,sp}/current.json`。

复核命令：

```sh
/Users/nate/miniconda3/bin/python3 tools/verify_editions.py --manifest manifests/editions/misc-text-20260922.json
```

提交仅包含本轮语料、字库配置、必要构建/验证修复、测试、导出/审阅工具和构建凭据；ISO 保留本地。其他发布说明、SP 规划和图集研究文件的未提交工作保持原样。

审阅站 4 个文件的 SHA-256 未变化。
