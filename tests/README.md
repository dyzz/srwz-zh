# 测试范围

当前单元测试统一位于 `tests/test_*.py`，按被测模块命名。编码、布局、
round-trip 和 PINE 协议均已落到可自动运行的测试文件，不再保留空的分类
占位目录。PCSX2 正常流程和截图属于独立运行证据，记录在 manifest 和
`docs/ISO_BUILD_AND_PCSX2.md`。

静态测试通过不能替代运行验证；涉及渲染和流程的结论必须有对应运行记录。

`test_project.py` 固定生产输入层的正向和负向契约：source hash 漂移、中文源
重复日文正文、编辑状态不足、未使用 codebook assignment 和编码结果都会被
检查。`test_canary.py` 另确认旧 canary 配置不再拥有译文/字形事实源，
E2 菜单、摘要、剧情三条隔离 fixture 和完整组合 manifest 都绑定到固定
component/ISO lock。

根目录下的 `test_archive.py`、`test_codec.py`、`test_codec_contract.py`、
`test_codec_diagnostics.py`、`test_text.py`、`test_menu.py`、
`test_stage.py`、`test_summary.py`、`test_font.py`、`test_corpus.py`、
`test_writeback.py`、`test_writers.py` 和其他 manifest/layout 测试验证
clean-room 基础设施、严格编解码边界、overlap copy、文本控制码、
24×24 glyph pack、原版 code→glyph 扩展表、语料契约、写回前像、归档重建，
以及 armips 来源锁和补丁差异/覆盖失败门：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

单元测试不读取 ISO，也不运行任何上游二进制。真实编码器验证单独运行：

```bash
python3 tools/validate_srwz_encoder.py --strategy greedy --force
python3 tools/validate_srwz_archive_rebuild.py --strategy greedy --force
python3 tools/validate_build_profile.py
python3 tools/check_armips_toolchain.py --force
python3 tools/audit_binary_patch.py --force
python3 tools/fetch_canary_font.py
python3 tools/build_static_canary.py --force
```

它们只在内存或被忽略的 `work/` 临时目录中编解码、重建或汇编本地样本，并
保存哈希和统计。工具链检查只构建固定的官方 armips 源码；canary 只下载固定
官方 OFL 字体并生成本地 SLPS/VT1 副本，不生成 ISO。

`test_iso9660.py` 固定只读 ISO9660 目录解析、双端字段一致性、原盘数据顺序
权重、PCSX2 v2.6.3 介质判定和成员内容摘要；`test_iso_builder.py` 固定
`dumps2iso` 非 UTF-8 volume 清理、staging XML 改写、固定 GPL 工具链配置，
以及 `rom/work/build` 的 profile 隔离目录契约；
`test_pine_runtime.py` 固定 PINE 帧、响应和连续 Read64 地址编码。
`test_tim2.py` 固定 TIM2 header/边界、indexed/shared CLUT 和 false-magic
拒绝；`test_asset_inventory.py` 固定资产 schema、来源路径、成员唯一性和
manifest 投影；`test_image_export.py` 固定 SEG offset、路径安全和
单-picture/调色板 bank 导出边界；`test_image_dashboard.py` 固定本地 HTML
数据投影、重复 PNG 分组和输出路径边界；`test_render_srwz_tim2.py` 固定 ImageMagick wrapper 只能写入
被忽略的 `work/*.png`；`test_tim2_writeback.py` 固定 4-bpp low/high nibble、
byte-exact no-op、VT1 六 picture 8-bpp index 替换、PSMT8 双向映射、CSM1
静态渲染和尺寸/格式/颜色失败门；`test_title_menu.py` 固定四张 mask 到黄色/
绿色 ramp 的量化、八个 128×32 槽写回和纹理右侧 byte-exact；
`test_inject_srwz_tim2.py` 固定
archive/report 输出边界；`test_mapname.py` 固定 Shift-JIS/NUL/全零 padding。
真实图片清单、MAPNAME 聚合计数、PCSX2 图片 canary 的 351-pixel 精确 RGBA
替换，以及标题四项中文的两种光标状态/运行时纹理一致性由 manifest 测试固定。
`test_ui_p0_fixed_slps.py` 与 `test_ui_p0_fixed_compdata.py` 另固定 P0
fixed-span 选择 ratchet、指针／非目标字节不变、组件哈希和压缩回解；两者均
明确要求运行状态仍为 `not_tested`。
`test_display_names.py` 固定 COMPDATA 人物／机体表几何、稳定 ID、指针归并、
零 padding 和 hash-only 提交投影；`test_ui_p0_display_names.py` 固定开场
45 个名称决策、原 allocation 写回、人物 ID／机体指针／非目标字节不变和
压缩流精确回解，并要求 ISO／运行状态仍未测试。
`test_summary_layout.py` 固定世界史 28 条、146 行、22 格、14 个空行、
三个跨记录连续组、零 allocation overflow、字库短缺和未运行边界，并检查
提交语料的标点禁则与 `UN` 术语引用随重分配记录移动。
真实 ISO 工具构建、镜像构建与 66 项逐成员校验单独运行：

```bash
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_canary_iso.py
python3 tools/build_tim2_runtime_canary.py --force
python3 tools/build_canary_iso.py --config config/iso/image-canary-build.json
python3 tools/build_tim2_runtime_canary.py \
  --config config/canary/tim2-vt1-title-zh.json --force
python3 tools/build_canary_iso.py \
  --config config/iso/title-menu-zh-build.json
```

PCSX2 已启用 PINE 且当前 canary 正在运行时，完整读取游戏解压后的字库并
只保存地址、尺寸和哈希：

```bash
python3 tools/verify_pcsx2_font_runtime.py --force
```
