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
| 最终组件 | `build_full_story_components.py`（通常由全局字体主链自动调用） |
| ISO | `build_iso.py --config config/iso/zh-release-full-story-build.json` |
| 静态回读 | `verify_zh_release_font.py`、`ui_atlas.py verify-suite`、`verify_full_story_iso_content.py` |
| 运行证据 | `pcsx2.py prepare/verify/launch/stop/collect/savestate-register/savestate-verify` |

`tools/*.py` 只保留可直接执行的领域入口。PCSX2 和 UI atlas 的同类操作分别由
`pcsx2.py`、`ui_atlas.py` 子命令统一承载；旧 boot-smoke、单点字体探针和重复的
分域 ISO 回读入口已移除。`rebuild_zh_font.py` 与
`build_zh_font_component.py` 各自直接包含规范实现，不再经过兼容转发层。

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
