# SP 审阅站按机体补齐武器（2026-09-29）

按用户要求，收录机体后列出它的全部武器名称，与本篇或其他机体共用的名称只作标记，不再过滤。

导出先固定专题机体集合（已有机体名称条目及原有 SP 武器的机体），再从原盘 `COMPDATA` 读取每个机体的 21 个武器槽和每条武器记录的简称、全称指针。共用名称不会继续拉入其他无关机体。同一文本指针保持一个审阅目标，在所有对应机体下展示；按原始槽位排序。

- 机体条目仍为 46 项。
- 武器名称字段从 91 增至 220，补回 129 处本篇共用名称；简称和全称分别计数。
- 原有 302 个审阅字段（ID、原文、译文、基准与定位）逐字段保持一致；专题总字段为 431。
- 共用字段以日文原文 SHA-256 唯一绑定本篇 `corpus/zh/menu/weapons.json` 当前译稿及固定基准，已有 SP 审订覆盖仍优先。页面显示“共用名称”，区分与本篇共用和多机体共用。
- XAN 的顺序为苦无、光子垫攻击、恶薙之剑、雅邦忍法。其中光子垫攻击标注与本篇及其他机体共用。它沿用本篇当前译稿；此次仅更新审阅站，不改 ISO。

验证：44 项数据测试、63 项审阅测试、8 项部署测试通过；新增原盘检查逐机体覆盖全部非空槽的两个文本指针，故意删掉光子垫名称时导出必须失败。修改文件的 ESLint 与生产构建通过。完整 TypeScript 检查仍报告未修改的 `scripts/review-store.test.ts` 中 5 处既有 unknown-body 错误，本次修改文件没有类型错误。

发布版本：`4deee8a-sp-complete-weapons-20260929`。部署前在线备份及数据库完整性检查通过，原子切换后公网 JSON 与发布包逐字节一致。发布前后 2,996 条用户建议逐条哈希一致。CDN 刷新 1 个数据 URL、预热 11 个前端资源，均为 Complete。

公网浏览器确认 XAN 四项按槽位顺序显示，共用标记及中日文正常；点击光子垫攻击的“提出修改”打开正确的审阅弹窗，未提交测试意见。[线上 XAN](https://srwz.dreamquest.club/sp?section=units&entry=sd%2Fcompdata%2F84AC8)、[公网回读](../issue-assets/special-disc-complete-weapons-20260929/public-readback.json)、[CDN 回执](../issue-assets/special-disc-complete-weapons-20260929/cdn.json)、[上线截图](../issue-assets/special-disc-complete-weapons-20260929/xan-live.png)。

[源码增量补丁](../../config/editorial/community-sp-complete-weapons-20260929.patch)在修改前快照上通过 `git apply --unidiff-zero --check`；[源文件哈希和验证记录](../../config/editorial/community-sp-complete-weapons-20260929.json)。
