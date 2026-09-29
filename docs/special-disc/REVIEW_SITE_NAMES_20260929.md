# SP 审阅站名称补齐（2026-09-29）

用户授权提交、推送 SP 名称／编码修复，并在审阅站补上遗漏的机体和机师。

旧导出只选择冻结的“SP 独有原文”筛选结果。本篇已存在的名称即使后来补入 SP 写回契约，仍不会出现在审阅站。现在导出器合并 SP 机体、机师名称写回契约，先核对日文原文、源哈希、分类和原盘位置，再绑定 `native-text.json` 当前译文；不修改冻结快照，也不将镜像误解码结果当作译稿。

| 范围 | 发布前 | 发布后 | 新增 |
| --- | ---: | ---: | ---: |
| 人物 | 11 项／22 字段 | 20 项／40 字段 | 提坦斯 `0331–0339`，9 项／18 字段 |
| 机体名称 | 5 项／6 字段 | 15 项／16 字段 | 10 项／10 字段 |
| SP 专题审阅字段 | 274 | 302 | 28 |

新增机体为赤骑士死神凯恩、青骑士地狱戴恩、比亚路 II／III 世、Gran Σ、强攻型机械天使·德尔塔，以及四个斯派扎名称。原有 274 个字段的译文、源哈希、目标 ID、快照 ID 均保持一致。所有 15 个机体写回槽、38 个机师写回字段均有唯一可审阅目标；武器关系仍使用原有目标和链接。

线上机体页合并了“仅武器有更新”的机体，因此页面总数为 46 项／107 处文字；上表的 15 项／16 字段仅计算机体名称本身。

发布版本：`c0b4033-sp-roster-20260929`。正式语料提交为 `cf54c1effbbab7eb96f1f2cdf1598ba495e74efd`，导出来源无未提交修改。源站沿用现有阿里云发布流程，部署前在线备份并验证审阅数据库，原子切换 release。

- 43 项数据测试、63 项审阅功能测试、8 项部署测试及生产构建通过。
- 9 个变更 JSON 的公网 HTTP 响应与发布包逐字节一致。
- 发布前后 2,996 条用户建议逐条哈希一致；本次没有新增或处理任何线上翻译意见。
- CDN 文件刷新 9 项、前端资源预热 10 项全部 `Complete`。
- 公网浏览器确认新增机体的中日文对照及审阅入口，并确认提坦斯头像、显示名、名字字段正常显示。

入口：[SP 机体](https://srwz.dreamquest.club/sp?section=units)、[SP 人物](https://srwz.dreamquest.club/sp?section=people)。

前端目录不在 Git 仓库内，继续按项目惯例归档四个源文件的增量补丁：[站点源码补丁](../../config/editorial/community-sp-roster-completion-20260929.patch)，使用 `git apply --unidiff-zero`，已在修改前快照上检查。前后源文件哈希、测试与发布收据见 [结构化记录](../../config/editorial/community-sp-roster-completion-20260929.json)。

[公网数据回读](../issue-assets/special-disc-name-audit-20260929/site/public-readback.json)、[CDN 完成回执](../issue-assets/special-disc-name-audit-20260929/site/cdn.json)、[机体画面](../issue-assets/special-disc-name-audit-20260929/site/unit-live.png)、[机师画面](../issue-assets/special-disc-name-audit-20260929/site/pilot-live.png)。站点补齐不改变上一轮验证的 ISO 字节，也不增加游戏运行验收结论。
