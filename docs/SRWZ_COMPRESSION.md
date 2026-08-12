# SRWZ 压缩格式与生产约束

## 最终结论

- `STAGE.BIN`、`COMPDATA.BN`、`MTV_PROS.BIN` 和 VT1 使用同一类游戏原生压缩
  流；仓库已有严格 clean-room decoder 和确定性 encoder。
- 当前 232 个真实可解码流均可完整 round-trip；`STAGE.BIN` 为 205/205 块。
- 生产统一使用 `tools/native/srwz-codec-rs/` 的 Rust codec。Python codec 只作
  严格 decoder、round-trip 和回归 oracle。
- 不执行上游 DLL/EXE，也不把其视为生产依赖；不改用 Deflate、LZMA 等游戏不
  支持的格式。
- COMPDATA 生产硬门为 145,408 bytes／71 sectors；最终组件必须压入该预算，
  不要求为了更小而固定使用最慢的最大化策略。
- 格式正确、静态回解和 PCSX2 目标流程是独立门；不能用其中一层代替另一层。

## 流格式

### Coded integer

每个字节贡献高 7 位，最低位表示终止：

```text
value = (value << 7) | (byte >> 1)
if byte & 1:
    end
```

decoder 默认最多读取 10 字节；未终止或越界时抛出带输入 offset 的
`SrwzCodecError`。

### Header

读取顺序：

1. declared output size；
2. flags；
3. flags 的 `0x40` 条件成立时读取 `header_unknown_0`；
4. 读取 `header_unknown_1`。

窗口为：

```text
window = 1 << (((flags >> 1) & 0x0f) + 8)
```

当前 232 个样本使用的写入规则是：选择不小于 decoded size 的最小二次幂窗口，
下限 256、上限 8 MiB，并写入对应 odd flags；`header_unknown_1 = 0`。
`0x40` 头部变体尚无真实生产样本，显式触发时必须同时提供其字段。

### Block

控制字节：

```text
literal_count = control & 0x0f
match_count   = control >> 4
```

nibble 为零时继续读取 coded integer 扩展计数。先复制 literal；若输出已经达到
declared size，流在这里结束，否则继续复制 match。

游戏 R5900 解压器的 literal 与 match 都是 post-tested loop，因此 encoder 必须
保证：

- 每个 block 的最终 `literal_count >= 1`；
- 输出未完成时 `match_count >= 1`；
- 不生成依靠宿主语言零次循环语义才能工作的 block。

### Back-reference

```text
distance_seed     = (token & 0x0f) >> 1
distance_extended = (token & 1) == 0
length_seed       = token >> 4
distance          = distance_value + 1
length            = length_value + 1
```

distance 扩展以 seed 为 coded-integer 初值继续读取；length nibble 为零时读取扩展。
copy 允许 overlap，每产生一个字节便立即进入可回溯窗口。

## Decoder 门禁

`tools/srwz/codec.py` 必须：

- 对每次输入读取做边界检查；
- 拒绝 truncated／malformed coded integer；
- 拒绝指向未生成输出或超出窗口的 back-reference；
- 拒绝 literal／match 越过 declared size；
- 拒绝零 literal 和非最终零 match；
- 返回达到 declared size 时的实际 `consumed`，不吸收归档层尾部；
- 对最大输出、token 数和 coded-integer 长度执行上限。

VT1 中存在“压缩流前缀 + 非零外层尾部”和非当前格式段；writer 必须保留其外层
结构，不能把剩余字节自动当作 padding。

## Encoder 门禁

生产 Rust codec 使用原生 block／token 语法、compact distance seed 和真实序列化
成本。生产 profile 统一使用 `rust-fit`，一旦满足目标预算即可停止；
`rust-maximum` 仅保留为研究和小样本比较，不进入生产链：

```text
backend:           rust-only
strategy:          rust-fit
budget:            profile max_output_size / member sectors
```

具体 match 参数由 profile 锁定。`rust-maximum`、旧 greedy 和 Python maximum
只作小样本回归参考，不能进入生产组件。

encoder 或 suffix writer 超过 `max_output_size` 时必须抛出 `SrwzEncodeError`，
不得截断、修改 declared size、丢弃 decoded tail 或依靠移动 LBA 规避预算。

生产 Rust 策略会重压完整 decoded payload，避免把旧 Python encoder 的 block
带入生产结果；非生产回归策略仍可保留未变的原 block。Python decoder 只保留源码
用于隔离格式研究，生产和静态验收均使用 Rust decoder。任何生产路径都必须执行：

1. Rust 完整 decode；
2. decoded payload 精确一致；
3. consumed 与外层 padding 检查；
4. archive alignment 和 offset 重读；
5. 组件成员大小／哈希和 ISO LBA 检查。

## 已验证范围

固定原版样本和当前回归测试的聚合结果：

| 域 | 可解码流 | Round-trip |
| --- | ---: | ---: |
| STAGE | 205 | 205 |
| COMPDATA | 1 | 1 |
| MTV_PROS | 14 | 14 |
| VT1 | 12 | 12 |
| 合计 | 232 | 232 |

原版 `STAGE.BIN` 大小为 3,910,128 bytes，205 个 slice 的尾部为 0–15 bytes
零 padding。该结论只适用于固定样本，不能外推所有归档。

当前 STAGE、COMPDATA 和 VT1 都已通过 Rust 重编码、Rust 完整回解和成员预算门。
对同一物理流的多组写入先共用 decoded workspace，完成写入与检查后只重编码一次。
运行结论仍必须绑定当前组件、精确 ISO 哈希和目标 PCSX2 流程，不能从旧候选继承。

## 未覆盖边界

- flags 全部位的语义和 `header_unknown_*` 的业务含义；
- `0x40` 条件头部真实样本；
- VT1 混合段的完整外层结构；
- 未扫描归档是否存在其他变体；
- 原版压缩器的全局最优匹配策略。

这些未知项不阻塞当前已登记格式的 deterministic production，但遇到新变体必须
fail closed，不能静默套用现有规则。
