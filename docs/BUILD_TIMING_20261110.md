# 三版镜像构建耗时（2026-11-10）

命令：`python3 tools/build_editions.py --candidate`，三版一起构建。
机器：Apple M4 Max，16 核。
回执：`work/editions/0e6768e88daa3f248890a3cf028a1e6994233e7eaf503b19d7a19e9fe3404290/original-best-sp-candidate.json` 的 `timing`。
这是普通构建，可以复用已验证的组件，不是 `--force-rebuild` 的全量冷构建。

## 总览

| 镜像 | 耗时 |
|---|---:|
| Original | 117.1 s |
| Best | 24.4 s（排在 Original 之后，用 Original 的前端结果） |
| SP | 181.6 s（和 Original→Best 并行） |
| 整批墙钟时间 | 185.3 s |

整批时间基本由 SP 决定。

## 分步

| 镜像 | 步骤 | 耗时 |
|---|---|---:|
| Original | components | 77.1 s |
| Original | event-subtitles | 12.2 s |
| Original | readback | 12.2 s |
| Original | iso | 11.3 s |
| Original | codec | 2.1 s |
| Original | iso-toolchain | 0.3 s |
| Original | fonts | 0.1 s |
| Best | native-components-and-iso | 8.1 s |
| Best | event-subtitles | 4.6 s |
| SP | sp-full-text | 166.4 s |
| SP | rust-compressor | 2.1 s |

Best 和 SP 的分步加起来小于各自总时间，差额没有单独记录。

## 可以优化的线索

- SP 的 `sp-full-text` 是最大的一步。同一天单独构建 SP 时这一步约 108–110 s，三版并行时是 166 s，并行争抢多出约 56 s。
- Original 的 `components` 占 Original 总时间的三分之二。
- 2026-10-14 记录的全量冷构建是 57 s，原因见下一节。

## 变慢的原因（实测）

历次回执显示，三版总耗时在 2026-11-07 约 95 s，2026-11-08 引入比例排版后升到 190–220 s。

用记录调用的 Node 包装脚本跑了一次全量冷构建（`--candidate --force-rebuild`，199.9 s）。Node 共调用 2,334 次，整批 184.9 s 里有 145.9 s 至少有一个 Node 在运行。

最大的一项是图鉴正文的比例排版。它每批只有 64 条，每批约 2 s（每条约 33 ms），按顺序一批批跑，而且整个构建算了三遍：

| 位置 | 调用 | Node 耗时 |
|---|---:|---:|
| Original `build_library_v02_component` | 21 批 | 45.0 s |
| SP 写入 `current-shared-library` | 23 批 | 46.9 s |
| SP 独立回读 | 62 次 | 47.0 s |

SP 177.9 s 按阶段分，Node 耗时占比如下：

| 阶段 | 阶段耗时 | Node 占用 |
|---|---:|---:|
| 组件（剧情、战斗台词、画面文字） | 62 s | 42 s |
| 图鉴写入 | 48 s | 47 s |
| 独立回读 | 53 s | 47 s |

全量冷构建 199.9 s 和普通构建 185 s 差别很小，说明组件复用省不掉这部分时间。

## 第一项优化：图鉴排版并行（已完成）

`srwz.build_layout.library_batch` 把各批同时发给多个 Node 进程，最多 8 个，受 `SRWZ_WORKERS` 控制。

全量冷构建（`--candidate --force-rebuild`）对比：

| 项目 | 优化前 | 优化后 |
|---|---:|---:|
| 三版总耗时 | 199.9 s | 117.9 s |
| Original | 108.7 s | 78.4 s |
| Best | 23.5 s | 22.8 s |
| SP | 192.5 s | 111.3 s |
| SP 图鉴写入 | 48.1 s | 7.8 s |
| SP 独立回读 | 53.4 s | 13.3 s |

三个镜像的 SHA-256 与优化前逐字节相同：Original `061443c5…`，Best `e3c9ed4e…`，SP `af82f520…`。

同一份代码的前一次运行是 156.1 s，当时机器负载较高，说明这个数字会随机器负载波动。

## SP 组件阶段的剖析

用 cProfile 单独运行两个脚本，带剖析时分别是 60.2 s 和 22.6 s，不带剖析约 50 s 和 22 s。

`migrate_stage_dialogue`：

| 内容 | 耗时 | 说明 |
|---|---:|---|
| 地点字幕、条件等的逐行宽度检查 | 23.4 s | 455 次 `request_layout`，每个不同的行新起一个 Node（约 51 ms） |
| 对白折行 `fit_candidate_stories` | 10.1 s | 87 批 |
| 折行后复核 `stored_geometry_issues` | 9.9 s | 176 批 |
| `reject_interior_references` | 12.6 s | 纯 Python，每个 4 字节位置线性扫描全部区间，约 1.4 亿次比较 |
| 实际写入文本 `repack_stage_texts_in_place` | 1.2 s | |

42 个章节按顺序处理，没有并行。

`migrate_srvc`：

| 内容 | 耗时 | 说明 |
|---|---:|---|
| SP 台词逐句检查 `battle_subtitle_layout_issues` | 9.0 s | 123 句，184 次单独起 Node |
| 全部台词复核 `stored_geometry_issues` | 6.1 s | 101 批 |
| 解析 SRVC 档案 | 4.8 s | 解析两次 |
| 重建档案 | 2.4 s | |

## 第二项优化：批量量宽度、指针检查改二分（已完成）

逐行宽度检查改成先用 `prime_text_extents` 成批测量；`reject_interior_references` 改用合并后的有序区间二分查找。全量冷构建对比：

| 项目 | 第一项优化后 | 第二项优化后 |
|---|---:|---:|
| 三版总耗时 | 117.9 s | 104.2 s |
| Original | 78.4 s | 74.4 s |
| Best | 22.8 s | 23.3 s |
| SP | 111.3 s | 84.2 s |
| `migrate_stage_dialogue` | 50.1 s | 25.4 s |
| `migrate_srvc` | 21.7 s | 10.5 s |
| SP 组件阶段 | 62.0 s | 34.9 s |

三个镜像的 SHA-256 仍与优化前逐字节相同。现在总耗时的瓶颈是 Original→Best 这条线，合计约 98 s。

## 剩余优化方向（收益是估算，未实测）

1. 用一个常驻 Node 进程代替每批新起进程。
2. Original 的 `components`（41.7 s）现在是最大的一步，还没有拆开分析。
3. 按“输入文本 + 排版引擎版本”缓存结果，Original 和 SP 共用。SP 独立回读要不要用缓存需要取舍，用了就不再是独立重算。
