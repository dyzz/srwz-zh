# 新对话 Prompt：实现 SRWZ 解码器

你正在 `/Users/nate/Super-Robot-Wars-Z/srwz-zh` 工作。这是独立的《超级机器人大战 Z》中文化仓库；相邻的 `/Users/nate/Super-Robot-Wars-Z` 是只读上游参考，不能修改。

目标：基于已经迁移的上游分析代码，实现 SRWZ 自定义 LZSS 码流的原生 Python **解码器**，建立真实 ISO 样本验证，并把通用修复整理成可贡献回上游的改动。当前阶段不实现编码器、ISO 回包或汉化文本。

开始前完整阅读：

- `README.md`
- `docs/UPSTREAM_REUSE.md`
- `docs/SRWZ_COMPRESSION.md`
- `tools/srwz/codec_contract.py`
- `tools/srwz/archive.py`
- `config/stage-offsets.json`
- `vendor/upstream-python/README.md`
- `vendor/upstream-python/tools/python/lib/decompressor.py`
- `vendor/upstream-python/tools/python/lib/archive.py`

严格约束：

1. 不执行 `SRWZ.exe`、`SRWZ.dll`、`CompressTool.exe`、Wine、Mono 或其他上游二进制。
2. 项目已确认允许直接复用上游源码。优先使用 `vendor/upstream-python/` 中固定提交的快照；保留来源和差异，通用修复应设计为以后可以回馈上游。
3. 不提交 ISO、`STAGE.BIN`、拆出的 `.bin`、解压结果或其他原版数据；这些必须留在已忽略的 `rom/`、`work/`。
4. 只修改 `srwz-zh`，不能改相邻上游仓库。
5. 保持 Python 3.9 可运行；不要使用 `dataclass(slots=True)`。
6. 所有 malformed/truncated 输入都必须显式报 `SrwzCodecError`，并携带输入 offset；不能依赖 `IndexError`。
7. 不要先写“猜测可运行”的宽松解码器。未知字段应保留原值并通过真实样本归纳。
8. 不要直接破坏初始上游快照；核心实现放在 `tools/srwz/codec.py`。如果发现上游 `decompressor.py` 的通用修复点，另行记录最小移植差异。

注意：整份上游快照在 Python 3.9 下已有两个与本任务无关的原始语法错误：`SRWZ.py:337` 和 `mtvpros.py:23` 使用了嵌套单引号 f-string。不要为了本任务修改快照或把整份 vendor `compileall` 作为完成门槛；只编译 `tools/` 和 `tests/`。

现有证据：

- coded integer 推定规则：

  ```text
  value = (value << 7) | (byte >> 1)
  byte & 1 == 1 时结束
  ```

- 第一个 coded integer 是声明的输出大小，第二个是 flags。
- `window = 1 << (((flags >> 1) & 0x0f) + 8)`。
- block 控制字节：

  ```text
  literal_count = control & 0x0f
  match_count   = control >> 4
  ```

  nibble 为零时，随后读取 coded integer 扩展数量。

- match 首字节：

  ```text
  distance_seed = (token & 0x0f) >> 1
  distance_extended = (token & 1) == 0
  length_seed = token >> 4
  ```

  distance 扩展后取 `~distance` 作为负回溯距离；length 为零时扩展，实际复制长度为 `length + 1`，需要支持 overlap copy。

- 上游 `decompress2()` 的 `get_coded_int()` 有缩进错误，会在 continuation byte 后提前返回，不能照抄。
- 头部可选字段、第三个 coded integer 的语义、padding 和特殊 flags 仍需验证。

仓库已经提供不调用上游解压器的样本准备工具：

```bash
python3 tools/extract_iso_member.py DATA/STAGE.BIN
python3 tools/split_stage_archive.py --index 0 --index 1 --index 2
```

它们只使用 `7z` 读取指定 ISO 成员并按固定 offset 切片。`STAGE.BIN` 应为 3,910,128 字节，SHA-256 为 `9c56d42f96df7b409ccf468b24412322ed627b9cbbd656864818a404d89240dc`；布局为 206 个 offset、205 个 chunk。

当前本地已经准备好：

- `work/disc/DATA/STAGE.BIN`
- `work/stage/compressed/000.bin`
- `work/stage/compressed/001.bin`
- `work/stage/compressed/002.bin`

三份样本的大小、offset 和 SHA-256 已登记在 `manifests/codec-samples.json`。开始时先验证这些哈希；不要重新提取或覆盖文件，除非验证失败。

```bash
python3 tools/verify_codec_samples.py
```

请完成：

1. 新增 `tools/srwz/codec.py`：
   - 有边界检查的 byte reader。
   - `read_coded_integer()`，返回现有 `CodedInteger`。
   - 严格头部解析，未知字段放入 metadata，避免无证据命名。
   - `decode()`，返回现有 `DecodeResult`。
   - 可配置 `max_output_size`、coded integer 最大字节数和 token 上限。
   - 返回实际 consumed byte 数，不把尾部 padding 自动算进码流。

2. 新增只读诊断 CLI，例如 `tools/inspect_srwz_stream.py`：
   - 输入一个 chunk。
   - 默认打印简洁 header/block/token 统计。
   - 可选择输出 JSON trace 到 `work/`。
   - trace 必须有大小上限，不能把 literal 原文或完整解码数据写进可提交文件。

3. 增加单元测试：
   - 单字节、多字节 coded integer。
   - coded integer 截断和超过上限。
   - literal-only。
   - 普通 back-reference。
   - overlap copy。
   - 非法负距离、输出越界、声明大小不一致。
   - consumed 与尾部 padding 分离。

4. 使用真实 stage chunk 验证：
   - 先对 0、1、2 号块生成 bounded trace，确认头部和 token 解释。
   - 再扫描全部 205 个块，记录成功数、flags 分布、声明输出大小、consumed、padding 和失败 offset。
   - 扫描结果可在 `work/` 保存完整 JSON；如要提交摘要，只提交聚合统计和样本 SHA-256，不含游戏字节。
   - 不能为了让 205 个块“全绿”而吞掉异常；按格式变体分类。

5. 更新 `docs/SRWZ_COMPRESSION.md`：
   - 将已验证事实和仍未知项分开。
   - 写清每个判断来自单元 fixture、真实 chunk 统计还是静态上游证据。

完成标准：

- `python3 -m unittest discover -s tests -p 'test_*.py'` 全部通过。
- `python3 -m compileall -q tools tests` 通过。
- `git diff --check` 通过。
- 至少 0、1、2 号真实 chunk 有可复现的诊断结果。
- 尽可能扫描 205 个 chunk；若有格式变体，准确报告而不是猜测修复。
- 外层上游仓库保持干净，且没有运行任何上游二进制。

直接实施并验证，不只给方案。最终说明实现文件、测试结果、真实样本统计、仍未知项，以及下一步是否已经具备实现编码器的证据基础。
