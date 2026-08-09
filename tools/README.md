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
| 图片 | `build_ui_atlas_localization.py`、`build_ui_atlas_suite.py` |
| 剧情组件 | `build_story_component.py`（通常由全局字体主链自动调用） |
| 最终组件 | `build_full_story_components.py`（通常由全局字体主链自动调用） |
| ISO | `build_iso.py --config config/iso/zh-release-full-story-build.json` |
| 静态回读 | `verify_zh_release_font.py`、`verify_ui_atlas_suite.py`、`verify_full_story_iso_content.py`；按领域复核时另用 `verify_remaining_ui_iso_content.py`、`verify_srvc_battle_iso_content.py` |
| 运行证据 | `prepare_pcsx2_session.py`、`launch_pcsx2_session.py`、`collect_pcsx2_session.py`、`verify_pcsx2_session.py`；boot smoke、进程停止和 savestate 登记／复核是同目录的独立手工命令 |

`tools/*.py` 是可直接执行的命令，因此手工验收工具不一定会被其他 Python 文件
导入；是否保留以当前运行流程和证据职责为准。旧的单行兼容转发层已经移除，
`rebuild_zh_font.py` 与 `build_zh_font_component.py` 现在各自直接包含规范实现。

`tools/srwz/codec.py` 保留严格 decoder 和小样本 oracle；生产写回必须选择 Rust
策略，满足原槽或成员扇区预算即可，不要求无意义地追求全局最大压缩率。

基础 UI 的中间过程已经折叠为 `release-base-ui` 验证收据；旧 ISO 组合、翻译模型、
审校网页、通用解析导出器、研究探针和 dashboard 命令已移除。各生产模块仍在构建
时直接解析自己的锁定输入，不依赖预生成的总解析报告。

当前生产重建只有两个顶层入口：

```bash
python3 tools/rebuild_zh_font.py --skip-fetch
python3 tools/build_iso.py --config config/iso/zh-release-full-story-build.json
```

前者按顺序重建全局字体、154 个 STAGE 块、六张图集和 12 成员最终组件；确认输入
或 ratchet 发生预期变化时才附加 `--refresh-manifests`，字体视觉规则变化时再附加
`--refresh-asset-ratchets`。
