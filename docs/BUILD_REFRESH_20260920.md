# 2026-09-20 三版当前 ISO 重建

统一入口 `python3 tools/build_editions.py` 已实际完成 Original、The Best、SP 的同批构建。
三版使用输入快照 `8beea19f6c3bf422b79b17cfa1dc41c73bf8405885aee66f79b6e467f411965e`。
批次状态为 `requested_editions_static_validated_runtime_pending`，独立核验结果为
`edition_batch_receipt_integrity_passed`。

| 版本 | 当前 ISO | SHA-256 |
| --- | --- | --- |
| Original | `build/iso/zh-release-original/current-original.iso` | `72639bb958258006f3262a911c77da323cf0d809943fa44dacf555831f69d061` |
| The Best | `build/iso/zh-release-best/current-best.iso` | `64215de32db84b1ee69fa86b90f69c0ae127b9f0438f89b4368407e2a6e076bb` |
| SP | `build/iso/special-disc/sp-current.iso` | `faf9d218816f79545ec703f3669714443baf82e740131cb97fbe9da3bbe217f1` |

## SP 接入时修复的构建问题

- 将原生盘身份、字体码表、基线差分和必要剧情绑定纳入锁定依赖与同批输入快照。
- 本篇提取不再误读 SP 的数组型导出配置；私有 mkps2iso 提取目录强制刷新，避免继承旧缓存。
- 正常 SP 图像构建使用冻结索引数据，PNG 预览改为显式 `--previews`，不再阻塞无 Pillow 的生产环境。
- 保留当前指令标题和 DATA HELP「项目说明」资源，未重新启用已撤回的其他标题实验。
- 修正三个流程图概要、三个菜单简介、一个同乘者标签和一条战斗台词的容量溢出。
  保留 `T-Bone`、`Dove`、`013`、话数等可见拉丁字母与数字；同乘者标签改为「同乘」。
- 结尾旁白仅合并两个连续语意段落，保留全部文字、空行与摘录署名，适配原生 13 行。
- HSFC 使用 Rust maximum 的两字节匹配，压缩后为 **5071 / 5072 字节**；没有扩大槽位或移动后续 LBA。

SP 独立回读覆盖 8754 条 STAGE 文本记录、1338 个编队名称单元、147 个 frame 目标、
1679 次系统文本写入、35 个 ticker 槽位，并核对地形、机体名、武器效果、场景图和标题。
这些是不同维度的计数，不能相加视为唯一翻译条目数。SP 独立构建与随后默认三版构建
产出的 ISO SHA-256 相同。

## Q&A 与运行证据边界

三版 Q&A 的解码字节与本次重建前完全一致，覆盖文本、坐标、样式和控制元数据：

- Original／The Best：`60bd421801bd77d879a5b5e039b45bf09aa4800a51f2abcfd3fd6a05733410be`。
- SP：`20223753576a151322015a30c0a6efc26497bb5d31eb75c6a288ec4c498c5fb3`。

因此本次全量构建没有回退已校订的 Q&A，包括第 12 页的数字排版。
本次未对新整盘执行模拟器或人工验收；此前 Q&A 的运行截图和验收仍绑定其原 ISO 身份，
不升级为这三个新 ISO 的完整运行验收。

## 校验与保留文件

- 统一入口测试 27 项、SP 测试 76 项、Q&A 测试 18 项、双版本发布兼容性测试 10 项通过。
  测试组有交集，不合计为唯一测试数。
- 初次全仓测试运行 423 项：两个既有文案断言失败，另有一个本地旧码表缓存绑定错误。
  初次构建时，码表相关的 Z:Report 测试仅在新构建私有目录复测通过。
- 后续按用户确认同步文案断言：`battle:00113` 保留“可恶！快脱出！”，
  `story/014/dialogue/02.02/0073` 保留“流浪修理工”；语料本身无需修改。
  根目录运行 `python3 tools/prepare_zh_release_font.py --force` 刷新旧编码提案及 readiness 缓存，
  提案与当前 Original 构建工作区的文件逐字节一致（SHA-256：
  `1fea8d6476bff26a6968f2f2eb1e79cf30bd293f4c28dddc18040b3ca27b5713`）。
  未放宽编码表一致性检查；本次修复不改变三个当前 ISO 的内容或运行验收状态。
  根目录完整测试复跑 **425 项：424 项通过、1 项跳过、0 失败、0 错误**。
- 两份本篇子 CHD 位于 `build/chd/current-20260920/`，分别以对应日文 CHD 为父盘。
  已实际还原并核对整个 ISO 哈希，当前 ISO 继续保留供检查。旧发布及此前 Q&A CHD 保留。
- SP 保留 `build/iso/special-disc/sp-current.iso` 一个当前输出，历史构建基线使用已验证差分。

证据文件：

- [同批构建回执](../manifests/editions/current-build-20260920.json)
- [Q&A、CHD、SP 范围与测试汇总](../manifests/editions/refresh-20260920.json)
- [统一构建使用说明](BUILD_EDITIONS.md)

可重新核验当前输出与回执绑定：

```bash
python3 tools/verify_editions.py --manifest manifests/editions/current-build-20260920.json
```
