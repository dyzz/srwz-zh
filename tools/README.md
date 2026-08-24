# v0.3.0 构建工具

`tools/` 只保留重建 v0.3.0 所需的 Python 入口和它们直接使用的 clean-room
模块。实验、分析、机器翻译、审校网页、迁移、运行控制和一次性快照脚本不属于
发布构建闭包，已从当前树移除；需要追溯时使用 Git 历史。

```text
tools/*.py                    v0.3.0 构建与回读入口
tools/srwz/*.py               入口直接依赖的解析、写回和验证模块
tools/native/srwz-codec-rs/   生产压缩与解压工具
vendor/upstream-python/       构建链读取的固定静态定义
```

## 发布主链

| 阶段 | 入口 |
| --- | --- |
| 原版校验与提取 | `verify_original_disc.py`、`extract_iso_member.py` |
| 工具链准备 | `bootstrap_mkps2iso.py`、`build_rust_compressor.py` |
| 基础 UI | `build_release_base_ui.py` |
| 字体来源与组件 | `fetch_zh_font.py`、`prepare_zh_release_font.py`、`rebuild_zh_font.py` |
| 领域组件 | `build_library_v02_component.py`、`build_story_component.py`、`build_zh_font_component.py`、`build_full_story_components.py`、`ui_atlas.py` |
| 最终组合 | `compose_full_story_library_components.py` |
| ISO | `build_iso.py` |
| 静态回读 | `verify_zh_release_font.py`、`verify_full_story_iso_content.py` |
| 发布包 | `build_release.py` |

通常按以下顺序构建：

```bash
python3 tools/verify_original_disc.py
python3 tools/extract_iso_member.py --force <主链成员...>
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_rust_compressor.py
python3 tools/build_release_base_ui.py
python3 tools/rebuild_zh_font.py --skip-fetch
python3 tools/build_iso.py
python3 tools/verify_full_story_iso_content.py --force
python3 tools/build_release.py
```

不带 `--config` 时，ISO 与发布入口分别读取
`config/iso/zh-release-current-build.json` 和 `config/release/v0.3.0.json`。
完整的原版成员列表见 `docs/BUILD_AND_RUNTIME.md`。`rebuild_zh_font.py` 会按依赖顺序
生成全局字体、reviewed LIBRARY、STAGE、UI 图集和最终组合组件；
`build_iso.py` 强制校验固定 LBA、成员预算与整盘哈希；`build_release.py` 生成 xdelta
后会实际还原一次并核对目标 ISO，发布目录和 ZIP 均不得包含完整 ISO。

生产压缩、解压和压缩后回读只使用 `tools/native/srwz-codec-rs/`。Python 模块负责
结构解析、前像检查、受控写回和结果核验，不提供另一套发布编码器。
