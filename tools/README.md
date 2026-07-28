# 工具目录

`tools/` 分成两层：

- `tools/srwz/`：可导入、可单元测试的 SRWZ clean-room 实现；
- `tools/*.py`：参数检查、文件 I/O 和外部工具编排的命令行入口。

核心库只使用 Python 标准库和本目录模块，不导入
`vendor/upstream-python/` 中的 Python 实现。命令行入口会按用途读取固定的
上游数据表、原版文件和本机构建工具。

## 核心库

| 领域 | 模块 | 当前职责 |
| --- | --- | --- |
| 压缩格式 | `codec.py`、`codec_contract.py`、`diagnostics.py` | 严格解码、确定性 literal/greedy 编码、header-preserving suffix 重编码、边界和 trace |
| 归档与布局 | `archive.py`、`iso_layout.py` | offset 表、chunk 切分/重建、SLPS 内嵌布局 |
| 文本数据 | `text.py`、`menu.py`、`stage.py`、`summary.py`、`summary_layout.py`、`display_names.py`、`reference.py` | 码表、控制码、菜单/剧情/摘要、世界史固定 allocation 中文布局、COMPDATA 名称表解析和参考结果对照 |
| 语料与写回 | `corpus.py`、`translation_review.py`、`writeback.py`、`writers.py` | 稳定 ID、译文/术语审核、严格序列化、前像保护、文本池/指针、定长文本和归档 writer |
| 生产选择 | `project.py` | SurfaceSpec、中文语料、codebook 和 BuildProfile reconciliation |
| 字库、canary 与 UI 集成 | `font.py`、`font_source.py`、`ui_font.py`、`canary.py`、`complete_canary.py`、`ui_integration.py`、`ui_runtime_matrix.py`、`ui_runtime_evidence.py` | 许可证/哈希锁定的字体源、VT1 字库段、24×24/4-bpp glyph、继承式 UI 字库 profile、菜单/摘要/剧情 canary、已验证 UI 组件组合，以及逐屏运行计划／证据收据 |
| 图片与地图名 | `tim2.py`、`tim2_writeback.py`、`ui_atlas_canary.py`、`image_export.py`、`image_dashboard.py`、`imagemagick.py`、`assets.py`、`mapname.py` | TIM2 v4 严格元数据、全量图片导出与本地 Dashboard、固定 4-bpp/VT1 8-bpp index 注入、受 mask 约束的信息页定位 canary、确定性 ImageMagick adapter、归档清单和 MAPNAME |
| 镜像验证 | `iso_config.py`、`iso9660.py` | ISO profile schema／目录所有权契约、只读 ISO9660 扫描、成员哈希、布局和 PCSX2 介质判定 |
| 补丁审计 | `patch_audit.py`、`toolchain.py` | 写入所有者、允许范围、armips 来源/构建/结果审计 |

没有通用 ISO 编辑器、编码器 GUI 或 Windows helper 兼容层。当前 ISO 构建由
固定的 `mkps2iso` 完成；`iso9660.py` 负责独立验证，不冒充 ISO authoring
实现。

## 命令入口

| 阶段 | 入口 |
| --- | --- |
| 原版与样本 | `verify_original_disc.py`、`extract_iso_member.py`、`split_stage_archive.py`、`verify_codec_samples.py` |
| 解码诊断 | `inspect_srwz_stream.py`、`scan_stage_streams.py` |
| 全量解析与语料 | `parse_srwz_iso_data.py`、`parse_srwz_display_names.py`（COMPDATA 人物／机体名称结构）、`export_srwz_corpus.py`、`review_srwz_translations.py`（含当前剧情里程碑术语、例外和官方简中异名专项表）、`build_biligame_gundam_reference.py`（从 Jina 缓存离线重建 SRWZ 高达人物／机体审核索引，不自动采用社区 WIKI 译名）、`reflow_first_five_dialogue.py`（24 字宽、最多 3 行、术语／运行时 token 不拆分和中文标点禁则）、`reflow_world_history.py`（28 条 MTV_PROS、22 格、空行和固定 allocation 门）、`audit_first_five_language_quality.py`（前五关显示行宽、结构符号和同源异译说明门）、`audit_first_five_upstream_english.py`（固定上游英语直接覆盖与跨关同源参考审计）、`audit_ui_coverage.py`（UI 场景选择、当前字库需求、动态名称结构／writer、世界史布局和提交清单 freshness）、`audit_ui_runtime_matrix.py`（14 类场景的精确 ISO、原生存档、截图／序列／texture-delta 和延期门禁）、`build_ui_p0_fixed_slps.py`／`verify_ui_p0_fixed_slps.py`（原 span 内 P0 SLPS 写回、独立复建和指针／非目标字节门禁）、`build_ui_p0_fixed_compdata.py`／`verify_ui_p0_fixed_compdata.py`（COMPDATA 原位写回、保留前缀重编码和完整回解）、`build_ui_p0_display_names.py`／`verify_ui_p0_display_names.py`（开场 45 个动态名称字段及 ID／指针／非目标字节门禁）、`export_story_dialogue_stage_review.py`、`build_story_dialogue_stage_translation.py` |
| 生产 profile | `validate_build_profile.py` |
| 字库 | `analyze_srwz_font.py`、`render_srwz_font.py`、`fetch_canary_font.py`、`fetch_first_five_font.py`、`audit_first_five_writeback.py`、`build_first_five_font.py`（也接受独立 proposal/config/output 参数）、`audit_first_five_font_coverage.py`、`audit_ui_p0_font.py`／`verify_ui_p0_font.py`（兼容 P0 入口）、`audit_ui_font.py`／`verify_ui_font.py`（显式 profile 的 P1+ 通用入口） |
| UI 集成 | `build_ui_p1_core.py`／`verify_ui_p1_core.py`（标题、P0 菜单、开场动态名、P1 字库和世界史的所有权合并、确定性复建与全文回读） |
| 图片/地图名 | `inventory_srwz_assets.py`、`export_srwz_images.py`、`build_image_dashboard.py`、`render_srwz_tim2.py`、`inject_srwz_tim2.py`、`build_tim2_runtime_canary.py`、`build_ui_atlas_map_canary.py`／`verify_ui_atlas_map_canary.py`（受 mask 约束的 KVMDATA 定位组件）、`parse_srwz_map_names.py` |
| 编码与归档写回验证 | `validate_srwz_encoder.py`、`validate_srwz_archive_rebuild.py` |
| 静态 canary | `build_static_canary.py`、`build_complete_canary.py` |
| ISO | `bootstrap_mkps2iso.py`、`build_canary_iso.py`、`verify_first_five_iso_content.py`、`verify_ui_p1_world_history_iso.py`（世界史 component→隔离 ISO 静态绑定）、`verify_ui_p1_core_iso.py`（组合 UI component→ISO 静态绑定）、`verify_ui_atlas_map_canary_iso.py`（UI atlas 定位 component→单成员、零 LBA 位移的隔离 ISO 静态绑定） |
| PCSX2/PINE | `prepare_ui_runtime_case.py`（生成 case plan／空白草稿）、`probe_ui_runtime_session.py`（精确 ISO＋PINE＋日志 R0）、`verify_ui_runtime_evidence.py`（截图／序列／atlas delta＋断言收据）、`verify_pcsx2_font_runtime.py`、`verify_first_five_runtime.py`、`send_pcsx2_keys.swift`；准备工作区或 ISO verifier 都不冒充运行证明 |
| ASM 与二进制审计 | `check_armips_toolchain.py`、`audit_binary_patch.py` |
| 上游快照 | `compare_upstream_snapshot.py` |

入口保持薄层；可复用逻辑应放入 `tools/srwz/` 并由 `tests/test_*.py` 覆盖。

## 所有权和依赖边界

不能把整套工具链称为“全部自研”。准确分类如下：

### 中文工程维护的独立实现

- SRWZ 压缩流严格解码器和确定性编码器；
- 归档切分/重建、文本解析/序列化、语料导出和写回保护；
- VT1 字库解析、glyph pack/render、静态 canary 构建；
- ISO9660 只读验证器、PINE 客户端和运行时哈希验证；
- 二进制差异、写入所有者和边界审计。
- TIM2 元数据清单、单 picture 提取边界和 MAPNAME 固定记录解析。
- 固定 256×256/4-bpp TIM2 原位像素注入，以及 VT1 标题六 picture
  512×256/8-bpp 的固定 index 替换、PSMT8 坐标级中文文字槽写回、
  重压缩和 offset 前像审计。

这些源码位于 `tools/srwz/` 和薄 CLI 中，具有本项目单元测试；格式常量、
原盘布局和预期行为仍来自原版实测、反汇编及固定上游研究成果，不能把逆向知识
也说成完全从零产生。

### 固定上游参考和数据

- `vendor/upstream-python/` 是固定提交的 23 项原样快照，用于逆向知识、行为
  对照和来源追踪，不是当前运行时 Python 依赖；
- 当前入口直接读取其中的 `project/tbl_all.json` 和
  `project/menu_files.json`；
- `config/stage-offsets.json` 由固定的上游 `Stages_Offset.bin` 转换；
- 全量解析可选择与相邻上游 XML 对照；armips 检查会在原版副本上审计相邻
  上游 ASM，但中文 canary 本身不使用这些 ASM。

固定上游 checkout 没有 `LICENSE` 文件；`config/upstream.lock.json` 明确记录
的是项目协作方授权和来源追踪，不应把这份快照误称为具有标准开源许可证的本项目
源码。

### 第三方开源或系统工具

| 工具/资源 | 用途 | 边界 |
| --- | --- | --- |
| Python 3 标准库 | 全部本项目 Python 工具 | 不需要上游 Python 依赖集合 |
| 7-Zip | ISO/UDF 指定成员读取 | 只读；路径和结果受校验 |
| ImageMagick | 固定字体的 glyph/mask rasterize、单 picture TIM2 只读 PNG 预览 | 生成灰度 mask 和预览；PSMT8/index 写回、CLUT 保留及边界验证由项目 writer 完成 |
| Noto Sans CJK SC | canary 中文字形 | OFL-1.1，文件和许可证哈希固定 |
| LXGW Neo XiHei Screen | 前五关统一汉字字形 | IPA Font License 1.0；版本、提交、字体和许可证哈希固定 |
| Git、CMake、Ninja、CTest | 固定源码获取与本机构建 | 版本/提交受 lock 校验 |
| armips | 上游 ASM 行为复现和审计 | 官方 MIT 源码在 macOS 构建；不是本项目实现 |
| mkps2iso/dumps2iso | PS2 DVD 提取布局与 ISO 回包 | 官方 GPL-2.0-only 固定版本；不是本项目实现 |
| PCSX2 | 运行验证及 PINE IPC 服务端 | 模拟器和协议服务端均为外部工具 |
| GNU binutils、Ghidra | R5900 静态研究 | 研究辅助，不进入日常构建 |

禁止执行的 Windows helper、Wine 和 Mono 不属于可用工具链。完整来源锁见
`config/`，可提交验证结果见 `manifests/`。
