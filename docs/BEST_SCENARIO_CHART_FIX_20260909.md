# v0.4.0 BEST 剧情流程黑屏修复

2026-09-09。状态：源码修复、完整构建／静态回读和 LRPS2 回归通过；当前哈希的
PCSX2 手工验收待确认。问题编号 `V040-BEST-SCENARIO-CHART`。

GitHub：[issue #21](https://github.com/dyzz/srwz-zh/issues/21)（保持开放，待手工验收）。

反馈人：**AL-E**。v0.4.0 The Best 版从“资料库 → 剧情流程”进入后黑屏卡死，BGM 继续，
按键无响应。冻结发布镜像的 LRPS2 运行复现了持续黑屏及叉键无法返回；BGM 为用户
报告，本次截图验证不单独证明音频状态。

## 原因与修复

BEST 后端重打包 `DATA/HSFC.BIN`，但只更新了 ELF 中供概要读取使用的偏移表。
剧情流程加载函数使用另一份表，仍按旧偏移读取压缩流。

| 消费者 | Original ELF 文件偏移 | BEST ELF 文件偏移 | 表项 |
| --- | --- | --- | --- |
| 概要读取 | `0x3476A0` | `0x347E90` | 四个块起点 |
| 剧情流程加载 | `0x33BE20` | `0x33C610` | 四个块起点及成员末尾 |

BEST 加载函数从运行地址 `0x1A6C60` 开始；`0x1A6C78` 和 `0x1A6CA4` 分别构造
第二张表的当前项、下一项地址，使用两者之差作为读取长度。冻结版仍使用
`0, 0x2570, 0x39B00, 0x3D0C0, 0x3D190`，正确值应为
`0, 0x1D50, 0x36450, 0x39A10, 0x3D190`。

`config/editions/best/source-layout.json` 现声明该别名表，`BestCompiler` 在压缩归档
重排后同步写入所有声明的消费者。写入前分别核对两版原盘的主表和别名表，写入后
记录实际表值；未知原盘前像直接失败。紧邻的 decoded-size 表 `0x33C630` 保持原值。
对 13 组原生主表执行完整表字节搜索，HSFC 是此次唯一发现第二处完整匹配的归档。

回归测试覆盖两份表同步、末尾 sentinel、加载长度、相邻元数据保护，以及任一版
原盘别名表漂移时拒绝构建。Original 前端仍保留 HSFC 固定分块布局。

## 验证

1. 冻结 v0.4.0 BEST：第 2760 帧选中剧情流程，3000／3540 帧全黑；3601 帧按叉，
   3900 帧仍全黑。
2. 仅修正三个偏移值的诊断镜像：与冻结版仅有 ELF 六个字节不同；同一路线正常
   显示流程图并返回资料库，确认该遗漏与黑屏的因果关系。
3. 从当前源码完整重建 Original／BEST，双版组件及 ISO 静态回读、实际 ISO 与输入
   快照绑定验证通过；Original 与本批开始时的生产锁逐字节一致。完整测试 255 项通过。
4. 正式 `current-best.iso` 重新启动 LRPS2：原路线 dHash 断言全部通过，并实测再次
   进入流程图、打开第 21 话概要、关闭概要、再次返回资料库。已逐图查看流程图、
   中文概要及返回后的菜单。三次运行均使用隔离记忆卡，源卡哈希未变。

| 镜像 | SHA-256 |
| --- | --- |
| 冻结 v0.4.0 BEST | `4ccb2355ab6d18e08db4183f06333f1d9d58b7cb7e3e4e98e6d972ae9784a18a` |
| 仅偏移修正的临时诊断镜像 | `30bf60ea7c84d2f33f997f46ccf8861094e6e8f37d89e014c976fa205c832d2f` |
| 当前正式 BEST 工作镜像 | `33e71eabc2aa2c84799e2d24c57aa78f0035e8a4633a1964735bfbb3e392894f` |

修复产物：`build/iso/zh-release-best/current-best.iso`。原冻结发布镜像保持原哈希。
工作区另有补给装置和干扰功能两条 COMPDATA 帮助文案更新，完整构建保留了它们；
这部分不归本问题修复。正式 BEST 对冻结版只变更 `SLPS_732.70` 和
`DATA/COMPDATA.BN`；其中 ELF 仅在 `0x33C614/15`、`0x33C618/19`、
`0x33C61C/1D` 六个字节不同。因果验证使用的临时诊断镜像不含文案更新。

## 凭据与复验

- 机器可读记录：[`scenario-chart-20260909.json`](../manifests/editions/best/scenario-chart-20260909.json)。
- 构建／静态日志：`work/analysis/v040-best-chart-20260909/`。
- LRPS2 receipt、隔离记忆卡和截图：`work/runtime/lrps2/v040-best-chart-20260909/`。
- 本批输入摘要：`724b7fe79029b7f62195a0df325fb4ac110282e82140e6fe6d4f7651cd98631d`。

本轮执行：

```sh
python3 -m unittest discover -s tests
python3 tools/build_editions.py --editions original,best --require-legacy-equivalence
python3 tools/verify_editions.py --manifest work/editions/724b7fe79029b7f62195a0df325fb4ac110282e82140e6fe6d4f7651cd98631d/original-best.json
arch -x86_64 work/runtime/lrps2/python-x86_64-3.12.14/bin/python3.12 \
  tools/run_lrps2_validation.py \
  --scenario work/analysis/v040-best-chart-20260909/fixed-scenario.json
```

运行记录单独保存，静态构建 receipt 的 `runtime=not_tested` 不改写为手工验收。
PCSX2 待用上述当前 BEST 哈希验证同一路线；LRPS2 通过不自动关闭该手工验收项。

按六个 ISO 槽位契约，本轮临时诊断镜像、隔离构建中的原盘／输出副本，以及与
当前 Original 相同的隔离输出在哈希核对后移除，日志与回读凭据保留。后续重跑历史
批次的 `verify_editions.py` 前，先将 `build/iso/zh-release-full-story/current-original.iso`
按本批记录的哈希校验并临时复制到 `build/iso/zh-release-original/current-original.iso`；
核验后移除该副本。LRPS2 回归直接读取保留的 `current-best.iso`。
