# 当前中文全量构建时间技术分析

## 结论

优化前，跳过字体下载的全量并行构建约需 `213～214 秒`。默认路径发生顶层 cache miss、
但最终冻结成员未受影响时，真实总入口现在为 `47.30 秒`；随后生成 ISO 约需 `9.5 秒`，
所以普通改动候选约 `57 秒`即可产出。强制执行一次完整 ISO 内容回读现在为 `28.98 秒`，
但它不属于日常候选的默认链路。

日常重复构建现在使用两层复用。整个输入闭包未变时，顶层内容寻址缓存核对生产构建
代码、配置、受管语料、锁定输入和最终组件输出；本机 451 个文件、约 698 MB 的 inventory
微基准为 `0.28 秒`，完整命令热命中为 `0.41 秒`。闭包中只有部分内容变化时，最终组件
整合不再重演全部图像生成和
逐像素验收，而是按物理成员计算影响范围；已审核且输入未变的 NISV、VEFF、MAPMODEL
等产物只核对锁定身份并直接复用。当前候选无成员受影响时，增量整合实测 `0.46 秒`，
而不是约 `105 秒`的强制全量整合。

复杂的 palette、alpha、PSMT4/8、压缩流和事件绑定检查仍保留在资源制作、资源变更和
显式 `--force-rebuild` 路径。它们用于确认一个新冻结件，不再是每次日常整合的默认
成本。缓存不是按 mtime 猜测：缺文件、输出锁漂移、已声明输入变化或没有依赖规则的
变化都会拒绝复用。

回读变慢**不只是因为计算哈希**。哈希是完整性检查的一部分，但主要耗时还包括
读取 ISO 成员、解压缩、解析 170 个 STAGE、逐条比对文本和运行时 token，以及检查
固定 LBA、容量边界和组件结构。当前证据可以确认“哈希参与其中”，但还没有做哈希与
解析的隔离 profile，因此不能给出哈希占用的精确百分比。

本报告只讨论静态构建和 ISO 回读，不把它们当作 PCSX2 或实机运行验收。

## 测量范围与基线

- 测量日期：2026-09-03（Asia/Singapore）。
- 仓库：`/Users/nate/Super-Robot-Wars-Z/srwz-zh`。
- Git 基线：`main`，`2f0cbb2`；本次并行构建优化仍在未提交工作树中。
- Python：3.9.6；检测到 16 个 CPU 逻辑核心；默认 atlas worker 上限为 6。
- 构建输入：现有锁定字体、manifest、组件和原版成员缓存；字体步骤使用
  `--skip-fetch`，没有把网络下载时间计入。
- 目标 ISO：`build/iso/zh-release-full-story/srwz-zh-current.iso`。

## 端到端实测

以下是同一工作区的 `/usr/bin/time -p` 实测。`real` 是用户实际等待时间；不同缓存
状态、CPU 负载和后台进程会带来小幅波动。

| 流程 | 命令口径 | `real` | 说明 |
| --- | --- | ---: | --- |
| 串行参考构建 | `rebuild_zh_font.py --skip-fetch --atlas-workers 1` | 265.99 s | 用于比较并行收益 |
| 优化前全量构建 | `rebuild_zh_font.py --skip-fetch` | 212.94 s | story、UI atlas、LIBRARY 并行；最终整合全量重验 |
| 冻结成员复用后的中间结果 | `rebuild_zh_font.py --skip-fetch` | 104.62 s | 最终整合增量复用，STAGE 尚未优化 |
| prepared STAGE encoder 后的 cache-miss 构建 | `rebuild_zh_font.py --skip-fetch` | 74.84 s | 冻结成员复用，并复用 prepared STAGE encoder |
| 当前默认 cache-miss 构建 | 同上 | 47.30 s | 再复用源 STAGE 解压/解析，并发栅格化字体 |
| ISO 组合 | `build_iso.py --config config/iso/zh-release-current-build.json` | 9.45 s | 保持固定布局和 LBA |
| 优化前完整 ISO 回读 | `verify_full_story_iso_content.py ... --force` | 56.47 s | 强制执行完整静态内容门禁 |
| 当前完整 ISO 回读 | 同上 | 28.98 s | STAGE 期望字节编码器复用 |
| 日常改动候选合计 | 默认 cache-miss 构建 + ISO 组合 | 56.75 s | 不含按需 ISO 语义回读 |
| 顶层构建热缓存核对 | 内容寻址 inventory 微基准 | 0.28 s | 451 个文件、698,236,067 字节；只测缓存核对 |
| 缓存引入时的完整回读 | `verify_full_story_iso_content.py --force` | 52.02 s | prepared encoder 优化前的历史测量 |
| 当前完整回读热缓存 | `verify_full_story_iso_content.py` | 1.74 s | 458 个文件、4,467,619,404 字节全部 SHA-256 一致 |

当前 ISO 的大小为 `3,758,358,528` 字节，SHA-256 为
`7db28ff65b8a2e404af079e8b7995f80f53fbae16b495603c18a599cf85e9a16`。回读结果为
`full_story_final_iso_static_content_readback_passed`，并核对了 170 个 STAGE、93,071
条翻译记录、83,668 条对白、670 个条件、8,733 个说话人、1,952 个运行时 token 和
2,452 个机师名。

## `rebuild_zh_font.py` 实际做了什么

脚本名称容易让人以为它只生成字体，实际它是中文生产链的总入口：

1. 准备并校验全局中文字体及字形映射。
2. 构建字体组件并执行字体回读校验。
3. 重建 reviewed LIBRARY（约 2,709 个条目、4,921 个字段引用、784 个数据块）。
4. 重建 170 个 STAGE 的剧情组件（约 84,338 条原始记录）。
5. 构建并校验 6 组 UI atlas 以及 atlas suite。
6. 重新整合全量 story 组件，执行解码、写入、压缩和结构验证。
7. 接入 AIDDATA、TRICMN 的锁定索引快照并组合最终组件。

这里的 `--force` 是有意的：它保证全局字体或编码表变化能够传播到所有消费者，避免
生成“表面成功、实际混用旧组件”的结果。AIDDATA 和 TRICMN 的普通构建使用锁定快照，
不会因为每次构建而重新栅格化全部图像。

## 串行阶段 profile

下面是一次串行剖析中的主要阶段。它用于定位瓶颈，和端到端 `real` 时间不是完全同一
口径（profile wrapper、缓存和校验重复会产生少量差异），因此不应直接把每一行相加后
当作发布承诺。

| 阶段 | 约耗时 | 约占串行 profile |
| --- | ---: | ---: |
| `build_full_story_components.py --force` | 105.32 s | 39.2% |
| `build_story_component.py`（优化前） | 44.98 s | 16.7% |
| 6 组 UI atlas build + verify | 40.06 s | 14.9% |
| `build_zh_font_component.py` | 36.83 s | 13.7% |
| `build_library_v02_component.py` | 19.95 s | 7.4% |
| 字体准备与字体 verify | 11.37 s | 4.2% |

这说明瓶颈不是单一的 ImageMagick 字体栅格化，而是“全量组件重新解析、写入、压缩、
验证”的组合成本；其中整合组件本身占比最高。

## STAGE 编码映射重复验证

优化前，`encode_stage_message()` 为每条 STAGE 记录复制同一份字符 override，并重新创建
`PreparedTextEncoder`。因此 `_validated_overrides()` 在一轮构建中被调用 `84,781` 次，
累计约 `41.22 秒`；这不是必要的文本安全检查，而是错误的对象生命周期。

当前实现为普通文本、运行时姓名占位符、关键词链接、占位符与关键词组合四种语义各创建
一个只读 encoder，并在 170 个 STAGE worker 间共享。字符映射仍在创建 encoder 时完整
验证，`:` 的原始 `0x3A` 和 `《》《》` 的 `0x8173/0x8174` 表面规则也保持不变。

同口径结果：

| 项目 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 单线程 STAGE profile 实际时间 | 80.60 s | 36.05 s |
| `_validated_overrides()` 调用 | 84,781 | 277 |
| `_validated_overrides()` 累计时间 | 41.22 s | 0.06 s |
| `encode_stage_message()` 累计时间 | 47.99 s | 3.58 s |
| `repack_stage_texts_in_place()` 累计时间 | 58.78 s | 13.87 s |
| 正常 12-worker STAGE 构建 | 约 45.14 s | 18.03 s |

优化前后 `STAGE.BIN`、`HB.BIN` 和组件报告 SHA-256 完全一致。这一项保留校验本身，只把
校验从“每条记录一次”移到了“每份映射一次”。相同的 prepared encoder 也用于最终 ISO
STAGE 字节回读；强制完整回读实测由 `56.47 秒`降到 `28.98 秒`。

## STAGE 解压、解析和定点回读

继续 profile 后确认，优化后的 STAGE 构建仍重复消费同一份源数据。205 个压缩 chunk 原本
在 ticker 全盘发现、Z Report 全盘发现、未翻译覆盖检查和实际构建之间被解压 629 次；
再加上 182 次压缩 round-trip，一轮构建共有 811 次解压、993 次 Rust codec 子进程。

当前在本轮构建开始时把 205 个 Rust `DecodeResult` 保存在内存中，供所有只读消费者复用。
一次解压全部源 chunk 实测 `0.62 秒`，解压后数据共 `11,687,504` 字节；因此不值得增加
磁盘缓存格式。源解压由 629 次降到 205 次，全部 codec 子进程由 993 次降到 569 次。

同一个翻译 STAGE 过去还会在 `build_stage()` 和 writer 内连续解析两次源结构。writer
现在接收调用方已经获得的只读 `StageParseResult`。写完以后也不再重新发现整个 STAGE
的未改动区块，而是定点读回每个唯一写入：逐一核对指针、说话人、正文、NUL 终止符和
payload 边界。压缩流仍执行 Rust 解压 round-trip；完整 ISO 验证器仍独立解析最终成员。

这两项不删除写入证明，只删除重复发现。同一份 `STAGE.BIN`、`HB.BIN` 和组件报告的
SHA-256 均保持不变。独立 STAGE 构建的后续实测为：

| 状态 | worker | `real` |
| --- | ---: | ---: |
| prepared encoder 基线 | 12 | 18.03 s |
| 源解压缓存 | 12 | 17.00 s |
| 源解压缓存，worker 扫描最优点 | 4 | 16.71 s |
| 再复用源 parse | 4 | 14.89 s |
| 当前定点输出读回 | 4 | 13.55 s |

源解压缓存后的 worker 扫描为：1/2/4/6/8/12/16 workers 分别需要
`23.34/17.35/16.71/17.11/17.32/17.52/17.56 秒`。4 workers 是甜点位；继续增加
并发会让短命 Rust 进程相互争用。当前 4-worker 时间轴中，Rust 编解码子进程的去重
墙钟覆盖为 `9.89 秒`，重编码阶段覆盖 `11.64 秒`，STAGE 重排覆盖 `5.69 秒`；这些阶段
互相重叠，不能相加当作总时间。

## 字体栅格化 profile

顶层正常 cache miss 的区间 profile 显示，优化前的前 `45.55 秒`完全串行：字体输入准备
`9.12 秒`、字体组件 `34.45 秒`、字体验证 `1.95 秒`。随后 STAGE 已不是关键路径；
LIBRARY 需 `20.41 秒`，而 UI atlas build/verify 加 suite build/verify 的关键路径约
`23.39 秒`。最终冻结成员增量整合只有 `0.47 秒`。

字体组件的 cProfile 进一步显示，`34.45 秒`中 `33.31 秒`来自 3,455 次独立的
`rasterize_character()`；逐字形 Python 写入不到 1 秒，字体压缩约 `3.18 秒`。这些
渲染任务现已并行执行，结果仍按 assignment 顺序逐项核对锁定的灰度 SHA、4-bpp SHA、
packed glyph SHA 和 metrics，之后才写 VT1。

2/4/6/8/12/16 个 raster workers 分别实测
`20.82/12.15/10.33/10.44/10.53/11.06 秒`，默认取 6。字体组件由 `34.45 秒`降到
`10.33 秒`，所有三个输出文件逐字节不变；正常顶层 cache-miss 构建因此由 `73.80 秒`
降到 `47.30 秒`。

## 为什么优化前完整回读要 56 秒

`tools/verify_full_story_iso_content.py` 的回读不是只读取一个整盘校验值，而是按成员和
语义逐层检查：

- 读取 ISO 中需要验证的成员，并检查成员大小及 SHA-256；
- 对字体、组件、文本 corpus、translation lock 和源归档反复计算哈希；
- 解压并解析 STAGE、LIBRARY、NISV、COMPDATA、SRVC 等结构；
- 逐项核对翻译 entry 集合、源文本 preimage、对白/说话人对应关系和运行时替换 token；
- 检查编码禁用项、可见 ASCII/空格规则、图像逻辑索引、压缩流 round-trip；
- 检查 replacement 的固定 LBA、容量预算、未替换成员和 manifest 一致性。

优化前回读计时为：

```text
real 56.28s
user 50.87s
sys   4.77s
```

`user` 时间明显高于 `sys`，表示主要工作在本地 CPU 上完成，符合“解析、解压、比较、
哈希”混合负载，而不是单纯等待磁盘。相比之下 ISO 组合只有 `9.45 秒`，所以当前瓶颈
在验证器的内容/结构检查，而不是 mkps2iso 写盘。prepared STAGE encoder 接入后，同一
候选的强制完整回读为 `28.98 秒`。

## 已完成的优化与收益

当前 `rebuild_zh_font.py` 已对无共享写入冲突的工作并行化：

- story 与 6 组 UI atlas 可以同时构建；
- LIBRARY 构建与 story/UI atlas 组可以重叠；
- `--atlas-workers 1` 保留串行参考路径，便于回归和故障定位。

第一步并行调度从 `265.99 秒` 降至 `212.94 秒`，减少 `53.05 秒`，约 `19.9%`。
第二步把最终整合切到冻结成员复用后，真实默认 cache-miss 总入口为 `104.62 秒`；相对
此前 `214.09 秒`减少 `109.47 秒`，约 `51.1%`。被省掉的是未受影响成员的重复生成和
重复逐像素验收，不是当前改动所涉及成员的写回检查。

第三步复用 prepared STAGE encoder 后，正常 12-worker 剧情组件从约 `45.14 秒`降到
`18.03 秒`，减少 `27.11 秒`，约 `60.1%`；完整 ISO 回读也从 `56.47 秒`降到
`28.98 秒`，减少 `27.49 秒`，约 `48.7%`。最终真实默认 cache-miss 总入口为
`74.84 秒`，相对最初 `214.09 秒`累计减少 `139.25 秒`，约 `65.0%`。

第四步缓存每轮 205 个源 STAGE 解压结果、复用 source parse，并把输出全结构 reparse
收窄为写入 allocation 定点回读。默认 4-worker 剧情组件进一步降至 `13.55 秒`；相对
prepared encoder 基线再减少 `4.48 秒`，约 `24.8%`。

第五步把 3,455 个互不依赖的字体栅格任务并行化。6-worker 字体组件由 `34.45 秒`降至
`10.33 秒`，减少 `24.12 秒`，约 `70.0%`。当前正常 cache-miss 总入口为 `47.30 秒`；
相对最初 `214.09 秒`累计减少 `166.79 秒`，约 `77.9%`。

在此基础上已经完成两级内容缓存：

1. `rebuild_zh_font.py --skip-fetch` 默认复用上一次完整通过的全链结果；它核对完整
   inventory，而不是只看顶层 manifest 的时间戳。`--force-rebuild`、字体下载、
   `--skip-assets` 和任何 `--refresh-*` 模式都会绕过缓存。
2. `verify_full_story_iso_content.py` 不带 `--force` 时只会复用精确匹配的完整回读；缓存
   不可用时拒绝把旧报告当作当前证据，并要求显式 `--force` 重新执行完整回读。

仓库已有的整合组件增量入口在“无受影响成员”时约 `0.46 秒`，但它只覆盖整合阶段。
本轮选择在它上层缓存已经完整验证过的闭包，避免在无输入变化时仍重复执行字体、剧情、
LIBRARY、冻结图集和相同的语义回读；任一受管文件变化仍回退到原有全量 fail-closed 链。

2026-09-03 已为 STAGE 扩容接入跨模块类型化所有权：1 个运行时关键词指针、7 个编队
owner record 和 1 个锁定前像的 `u16` 非指针全部通过数量门；未知候选仍然 fail closed。
同一工作树上的真实顶层冷构建为 `214.09 秒`，写入覆盖 451 个文件、698,267,029 字节的
完整内容哈希收据；紧随其后的无改动热构建为 `0.41 秒`。该轮优化前的强制 ISO 回读为
`56.47 秒`，prepared STAGE encoder 接入后的同类回读为 `28.98 秒`；相同参数的缓存回读
仍约 `1.80 秒`。

## 已定方案与后续边界

1. **默认开发路径**：完整闭包未变时复用顶层缓存；有局部变化时，最终整合默认使用
   物理成员级增量模式。未受影响的冻结资源不重新 rasterize、swizzle、压缩或逐像素
   回读，只检查现有输出、manifest 和输入锁是否仍能对应。
2. **资源制作路径**：只有修改贴图文字、布局、调色板、字体源或对应 writer 时，才重跑
   该资源的完整生成与结构/像素验收，人工审图通过后更新冻结件和锁。
3. **显式冷复验路径**：`--force-rebuild` 保留完整重算，用于调试生成器、改变资源契约或
   需要证明从源输入可重现时；它不再代表普通开发 build。
4. **ISO 路径**：日常候选生成到 `build_iso.py` 即可，完整 ISO 语义回读改为发布候选、
   固定 LBA/成员映射变更或专项排错时显式执行。相同 ISO 的回读缓存仍可用于快速复核。
5. **Rust 优先级下调**：NISV/VEFF/MAPMODEL 的像素循环在强制冷复验中适合 Rust，但默认
   路径已通过冻结成员复用消除这部分等待，先不为日常 build 重写一套实现。若冷复验仍
   成为高频需求，再批量迁移这些 kernel。
6. **下一缓存边界**：正常 cache miss 已降到约 47 秒；若仍需优化，优先把字体阶段和
   atlas suite 做成各自的内容寻址节点，使仅改剧情 writer 时不必重跑未受影响的字体与
   atlas。当前顶层无改动闭包已经由完整缓存覆盖，不再为热缓存重复设计第二套捷径。

## 可复现实测命令

```bash
cd /Users/nate/Super-Robot-Wars-Z/srwz-zh

/usr/bin/time -p python3 -u tools/rebuild_zh_font.py \
  --skip-fetch --atlas-workers 1

# 单独比较字体逐字串行栅格化；普通构建默认使用实测最优的 6 workers
/usr/bin/time -p python3 -u tools/build_zh_font_component.py \
  --font-config config/fonts/zh-release-font.json \
  --proposal work/writeback/zh-release-codebook-proposal.json \
  --allocation-registry config/encoding/zh-release-font-assignments.json \
  --output-root work/build/zh-release-font/components \
  --raster-workers 1 --force

/usr/bin/time -p python3 -u tools/rebuild_zh_font.py \
  --skip-fetch

# 发布、可重现性复验或缓存诊断：显式冷构建
/usr/bin/time -p python3 -u tools/rebuild_zh_font.py \
  --skip-fetch --force-rebuild

/usr/bin/time -p python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json

/usr/bin/time -p python3 tools/verify_full_story_iso_content.py \
  --iso build/iso/zh-release-full-story/srwz-zh-current.iso \
  --build-config config/iso/zh-release-current-build.json \
  --force

# 相同候选的日常重复回读；仅在全部 SHA-256 一致时复用
/usr/bin/time -p python3 tools/verify_full_story_iso_content.py
```

相关入口：[`tools/rebuild_zh_font.py`](../tools/rebuild_zh_font.py)、
[`tools/build_full_story_components.py`](../tools/build_full_story_components.py)、
[`tools/build_iso.py`](../tools/build_iso.py)、
[`tools/verify_full_story_iso_content.py`](../tools/verify_full_story_iso_content.py)。
