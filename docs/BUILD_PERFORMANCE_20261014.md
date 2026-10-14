# 从零构建三版镜像提速（2026-10-14）

目标：缩短 `python3 tools/build_editions.py --force-rebuild --editions original,best,sp` 的耗时。
"从零"指不复用上一批次的任何组件缓存与文件身份记录；三张镜像必须逐字节不变。

## 实测结果

同一台机器（12 核），同一输入，`--force-rebuild`：

| 阶段 | 之前 | 之后 |
| --- | ---: | ---: |
| Original 组件（`rebuild_zh_font` 链） | 66.9 s | 34.7 s |
| ├ 剧情 STAGE 组件 `build_story_component` | 15.3 s | 4.4 s |
| ├ LIBRARY 组件 `build_library_v02_component` | 13.7 s | 4.9 s |
| ├ 集成组件 `build_full_story_components` | 32.6 s | 11.3 s |
| Original 封盘 / 回读 / 字幕 | 9.3 / 15.4 / 9.7 s | 8.1 / 13.2 / 4.3 s |
| The Best 原生组件与封盘 / 字幕 | 18.7 / 9.4 s | 16.2 / 4.3 s |
| SP `sp-full-text` | 83.1 s | 35.0 s |
| ├ 共享图鉴写入 | 13.7 s | 2.2 s |
| ├ 事件鉴赏（12 块字幕贴图） | 3.4 s | 0.8 s |
| ├ 独立回读 | 17.4 s | 6.1 s |
| ├ 基线还原 + 各进程整盘哈希 | ≈ 11 s | ≈ 3 s |
| 三版合计 | 227.2 s | 134.8 s |

三张镜像保持 Original `9eebed21…`、The Best `24a9f080…`、SP `43f32022…`。单独运行
`build_full_text.py --force-rebuild` 从 83 s 降到 28 s。第二轮（见下）再降到 82–85 s。相同输入再次运行统一入口仍为三版
`verified_current_reuse`（约 1 s）。全部单元测试通过（764 项，6 项按环境跳过）。

## 根因

1. **`--force-rebuild` 连内容寻址的压缩缓存也关掉了。** `SRWZ_REHASH=1` 本意是不信任持久文件身份
   记录，但 `codec._rust_payload` 也用它跳过压缩结果缓存的读取，于是强制全量把 STAGE、LIBRARY、
   MAPMODEL 等所有块重新压缩一遍，集成组件 32.6 s 里约 20 s 是这个。缓存键已经包含压缩器字节、
   参数和输入内容，条目自带摘要，命中就是压缩器会再算出的同一串字节；现在强制全量照常读取。
2. **进程内阶段没有压缩缓存。** `build_editions` 只给子进程设置 `SRWZ_COMPRESSION_CACHE`，
   自己进程里跑的本篇字幕阶段每版都重新压缩 12 个 effect 块（2.8 s）。
3. **纯 Python 的排版用线程池并不并行。** LIBRARY／SP 图鉴正文的 `reflow_body`、剧情 STAGE 的
   对白排版、字幕贴图的像素循环都是 `Fraction` 与 Python 循环，`ThreadPoolExecutor` 只是在
   解释器锁上排队；SP 还在写入和独立回读里各算一遍同样的图鉴排版。
4. **基线镜像反复哈希。** SP 每批 xdelta 还原 3.7 GB 基线（5.6 s），父进程哈希一次，但文件刚写完
   不满足身份缓存的"稳定"条件，于是合成阶段、5 个写入器子进程和回读又各整盘哈希一次；
   `--force-rebuild` 下身份缓存整体关闭，刚封好的候选镜像也被回读再哈希。
5. **`PreparedTextEncoder` 每条记录重新校验覆盖表。** 几千项的覆盖表在每次 `encode_text` 时
   逐项校验，集成组件里 8330 次、SP 5352 次，各约 4–6 s。

## 修改

- `srwz/codec.py`：压缩缓存读取不再看 `SRWZ_REHASH`；压缩器二进制摘要按文件身份记一次。
- `build_editions.py`：进程自身也应用 `phase_environment`；`--force-rebuild` 不再设 `SRWZ_REHASH`，
  而是把本批次的文件身份存储指向新建的空文件 `work/cache/file-identity-rebuild.json`——
  批次之前的记录仍一概不信，但本批次验证过的摘要可以交给子进程。
- `srwz/parallel.py`（新）：`map_processes` 把纯函数作业分到工作进程，调用进程单线程时 fork
  （闭包可直接使用），否则 spawn；结果按输入顺序返回。`SRWZ_WORKERS` 控制进程数，`1` 为串行。
  用在：`build_library_v02_component.reflow_bodies`（LIBRARY 与 SP 共享图鉴写入／回读都改为
  先收集全部正文、排版一次、再逐文档查表）、`build_story_component`（逐关卡 `build_stage`）、
  `event_gallery/subtitles.build_many`（SP 鉴赏与本篇字幕的 12 个 effect 块）。
- `srwz/file_identity.remember_digest(settled=True)`：调用方确认写入已结束时立即记录摘要。
  用于：还原的 SP 基线（`baselines.baseline_iso`）、受保护区域校验顺带得到的候选镜像摘要
  （`build_text_candidate.verify_iso_ranges` 的 `after_sha256`、`iso_relocation.verify_untouched`
  的 `final_sha256`、`best_build.build_iso` 的逐字节比对）。合成阶段的单独 `candidate-hash` 取消。
- `special_disc/baselines.py`：首次 xdelta 还原后记录与原盘不同的 64 KiB 粒度区间
  （`<name>.sparse.{json,bin}`，text-canary 约 111 MB）；之后 APFS 克隆原盘、只写这些区间，
  整盘哈希仍须等于锁定值，不符就丢弃边车回退 xdelta。
- `srwz/text._validated_overrides`：按覆盖表对象缓存校验结果。
- `prepare_zh_release_font.py`：字形栅格线程数从 8 提到 2×CPU（每个字形一个 ImageMagick 进程，
  线程只是等待）。此项在上表的冷构建之后才改，尚未单独计时。

验证：每一步都以三张镜像哈希不变为准；LIBRARY／剧情组件在私有工作区单独重跑，组件报告中全部
哈希字段与冷构建产物一致（剧情组件报告只有绑定脚本自身内容的 `chunk_cache.shared_signature` 变化）。
新增 `tests/test_parallel_map.py`、`tests/test_text_override_validation_cache.py`，并扩展
`test_special_disc_baselines`（稀疏边车、损坏回退）、`test_sp_iso_relocation`（整盘摘要）、
`test_file_identity`（settled 记录）、`test_compression_cache`（强制全量仍命中）。

## 第二轮：放开三版并行与剩余热点（同日）

用户确认允许 SP 与 Original／Best 并行后，统一入口把 SP 放进线程与 Original→Best 链同时跑
（试过给 SP 加 `nice -n 10`，总时长在噪声内无差别，未保留），并继续处理主线上的热点：

| 阶段 | 第一轮后 | 第二轮后 |
| --- | ---: | ---: |
| Original 回读 `verify_full_story_iso_content` | 13.2 s | 7.4 s |
| Original 封盘 `build_iso`（提取另起线程与组件并行） | 8.1 s | 5.7 s（提取 3.9 s 已重叠） |
| 字形栅格 `prepare_zh_release_font` | 9.2 s | 5.0 s |
| The Best 原生组件与封盘 | 16.2 s | 7.7 s |
| SP `sp-full-text`（与主线并行） | 35.0 s | 46.6 s（不在关键路径） |
| **三版合计** | **134.8 s** | **81.7 s**（三次冷构建 81.7／85.2／84.5 s） |

三张镜像哈希不变，`verify_editions.py` 通过，单元测试 766 项通过（6 项跳过）。并行后主线组件阶段
因与 SP 争用 CPU 从 34.7 s 回升到 38–40 s（图集 5→8.8 s），但总时长仍由 Original→Best 链决定
（约 70 s），SP 在 45–49 s 处完成。

- **回读循环分片**：`verify_full_story_iso_content.main()` 的逐关卡循环（约 620 行）搬进嵌套函数，
  按 AST 找出循环改写且循环后仍读取的 28 个累加变量（计数 `+=`、`max`、列表 `append`、集合、
  字典、`Counter`、三处单次赋值），每个分片从相同初值出发跑原循环，`parallel.merge_shard_values`
  按类型合并；`story_ascii_storage_examples` 在串行里是"首次出现为准"，合并时同样保留第一个分片。
  回读清单与报告（去掉时间字段）与改造前逐字节相同。
- **Best 逐块编译进程并行**：`BestCompiler.compile` 的每块 `compile_stage`／`compile_compdata`／
  `compile_zkan` 在工作进程里算，关卡证明随结果带回按序追加；顺带修了 `pack_archive` 压缩缓存
  的写入竞争（同 key 的块并发时读到半写的文件，改为临时文件 + 原子替换，读到坏条目就重算）。
- **原盘布局提取与组件并行**：`build_iso.py --extract-only --refresh-extraction` 在
  `iso-toolchain` 之后另起线程跑，`components` 结束后汇合；封盘阶段复用并逐字节复验该提取。
- **字形栅格批量渲染**：`font_rasterizer.rasterize_characters` 每个 ImageMagick 进程渲染 64 个字形
  （各自在括号分组里保持完整的单字形管线），3 个进程并行；3,569 个字形与逐字渲染逐字节相同。
  实测单进程启动约 9 ms、每字渲染约 1.3 ms，并行到 3 个之后不再加速；`MAGICK_THREAD_LIMIT=1`。

## 第三轮：主线上的重复哈希与重复计算（同日）

三版并行后主线（Original→Best）决定总时长，继续 profile 主线各脚本：

| 阶段 | 第二轮后 | 第三轮后 |
| --- | ---: | ---: |
| 7 个 UI 图集（并行） | 各 8.8–9.5 s | 各 0.3–0.4 s |
| 字体链（快照／栅格／校验） | 1.9 / 5.0 / 1.8 s | 1.9 / 3.7 / 0.8 s |
| Original 组件合计 | 38–40 s | 21.6 s |
| Original 回读 ‖ 字幕 | 7.4 + 4.3 s（串行） | 6.9 s（字幕 7.0 s 与回读并行） |
| **三版合计** | **82–85 s** | **56.7 s** |

三张镜像哈希不变，`verify_editions.py` 通过，单元测试 768 项通过（6 项跳过）。

- **图集构建各自整盘哈希原盘**：`ui_atlas_canary._sha256_path`（以及 `ui_atlas_suite`、
  `ui_atlas_localization`、`build_story_component` 的同类函数）自己分块读文件算 SHA-256，7 个图集
  并行时各读一遍 3.7 GB 并互相拖慢；改走 `file_identity.sha256_file`，同一批次只算一次。
- **翻译树选择算三遍**：`release_font.selected_translation_tree_entries` 遍历约 14 万条目（2.4 s），
  字体快照、栅格、校验三个脚本各算一次；按"选择契约 + 全部文件摘要"入键，结果 pickle 在身份存储
  旁的 `work/cache/translation-tree-selection/`，后两次直接读取。
- **刚封好的镜像被回读重新整盘哈希**：`publish_verified` 记录摘要时受"文件刚写完不算稳定"的保护
  拒绝，改为 settled；`build_iso` 封盘后一次顺序读取同时得到整盘与逐成员摘要
  （`_hash_output_image` → `remember_range_digests`），成员校验与回读都命中。
- **本篇字幕与回读并行**：字幕只依赖已封盘的基础镜像，在线程里与回读阶段同时跑。

## 仍未处理

- 主线关键路径现在约 50 s：预检 3 s → codec 2 s → Original 组件 21.6 s（字体链 7 s、集成组件 11 s、
  剧情／LIBRARY 3.3 s 并行）→ 封盘 4.4 s → 回读 6.9 s（字幕并行）→ Best 7.2 s + 字幕 4.2 s。
  集成组件是主线程串行的一长串小步骤（采样无单点热点），进一步并行需要重组其流程。
- Original 封盘的 mkps2iso 整盘写出；改为克隆原盘并就地改写会改变镜像布局。
- 本篇字幕阶段每版约 2.5 s 是 7.6 GB 的未改动字节逐字节比对；Best 的字幕阶段没有可并行的伙伴。
- 回读里 SRVC 档案解析（`srvc._decode_index_candidate` 约 3 万次）约 1.5 s。
- SP 写入器中 `migrate_stage_dialogue.py` 是 SP 组件阶段的关键路径，但 SP 已不在批次关键路径上。

结构化记录：`manifests/editions/build-performance-20261014.json`。
