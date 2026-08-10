# 全局术语资产

`corpus/glossary/*.json` 是便于按领域维护的组件，但在构建和审核时必须视为**一个全局注册表**，不得由剧情、图鉴、菜单或战斗文本各自维护另一份定稿。

确定性约束如下：

- `id` 是术语的全局身份；同一 `id` 只能有一个 `translation`。
- 多个组件可以补充同一 `id` 的来源词、领域和旧译，但若定稿译名不同，加载立即失败。
- `deprecated_translations` 记录旧译；默认只在日文来源已绑定该术语时替换，只有明确标为 `variant_scope: "global"` 的无歧义旧译才允许全局替换。
- 只有 `status: "approved"` 且 `enforce: true` 的术语构成正式语料的硬约束。
- 所有正式中文条目的 `glossary_refs` 必须能在全局注册表中解析；绑定到硬约束术语的译文必须包含其定稿形式（版面换行不影响判断）。

统一实现位于 `tools/srwz/glossary.py`，门禁位于 `tests/test_global_glossary.py`。图鉴审核配置只保留文风和展示规则，不得复制术语决定。
