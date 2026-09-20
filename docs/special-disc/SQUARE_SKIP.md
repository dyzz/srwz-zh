# SP 方块 skip

SP current 默认安装本篇采用的 native-tail-r5 方块 skip。战斗演出中按 □ 请求结束当前
演出阶段；保留真实资源等待、原生清理、伤害效果、数字和后续行动。未知队列继续原生
快进，不强制伪造完成状态。默认完整构建与增量更新使用同一锁定契约。

## 构建与验证

- 契约：`config/products/special-disc/battle-square-skip.json`。
- 共享汇编：`tools/native/battle-square-skip/skip_hook.s`；Original／Best 成品字节保持不变。
- SP 完整构建：`build_full_text.py` 写入，`verify_full_text.py` 独立验证机器码与契约哈希。
- 现有 current 增量安装：`python3 tools/special_disc/writeback/update_current_skip.py`。
  先核对 current 及 ELF 哈希、原指令和空洞前像，在私有临时 ISO 写入并回读，确认其他字节
  与 LBA 不变后替换 current。已安装时只验证；源漂移或并发更新时失败。
- 汇编复验：`python3 tools/native/battle-square-skip/assemble_hook.py --special-disc`。
- 指令测试覆盖 Original／Best／SP，以及 SP 播放模式字节、双场景收尾、资源等待、队列代次、
  无按键、非法队列、寄存器保存和原生追加函数重放。

## SP 适配边界

| 项目 | SP 值 |
| --- | --- |
| 可执行文件 | `SLPS_259.20`，文件基址 `0x980`，虚拟基址 `0x100000` |
| hook／状态区 | `0x450780`／`0x450D80`，总预算 `0x800` 字节 |
| 世界更新调用 | `0x2E9C48` → `0x30E7B0` |
| 队列追加入口／续接 | `0x2F2280`／`0x2F2288` |
| 输入状态 | `0x75A900`，相关标志比本篇偏移 `+1`；保留新增的播放模式字节 |
| 场景结构步长 | `0x1150`，比本篇少 `0x10`；两个场景及队列代次均按此适配 |
| 方块触发／读取忙 | `0x62514E`／`0x4ED160` |

静态定位依据为原盘反汇编及严格指令匹配，保存在
`work/analysis/sp-square-skip-20260920/disassembly.txt`。仅文件零区不代表运行时安全，
运行探针另逐帧检查前 `0x600` 字节代码区；状态区允许游戏 hook 正常写入。

## 验证记录

可提交、不含游戏数据的摘要见 `manifests/special-disc/square-skip-validation.json`。

静态／ISO 回读见 `work/verification/sp-square-skip-20260920/readback.json`。
本轮只改变 ELF 中 749 个字节；4 个允许写入范围以外的 3,791,779,828 字节完全一致。
全量已绑定文本回读通过，ISO 长度和成员 LBA 不变。

LRPS2 软件渲染证据、输入记录、逐帧 trace 和截图位于
`work/runtime/lrps2/sp-square-skip-20260920/`。精确运行结果以该目录的
`runtime-receipt.json` 为准。该证据不替代 PCSX2 人工验收，也不代表剧情、战斗剧场、
普通／简易鉴赏全部攻击分支已覆盖。

本轮 LRPS2 简易鉴赏实测：两次 □ 请求、两次原生清理、两次终态推进；保留 27 帧资源等待，
失效记录为零；第 1200–6065 帧共 4866 次代码区检查通过，伤害数字可见，最终返回鉴赏
设置界面。只覆盖这场攻击及反击，不宣称其他模式或 PCSX2 人工验收已完成。
