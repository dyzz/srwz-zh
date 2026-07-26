# SRWZ 压缩流研究记录

状态：中文仓库已经实现严格的 clean-room **编解码器**和只读诊断工具，并用
原版 `STAGE.BIN` 的全部 205 个 chunk，以及 `COMPDATA.BN`、`MTV_PROS.BIN`
和 VT1 的可解码流完成验证。归档重建、PS2 DVD 回包和 canary 字库的游戏内
解压也已验证；菜单、MTV_PROS 摘要和 STAGE 剧情三类 canary 均已完成
PCSX2 运行与画面验收。

## 证据等级

- **[UNIT]**：中文仓库自行构造的最小 fixture；用于验证边界、错误和 overlap copy。
- **[STAGE]**：SHA-256 固定的原版 `STAGE.BIN` 及其 offset 切片；扫描不保存解码
  输出或 literal 原文。
- **[CORE]**：汉化关键归档 `COMPDATA.BN`、`MTV_PROS.BIN` 和 VT1 段；
  完整统计见 `SRWZ_DATA_PARSING.md`。
- **[MIPS]**：原版 `SLPS_258.87` 中游戏实际运行的 R5900 解压器反汇编。
- **[DLL-IL]**：`SRWZ.dll` 的 PE/.NET 元数据和 CIL 静态反汇编；没有加载或
  执行 DLL，也没有复制反编译源码。
- **[RUNTIME]**：PCSX2 v2.6.3 + PINE 对游戏运行状态和 EE 内存的读取验证。

上游分析函数 `tools/python/lib/decompressor.py::decompress2` 只能作为
**[STATIC]** 证据：其 `get_coded_int()` 在 continuation byte 后会提前返回，并且
函数混入 NumPy、Pandas 和调试 Excel 输出。

## 已验证格式

### 变长整数

每个输入字节贡献高 7 位，最低位是终止位：

```text
value = (value << 7) | (byte >> 1)
if byte & 1:
    end
```

- 单字节、多字节、截断和最大字节数由 **[UNIT]** 验证。
- stage 的声明大小包含多字节实例，且 205 块均按此规则完成解码，属于
  **[STAGE]** 验证。
- distance 扩展使用已有 seed 继续执行同一规则；这个控制流来自
  **[STATIC]**，实际 token 解释由 **[STAGE]** 全扫验证。

解码器默认限制 coded integer 为 10 字节；超限或未终止时抛出带输入 offset 的
`SrwzCodecError`。

### 头部

当前解析顺序：

1. 声明输出大小；
2. flags；
3. 仅在静态控制流指定的 `0x40` 条件成立时读取一个 coded integer，原值保存在
   `metadata["header_unknown_0"]`；
4. 始终再读取一个 coded integer，原值保存在
   `metadata["header_unknown_1"]`。

窗口值为：

```text
window = 1 << (((flags >> 1) & 0x0f) + 8)
```

第 1、2、4 项和窗口计算同时有 **[STATIC]** 与 **[STAGE]** 支持。条件字段分支
只有 **[STATIC]** 支持：stage 的 205 个 flags 都没有设置 `0x40`，因此当前真实
样本没有覆盖该字段。

205 个 stage chunk 的 flags 分布为：

| flags | chunk 数 |
| ---: | ---: |
| 3 | 20 |
| 7 | 1 |
| 9 | 15 |
| 11 | 18 |
| 13 | 16 |
| 15 | 9 |
| 17 | 42 |
| 19 | 66 |
| 21 | 18 |

所有 205 个 `header_unknown_1` 都是 `0`。这只是 **[STAGE]** 观察值，不将其
命名为字典、版本、模式或其他未经证实的语义。

### 数据块

控制字节：

```text
literal_count = control & 0x0f
match_count   = control >> 4
```

对应 nibble 为零时，紧随其后读取 coded integer 扩展数量。两个数量解析完成后，
先复制 literal；如果输出恰好达到声明大小，码流在 literal 后结束，不消费控制字节
中尚未使用的 match 数量。

游戏内 core 位于 `0x001C6D70`。它在 `0x001C6DE8` 的 literal copy 和
`0x001C6EA0` 的 match copy 都使用“先复制一次、再判断计数”的 post-tested
循环，因此存在两个必须由编码器遵守的运行时约束：

- 每个 block 的最终 `literal_count` 必须至少为 1；扩展值 0 会在
  `addiu t0,t0,-1` 下溢并失控复制。
- 只要 literal 尚未达到声明输出末尾，`match_count` 必须至少为 1；只有最终
  literal 已填满输出时，游戏才会在进入 match loop 前退出。

原版字体流 66,595 个 block、相邻上游 `2_translated/font/2.bin` 的 62,257
个 block，最小 literal 均为 1。旧 clean-room canary 的 175,385 个 block 中有
139,993 个零 literal block；第一个位于 block 8、输入 offset 48、输出 offset
576，随后游戏在 `0x001C6DE8` 产生 TLB miss。这一证据修正了早先“仅因压缩流
变大跨过 32 MiB”的推断。

### Back-reference

首字节：

```text
distance_seed = (token & 0x0f) >> 1
distance_extended = (token & 1) == 0
length_seed = token >> 4
```

- distance 扩展时，以 `distance_seed` 作为 coded integer 初值继续读取。
- 实际负回溯量 `~distance_value` 等价于向前距离 `distance_value + 1`。
- length nibble 为零时读取 coded integer 扩展。
- 实际复制长度为 `length_value + 1`。
- overlap copy 每生成一个字节就立即加入可回溯窗口。

普通 back-reference、overlap、非法向前越界和输出越界有 **[UNIT]** 验证。全部
stage chunk 在不截断 match、不吞掉异常的条件下精确生成声明输出大小，提供
**[STAGE]** 验证。

## 解码器的严格边界

`tools/srwz/codec.py`：

- 所有输入读取都经过有边界检查的 `ByteReader`；
- truncated/malformed 流抛出带输入 offset 的 `SrwzCodecError`，不依赖
  `IndexError`；
- 拒绝超出已生成输出或计算窗口的 back-reference；
- 拒绝 literal/match 超出声明输出大小，不采用上游分析函数的静默截断行为；
- 拒绝游戏内 post-tested copy loop 无法安全处理的零 literal block；
- 拒绝输出尚未完成时的零 match block；
- 可配置最大输出大小、coded integer 最大字节数和结构 token 上限；
- 返回达到声明输出大小时的实际 `consumed`，不会自动吸收 archive slice 的尾部。

`tools/inspect_srwz_stream.py` 只解码内存中的 chunk，不保存解码结果。可选 JSON
trace 必须位于已忽略的 `work/`，最多保留 10,000 个事件，并且事件不包含
literal 原文或完整输出。

## 原版 stage 验证

可复现命令：

```bash
python3 tools/verify_codec_samples.py
python3 tools/inspect_srwz_stream.py work/stage/compressed/000.bin \
  --json-trace work/stage/traces/000.json --max-trace-events 128 --force
python3 tools/inspect_srwz_stream.py work/stage/compressed/001.bin \
  --json-trace work/stage/traces/001.json --max-trace-events 128 --force
python3 tools/inspect_srwz_stream.py work/stage/compressed/002.bin \
  --json-trace work/stage/traces/002.json --max-trace-events 128 --force
python3 tools/scan_stage_streams.py --force
```

0、1、2 号固定样本：

| index | SHA-256 | slice | declared | flags | window | consumed | padding | blocks | matches |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | `3b334daeec1d18be3827c0e6fe874a592c2f7902ed193b710936255bec08f1c9` | 55,392 | 152,336 | 21 | 262,144 | 55,392 | 0 | 6,366 | 12,375 |
| 1 | `7871a3f384612b8a33465de17f35a8036e12b95796bfd98b3dd7981dd298a803` | 17,024 | 45,968 | 17 | 65,536 | 17,019 | 5 | 2,124 | 3,703 |
| 2 | `84aaa58595918e20538d65d34844ca664663bd74d868f9c12a3d8992232ac19b` | 22,608 | 75,152 | 19 | 131,072 | 22,600 | 8 | 2,830 | 4,929 |

完整 `STAGE.BIN`：

- archive：3,910,128 字节，
  SHA-256 `9c56d42f96df7b409ccf468b24412322ed627b9cbbd656864818a404d89240dc`；
- 205/205 块成功，0 个失败；
- 声明输出最小 272、最大 210,448、合计 11,687,504 字节；
- 码流实际消费最小 88、最大 62,691、合计 3,908,650 字节；
- 479,386 个 block、905,399 个 match token；
- literal 合计 1,054,998 字节，match copy 合计 10,632,506 字节，二者之和
  精确等于总声明输出；
- slice 尾部 padding 为 0–15 字节，总计 1,478 字节，205 个尾部全部为零。

逐块 metadata 和失败 offset（本次为空）保存在已忽略的
`work/stage/codec-scan.json`。尾部观察只证明该 `STAGE.BIN` 样本使用零填充到
slice 边界；不能外推为所有 SRWZ 归档的通用 padding 规范。

其他汉化关键归档的 **[CORE]** 结果：

- `COMPDATA.BN`：1 个完整流，flags `23`，解码为 524,032 字节；
- `MTV_PROS.BIN`：14/14 个完整流，flags 分布
  `1:2, 3:1, 5:4, 7:7`；
- VT1：8 个完整流的 flags 分布
  `17:1, 21:1, 25:3, 27:2, 29:1`；另有 4 个带非零尾部的流前缀和 2 个不能
  按当前格式解码的段，均保留原分类，没有吞成 padding。

## Clean-room 编码器

`tools/srwz/codec.py::encode()` 提供两种确定性策略：

- `literal`：一个纯 literal block；只依赖已经由解码器 fixture 和原版流验证的
  语法，是最保守的格式接受性基线。
- `greedy`：使用相同 block/match 语法增加确定性的 greedy back-reference；
  默认最短 match 为 3、每个 key 最多检查 64 个历史候选，并把一个非空
  literal run 后连续出现的 match 合并到同一 block。

production writer 还可调用 `reencode_changed_suffix()`。它解析并逐字节保留
首个修改位置之前的原版 header 和完整 block，只对受影响 suffix 使用同一
确定性编码规则；decoded size 改变时只重写 header 中声明大小的 coded
integer。调用方仍必须执行完整 decode round-trip、archive alignment 和
offset 重读，不能把前缀保留当作正确性捷径。

`SRWZ.dll` 是 10,240 字节的 .NET 8 程序集
（SHA-256 `79567ccced11b2478d8ea195f9492114482a9b15c256bef72d818649d2f0277d`）。
静态 CIL 显示其 `Compress` 方法同样先累积 literal entry，再收集随后连续的
compressed entry；这与当前块组织方式一致。该 DLL 证据只作交叉验证，游戏
兼容性以 **[MIPS]** 和 **[RUNTIME]** 为准。

编码器不写 archive padding，调用方必须在归档层明确处理 alignment。

### 头部写入规则

对当前 232 个真实可解码流，原版 flags 都等于：

```text
window = smallest power of two >= decoded_size, minimum 256, maximum 8 MiB
flags  = 2 * (log2(window) - 8) + 1
```

编码器按这个规则选择 odd flags，并写 `header_unknown_1 = 0`。232/232 个重新
编码流选择的 flags 与原版一致。调用方也可以显式提供 flags；如果它触发
`0x40` 条件字段却没有同时提供 `header_unknown_0`，编码立即失败。

这证明了当前样本的确定性写入规则，不证明所有游戏归档或 `0x40` 变体都使用
相同策略。

### 真实流往返

可复现命令：

```bash
python3 tools/validate_srwz_encoder.py --strategy literal \
  --json-output work/encoder/encoder-validation-literal.json --force
python3 tools/validate_srwz_encoder.py --strategy greedy --force
```

两种策略都满足 232/232：

```text
decode(encode(decode(original_stream).output)).output
    == decode(original_stream).output
```

greedy 结果：

| 域 | 测试流 | exact | 解码字节 | 原版 consumed | 新编码 |
| --- | ---: | ---: | ---: | ---: | ---: |
| STAGE | 205 | 205 | 11,687,504 | 3,908,650 | 4,356,836 |
| COMPDATA | 1 | 1 | 524,032 | 144,990 | 165,590 |
| MTV_PROS | 14 | 14 | 13,088 | 8,947 | 9,536 |
| VT1 | 12 | 12 | 8,287,552 | 2,053,979 | 2,370,788 |
| 合计 | 232 | 232 | 20,512,176 | 6,116,566 | 6,902,750 |

539,875 个新 block 的 literal 全部至少为 1，且没有非最终零 match block。
新编码约为解码数据的 33.65%，为原版 consumed 的 112.85%。因此当前 greedy
编码器已经满足正确性、游戏语法兼容和可重复性，不以逐字节复制原压缩率为目标。

VT1 的 12 个测试项包含 8 个完整流和 4 个“流前缀 + 非零外层尾部”。后者只验证
压缩流前缀的编解码，正式 writer 必须保留并理解外层尾部；另 2 段仍分类为
`not_decoded_as_stream`。

完整逐流结果位于被忽略的 `work/encoder/encoder-validation.json`，可提交聚合
结果位于 `manifests/codec-encoder-validation.json`。

### 游戏内解压验证

当前 canary 字库的 suffix 重编码压缩流为 599,742 字节。使用命令行
PCSX2/PINE 运行重建 ISO 后：

- 游戏 ID 为 `SLPS-25887`，PINE 前后状态均为 Running；
- 游戏字库目标指针 `0x0046E3A8` 的值为 `0x009AE610`；
- 游戏声明的字库解压尺寸 `0x003F7D68` 为 1,290,240；
- 通过 PINE 读取完整目标缓冲区所得 SHA-256 为
  `cc44fa82d1581c3eb1c5852d017efbcbe8e454d4cbd9f374688c408fb236a119`，
  与构建前修改字库完全一致；
- 菜单、摘要和剧情三条独立 fixture 以及完整组合 smoke 的日志均没有
  TLB miss，PCSX2 均由命令行正常停止。

可复验命令（PCSX2 已启用 PINE 且 canary 正在运行时）：

```bash
python3 tools/verify_pcsx2_font_runtime.py --force
```

该验证证明当前字体 canary 流已由游戏自己的 R5900 解压器完整接受，不只是被
clean-room Python 解码器接受。MTV_PROS 与 STAGE 修改流还分别取得目标文本
画面证据，详见 `manifests/canary-summary-validation.json` 和
`manifests/canary-story-validation.json`。

## 仍未知或未验证

- flags 每一位的完整语义；当前只能验证其窗口位和 stage 分布。
- `header_unknown_0`、`header_unknown_1` 的含义。
- `0x40` 条件头部字段的真实游戏样本。
- 是否存在未压缩模式、特殊模式或另一种结束规则。
- padding 是否由归档层、压缩器或某个对齐规则产生。
- VT1 中 4 个“压缩流前缀 + 非零尾部”段和 2 个非当前码流段的外层结构。
- 其他未扫描归档是否共享相同的头部变体。
- 原版压缩器的 match 选择和压缩率优化策略；clean-room encoder 已有自己的
  确定性选择，但不声称复制原算法。
- 当前运行证明覆盖 canary 字库流，不自动证明每个将来写回的 STAGE、COMPDATA
  或其他归档在所有游戏路径上都已执行。

因此，当前证据已经足以支持 **stage、COMPDATA、MTV_PROS 和 VT1 完整压缩流**
的确定性 clean-room 重新编码；canary 字库也已取得游戏内解压的完整输出哈希
证据。它还不足以声称 `0x40`/未知归档变体、VT1 外层混合结构或所有归档路径
均已完成运行验收。
