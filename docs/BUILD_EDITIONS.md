# Original、The Best 与 SP 的统一构建

`python3 tools/build_editions.py` 默认刷新并构建三个当前 ISO，三版均内置方块键跳过战斗动画（skip）。每版都有独立写入锁、
工作目录、原盘身份和最终回执。旧发布快照不被覆盖，完整 ISO 不提交到 Git。

```bash
python3 tools/build_editions.py --plan
python3 tools/build_editions.py
python3 tools/build_editions.py --editions original,best
python3 tools/build_editions.py --editions sp
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best-sp.json
```

注册表沿用 `config/release/dual-current.json` 路径，现已注册三版。现有发布打包配置
仍明确选择 Original／The Best；加入 SP 构建不自动扩大已冻结的发布包范围。

| 版本 | 日文输入 | 当前输出 |
| --- | --- | --- |
| Original | `rom/original.iso` | `build/iso/zh-release-original/current-original.iso` |
| The Best | `rom/best.iso` | `build/iso/zh-release-best/current-best.iso` |
| SP | `rom/Super Robot Taisen Z - Special Disc [J].iso` | `build/iso/special-disc/sp-current.iso` |

原盘实体统一位于 `build/iso/sources/`，表中的 `rom/` 为兼容入口。各版私有工作区位于 `build/editions/<profile>/<run-key>/project/`；包含原盘副本和临时 ISO 的目录不再新建于 `work/build/`。目录说明及历史路径兼容见 [ISO 目录契约](ISO_DIRECTORY_LAYOUT.md)。

本篇构建工具要求见 [构建与运行](BUILD_AND_RUNTIME.md)。三份日文原盘必须匹配各版
`config/editions/<edition>/edition.json` 中的大小、SHA-256 与可执行文件身份。

SP 另需 xdelta3，以及 `config/editions/sp/inputs.json` 锁定的本地资源：日文原盘对应的
基线差分、已验证的字体码表与组件、旧 system 组件的合成前像、Original Q&A 原始成员、
图像字体和五份场景图／剧情绑定配置。这些二进制不进入 Git；缺失或哈希变化会直接拒绝构建。
这是当前 SP 后端的明确依赖，尚不是只凭日文原盘即可从零重建全部历史组件的入口。

同批源码、语料、配置及上述 SP 依赖在构建前统一冻结，复制到各版私有工作目录。
Original 为 BEST 提供同一快照的公共编译结果。SP 独立使用自己的锁定字体与基线，
重新运行 system、42 个 STAGE 块、战斗字幕、frame 与图像写入器，再合成当前 Q&A、
地形、武器效果、机体名和标题组件。不会用本篇 Q&A 覆盖 SP 专有条目。

SP 在替换当前 ISO 前验证原盘、组件报告、码表、语料覆盖、字体覆盖、成员大小与 LBA、
ISO 非目标区域以及最终成员回读。统一回执位于 `manifests/editions/sp/current.json`，
完整 SP 组件回执同时保留在 ISO 旁的 `sp-current.json`。批次验证还核对输入快照、
输出 ISO 哈希和各版回读报告的绑定。

正常 SP 图像构建只写入冻结的索引数据。需要 PNG 预览时，可单独运行
`python3 tools/special_disc/writeback/write_image_labels.py --previews`；该可选步骤需要
Pillow。默认统一构建不依赖 Pillow，也不重新栅格化已冻结图片。

每版通过回读并更新当前 ISO 后，立即保存该版回执。后续版本失败时，批次仍明确记为
失败，但不会让已经完成的当前 ISO 对应旧回执。

这些结果只证明静态构建和回读通过。新 ISO 的 LRPS2、PCSX2 人工检查、全剧情及
存读档回归独立记账；不会把历史 ISO 的运行证据自动归入新镜像。

## 日常测试副本与计时

每版通过内容回读后，构建器自动更新 `build/iso/daily-test/current-{original,best,sp}-skip.iso`。
副本与该版当前 ISO 逐字节身份一致，不再在构建后另外打 skip 补丁。发布前核对完整 SHA-256、
大小，并从副本读取本版可执行文件检查 skip 跳转和 hook；失败保留旧日常副本。副本不采用硬链接。
只构建 SP 时只更新 SP；BEST 单独构建仍会重建并更新其 Original 前端。

`config/iso/daily-test-isos.json` 和 `retained-isos.json` 只保存当前盘的路径及策略，
其实际身份读取 `manifests/editions/<edition>/current.json` 的 `daily_test` 字段。
构建生成的哈希不写回输入配置，避免下一轮输入快照因上轮产物而变化。
`verify_editions.py` 会校验新版批次中的日常副本及 skip；历史无此字段的批次保持兼容。
已冻结的 v0.4.2 镜像与发布配置不变。

批次 JSON 的 `timing` 保存 UTC 起止时间、完整墙钟耗时、预检/快照耗时、各版总耗时、
子命令分项耗时及日常副本校验/发布耗时。各版工作区另有 `timing.json`，失败阶段也记录退出码与耗时。
分项之和之外的耗时包括快照物化、缓存准备、文件哈希、发布当前盘和回执检查；三版总耗时包含这些开销。
这是现有本地缓存条件下的正常完整构建计时，不能当作空缓存机器的冷启动时间。
