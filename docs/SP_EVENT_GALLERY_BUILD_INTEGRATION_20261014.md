# 事件演出并入统一构建与构建流程整理（2026-10-14）

把[本篇对齐后的 SP 特别剧场事件演出](SP_EVENT_FIDELITY_20261014.md)从“对已合成 SP 镜像再打一层补丁的独立候选”改为 SP 统一构建的一个合成阶段，同时整合最新文案改动（`stage-007`、`stage-013` 社区采纳稿）重新构建三版当前镜像。同日用户确认字幕稿可接受后，本篇 Original／Best 的原关卡事件字幕（`tools/event_subtitles/`）也以同一机制并入两版构建，见下文“本篇字幕并入”。

## 结果

| 版本 | 当前镜像 SHA-256 | 大小 | 本轮耗时 |
| --- | --- | ---: | ---: |
| Original | `e7b54efd23765baa68fe20c1ac4a4586c1f0d39dcec61f3436925183afdd820b` | 3758358528 | 94.6 s（组件完整引导） |
| The Best | `5f100d7c7ad84d20dad4fd312ee52756fa317856cb3cd82f739a44cefd5bae83` | 3755081728 | 22.0 s |
| SP | `43f3202236de9bf56b11b38734ef7fd5ef5eba8125e9a7ca64e0ffbeb47b0bd4` | 3913996288 | 74.1 s（含鉴赏 7.2 s、追加成员 0.1 s、独立回读 18.1 s） |

批次 `work/editions/81a4b7bae603e7584e62225e5ec57fd07095f95a116b4ee3481e2a04821d52b4/original-best-sp.json`，总耗时 192.6 s，`verify_editions.py` 通过。回执副本见 [issue-assets/sp-event-fidelity-20261014/build/](issue-assets/sp-event-fidelity-20261014/build/)。

SP 镜像里的 `SLPS_259.20`（`ed648f65…`）、`AID_DATA/AIDDATA.BIN`、`EFF/VEFF2DX.BIN` 三个成员与 LRPS2 验收候选 `c163bac9…` 中的对应成员逐字节相同，LBA 与大小也相同；因此[对齐记录](SP_EVENT_FIDELITY_20261014.md)的 15 轮冷启动播放、恢复和 BGM 证据直接适用于当前 SP 镜像。另对当前 `sp-current.iso` 做了一次冷启动抽检（魔神Z、脉冲各一轮，原生按键，只读观察），结果见本页末尾。

## SP 合成流程的变化

`writeback/build_full_text.py` 的 `assemble()` 在指令覆盖之后、写盘之前增加“事件演出”阶段：

1. `special_disc/event_gallery/apply.py::apply_event_gallery` 是纯成员变换：输入全文本补丁后的可执行文件和原生 AID／VEFF，输出三个鉴赏成员。它完成菜单数据、原生运行脚本汇编、AID 块 2 横幅、9 处指令钩子、12 个 effect 块字幕贴图、字幕表和私有程序段，并把配置、字幕稿、码表、字体、源码和资源的哈希写入回执。菜单文案改用写入器共用的锁定码表 `work/build/special-disc/text-candidate/font/proposal.json`（与旧的 `work/writeback/zh-release-codebook-proposal.json` 逐字节相同），不再依赖私有工作区外的文件。
2. 三个成员超出原盘分配，由新模块 `special_disc/iso_relocation.py` 追加到基线镜像之后：写目录记录与两份卷描述符、改 `VMAP.DAT` 扇区目录、更新 UDF 文件项并扩展分区。它返回所有在原镜像长度内被改写的字节区间；受保护区域校验（`verify_iso_ranges`）把这些区间和就地写入的成员区间合并后，证明其余每个字节与基线相同；尾部必须恰好是三个成员载荷加 257 块 UDF 元数据，非锚点块全零。
3. 报告的 `files` 现在包含三个重定位成员的哈希，`relocated_members`、`relocation_readback`、`event_gallery`、`event_gallery_readback` 记录追加位置和回读。独立回读 `verify_full_text.py` 新增 `verify_gallery_members`：核对 9 处钩子、第 72 个程序头和 12 个字幕块的解码哈希；Data Link 校验改为只看原生长度的代码区（附加段由鉴赏回读负责）。
4. `event_gallery/build.py` 只保留为隔离实验包装：从一张已合成的 SP 镜像读出三个成员、做同样的变换、经同一重定位模块写到 `work/iso/` 候选。

依赖登记：字幕字体 `HarmonyOS_Sans_SC_Regular.ttf` 加入 `config/editions/sp/inputs.json` 锁；横幅资源随 `tools/` 进入冻结快照。`incremental.ASSEMBLY_ONLY` 把 `event-gallery.json`、`event-subtitles.json`、`tools/special_disc/event_gallery/` 和该字体排除在五组组件的指纹之外——它们只被每次都执行的合成阶段读取，改动不再触发五组组件重建；新增的未知配置文件仍保守地重建全部组件（测试覆盖）。

旧候选归档：`build/iso/special-disc/` 下只保留 `sp-current.iso`（`test_only_current_sp_iso_is_retained` 恢复通过），V7 与验收候选移至 `work/iso/archive/`，兼容链接 `work/iso/sp-event-gallery-review.iso` 指向 `sp-current.iso`。

## 统一入口的一处修复

首次三版构建在 Original 组件阶段失败：`incremental candidate config drift`。原因是 Original 在无法承接上一批次已验证缓存时（本次因 `config/editions/sp/inputs.json` 变化而拒绝承接），`seed_original_caches` 把主工作区的 `work/build/zh-release-full-story/components` 原样复制进私有工作区；该目录含 10 月 12 日一次直接运行留下的、未晋升的两阶段候选（报告 ≠ 清单），集成组件构建器把它当作待晋升候选并因配置锁不符而拒绝。此前的批次都能承接上一批次，所以没有触发。

修复：`build_original` 在无法承接时不再复制集成组件根（`release_inputs.INTEGRATED_COMPONENT_BUILD_DIRS`），让 `rebuild_zh_font` 走它既有的“full-bootstrap”路径完整构建组件，逐字形字体栅格等每消费者缓存仍然生效。本轮 Original 组件 59.8 s、整版 94.6 s，是这条路径的实际耗时。主工作区那份过期候选未动。

## 验证

- 静态：全工作区 `tests/` 运行结果见下文；新增 `test_sp_iso_relocation`（区间合并）、`test_edition_incremental.IntegratedComponentSeedTests`、SP 增量矩阵中的合成专用输入用例；`test_sp_event_gallery_fidelity` 等 10 项鉴赏测试保持通过。
- 构建：`build_editions.py` 三版通过，`verify_editions.py` 通过；SP 独立回读含鉴赏段。
- 运行：鉴赏成员与验收候选逐字节相同；当前镜像冷启动抽检见下。

### 当前镜像冷启动抽检（LRPS2）

对 `sp-current.iso`（`43f32022…`）冷启动、隔离记忆卡、原生按键进入特别剧场，播放魔神Z出击（第 11 项）和脉冲高达出击（第 1 项）各一轮：两轮自然结束并返回列表，播放中的 BGM 分别为 0x46、0x1e（与原脚本一致），返回后名册快照逐字节相同、关卡标志／缩放／占位表恢复、剧场 BGM 回到 99 号。`verify_flow.py` 通过，无宿主写入。关键帧、录音、流程报告和命令记录见 [runtime-integrated/](issue-assets/sp-event-fidelity-20261014/runtime-integrated/)。这是对已逐字节等同的成员做的抽检，不替代对齐记录中的 15 轮全量验收。

全工作区单元测试：753 项通过，6 项跳过（`python3 -m unittest discover -s tests`）。


## 本篇字幕并入 Original／Best（同日第二轮）

用户确认 37 句 SP 字幕稿与本篇补充的一句拟声字幕可接受后，把 `tools/event_subtitles/build.py` 拆成纯成员变换 `apply.py`（`apply_event_subtitles`／`verify_subtitle_members`／`verify_subtitled_iso`）和隔离候选包装。`build_editions.apply_main_event_subtitles` 在每版原生封盘与语义回读之后运行：读出已验证镜像的可执行文件与效果档，追加 12 个 effect 块的字幕贴图（38 句，含 effect256 第 710 帧的本篇专有一句）和绘制钩子私有段，再由 `iso_relocation.append_members(catalog_policy="inherit")` 追加两个成员——主镜像的 `VMAP.DAT` 本来就带有 COMPDATA／MTV_PROS 的继承差异，按既有候选的策略保留不动。`verify_untouched` 证明基础镜像内除声明写入点外每个字节未变（Original 3758345168 字节、Best 3755068368 字节已比对）。

回执采用两层绑定：语义回读仍绑定基础镜像（`base_output`），`event_subtitles` 回执把基础镜像、最终镜像、两个成员哈希与钩子回读绑在一起；`verify_editions.py`、`freeze_release.py`、`build_release.py` 据此核对，并在发布镜像上重读成员和钩子。Best 的共享前端绑定改用 Original 的基础镜像。

| 版本 | 最终镜像 SHA-256 | 大小 | 基础镜像 | 字幕后 ELF |
| --- | --- | ---: | --- | --- |
| Original | `9eebed21193d49704fee98253c96e01c4dd5589addea711a9c609912b9e23cce` | 3799408640 | `e7b54efd…` | `d000e75d…`（与 10-13 的 V2 候选 ELF 相同） |
| The Best | `24a9f080d04318c7eec368d68379f525cbe7e0aa7fb9c5fd4c8ef7556556f0cf` | 3796135936 | `5f100d7c…` | `37b04085…`（与 V2 候选 ELF 相同） |
| SP | `43f32022…`（未变） | 3913996288 | — | — |

批次 `work/editions/684e02737d06c8177baa071f159cdbb3135423233b6d95ac65f87bd33348779c/original-best-sp.json`，总耗时 129.9 s（Original 29.9 s：承接缓存后组件 0.3 s、回读 14.1 s、字幕 10.1 s；Best 29.4 s；SP 69.0 s 因 `special_disc/` 代码变化重建五组组件）。`verify_editions.py` 通过；两版镜像 LRPS2 冷启动到标题菜单（[截图](issue-assets/sp-event-fidelity-20261014/boot/)）。回执见 [build/](issue-assets/sp-event-fidelity-20261014/build/)。

边界：本篇字幕在原关卡自然触发时的实际显示仍只有 10-13 的受控组件画面，没有新的运行证据；用户表示自行验收。相同输入再次运行 `build_editions.py`：三版 `verified_current_reuse`，总耗时 0.97 s。
