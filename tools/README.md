# 工具结构

目录沿用上游“命令入口 + 格式库”的分层，但生产实现全部是本仓库 clean-room
代码：

```text
tools/*.py                    可执行命令
tools/srwz/*.py               解析、写回和验证模块
tools/native/srwz-codec-rs/   唯一生产压缩器
vendor/upstream-python/       两份固定只读数据定义
```

## 当前入口

| 任务 | 命令 |
| --- | --- |
| 原版准备 | `verify_original_disc.py`、`extract_iso_member.py` |
| 字体 | `fetch_zh_font.py`、`update_zh_release_font_snapshot.py`、`rebuild_zh_font.py` |
| 图片 | `ui_atlas.py build/verify/build-suite/verify-suite` |
| 剧情组件 | `build_story_component.py`（通常由全局字体主链自动调用） |
| 剧情批量初译 | `run_aliyun_story_dialogue_batch.py`（强制说话人、作品和相邻上下文；仅输出 `work/` 机器初稿） |
| 最终组件 | `build_full_story_components.py`（通常由全局字体主链自动调用） |
| ISO | `build_iso.py --config config/iso/zh-release-current-build.json` |
| 发布补丁 | `build_release.py --config config/release/v0.2.0.json` |
| 静态回读 | `verify_zh_release_font.py`、`ui_atlas.py verify-suite`、`verify_full_story_iso_content.py` |
| 运行证据 | `pcsx2.py prepare/verify/launch/stop/collect/savestate-register/savestate-verify` |

`tools/*.py` 只保留可直接执行的领域入口。PCSX2 和 UI atlas 的同类操作分别由
`pcsx2.py`、`ui_atlas.py` 子命令统一承载；旧 boot-smoke、单点字体探针和重复的
分域 ISO 回读入口已移除。`rebuild_zh_font.py` 与
`build_zh_font_component.py` 各自直接包含规范实现，不再经过兼容转发层。

`tools/srwz/codec.py` 只为格式研究和隔离单元测试保留严格 Python decoder 的代码；
任何 build、提取、静态验证和压缩后回读都只走仓库自有 Rust codec，Python decoder
不再是生产或验收路径。写回满足原槽或成员扇区预算即可，不要求无意义地追求全局
最大压缩率。

基础 UI 的中间过程已经折叠为 `release-base-ui` 验证收据；旧 ISO 组合、翻译模型、
重复审校网页入口、通用解析导出器、研究探针和 dashboard 命令已移除。各生产模块
仍在构建时直接解析自己的锁定输入，不依赖预生成的总解析报告。

当前生产重建只有两个顶层入口：

```bash
python3 tools/rebuild_zh_font.py --skip-fetch
python3 tools/build_iso.py --config config/iso/zh-release-current-build.json
python3 tools/build_release.py --config config/release/v0.2.0.json
```

`build_editorial_review.py` 只生成 `work/review/` 下的离线人工审核页面和候选 JSON，
不会被字体、组件、ISO 或发布入口调用。需要更新审核页面时必须单独显式执行；网页及
候选统计不属于生产构建输入或发布验收门：

```bash
python3 tools/build_editorial_review.py
```

日常润色后的工作版使用通用增量构建。它会比较上一次完整验证留下的输入快照，按
依赖关系计算受影响的 ISO 成员；例如新游戏主人公选择画面的固定名称只会更新
`SLPS_258.87`：

```bash
python3 tools/build_full_story_components.py \
  --config config/full-story-components.json \
  --incremental --force --refresh-manifest
python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json \
  --refresh-output-locks
```

`--incremental` 要求先有一次完整构建留下的增量状态，并会先核对上一份组件清单中的
全部 16 个输出。人物/机体与菜单文本、STAGE、HSFC、NISVDATA、SRVC、自动演示、
VEFF2DX、MAPMODEL、字体及继承组件均有明确依赖边；只有能证明未受影响的成员才会
复用。出现未登记的输入或配置变化时会直接拒绝增量构建。`--refresh-output-locks`
仅允许无 `release_tag` 的工作配置使用，不会修改已经冻结的版本化发布配置；ISO 封装仍会
执行完整的固定 LBA 与成员回读验证。

STAGE 编队名的生产构建只读取
`config/stage-default-formation-inventory.json` 中已经审核并冻结的关卡号、布局和
槽位偏移，逐项核对原始日文前像、容量、零填充及记录元数据；不会在构建时发现新
位置。只有明确进行编队资源审计时才运行扫描并重新冻结：

```bash
python3 tools/freeze_stage_default_formation_inventory.py --force
```

`report_stage_default_formation_names.py` 默认同样只报告冻结位置；
`--formation-tables-only`、`--all-structural` 与 `--legacy-heuristic` 是显式扫描模式。

MAPMODEL 地形名同样只读取 `config/terrain-name-inventory.json` 中冻结的 475 个位置；
生产 build 不再扫描成员 0–80，只解压并最终压缩实际命中的 10 个成员。世界地图标题
的位置已经由审核 corpus 的 member 列表锁定，也不做发现式扫描；普通 build 直接读取
`config/world-map-title-render-snapshot.json` 中冻结的 4bpp 渲染结果和预览，不启动
ImageMagick。只有明确改变标题语料、字体或渲染规则时才显式重新冻结：

```bash
python3 tools/freeze_world_map_title_renders.py --force
```

中场休息图集和 LIBRARY 主菜单也使用相同的“显式重冻结、普通构建只消费快照”规则。
只有明确改变译文、字体或渲染合同后才运行：

```bash
python3 tools/freeze_ui_atlas_renders.py --force
python3 tools/freeze_library_menu_renders.py --force
```

最终组件构建把同一物理压缩流视为一个 decoded workspace。`COMPDATA.BN` 先用 Rust
解码一次，依次完成全人物／机体名、关卡标题、剩余 UI、战斗字幕、武器名和全局安全
别名写入及各自回读，再只压缩一次；`STAGE.BIN` chunk 0 的概览与系统对白也共用一次
解码和一次最终压缩。工作报告的 `compression.*_workspace` 会锁定阶段数、解码次数和
压缩次数。

前者按顺序重建全局字体、170 个含对白 STAGE 块、六张图集、MAPMODEL 世界地图地名和
20 个当前最终组件成员；确认输入或 ratchet 发生预期变化时才附加
`--refresh-manifests`，字体视觉规则变化时再附加 `--refresh-asset-ratchets`。
发布入口先验证原版和目标 ISO 的固定大小与 SHA-256，再用锁定的 xdelta3 版本生成
补丁并实际还原一次；`build/release/v0.2.0/` 中不得出现 ISO。
