# v0.4.1 构建与发布记录

2026-09-09。针对 v0.4.0 The Best 剧情流程黑屏卡死发布修复版，同时打包 Original 与
The Best 两个独立 xdelta。游戏源码与 Q&A 修复已提交至 `180663c`；后续发布配置、
默认打包版本、文档和验证摘要不改变游戏字节。

## 冻结产物与源码绑定

冻结本日已完成双版构建、静态回读和 Q&A 运行验收的最终产物，本轮不重新改动游戏
内容。实际双版构建输入摘要为
`3e738e23a2b3dc3962b06bf07ea4406d0179acef242034fe7e1bace6f24f6746`。

| 版本 | 冻结路径 | SHA-256 |
| --- | --- | --- |
| Original | `build/iso/v0.4.1/srwz-zh-v0.4.1-original.iso` | `7ee310d80d6167a85ab4a4fe4ea373df45817e02b0ebd1838f4506e1fdcea6e6` |
| The Best | `build/iso/v0.4.1/srwz-zh-v0.4.1-best.iso` | `d7a92841d3981ef0fb59d67f1f794692103b00730d6936fdec767a216ab6af9c` |

冻结前逐盘重新核对大小与 SHA-256，再运行 `verify_editions.py`，重新核对输入快照、
两版回读、Best 组件回读及实际 ISO 的绑定。Original 回读覆盖 170 个 STAGE、93,071
条翻译；Best 回读覆盖 205 个 STAGE 块、84,338 条剧情文本所有者。

发布工作树与该批输入逐文件对比：游戏工具源码、语料、字库及版本布局配置一致；
差异仅为构建完成后更新的输出锁和验证报告。构建时未提交的 Q&A 源码已单独提交。
差异前后哈希及说明见 [源码绑定记录](../manifests/releases/v0.4.1/source-binding.json)。
构建快照的 `source_head` 是创建快照时的 HEAD，不能单独代表当时包含的工作树修改。

## 检查与运行验收

- `python3 -m unittest discover -s tests`：263 项通过。
- 原盘验证、Python 编译、构建与打包 CLI 入口及 Git 空白检查通过。
- 最终冻结 Best ISO 冷启动 LRPS2，执行进入流程图、返回、再次进入、打开第 21 话
  概要、关闭概要、再次返回资料库；10 个截图检查点通过。逐图查看第 3000、4500、
  5100 帧，确认流程图、中文概要及菜单返回，源记忆卡哈希未变。
- 两版 SR 点数 Q&A 的已有 LRPS2 receipt 与截图重新核验哈希，绑定的 ISO 与冻结
  产物完全一致；本轮再次查看两版第 3900 帧的完整提示、两端引号及普通色句号。

用户已确认相关问题以 LRPS2 通过作为运行验收，无需另做 PCSX2。本次没有执行 PCSX2；
静态构建原始 receipt 中的 `runtime=not_tested` 保留，运行结果由
[独立运行记录](../manifests/releases/v0.4.1/runtime.json) 绑定，不能扩大为全路线验收。

搜索说明此前已做两版 LRPS2 验证，绑定的是当时修复镜像。新增菜单帮助、名称表和
充能贴图仍为静态回读通过；Q&A 的其余 44 个候选另在 issue #24 跟进。

## 补丁生成与复验

发布工具固定 xdelta3 3.2.0，使用 `-e -9 -S djw -A -a` 编码，再对每个补丁从对应
日文原盘实际还原临时 ISO，核对大小和整盘 SHA-256。临时还原文件不进入发布目录。
补丁大小、校验值与实际还原结果见 [补丁清单](../manifests/releases/v0.4.1/patches.json)。
GitHub Release 仅上传两个 `.xdelta`，不上传完整 ISO 或存档。

可在 v0.4.1 标签工作区准备两版固定原盘后重建：

```bash
python3 tools/build_editions.py --editions original,best
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best.json
mkdir -p build/iso/v0.4.1
cp -n build/iso/zh-release-original/current-original.iso build/iso/v0.4.1/srwz-zh-v0.4.1-original.iso
cp -n build/iso/zh-release-best/current-best.iso build/iso/v0.4.1/srwz-zh-v0.4.1-best.iso
python3 tools/build_release.py --config config/release/v0.4.1.json
```

发布目录为 `build/release/v0.4.1/`。若重建结果与本版固定目标不符，打包工具会在编码
前失败。新生成的输入摘要可因发布元数据不同而变化；最终游戏镜像必须匹配上表。

## 本地保留

两份 v0.4.0 冻结 ISO 继续作为原问题复现基准；新增两份 v0.4.1 冻结 ISO。加上两版
原盘和两版 current，共八个长期槽位，见 [ISO 目录契约](ISO_DIRECTORY_LAYOUT.md)。
为复验旧批次恢复的 Original 隔离输出在核对后移除；保留构建、运行日志和截图。
本轮本地日志位于 `work/release/v0.4.1/`，黑屏回归位于
`work/runtime/lrps2/v041-best-chart/`。
