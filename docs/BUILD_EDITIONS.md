# Original、The Best 与 SP 的统一构建

`python3 tools/build_editions.py` 默认更新三个当前 ISO，三版均内置方块键跳过战斗动画（skip）。输入未变且回执、ISO 与日常副本验证通过时直接复用；Original 语料更新使用已验证的组件缓存。每版都有独立写入锁、
工作目录、原盘身份和最终回执。旧发布快照不被覆盖，完整 ISO 不提交到 Git。

```bash
python3 tools/build_editions.py --plan
python3 tools/build_editions.py
python3 tools/build_editions.py --editions original,best
python3 tools/build_editions.py --editions sp
python3 tools/build_editions.py --force-rebuild
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best-sp.json
```

注册表沿用 `config/release/dual-current.json` 路径，现已注册三版。后续 release 固定包含
Original、The Best 和 SP，三版发布镜像全部内置方块 skip：
`python3 tools/freeze_release.py --manifest <批次 JSON> --version <x.y.z>` 复制已验证的
三版当前 ISO、回读其 skip hook 并写出 schema 4 发布配置，之后 `build_release.py`
为每版生成一份补丁。冻结器要求同一批次包含全部三版（`original-best-sp.json`），缺少任一版
即拒绝冻结。SP 的独立语义回读报告一并冻结，发布校验不依赖可清理的私有工作区。
三份补丁分别绑定各自日文原盘，生成后逐一实际还原并核对目标哈希；不再生成 skip 变体。

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

Original 与 The Best 在各自的原生封盘和语义回读之后，还有最后一个阶段：原关卡事件演出的中文字幕
（`tools/event_subtitles/apply.py`，`build_editions.apply_main_event_subtitles`）。它把 13 个 effect 块加上
字幕贴图、给可执行文件加挂绘制钩子和私有段，两个成员超出原盘分配，同样由 `special_disc/iso_relocation.py`
追加到已验证镜像之后（目录记录、卷描述符、`VMAP.DAT` 保留既有的非目标差异、UDF）。语义回读仍绑定追加前的
基础镜像；版本回执的 `output` 是最终镜像，`base_output` 是基础镜像，`event_subtitles` 回执把两者绑定，
并记录基础镜像内除声明写入点外每个字节未变的校验、两个成员的哈希与钩子回读。`verify_editions.py`、
`freeze_release.py`、`build_release.py` 都按这两层绑定核对：回读对基础镜像，字幕回执对发布镜像，并在发布镜像上
重读两个成员和钩子。`tools/event_subtitles/build.py` 只保留为隔离实验包装。

SP 合成的最后一个可执行阶段是特别剧场“事件演出”（`special_disc/event_gallery/apply.py`）：
在全部文本补丁之后，对可执行文件加挂原生钩子与私有段、在 AID 块 2 追加横幅、给 12 个
effect 块追加字幕贴图。这三个成员超出原盘分配，由 `special_disc/iso_relocation.py` 追加到
基线镜像之后，并同步 ISO9660 目录记录、两份卷描述符、原生 `VMAP.DAT` 扇区目录和 UDF 文件项；
其余成员仍保持原 LBA 与大小。受保护区域校验覆盖基线长度内除这些声明写入点之外的每个字节，
尾部必须恰好是三个成员载荷加 UDF 元数据块。配置、字幕稿、字体、代码与资源的哈希写入回执的
`event_gallery`，独立回读另行核对钩子、载荷段和 12 个字幕块的解码哈希。
鉴赏的机体、镜头与 BGM 对齐证据见 [SP_EVENT_FIDELITY_20261014.md](SP_EVENT_FIDELITY_20261014.md)。

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

## 当前镜像与计时

Original、BEST、SP 各保留一个正式 current ISO，均默认内置方块 skip。统一构建器直接从
当前镜像读取本版可执行文件，检查 skip 跳转和 hook，不再自动生成 `daily-test/*-skip.iso` 副本。
只构建 SP 时只更新 SP；BEST 单独构建仍会更新其 Original 前端。

`config/iso/current-isos.json` 和 `retained-isos.json` 只保存当前盘的路径及策略，
其实际身份读取配置指定回执中的 `output` 字段；SP 资源增量更新以镜像旁回执的 `iso` 字段为准。
构建生成的哈希不写回输入配置，避免下一轮输入快照因上轮产物而变化。
`verify_editions.py` 校验当前镜像中的 skip；历史 `daily_test` 字段不再要求副本存在。
SP 批次校验直接回读已发布的 current ISO，并核对私有工作区中的组件与独立回读报告；
私有工作区的 ISO 副本可以清理，不影响这条验证链。
已冻结的 v0.4.2 镜像与发布配置不变。

批次 JSON 的 `timing` 保存 UTC 起止时间、完整墙钟耗时、预检/快照耗时、各版总耗时、
子命令分项耗时。各版工作区另有 `timing.json`，失败阶段也记录退出码与耗时。
分项之和之外的耗时包括快照物化、缓存准备、文件哈希、发布当前盘和回执检查；三版总耗时包含这些开销。
这是现有本地缓存条件下的正常完整构建计时，不能当作空缓存机器的冷启动时间。

## 日常更新与强制复验

- 相同输入：核对冻结输入、ISO 全盘哈希、内容回读回执与日常副本后直接复用，计时标记 `verified_current_reuse`。
- 输入快照只包含真正的构建定义（`tools/srwz/release_inputs.py::is_build_input`）：文档、
  写作辅助脚本、运行验证工具和模板不进入快照，改动它们不改变输入摘要，也不触发重建。
- Original 语料或非组件文件变化：从上一批次复制已验证的组件缓存、生成配置与 ISO 基线到新私有工作区。
  只有 `COMPONENT_BUILD_DEFINITION_ROOTS`（`tools/srwz`、组件构建脚本、codec 源码、`config`、
  `corpus`、`vendor`、`manifests`）中的文件发生了“不是上一批次自身刷新”的变化时才拒绝承接；
  与上一批次输出逐字节一致的回执／锁同步回仓库不算变化。改动 `build_editions.py`、`build_iso.py`、
  回读脚本或文档都不会让组件缓存失效。
- 承接后组件层按自身逐消费者指纹判断重建范围；未承接时组件层仍使用自己的已验证缓存并复用
  逐字形字体栅格。统一入口不再因缓存不可承接而自动升级为 `--force-rebuild`。
- Original 封盘使用 `build_iso.py --incremental`：上一批次的已验证镜像按内容哈希重新绑定后克隆，只改写
  变更成员并复验；镜像、配置或实现不匹配时自动回退完整 mkps2iso。
- 所有 SHA-256 经 `srwz/file_identity.py`：同一文件身份（设备、inode、大小、mtime、ctime）
  只哈希一次，APFS 克隆继承已验证摘要，同一构建的全部子进程共享
  `work/cache/file-identity.json`。校验点不变，只去掉重复计算。
- `--force-rebuild` 跳过当前镜像复用，强制 Original 全组件、字体重栅格、原盘布局重提取、
  SP 五组组件全部重建、完整内容回读。文件身份不信任批次之前的记录：该批次从空的
  `work/cache/file-identity-rebuild.json` 开始，本批次自己验证过的摘要（还原的基线、刚封好的镜像）
  仍经它交给子进程，不再重复整盘哈希。压缩结果缓存按“压缩器字节 + 参数 + 输入内容”入键、
  条目自带摘要，强制全量也照常读取（2026-10-14 起；此前 `SRWZ_REHASH=1` 连它一起绕过）。
- 纯 Python 的 CPU 密集阶段（LIBRARY／SP 图鉴正文排版、剧情 STAGE 对白排版、事件字幕贴图、
  Original 回读的逐关卡循环、Best 的逐块编译）经 `srwz/parallel.py::map_processes` 分到工作进程：
  调用进程单线程时 fork（闭包可直接使用），否则 spawn；结果按输入顺序返回，字节与串行完全一致。
  `SRWZ_WORKERS=1` 回到串行参考路径，默认每 CPU 一个、至多 8 个。回读循环按连续关卡分片，
  各分片从相同初值出发，`merge_shard_values` 按类型合并计数、列表、集合、字典与单次赋值。
- SP 与 Original→Best 链互不依赖，`build_editions` 把 SP 放在线程里与主线并行（2026-10-14 起，
  用户确认）；两者只共享按内容寻址的压缩缓存与带文件锁的身份存储。`--force-rebuild` 下原盘布局
  重提取（`build_iso.py --extract-only --refresh-extraction`）与 Original 组件阶段并行，封盘阶段
  直接复用并逐字节复验这份提取。
- 字体链三个脚本共用的翻译树选择结果按内容缓存在身份存储旁的 `work/cache/translation-tree-selection/`；
  封盘后一次顺序读取记录整盘与逐成员摘要，回读与成员校验不再重读镜像；本篇字幕阶段与回读并行。
- 字形栅格每个 ImageMagick 进程渲染 64 个字形、3 个进程并行（`font_rasterizer.rasterize_characters`，
  像素与逐字渲染逐字节相同；`MAGICK_THREAD_LIMIT=1` 避免 OpenMP 空转）。
- 私有工作区用 `work/edition-inputs.json` 中的冻结清单提供配置列表和源码身份，不向父目录 Git 查询文件。
- mkps2iso 工具链在私有工作区内直接复用已按固定 commit 构建、版本行匹配的可执行文件，不重跑 CMake。
- SP 基线镜像首次仍由 xdelta 还原，同时把与原盘不同的 64 KiB 粒度区间记成稀疏边车
  `work/build/special-disc/baselines/<name>.sparse.{json,bin}`（text-canary 约 111 MB）；之后每批
  用 APFS 克隆原盘再只写这些区间，整盘哈希仍须等于锁定值，不符即丢弃边车回退 xdelta。
  SP 只还原一次基线镜像并通过环境变量交给各写入器与回读脚本；system→STAGE 链与 SRVC、frame、
  图像写入器并行执行；临时 ISO 用 APFS 克隆而非整盘复制。SP 保留发布前独立语义回读；外层验证
  该回执、最终成员与 ISO 的绑定，取消同一验收脚本的第二次完整执行。
- SP 可变文本块先使用 `rust-fit`，只有原定槽位容纳不下才回退 `rust-maximum`。已冻结图像的压缩字节契约不变。
- 历次私有工作区与输入快照不会自动删除；`python3 tools/prune_edition_workspaces.py` 列出未被
  当前回执引用且不在最近 N 个之内的目录，加 `--apply` 才删除。

SP 支持组件级增量。统一入口从上一份已通过独立回读的 SP 回执承接组件，逐一核对
输入指纹、报告和输出文件的大小／SHA-256；缓存损坏、缺失或依赖变化时重建对应组件。
直接运行 `build_full_text.py` 也可从其当前 SP 回执承接，`--force-rebuild` 可禁用复用。

| 语料变化 | 需要重建的组件 |
| --- | --- |
| SP 剧情／挑战台词、编队名，本篇剧情／说话人／条件回退语料 | STAGE |
| 本篇或 SP 战斗字幕 | SRVC |
| 本篇关卡名称 | frame |
| SP system-text | system；其 STAGE 输出字节变化时再重建 STAGE |
| SP frame-text | system、STAGE、frame、image-labels |
| 不被 SP 写入器读取的其他语料 | 复用五组组件 |

配置、锁定基线／字体、共享编解码器或 SP 工具源码变化采取保守策略，重建全部组件；
只有事件演出专用的 `event-gallery.json`、`event-subtitles.json`、`tools/special_disc/event_gallery/`
和字幕字体（`incremental.ASSEMBLY_ONLY`）例外——它们只被每次都执行的合成阶段读取，改动不触发组件重建。
新缓存只随最终独立回读通过的报告发布；失败构建不会成为下一批次的已验证缓存。
每次组件增量后仍完整执行 ISO 合成、非目标区域校验和独立语义回读。
回执的 `incremental.components` 记录每组输入、依赖、`reused`／`rebuilt` 和原因；
统一 SP 回执的 `component_modes` 提供摘要。STAGE 当前以整个组件为单位，尚未细化到单块。

无变化整盘复用、组件增量和强制全量的计时分别报告。
真实文本修改的增量／全量等价结果见 [SP 增量构建实测](SP_INCREMENTAL_BUILD_20260927.md)。
本轮流程整理与实测见 [2026-09-27 构建流程整理](BUILD_PERFORMANCE_20260927.md)，上一轮见
[2026-09-22 构建性能复核](BUILD_PERFORMANCE_20260922.md)。组件全量变慢（约 22 分钟）的排查与修复见
[2026-10-07 全量构建变慢排查](BUILD_PERFORMANCE_20261007.md)。
