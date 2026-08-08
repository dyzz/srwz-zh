# 语料与二进制写回契约

## 语料记录

稳定语料按领域保存在 `corpus/ja` 与 `corpus/zh`。每条记录至少包含稳定 ID、
domain、kind、来源成员、来源文本哈希、结构位置、中文、状态和备注。生产 builder
直接从锁定原版成员重建结构并对账，不依赖一次性的总解析／导出结果。

状态单向推进：

```text
todo -> draft -> reviewed -> final -> runtime_verified
```

非 `todo` 必须有中文；状态不得倒退。`runtime_verified` 必须提供精确 ISO、路线、
存档和证据 receipt，不能由静态构建自动授予。

## 文本序列化

`tools/srwz/text.py::encode_text()` 必须：

- 反向使用固定双字节码表；重复映射确定性选择最低 code；
- 支持换行、已登记控制码和 lossless `{XX}` 原始字节；
- 保持 `$n/$F`、printf token 和其他运行时结构；
- 只接受 profile 显式提供的中文字符→码位 override；
- 对未映射字符、未知控制码和非法结构 fail closed；
- 满足 `decode_text(encode_text(text)) == text`。

## 通用写回原语

`tools/srwz/writeback.py` 提供：

- `PatchPlan`：源大小、SHA-256、前像、边界和唯一 owner；
- `PatchOperation`：只允许授权区间内的确定性修改；
- `AllocationPool`：带 alignment 的文本池分配，溢出立即失败；
- `fit_fixed_allocation()`：固定 span 不截断；
- `rebuild_aligned_archive()`：确定性归档和包含 terminal size 的 offset 表。

所有 writer 必须从锁定领域配置与语料 reconciliation 结果读取译文、地址和 assignment，
不得由临时 CLI 参数或 canary 文件重新定义生产内容。

## 领域 writer

### Fixed-span

- 只在原 NUL span 或明确固定 allocation 内覆盖；
- payload 超过容量立即失败；
- 共享目标要求所有 owner 和 payload 一致；
- 非目标字节保持原样。

### 文本池与指针

- 池区必须由来源哈希绑定且前像满足预期；
- 普通 32-bit pointer 和 MIPS HI/LO 必须成对登记；
- 未配对 HI/LO、非零未授权池、重叠 owner 或池溢出立即失败；
- 写回后重新解析每个指针和目标文本。

### MTV_PROS

- 保留每条记录原有 `nul` 或 `end` 终止方式；
- 按固定 allocation 写入并逐条全文回读；
- 归档重建后复核 15-entry SLPS offset 表及 terminal size。

### STAGE

- 每个剧情块使用已登记 allocation／arena；
- 对白、说话人、条件和指针分别拥有明确 owner；
- 重建 205-chunk archive 时保持 16-byte alignment；
- 写回 `HEDBDY/HB.BIN` offset 表后逐项重读；
- 每个变更块必须严格解码并逐 ID 回读目标译文。

### SLPS／COMPDATA

- 区分 inline、普通 pointer、embedded HI/LO 和 fixed-span；
- COMPDATA 修改后使用生产 Rust codec，并执行 145,408-byte 硬门；
- 解压 payload、指针集合、压缩 consumed 和非目标记录全部复核。

### VT1 字库

- 字形 assignment 来自 append-only registry；
- 字库内容与 SLPS VT1 offset 表原子更新；
- 保留未修改 chunk 的原压缩字节或明确外层尾部；
- 重新解压完整目标段并验证 SHA-256；
- 字体加载和具体 glyph 画面分开验收。

## 归档与组件验收

每个候选组件至少验证：

1. 输入成员大小与 SHA-256；
2. 每个写入区间的原始前像和 owner；
3. 输出大小、哈希和允许变化区间；
4. 独立 parser／decoder 回读；
5. archive alignment、offset、pointer 和 terminal size；
6. 非目标成员或非目标字节 byte-exact；
7. manifest 与实际输出一致。

writer 永远不修改 `rom/` 或 `work/disc/` 原版缓存，只写
`work/build/<profile>/components/`。

## 禁止行为

- 静默截断或保留旧尾部；
- 先计算 offset／pointer 但不写回；
- patch-over-patch；
- 用“能编码”“有空白 glyph”替代 renderer 证明；
- 用 round-trip 替代游戏运行；
- 手工修改 manifest 让候选表面通过。
