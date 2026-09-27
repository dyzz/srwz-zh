# 构建工具

Special Disc 的独立开发工具见 [special_disc/README.md](special_disc/README.md)。

## 生产入口

日常构建、冻结和打包使用以下入口：

| 阶段 | 入口 |
| --- | --- |
| 三版同批构建（默认 Original、BEST、SP） | `build_editions.py`，独立复核用 `verify_editions.py --manifest <批次 JSON>` |
| 冻结发布（复制已验证镜像、回读 skip hook、写 schema 4 发布配置） | `freeze_release.py --manifest <批次 JSON> --version <x.y.z>` |
| 发布包（xdelta、实际还原、SHA-256） | `build_release.py --config config/release/<版本>.json` |

`build_editions.py` 冻结同一批源码、语料与配置，在每版私有工作区内依次执行下表的
子步骤，把通过整盘回读的 ISO 发布为当前盘和日常测试副本，并写出回执与计时。
输入未变时复用已验证的当前 ISO；只改语料时沿用上一批的已验证组件缓存，只重建
受影响组件。Original 支持成员级增量封盘，SP 仍完整合成 ISO 并独立回读。
`--force-rebuild` 强制组件重建并禁用持久文件身份缓存。
缓存规则、依赖、输出路径与计时见 [三版本构建](../docs/BUILD_EDITIONS.md)。

```bash
python3 tools/build_editions.py --plan
python3 tools/build_editions.py
python3 tools/build_editions.py --editions original,best
python3 tools/build_editions.py --editions sp
python3 tools/prune_edition_workspaces.py            # 列出可清理的历史私有工作区
python3 tools/freeze_release.py --manifest work/editions/<摘要>/original-best-sp.json --version 0.5.0
python3 tools/build_release.py --config config/release/v0.5.0.json
```

发布策略：后续 release 固定包含 Original、The Best 和 SP，三版均内置方块 skip，每版只有
一份补丁（`srwz-zh-v<版本>-original.xdelta`、`srwz-zh-v<版本>-best.xdelta`、
`srwz-zh-v<版本>-sp.xdelta`）。冻结器拒绝缺版批次，并保存 SP 独立语义回读报告。
发布工具会重新读取三版冻结镜像核对 skip hook，再逐个生成补丁并从对应日文原盘还原验证。
v0.4.2 的四补丁配置（schema 3）仍可原样重建。CHD 工具也支持 `--edition sp`。

## 统一入口内部的子步骤

以下工具由统一入口在私有工作区内调用；单独运行只用于排错和资源维护，不再作为
日常构建命令。

| 阶段 | 入口 |
| --- | --- |
| 原版身份（统一入口内置 `verify_disc` 与成员提取） | `verify_original_disc.py`、`extract_iso_member.py`（排错） |
| 工具链 | `build_rust_compressor.py`、`bootstrap_mkps2iso.py`（已构建的固定版本直接复用，不重跑 CMake） |
| 字体来源与组件 | `fetch_zh_font.py`、`prepare_zh_release_font.py`（`--reuse-raster-cache` 复用逐字形栅格）、`rebuild_zh_font.py` |
| 领域组件 | `build_library_v02_component.py`、`build_story_component.py`、`build_zh_font_component.py`、`build_full_story_components.py`、`build_aid_battle_prompts.py`、`build_tricmn_battle_overlays.py`、`ui_atlas.py`、`build_ui_headings.py` |
| 最终组合 | `compose_full_story_library_components.py` |
| ISO | `build_iso.py`（`--incremental` 克隆上一验证镜像并只改写变更成员） |
| 静态回读 | `verify_zh_release_font.py`、`verify_full_story_iso_content.py` |
| BEST 原生后端 | `build_best_current.py` |
| 剧情断行门禁 | `text_layout/check_story_dialogue_layout.py`（构建器执行同一检查）、`text_layout/rebalance_story_dialogue.py`、`text_layout/build_story_unbroken_words.py`（写作辅助） |
| 文本审阅候选（根工作区） | `build_text_update_iso.py`（`--release-proof` 执行完整回读和确定性复建） |
| 自动运行验证（构建闭包外） | `run_lrps2_validation.py` |
| 发布归档 | `build_release_chd.py` |

`build_tricmn_battle_overlays.py` 是一个例外：正式构建只解码并写入审核后冻结的三张
PSMT4 索引图，再校验完整 `BTL/TRICMN.BIN` 的固定哈希，不调用字体或 ImageMagick。
维护时只有显式传入 `--live-render` 才会进入保留的绘制链；替换冻结件还必须额外传入
`--refreeze-snapshot`，并在审图和运行验收后更新快照锁与清单。

## 共享约定

- 所有哈希经 `srwz/file_identity.py`：每个文件身份（设备、inode、大小、mtime、
  ctime）只计算一次 SHA-256，APFS 克隆继承来源的已验证摘要；同一构建的所有
  子进程共享 `work/cache/file-identity.json`。`SRWZ_REHASH=1` 或 `--force-rebuild`
  禁用该持久层。
- 复制大文件统一用 `srwz/release_inputs.py::copy_file`（APFS 克隆，不用硬链接）。
- 冻结输入范围由 `srwz/release_inputs.py::is_build_input` 决定：文档、写作辅助、
  运行验证工具不进入输入快照，改动它们不触发重建。
- 组件缓存失效范围由 `srwz/build_fingerprints.py::COMPONENT_BUILD_DEFINITION_ROOTS`
  决定，字体链缓存与私有工作区的缓存承接使用同一份定义。
- 生产压缩、解压和压缩后回读只使用 `native/srwz-codec-rs/`。Python 模块负责结构
  解析、前像检查、受控写回和结果核验，不提供另一套发布编码器。

```text
tools/*.py                    构建、回读、发布及维护入口
tools/srwz/*.py               入口直接依赖的解析、写回和验证模块
tools/native/srwz-codec-rs/   生产压缩与解压工具
tools/native/battle-square-skip/  □ 跳段 hook 汇编源与开发期汇编脚本（生产只用配置内字节）
vendor/upstream-python/       构建链读取的固定静态定义
```

## 已移除的入口

- `build_best_candidate.py`（实验性二进制移植）已由 `build_best_current.py` 取代。
- `update_qa_editions.py`（2026-09-20 的一次性 Q&A 热修）生成的回执不带
  `daily_test` 与新的输入摘要，统一入口无法复用；Q&A 修正走正常构建。
- `prepare_release_variants.py`（不带 skip 基底 + 派生 skip 变体的四补丁冻结）已由
  `freeze_release.py` 取代：发布全部内置 skip，每版一份补丁。`srwz/release_variants.py`
  只为重建已冻结的 v0.4.2 保留。
