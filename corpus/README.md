# 语料约定

`ja/` 保存从固定原版提取并经哈希确认的日文基准；不得人工改写。

`zh/` 保存中文译文。每条译文至少应记录稳定 ID、来源文件、分区、指针或条目索引、日文原文、中文、状态、来源哈希和备注。

当前日文基准通过：

```bash
python3 tools/export_srwz_corpus.py --force
```

导出到被 Git 忽略的 `work/corpus/srwz-corpus.jsonl`。它包含 94,189 条日文
原文，不进入 Git；`manifests/corpus-export.json` 只保存计数和聚合哈希。
`corpus/zh/` 后续只提交中文、稳定 ID、source text SHA-256、状态和备注，不重复
提交提取的日文正文。导出过程还会严格序列化并重新解码全部条目，当前结果为
94,189/94,189。

首条正式记录已位于 `zh/menu.json`，由
`config/build-profiles/canary-menu.json` 选择。可执行 reconciliation：

```bash
python3 tools/validate_build_profile.py
```

该门会把中文记录与 SurfaceSpec 的稳定 ID/source hash 对齐，并检查状态、
codebook、可编码性和定长要求。`zh/` 中出现第二份 `source_text` 会直接失败。

推荐状态：

```text
todo -> draft -> reviewed -> final -> runtime_verified
```

只有 `runtime_verified` 表示已经在游戏正常流程中确认显示。

字段和写回验证规则见 `docs/PRODUCTION_PIPELINE.md` 和
`docs/WRITEBACK_CONTRACT.md`。
