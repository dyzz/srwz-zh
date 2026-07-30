# SRWZ.dll 压缩路径静态研究

状态：2026-07-29 完成。本文只记录算法事实、控制流、数据结构、精简伪代码和
与原版码流的统计交叉验证；没有保存反编译源码，也没有加载或执行任何上游
程序集。

## 边界、样本与工具

静态输入：

| 文件 | 大小 | SHA-256 | 处理方式 |
| --- | ---: | --- | --- |
| `tools/utilities/SRWZ.dll` | 10,240 | `79567ccced11b2478d8ea195f9492114482a9b15c256bef72d818649d2f0277d` | PE／CLR metadata 和 CIL 静态解析 |
| `tools/utilities/CompressTool.exe` | 228,864 | `60a2a2af0e26de19cedbd667b8ecd25009441406292e5c621b9560fb90ff2226` | PE header、imports 和字符串静态解析 |

本次使用的开源工具：

- ILSpy 10.1.1，MIT：复核 managed assembly 的类型和方法；
- Ghidra 12.1.2，Apache-2.0：只读恢复 native PE 控制流；
- `dnfile 0.17.0`，MIT，
  <https://github.com/malwarefrank/dnfile>：解析 PE／CLR metadata；
- `dncil 1.0.2`，Apache-2.0，
  <https://github.com/mandiant/dncil>：只读解析 method body 和 CIL instruction；
- `pefile 2024.8.26`，MIT，
  <https://github.com/erocarrera/pefile>：`dnfile` 的 PE 后端；
- Apple LLVM `objdump` 21.0.0：读取原生 PE header、section 和 import table。

工具只读取文件。没有使用反射、程序集加载、入口点、测试调用、Wine 或 Mono。
完整临时 CIL dump 只留在已忽略的 `work/research/codec/`，不进入仓库。

## DLL 静态事实

以下均为 **[DLL-IL]**，不是对原版游戏 compressor 的声明。

### Match 索引和窗口

`LzssCompressionData` 持有：

- 256 项 `LzByteStartTable`；
- 256 项 `LzByteEndTable`；
- 262,144 项 `LzNextOffsetTable`；
- `WindowLen`、`WindowPos`、`InputSize`、`InputPos`。

两个常量 `LZSS_WINDOWLENGTH` 和 `LZSS_MAXLENGTH` 都是 `0x40000`
（262,144）。初始化把三张索引表填成 `-1`，窗口长度和位置归零。每加入一个
输入 byte，`LzssSlideByte`：

1. 窗口已满时，从该 byte 值的链表头移除最旧 ring offset；
2. 把当前 ring offset 追加到对应 byte 值链表尾；
3. 更新 262,144-byte 环形窗口的位置或长度。

因此候选不是按 3/4-byte hash 截断的链，而是按首 byte 分桶、覆盖完整当前窗口
的 FIFO linked list。

### Match 搜索和 tie-break

`LzssSearchMatch` 从当前输入 byte 对应链表头开始，遍历到 `-1`；窗口已满时跳过
等于当前 `WindowPos` 的失效节点。每个 ring offset 先换算成绝对历史输入位置，
再逐 byte 比较，直到：

- 当前输入末尾；
- 第一个不同 byte；
- 或长度达到 `0x40000`。

最短 match 为 3。更长候选替换当前最佳；长度相同时，绝对历史位置更大的候选
替换当前最佳，即选择更近距离。找到 `0x40000` 长度时提前结束。

搜索不查看下一输入位置，不做 lazy matching，也不计算 control、coded integer、
distance 或 length 的序列化成本。

### Literal／match 决策和 block 聚合

`Compress(byte[])` 对每个当前位置只调用一次 `LzssSearchMatch`：

- 找到长度至少 3 的 match：立即前进完整 match 长度并记录 compressed entry；
- 否则：把一个 byte 追加到当前 literal entry 并前进 1。

literal entry 在遇到下一条 match 时才入表；连续 match 各自形成 compressed
entry。序列化阶段每轮取最多一个 literal entry，再收集其后的全部连续
compressed entry，写成一个 SRWZ block。因此 DLL 和 clean-room writer 的
“非空 literal run + 连续 matches”聚合形态一致。

没有发现基于真实编码成本在 literal 与 match 间切换的分支。

### Token 和 coded integer 写法

block control、literal/match 扩展计数、length 和普通 coded integer 的写法与
当前 clean-room 格式一致。距离存在一个此前 clean-room encoder 没有使用的
紧凑分支：

1. 令 `distance_value = distance - 1`；
2. `distance_value < 8` 时直接写入 token 的三 bit seed，并令低位为 1；
3. 否则先拆成大端 7-bit 组；
4. 如果组数大于 1 且最高组小于 8，把最高组放入 token 的三 bit seed，只把
   剩余组作为 coded-integer continuation 写出；
5. 其他 extended distance 的 seed 为 0，写出完整 coded integer。

这正是 decoder 的 `read_coded_integer(initial_value=seed)` 所允许的表示。它不是
新的码流语法，而是同一数值的少一 byte 编码。

length 1–16 中的可内嵌范围按 `length - 1` 写入高 nibble；其他长度使用 coded
integer。计数 nibble 小于 16 时内嵌，否则写 coded integer。

### Header

DLL 的 `Compress` 固定依次写：

```text
coded_integer(decoded_size)
coded_integer(0)
coded_integer(0)
```

它没有按解码大小选择原版 flags。原版 COMPDATA flags 为 23，当前 232 个真实
流也都遵循“最小可容纳 2 的幂窗口”的 odd flags 规则。因此 DLL 的 compressor
不能被当作游戏原厂 compressor 或可直接替换的生产实现；本次只采用其与真实
码流相互支持的局部算法事实。

## CompressTool.exe 的关系

`CompressTool.exe` 是原生 PE32 console 程序，没有 CLR runtime header。import
table 只列出 `KERNEL32.dll`、`USER32.dll`、`MSVCP140D.dll`、
`VCRUNTIME140D.dll` 和 `ucrtbased.dll`；文件中没有 `SRWZ.dll`、
`CompressFile` 或 CLR host 字符串。可见字符串包含 `compdata.bn` 和
`Compress %s success... level %d`。

所以它不是通过普通 PE import 或可见 DLL 名动态调用 `SRWZ.dll` 的前端，而是
一套独立 native compressor。后续已用 Ghidra headless 在不执行程序、不保存
反编译源码的前提下恢复 level 0–9、两字节 hash chain、lazy parse、compact
distance 和 header 写法。完整规格、地址和真实流结果见
`docs/SRWZ_COMPRESS_TOOL_STATIC_ANALYSIS.md`。

## 精简行为规格

```text
initialize 256 FIFO heads/tails and a 262144-entry next table

while input_pos < input_size:
    best = longest match among every same-first-byte position in window
    tie: choose the nearest position
    if best.length >= 3:
        flush pending literal entry
        append one match entry
        slide best.length bytes
    else:
        append current byte to pending literal entry
        slide one byte

flush pending literal entry
write header(size, 0, 0)

while entries remain:
    take one optional literal entry
    take every immediately following match entry
    write control and extended counts
    write literals
    for each match:
        write compact seeded distance(distance - 1)
        write length(length - 1)
```

## 原版流交叉验证与压缩率损失

以下是 **[ORIGINAL-STREAM]**，聚合数据在
`manifests/compdata-compression-comparison.json`：

- 原版 COMPDATA 32,544 个 match 中，12,521 个 extended distance 满足
  “最高 7-bit 组小于 8”，12,521 个全部实际使用非零 seed；
- 旧完整 P0 后缀由 clean-room greedy 生成，1,796 个同类 token 的 seed 全为
  0，因此恰好多写 1,796 bytes；
- 从 decoded offset 474,256 重压原始后缀时，旧策略为 18,139 bytes，原版保存
  后缀为 16,209 bytes；启用 compact seed 后为 16,331 bytes，把 1,930-byte
  差距中的 1,808 bytes 消除，只剩 122 bytes；
- 对完整 P0，旧 147,050 bytes 降为 145,237 bytes。总计减少 1,813 bytes，
  进入 145,408-byte／71-sector 硬上限并剩余 171 bytes。

候选链实验显示 `64`、`256`、`4096` 深度并不单调改善 greedy 结果；更深链会
因局部最长 match 改变后续解析而偶尔变大。生产 `size-constrained` 策略因此
只在有界的 64/配置上限候选间按**完整序列化 byte 数**选择，不把增加链深当作
主要修复。

## 事实分层和仍未知项

### DLL 静态事实

- 262,144-byte 首字节 FIFO 候选链；
- 最短 3、最长 262,144；
- 最长优先、等长最近距离；
- 无 lazy、无 lookahead、无编码成本决策；
- literal entry 后聚合连续 compressed entry；
- compact extended-distance seed；
- DLL 自身固定写 header `(size, 0, 0)`。

### 原版流统计事实

- 原版 COMPDATA 完整使用 compact seed；
- 原版 header flags 与 DLL 输出不同；
- compact seed 是本次压缩损失的主因，恢复后完整 P0 达到扇区预算。
- 独立 CompressTool level-9 行为模型把原版 COMPDATA 重压为 145,064 bytes，
  与原版 144,990 只差 74 bytes，但不据此断言工具具有原厂来源。

### 推断

- DLL 可能是后来独立重写或调试实现；header 差异足以阻止把它认作原厂
  compressor。
- 原版 compressor 很可能也主动选择 compact seed，但原版 match 搜索和 parse
  是否与 DLL 相同仍不能由 token 统计唯一确定。

### 仍未知

- 光盘原版流究竟由哪个具体 compressor／版本产生；
- 原版 block 边界是否由成本优化产生；
- flags 全部 bit、两个未知 header 字段和 `0x40` 变体语义；
- 数学全局最优的 block-aware LZ parse；当前 `maximum` 是明确有界的候选组合，
  不作全局最优声明。
