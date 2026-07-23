# 语料约定

`ja/` 保存从固定原版提取并经哈希确认的日文基准；不得人工改写。

`zh/` 保存中文译文。每条译文至少应记录稳定 ID、来源文件、分区、指针或条目索引、日文原文、中文、状态、来源哈希和备注。

推荐状态：

```text
todo -> draft -> reviewed -> final -> runtime_verified
```

只有 `runtime_verified` 表示已经在游戏正常流程中确认显示。
