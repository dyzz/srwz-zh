# 全量构建变慢排查与修复（2026-10-07）

组件指纹变化时（工具源码改动后的第一次构建），三版全量从 09-27 的约 2 分钟涨到 22 分钟。
根因是 LIBRARY 正文排版搜索里的切片宽度计算退化；修复后三版全量 259 秒，三张 ISO 与修复前逐字节一致。

## 实测结果

| 阶段 | 修复前（`21dd32dc…`） | 修复后（`0db44459…`） |
| --- | ---: | ---: |
| Original `components` | 629.5 秒 | 101.5 秒 |
| 其中 LIBRARY（`build_library_v02_component.py`，单独重跑） | 约 550 秒 | 48.1 秒 |
| Original `readback` | 42.7 秒 | 26.1 秒 |
| BEST | 27.1 秒 | 18.4 秒 |
| SP `sp-full-text` | 615.6 秒 | 93.6 秒 |
| 三版合计 | 1336.9 秒 | 259.2 秒 |

修复前 SP 的大头是 `current-shared-library` 280.4 秒与 `independent-readback-and-publication` 268.1 秒：
SP 写入与回读都经 `shared_library.replacement_fields` 调用同一个 `reflow_body`。
修复后 Original／BEST／SP 输出分别为 `3cf68c57…`／`e950438e…`／`8e796122…`，与修复前完全相同，
三版静态回读均通过。两次构建同一台机器、同样有约 3 核的无关后台负载。

## 变慢时间线

`work/editions/*` 回执显示两次台阶，Original 组件与 SP 同步变化，指向共用的排版代码：

- 09-28 `ce6d64d`（按实测宽度平衡正文）：组件约 75 → 290 秒，SP 约 55 → 295 秒。
- 10-04 `38ab9fa`（百科排版）：`library_typography` 给机体／人物正文的拉丁字母、数字加
  `<width:..>` 作用域，几乎所有正文改走带 overhang 的受控路径，组件与 SP 再翻倍到约 600 秒。

## 根因与修改

`chinese_layout._partition_tokens` 的动态规划每个候选断点调用两次 `width(start, end)`。
无 overhang 时是前缀和差；有 overhang 时每次对 `tokens[start:end]` 重新调用 `_occupied_width`，
逐个累加 `Fraction`，单次 O(n)。cProfile 下一次 LIBRARY 构建 `_occupied_width` 调用 550 万次、
`Fraction` 加法约 5.7 亿次，`solve` 占总时间 84%。

修改：新增 `_occupied_width_index(tokens)`。切片占用宽度等于
`max(P[e] − P[s], max(P[k+1] + overhang_k, s ≤ k < e) − P[s], 0)`，用前缀和加稀疏表做区间最大值，
单次 O(1)，结果仍为精确的 `int`／`Fraction`，与原实现数值相同，断行选择因此不变。

## 验证

- `tests/test_chinese_layout_width_index.py`：500 组随机分数宽度／overhang 序列与一段真实受控正文，
  所有切片与 `_occupied_width` 逐一相等。
- 全部单元测试通过（708 项，6 项按环境跳过）。
- LIBRARY 单独重跑：5 个输出成员（JTIM、NISVDATA、MTVZKNRT／PT／KW）SHA-256 与修复前相同。
- 三版全量：ISO 与修复前逐字节一致（见上表）。
- 未运行 PCSX2 或 LRPS2；输出字节未变，运行状态沿用原批次。

## 第二轮：压缩结果缓存与去掉重复检查

三版仍串行构建。场景均为“组件构建定义有改动”的全量（在 `tools/srwz/chinese_prose.py` 末尾临时加一行
带时间戳的注释后构建，随后还原），压缩缓存已由上一次构建填充：

| 阶段 | 第一轮修复后 | 第二轮 |
| --- | ---: | ---: |
| Original `components` | 101.5 秒 | 46.4 秒 |
| Original `iso` | 8.1 秒 | 8.4 秒 |
| Original `readback` | 26.1 秒 | 14.4 秒 |
| BEST | 18.4 秒 | 17.5 秒 |
| SP `sp-full-text` | 93.6 秒 | 60.6 秒（同机负载约 10，波动 ±6 秒） |
| 三版合计 | 259.2 秒 | 159.4 秒 |

三张 ISO 仍为 `3cf68c57…`／`e950438e…`／`8e796122…`。压缩缓存为空的首次构建 272.9 秒，与第一轮持平。

1. **Rust 压缩结果缓存**（`srwz/codec.py`）。压缩器是确定性的：同一二进制、参数与输入必得同一负载。
   `_rust_payload` 以“压缩器二进制 SHA-256 + 参数 + 输入”为键，把负载存进 `work/cache/compression/`，
   每个条目自带负载摘要，读取时校验，不符即当未命中重算；调用方原有的解码回读校验不变。
   只在 `SRWZ_COMPRESSION_CACHE` 设置时启用（`build_editions.phase_environment` 指向根工作区），
   `--force-rebuild`（`SRWZ_REHASH=1`）只写不读；每批结束按最近使用保留至多 2 GiB。当前约 68 MB。
   工具改动后的全量里绝大多数被压缩的数据与上一批相同，MAPMODEL（单次 build 175 次、约 240 CPU 秒）、
   LIBRARY、SP `write_system_text`（17.7 → 1.2 秒）等都直接命中。
2. **`_rust_compressor_path` 只解析一次**；原先每次压缩／解码都 `resolve()`。
3. **LIBRARY legacy 排版改为按需。** legacy 只是 dense 塞不进原容量时的回退，原先每段正文都预先算好；
   带 `<width:..>` 作用域的正文 legacy 还直接调用同一个 `reflow_body`，等于同样的排版算两遍。
   现在只有 dense 压缩失败、需要回退时才计算 legacy，出错信息不变。LIBRARY 28 → 15.6 秒，输出不变。
4. **去掉重复的剧情排版计算／检查。**
   - 组件构建：门禁 `dialogue_layout_issues` 通过后不再调用 `fit_chinese_dialogue_layout`。两者判定条件
     （行数、首行与后续行宽、同一词表与字宽）完全相同，门禁通过时 fit 必然原样返回；
     `dialogue_layout_reflowed_count` 仍为 0。
   - 回读：删除对语料重跑的同一门禁与 fit。回读负责“ISO 字节等于语料”，语料自身的排版已由同一批构建、
     同一冻结输入上的组件门禁检查过；回读里按 21×3、默认 24 px 的宽度检查口径不同，保留。
     回读 manifest 与删除前逐字节相同（`1bb06e4e…`）。

验证：全部单元测试通过（714 项，6 项按环境跳过），新增 `tests/test_compression_cache.py`
（命中、参数／输入入键、损坏条目重算、`SRWZ_REHASH` 绕过、未设置不启用、按最近使用裁剪）。

## 第三轮：统一文件视角（解压一次、全部修改、压缩一次）

用 `sitecustomize` 给一次完整三版构建的所有 Python 进程挂上编解码追踪，按“某次解压／重压的输入
正是此前某次压缩的输出”串起链条。解压很便宜（17,243 次共 16 秒），重复链条集中在压缩：

| 链条 | 块数 | 中间压缩 CPU |
| --- | ---: | ---: |
| 剧情组件 → full-story（压 2 次） | 134 | 14.5 秒 |
| 剧情组件 → full-story → full-story（压 3 次） | 44 | 20.4 秒 |
| SP `write_system_text` → `migrate_stage_dialogue` | 33 | 16.3 秒 |
| SP `write_image_labels` → 组装 | 12 | 1.5 秒 |
| SP frame COMPDATA → 组装内连续 8 次重压 | 1 | 1.0 秒 |

### 机制

- `srwz/compressed_workspace.py` 新增 `CompressedArchiveWorkspace`：固定分配档案的每块首次访问时
  解压一次，写入器只改解压视图，`finalize` 对改动块各压缩一次（并行），档案大小与偏移不变。
  `export_overlay`／`import_overlay`／`from_overlay` 用于跨进程交接：上游只写出绑定源档 SHA-256 的
  解压改动（`SRWZOVL1` 格式，逐块哈希），由最终拥有者压缩。`decoded_view`／`write_decoded` 让写入器
  同时接受压缩字节或 workspace。
- 每块压缩参数取“最后写入它的领域”：只被剧情组件写过的块沿用剧情组件档案（匹配链 1024），其余用
  full-story 档案（16384），与此前链式结果逐字节相同。统一成一套参数会改变 ISO 字节，未做。

### 改动

1. **Original STAGE。** `build_story_component.py` 不再压缩，输出 `DATA/STAGE.BIN.overlay`（182 块），
   报告记 `output_decoded_sha256` 与 `codec_options`；按块缓存改从上一份 overlay 取。full-story 从原盘
   STAGE 打开整档 workspace、导入 overlay，编队名、系统对话、关卡图提示、关键词弹窗都写在同一视图，
   `_finalize_stage_archive` 一次压缩；输出报告新增 `compression.stage_archive`（每块最终编码），
   取代 `stage_chunk_0_workspace`。增量路径以上一批最终 STAGE 为底，只替换变化块。
   `verify_full_story_iso_content.py` 改为只认 `stage_archive`（未改动块须等于原盘块），不再按
   剧情→固定编队→默认编队→关键词逐层覆盖。`config/full-story-components.json` 的
   `full_story_stage.stage` 改指 overlay；上一批输入文件已不存在时按“该输入已变”重建受影响成员。
2. **SP COMPDATA（进程内）。** 组装阶段从 frame 组件取出 COMPDATA 后开一个 workspace，合并、共享图鉴、
   Gravion、机体名、驾驶员名、关键词名、共享标签、指令覆盖都只改视图，最后按 `encode_slot`
   规则（rust-fit，失败退 rust-maximum）压缩一次。
3. **SP 跨进程。** `write_system_text.py --decoded-overlays`（仅 `build_full_text` 使用；预览与调研工具
   默认仍得到压缩成员）输出 COMPDATA／STAGE overlay；`migrate_stage_dialogue.py` 拥有 SP STAGE 的
   一次压缩（含只被滚动字幕改过的块）；组装与 SP 回读直接读 overlay 的解压视图。SP 增量缓存指纹
   改绑 `system/DATA/STAGE.BIN.overlay`。
4. **MAPMODEL 局部修补（`rust-patch`）。** 地形名与世界地图标题各改原盘成员的几字节到几 KB，过去
   每个 1–5 MB 成员整段 rust-fit 重压（181 个成员、约 153 CPU 秒）。Rust 压缩器新增 worker 操作 2
   `patch_stream`：原样保留仍产出相同字节的原始记号；输出或源范围碰到改动字节的回引用，只把碰到的
   偏移改为字面字节，其余仍有效的片段保留为同距离回引用；全回引用失效的块把字面字节并入下一块
   （游戏不接受流中段零回引用块）。原盘分配几乎没有余量，纯修补放不下时，以改动处为中心取 16 KB
   起逐级放大的窗口用 fit 档案重压（以前文为字典），直到放进原分配；仍放不下才退回整段 rust-fit。
   `reencode_changed_suffix(strategy="rust-patch")`，配置 `world_map_titles.codec` 与
   `terrain_names.codec` 改为 `rust-patch`。实测 181 个成员全部修补成功、无回退，墙钟 22 秒 → 1.8 秒。

### 结果

| 场景 | 第二轮 | 第三轮 |
| --- | ---: | ---: |
| 工具改动后全量（压缩缓存已热） | 159.4 秒 | 151.5 秒 |
| 压缩缓存为空的全量 | 272.9 秒 | 171.8 秒 |
| SP `write_system_text`（空缓存） | 17.9 秒 | 1.4 秒 |

阶段 1–3 完成时三张 ISO 仍为 `3cf68c57…`／`e950438e…`／`8e796122…`；增量与 `--force-rebuild`
对同一处语料修改产出逐字节相同的 STAGE.BIN（`d05e3a1f…`），增量产物通过完整回读。

MAPMODEL 修补后 Original 为 `a1b9290e…`、BEST 为 `56ab0f2c…`，SP 不变（`8e796122…`）。逐成员比较：
两版都只有 `MAP/MAPMODEL.BIN` 变化；Original 196 个 MAPMODEL 成员中 175 个压缩字节变化，196 个解压
内容与此前完全相同。三版静态回读通过。

运行验证（LRPS2，x86_64，SW renderer，无音频输出，ARMSX2 记忆卡副本，
`work/runtime/lrps2/mapmodel-patch-20261007/`）：读取第 24 话后的幕间存档 → 下个地图，世界地图正确
显示中文地名「亚特兰迪亚」；进入战斗地图，地图模型正常渲染；导出 32 MB EE RAM，当前地图为 MAPMODEL
成员 9（新 ISO 中为修补流，压缩字节与旧版不同、解压内容相同），其 8 处地形名的译文编码全部在内存中，
其中 7 处前后 64 字节窗口与修补流的解压结果逐字节一致。未覆盖：其余地图逐一运行、PCSX2 手工验收。

验证：全部单元测试通过（723 项，6 项按环境跳过）；新增 `tests/test_compressed_workspace.py` 的
整档／overlay／按块参数用例、`tests/test_rust_patch.py`，Rust `patch_stream` 单元测试。

## 仍未处理

- SP 每批用 xdelta 从原盘还原 3.7 GB 基线镜像并整盘哈希，约 9 秒；可把还原结果放进根工作区缓存、
  以 APFS 克隆复用，代价是常驻约 3.7 GB 磁盘。
- SP 共享图鉴写入（14.5 秒）与独立回读（18.7 秒）各算一遍同样的图鉴排版。
- 排版动态规划仍用 `Fraction` 运算；整数化可再提速，但需另行证明断行完全一致。
- STAGE 按块压缩参数沿用历史（剧情 1024／其余 16384）；统一为一套会改变 ISO 字节。

结构化记录：`manifests/editions/build-performance-20261007.json`。
