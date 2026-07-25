# 语料与写回契约

状态：已建立生产 profile reconciliation、语料导出、严格文本序列化和通用写回原语；MTV_PROS 定长文本
writer、STAGE/MTV_PROS 原生重压缩与归档重建、MTV_PROS 的 SLPS offset
写回已经通过真实样本 dry-run。VT1 第 2 段的两 glyph 替换、归档重建和
SLPS offset 写回也已由静态 canary 完成；开场菜单已从正式
SurfaceSpec、`corpus/zh` 和 codebook 驱动同一 writer。通用 SLPS/COMPDATA 文本池、
STAGE 文本 arena 和通用 VT1 writer 仍需完成。

## 语料边界

```bash
python3 tools/export_srwz_corpus.py --force
```

该命令从 `work/parsed/srwz-data.json` 导出 94,189 条稳定记录到
`work/corpus/srwz-corpus.jsonl`。JSONL 包含日文原文，因此保持在被忽略的
`work/`；可提交的 `manifests/corpus-export.json` 只保存计数和聚合哈希。

每条记录包含：

- 稳定 ID、domain、kind、section 和 ordinal；
- 来源成员及其 SHA-256；
- source text SHA-256；
- stage/chunk scope；
- 指针、目标 offset、embedded HI/LO 或定长 allocation；
- 中文、状态和备注字段。

状态只能按以下方向推进：

```text
todo -> draft -> reviewed -> final -> runtime_verified
```

非 `todo` 状态必须有中文；只有经过实际游戏流程验证后才能使用
`runtime_verified`。`validate_status_transition()` 拒绝状态倒退，并要求进入
`runtime_verified` 时显式提供运行证据标记。

## 文本序列化

`tools/srwz/text.py::encode_text()` 是严格的文本层序列化器，不是压缩器：

- 反向使用固定双字节码表，重复映射固定选择最低 code；
- 支持换行、四类控制码和 lossless `{XX}` 原始字节表示；
- 可传入明确的中文字符→码位 override；
- 未映射字符和未知控制码立即失败；
- 当前 94,189 条解析文本全部满足
  `decode_text(encode_text(text)) == text`。

## 写回 dry-run

`tools/srwz/writeback.py` 提供：

- `PatchPlan`：校验源大小、SHA-256、每处原始字节和唯一写入所有者；
- `PatchOperation`：只允许等长、有前像的修改；
- `AllocationPool`：带 alignment 的文本池分配，溢出立即失败；
- `fit_fixed_allocation()`：定长文本不能截断；
- `rebuild_aligned_archive()`：确定性生成归档数据和包含终点的 offset 表。

`tools/srwz/writers.py` 在这些原语上实现：

- `build_summary_patch_plan()`：按 MTV_PROS 记录原有 `nul` 或 `end`
  终止方式生成定长覆盖，未知 ID 和溢出立即失败；
- `rebuild_codec_archive()`：原生编码每个 decoded chunk、16 字节对齐，
  再逐块解码并检查 consumed、零 padding 和完整 decoded SHA-256；
- `build_executable_offset_patch_plan()`：保持原 SLPS 表形态，兼容
  “只含 chunk start”和“包含 terminal archive size”两种真实布局；
- 所有计划仍校验源 SHA-256、写入前像、边界和唯一 owner。

`tools/srwz/project.py` 位于 writer 之前，负责把 BuildProfile 引用的
SurfaceSpec、中文决策和 codebook reconciliation 成一个只读选择集。writer
不得从 CLI 私有参数或 canary JSON 重新定义译文、offset 或字形分配。当前
字段契约见 `PRODUCTION_PIPELINE.md`。

这些 writer 不直接写原版文件。`validate_srwz_archive_rebuild.py` 全程在内存
构建候选归档和 patched SLPS，只把哈希、计数和聚合大小保存到 `work/`。

## 真实归档验证

```bash
python3 tools/validate_srwz_archive_rebuild.py --force
```

greedy 编码器的真实结果：

- STAGE：205/205 decoded 内容重建后完全一致；新归档 5,869,648 字节，
  206 个 offset 全部 16 字节对齐；
- STAGE offset 表为 824 字节，目标已确认是 `HEDBDY/HB.BIN + 0x7670`；
  当前 `work/` 没有该成员，所以只验证了确定性表数据，没有修改 HB；
- MTV_PROS：14/14 decoded 内容一致；28 条 summary 记录全部经过定长
  identity plan，14/14 decoded chunk 保持字节相同；
- 新 MTV_PROS 为 10,512 字节；15-entry SLPS 表包含 terminal size，
  内存写回后重新读取的 offset 与重建结果完全一致。

可提交聚合结果见 `manifests/archive-rebuild-validation.json`。

## 正式 writer 仍需完成

1. SLPS 和 COMPDATA 文本池、普通指针及 MIPS HI/LO 写回。
2. 所有剧情块的安全文本 arena、speaker 合并和指针重建。
3. 抽取原版 `HEDBDY/HB.BIN` 后，对 STAGE offset 前像和重读进行验证。
4. 将当前 VT1 第 2 段的 profile 驱动实现抽象为通用全量字库 writer。

第 4 项已有最小生产输入证据：`build_static_canary.py` 保留其他 13 个 VT1 chunk
的原始压缩字节，只重编码第 2 段并重读候选 SLPS offset。当前实现固定为两个
glyph 的验证入口；译文、surface 和 assignment 已迁出 canary 配置，但尚未
抽象成正式全量字库 writer。

任何 writer 都不得复现上游的静默截断、未截断旧尾部或计算 offset 后不写回的
行为。
