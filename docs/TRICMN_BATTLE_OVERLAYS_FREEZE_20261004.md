# TRICMN 战斗文字定稿与当前 ISO 写入

2026-10-04 用户确认这组贴图改动冻结。定稿包含本轮状态／抵抗文字 10 条、阵型／攻击标题 12 条，以及补上 EN 风格光晕的提示／原因文字 10 条。其余 19 条能力／防御文字沿用此前冻结的索引像素。

普通构建继续使用 `locked-indexed-snapshot`，不重新读取字体或栅格化。快照保持 `reviewed_locked`、`explicit_refreeze_only`；下一次视觉调整必须明确进入作者渲染及重新冻结流程。定稿不将 LRPS2 证据提升为 PCSX2 手工验收，运行状态仍为 pending。

## 定稿身份

| 文件 | SHA-256 |
| --- | --- |
| 冻结索引快照 | `71791d097ed2e480707533a5f3c12bc179f951ef42ae23d0f6fe2e07dff7de0f` |
| 主篇 `BTL/TRICMN.BIN`，677,424 字节 | `00b6de888086ea5198bbf166612c7961cc818288f11cebff3de64d283691253b` |
| SP `BTL/TRICMN.BIN`，677,456 字节 | `9e2031d7d190ea5c2a7405b147ca6ba11ff35d9a87953718fc131f86755c241f` |
| 主篇当前 ISO | `f3ee8e64a24f34fc4ef2207c9f9648844710bc931cbf1df20d90f2c1b649cc98` |
| SP 当前 ISO | `3265643bfd1f9a488a7a7805a1914d1ddcf08af6ad2543750f794ff005884c69` |

主篇当前路径为 `build/iso/zh-release-full-story/current-original.iso`，SP 当前路径为 `build/iso/special-disc/sp-current.iso`。不生成新的发行快照，ISO 二进制留在本地。

## 写入与回读

主篇只更新成员内 picture 0、1 两个 65,536 字节图像区，写入完整冻结成员之前检查其他图像、所有头、CLUT 与动画尾部均与当前镜像一致。写入后成员目录、大小、LBA 保持一致；成员 LBA 为 1,312,883。

其余 **3,758,227,456 字节**镜像内容与写入前逐字节比较一致。所有成员按 ISO9660 回读，并对配置中的 24 个成员进行独立 UDF 回读；`BTL/TRICMN.BIN` 与冻结成员完全一致。主篇集成组件及 ISO 配置只刷新 TRICMN 相关锁。旧文本输入锁保持原记录；本次没有将其他未提交文本改动重建入 ISO，也不宣称旧文本输入与当前工作区一致。

SP 镜像已是定稿版本，本轮重复刷新提示文字不产生修改。另从当前 ISO 独立回读 10 个状态、10 个提示和 12 个标题单元，逐个核对冻结索引字节，保留 SP 自身其他区域和 CLUT。

复现入口：

```sh
python3 tools/build_tricmn_battle_overlays.py --force
python3 tools/refresh_tricmn_battle_overlays.py --evidence work/analysis/<新的主篇证据目录>
python3 tools/special_disc/writeback/refresh_battle_prompts.py --evidence work/analysis/<新的SP证据目录>
```

当前已匹配冻结成员时，更新器直接返回。SP 后续全量构建按状态、提示、标题三组复制冻结单元，独立验证器核对同样的单元。32 个单元共用迁移／回读实现，禁止修改单元以外像素。

证据：

- `work/analysis/tricmn-freeze-20261004/main-production/production-readback.json`：主篇 ISO 回读、范围保护及继承的旧组件绑定。
- `work/analysis/tricmn-freeze-20261004/sp-production/frozen-readback.json`：SP 当前镜像 32 个冻结单元独立回读。
- `work/analysis/tricmn-freeze-20261004/tests.log`：30 项定稿相关测试全部通过，包含冻结快照、三组 SP 单元迁移／回读、PSMT4 及主篇写入的元数据／越界保护。

## 当前主篇镜像运行检查

使用之前都市关卡第 2 回合 Continue 的私有记忆卡副本，王者盖纳以“超限冻弹”攻击凯鲁宾兵，选择分散阵型并打开完整演出。没有修改 RAM、程序或运行事件。

帧 6104 自然显示“无目标”，帧 7544 自然显示“无法攻击（射程）”；可见补光晕后的本身槽位提示。

![当前主篇自然无目标](issue-assets/battle-prompts-20261004/frozen-main-no-target.png)

![当前主篇自然无法攻击射程](issue-assets/battle-prompts-20261004/frozen-main-range.png)

同一场战斗在帧 7304 自然触发新冻结的“运动性下降”，补充了状态组一条自然事件证据。其他状态文字仍保留原有诊断注入／借槽证据的边界，不能据此认为 10 种状态都已自然触发。

![当前主篇自然运动性下降](issue-assets/battle-prompts-20261004/frozen-main-mobility-down.png)

运行证据为 LRPS2 Software (SW)。源记忆卡 SHA-256 保持 `8880c03560fa0d436d005d8c9dde199239820a03c5106eecdb273186fcaabff0`，记录在 `work/runtime/lrps2/tricmn-freeze-20261004/production-native/receipt.json`。PCSX2 手工验收及完整淡入淡出检查仍待补。

前序修订与画面对照：[状态文字](SP_BATTLE_STATUS_TEXTURE_20261004.md)、[阵型／攻击标题](SP_BATTLE_TITLES_TEXTURE_20261004.md)、[提示文字与 EN 光晕](SP_BATTLE_PROMPTS_TEXTURE_20261004.md)。上述记录内旧 ISO 哈希属于各次历史修订，最终定稿身份以本文件为准。
