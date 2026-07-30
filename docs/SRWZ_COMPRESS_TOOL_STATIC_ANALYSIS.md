# CompressTool.exe 静态压缩规格

状态：2026-07-29 完成第一轮函数级恢复和真实流交叉验证。本文只保存算法事实、
地址、哈希、统计和独立伪代码结论；没有执行目标程序，也没有保存或复制反编译
源码。

## 边界与工具

| 静态输入 | 类型 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `tools/utilities/CompressTool.exe` | native PE32 x86 debug build | 228,864 | `60a2a2af0e26de19cedbd667b8ecd25009441406292e5c621b9560fb90ff2226` |
| `tools/utilities/SRWZ.dll` | managed PE32 / .NET 8 | 10,240 | `79567ccced11b2478d8ea195f9492114482a9b15c256bef72d818649d2f0277d` |
| `work/disc/SLPS_258.87` | PS2 R5900 ELF | — | `6c4c81c4e5aa3db1f52d70b8183ce11c01fc6b265ae4d53fa4d6a657c5019b50` |

使用：

- Ghidra 12.1.2 headless：native PE 函数、交叉引用和控制流；
- ILSpy 10.1.1：`SRWZ.dll` 的只读 CIL 静态检查；
- GNU `mipsel-linux-gnu-objdump`：游戏 R5900 解压器；
- Python clean-room 解码器：真实流统计、候选回解和逐字节比较。

没有调用 `CompressTool.exe`、`SRWZ.exe`、`SRWZ.dll` 的入口点，没有使用 Wine、
Mono 或反射加载。Ghidra／ILSpy 的临时输出只存在于忽略的 `work/` 或标准输出。

PE 的 `.data` raw size 只有 `0xA00`，virtual size 约 231 MiB。大虚拟区来自
64 MiB 输入缓冲、65,536 项 hash head、`0x2000000` 项四字节 prior-position
chain 和 token scratch；它不是一个 231 MiB 的磁盘 payload。PDB 残留路径为：

```text
t:\users\enhasa\documents\visual studio 2017\Projects\CONSOLE_TEST\Debug\CONSOLE_TEST.pdb
```

因此本文称它为“上游附带的 debug compressor”，不称作原厂 compressor。

## 命令行和入口

静态控制流恢复的参数为：

```text
-d <file>          decompress
-c <file> [level]  compress
```

level 接受 `0..9`；越界时使用全局默认值 7。上游 Python 路径显式传入 level 9，
并寻找 `<stem>9.mwo`。核心压缩函数位于 `0x0042C230`，近似签名：

```text
compress(input, input_size, output, output_size_pointer, level)
```

头部函数为 `0x0042D6E0`，match finder 为 `0x0042CDD0`，match serializer 为
`0x0042D8D0`。

## Level 表

四列依次对应：达到该长度后把 chain 降为四分之一、最大 lazy 长度、提前停止的
nice length、最大候选链。

| level | reduce at | max lazy | nice length | max chain |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 0 | 4 | 4 |
| 1 | 4 | 4 | 8 | 4 |
| 2 | 4 | 5 | 16 | 8 |
| 3 | 4 | 6 | 32 | 32 |
| 4 | 4 | 4 | 16 | 16 |
| 5 | 8 | 16 | 32 | 32 |
| 6 | 8 | 16 | 256 | 256 |
| 7 | 8 | 32 | 1,024 | 1,024 |
| 8 | 32 | 128 | 4,096 | 4,096 |
| 9 | 32 | 258 | 16,777,215 | 65,535 |

level 9 并不是可调“压缩率参数”的一个模糊标签：它明确把最大 chain 提到
65,535、最大 lazy 提到 258，并把 nice length 提到 `0xFFFFFF`。

## Match index 与搜索

匹配索引是滚动两字节 key：

```text
key = (previous_low_byte << 8) | next_input_byte
candidate = head[key]
prior[current_position mod 0x2000000] = candidate
head[key] = current_position
```

搜索规则：

- 最大距离为 `0xFFFFFE`；
- 最大长度为 `0xFFFFFF`，并受剩余输入限制；
- 最长 match 胜出；
- 等长不替换，因此保留链中先遇到的最近位置；
- 达到 nice length 后提前退出；
- 当前最佳长度达到 level 的 reduce threshold 后，chain budget 降为四分之一；
- 位置 0 同时被用作空链 sentinel，因此 debug tool 不会把位置 0 当候选。

长度成本过滤发生在 match finder 返回以后：

- 长度 2 只在实际距离不大于 7 时保留；
- 长度 3 只在实际距离不大于 `0x3FF` 时保留；
- 其他长度不做这两个距离过滤。

这两个门槛是工具启发式，不是游戏 decoder 的格式限制。

## Lazy parse 和 block

核心使用一字节 lookahead：

1. 保存上一位置的 match；
2. 在当前位置寻找新 match；
3. 若新 match 更长，先把上一字节留作 literal，等待新 match；
4. 否则发出上一 match；
5. match 内部跳过的位置仍逐一加入 hash chain。

block 始终是一个非空 literal run 后跟连续 match。新 literal 出现在已有 match
之后时，先结束当前 block。这个形状符合游戏在 `0x001C6DE8`／`0x001C6EA0`
使用 post-tested copy loop 的要求。

静态函数在一般输入结束时看起来缺少标准 deflate-slow 的最后一个 pending
literal flush。游戏相关 payload 都以长零串结束，没有走到该边界。clean-room
实现对任意 fixture 保留安全 flush，不复制这个疑似 debug-build 缺陷。

## 序列化和头部

block control、count VLE、distance seed、distance continuation 和 length VLE
与 clean-room 格式一致。distance 使用最短表示：

- `distance - 1 <= 7` 时全部放在 token seed；
- 多字节 VLE 的最高 7-bit group 小于 8 时，把该 group 放入 token seed；
- 只写剩余 continuation bytes。

头部写：

```text
VLE(decoded_size)
VLE(2 * (bit_length(decoded_size) - 8) + 1)
VLE(0)
```

COMPDATA 524,032 字节的实际开头为 `3e fc 01 2f 01`，语义 flags 为 23，与原版
完全一致。对恰好为 2 的幂的大小，debug tool 因使用 `bit_length(size)` 会选择
严格更大的窗口；当前 232 个真实样本没有覆盖这个差异。

## 四路证据交叉

| 行为 | 游戏 R5900 | Kuriimu LZSSVLE | SRWZ.dll | CompressTool |
| --- | --- | --- | --- | --- |
| VLE／block／token 语法 | 是 | 是 | 是 | 是 |
| compact distance seed | 解码支持 | 解码支持 | 写入 | 写入 |
| overlap copy | 是 | 是 | — | — |
| nonzero leading literal | 运行时必需 | 未严格校验 | 聚合产生 | 聚合产生 |
| header odd flags | 读取 | 读取 | 固定写 0 | 按大小写入 |
| encoder | — | 无 | greedy | level 0–9 lazy |

Kuriimu 的 `LZSSVLE.cs` 只有 decoder；`MTV.Save()` 为空，不能作为 encoder
来源。对应固定 commit：

- <https://github.com/IcySon55/Kuriimu/blob/ebfbf8de50755cc32a7e1ea4aee394628d49d3d2/src/Kontract/Compression/LZSSVLE.cs>
- <https://github.com/IcySon55/Kuriimu/blob/ebfbf8de50755cc32a7e1ea4aee394628d49d3d2/src/archive/archive_srtz/MTV.cs>

## 独立模型与真实流结果

独立 Python 行为模型不调用目标二进制，也不是反编译源码转录。

| 输入 | 原版／旧结果 | 模型结果 | 严格回解 |
| --- | ---: | ---: | --- |
| 原版 COMPDATA，524,032 decoded bytes | 144,990 | 145,064 | exact、fully consumed |
| STAGE chunk 001，45,968 decoded bytes | 17,024 slice／17,019 consumed | 16,995 | exact、fully consumed |
| P0 完整修改，整流重压 | 145,237 | 145,208 | exact、fully consumed |
| P0 修改，保留原 compressed prefix，工具式最长匹配 | 145,237 | 145,145 | exact、fully consumed |
| P0 修改，保留 prefix，成本感知＋lazy bias 2 | 145,237 | **145,057** | exact、fully consumed |

原版 COMPDATA 只差 74 bytes（0.051%）是对算法恢复的强验证，但不能证明该工具
就是生成光盘原版流的原厂程序。

## 工程中的极限模式

`tools/srwz/codec.py` 的 `maximum` 不是逐行移植工具：

- 复用静态恢复的两字节 hash、65,535 chain 和 `0xFFFFFF` 上限；
- 候选按真实 compact match byte gain 排名，而不是只看长度；
- 共享一次 match table，比较 lazy bias `0..8`；
- 小于等于 64 KiB 的 suffix 同时保留 `size-constrained` 回归候选；
- 大型生产 suffix 省略已确认不会胜出的旧纯 Python 候选，避免重复链搜索；
- 最后按完整序列化 bytes 选择最短结果；
- 允许合法且有收益的 2／3-byte match；
- 对任意输入执行安全 final-literal flush。

“maximum”表示当前工程最强的离线候选组合，不表示已证明 LZ parse 的数学全局
最优。P0 生产组件为 145,057 bytes，71 sectors，余 351 bytes；严格解码器逐
字节回解和完整消费已通过。精确 ISO
`4ddaa69512d5118c549016b0cea28d720f7039dfdd7da571d4f1bff21fd30c3e`
又完成 PCSX2 v2.6.3 fresh-process、PINE Running、零 TLB，因此新 parse 已
通过游戏启动路径；第一幕间目标画面仍是独立验收项。

可选加速器 `tools/native/srwz_maximum_match.c` 是独立编写的同算法实现：

- 先建立完整 prior chain，再把各 suffix 位置的搜索分配给最多 8 个 pthread；
- 用 8-byte LCP 比较跳过相同长区间；
- 不改变 65,535 chain、距离/长度上限、gain、tie-break 或 parse；
- 没有本地动态库时，`codec.py` 自动退回纯 Python；
- 单元测试在临时目录编译 C，并逐项比较 native/Python 的 distance、length、
  gain table。

P0 输出在加速前后均为同一个
`a81a7149e53529c0585c0f55c3e96cdefe7c6f89618803b6ff0ee87b9c8a6c76`。
P1/P2/P10 三个大候选最初分别由 25.4/30.4/31.4 秒降到
7.08/8.34/8.39 秒；进一步去掉大型 suffix 上不会胜出的重复旧 parse 后，
当前实测为 3.50/4.18/4.19 秒，压缩大小和哈希仍不变。

`maximum` P0 相对旧 `size-constrained`：block 从 17,529 降为 17,500，
match token 从 32,456 增为 32,582（+0.39%）；literal copy 少 414 bytes，
match copy 多 414 bytes，总解压输出复制仍为 524,032 bytes。因此构建端的
高成本搜索不会进入游戏，最终解压工作量也没有显著增长。
