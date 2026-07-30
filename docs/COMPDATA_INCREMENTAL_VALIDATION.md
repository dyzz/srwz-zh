# COMPDATA 递增验证与 71 扇区约束

`DATA/COMPDATA.BN` 不是一个可以整体替换后只看离线回解结果的普通成员。
当前实验证明：它后面的 `DATA/NisVData.bin` 及后续成员至少有一条启动读取
路径依赖原物理 LBA。生产候选在没有定位并修补全部读取点之前，必须留在原版
71 个 2,048-byte 扇区内，即不超过 **145,408 bytes**。

## 当前涉及的汉化层

| 层 | 已选决定 | 当前压缩大小 | 相对 145,408-byte 上限 | 状态 |
| --- | ---: | ---: | ---: | --- |
| P0 幕间按钮 | 24（23 写入、1 no-op） | 145,300 | 余 108 | 启动通过；目标画面待截图 |
| 全部 P0 COMPDATA 菜单（旧 greedy） | 44（41 写入、3 no-op） | 147,050 | 超 1,642 | 历史失败对照 |
| 全部 P0 COMPDATA 菜单（size-constrained） | 44（41 写入、3 no-op） | 145,237 | 余 171 | 71 sectors；启动通过；目标画面待原生存档 |
| 全部 P0 COMPDATA 菜单（maximum） | 44（41 写入、3 no-op） | 145,057 | 余 351 | 71 sectors；严格回解；fresh-process 启动通过、0 TLB |
| 开场姓名 | 45 | 156,161 | 超 10,753 | 被原位容量门阻塞 |
| researched 人物／机体名 | 1,262（连同开场共 1,307） | 144,485 | 余 923 | 已进入当前 P2 候选并通过 boot smoke |
| P10 数据库 COMPDATA 核心 | 170 | 148,705 | 超 3,297 | 仍被原位容量门阻塞 |
| 开场姓名（maximum 离线测量） | 45 | 143,493 | 余 1,915 | 严格回解；下一层运行候选 |
| researched 人物／机体名（maximum 离线测量） | 1,262（连同开场共 1,307） | 143,973 | 余 1,435 | 严格回解；P1 运行通过后再测 |
| P10 数据库 COMPDATA 核心（maximum 离线测量） | 170 | 144,700 | 余 708 | 严格回解；前序层运行通过后再测 |

阶段标题 122 条不在上述已写入层中。它们目前仍是
`corpus/zh/menu/stage-names.json` 中的翻译草稿，COMPDATA 文本池尚未注册，
不能把它们记为“已经写入但被 TLB 阻塞”。

前三个“被阻塞”行保留旧 greedy 组件的历史事实；其后的 `maximum` 行是对
完全相同 decoded payload 的新测量。体积过线只解除容量门，不自动继承 P0 的
运行结论。晋级仍按 P1 → P2 → P10，每次只替换当前唯一 ISO 并绑定新哈希。

## 因果实验

所有镜像都固定使用同一套已经启动通过的非 COMPDATA 成员，只改变
`DATA/COMPDATA.BN`。

| 实验 | COMPDATA | 后续 LBA | PCSX2 v2.6.3 fresh-process |
| --- | --- | --- | --- |
| 非 COMPDATA 基线 | 原版 144,990 bytes／71 sectors | 原位 | PINE Running；0 TLB |
| P0 幕间按钮 | 重编码 145,300 bytes／71 sectors | 原位 | PINE Running；0 TLB |
| 纯 LBA 控制 | 原始压缩流逐字节不变，只追加 419 个零字节；72 sectors | `NisVData.bin` 起 +1 sector | PINE Paused；1 TLB |
| 全部 P0 菜单 | 重编码 147,050 bytes／72 sectors | `NisVData.bin` 起 +1 sector | PINE Paused；1 TLB |
| 全部 P0 菜单优化版 | 重编码 145,237 bytes／71 sectors | 全部成员原 LBA | PINE Running；0 TLB |

两个失败镜像的首个异常均为：

```text
TLB Miss, pc=0x1c6ea0 addr=0x02000000 [store]
```

纯 LBA 控制的原始压缩流、声明输出和解码结果完全不变，因此这次失败不能
归因于中文文本或 clean-room 压缩 token。相反，重编码的 71-sector 按钮组件
可以启动，说明编码器不是当前首个故障原因。

优化版另用 P0 fixed SLPS 和保持原大小的 P0 VT1 构建 3-member replacement
ISO。静态报告确认 66 个成员全部保持原 LBA，`NISVDATA.BIN` 及其后成员无
shift；PCSX2 v2.6.3 fresh-process 连接 PINE，状态为 Running，日志 0 TLB。
精确镜像和 receipt 见
`manifests/compdata-step-02-p0-menu-inplace-runtime-validation.json`。

旧运行结论对应 145,237-byte `size-constrained` 版本。新 `maximum` 版本把
同一 decoded payload 压到 145,057 bytes，离线逐字节回解和完整消费通过；
精确 ISO SHA-256 为
`4ddaa69512d5118c549016b0cea28d720f7039dfdd7da571d4f1bff21fd30c3e`，
PCSX2 v2.6.3 fresh-process 为 PINE Running、0 TLB。该运行证据证明新压缩
parse 被游戏启动路径接受，仍不替代第一幕间的目标画面验收。

## 可重复验证

```bash
python3 tools/build_ui_p0_fixed_compdata.py \
  --config config/ui-writeback/compdata-step-01a-p0-buttons.json \
  --force
python3 tools/verify_ui_p0_fixed_compdata.py \
  --config config/ui-writeback/compdata-step-01a-p0-buttons.json \
  --force
python3 tools/build_compdata_lba_shift_control.py --force
python3 tools/prepare_ui_iso_incremental_chain.py \
  --config config/iso/compdata-incremental-chain.json
python3 tools/audit_compdata_incremental_chain.py --force
python3 tools/analyze_compdata_compression.py --force
python3 tools/build_ui_p0_fixed_compdata.py \
  --config config/ui-writeback/compdata-step-02-p0-menu-inplace.json --force
python3 tools/build_canary_iso.py \
  --config config/iso/compdata-step-02-p0-menu-inplace-build.json
python3 tools/record_pcsx2_boot_smoke.py \
  --iso build/iso/compdata-step-02-p0-menu-inplace/srwz-compdata-step-02-p0-menu-inplace.iso \
  --run-id 08-compdata-p0-menu-inplace --duration 8 --force
```

精确镜像、构建报告、PINE receipt 和日志由
`manifests/compdata-incremental-validation.json` 锁定。

## 下一步顺序

1. 取得第一幕间原生 memory-card fixture，完成完整 P0 目标画面验收；
2. 再逐层加入开场姓名、research 名称和 170 条数据库文本；
3. 每层都必须保持后续 LBA，不通过就继续拆分，不得直接晋级；
4. boot smoke 只证明 DVD／ELF／PINE／TLB。幕间按钮仍需匹配存档、导航和
   截图才能完成目标画面验收。
