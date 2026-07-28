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
单-picture/调色板 bank 导出边界；`test_imagemagick.py` 固定 TIM2→PNG8
渲染必须关闭 palette dithering；`test_image_dashboard.py` 固定本地 HTML
数据投影、重复 PNG 分组和输出路径边界；`test_render_srwz_tim2.py` 固定 ImageMagick wrapper 只能写入
被忽略的 `work/*.png`；`test_tim2_writeback.py` 固定 4-bpp low/high nibble、
byte-exact no-op、VT1 六 picture 8-bpp index 替换、PSMT8 双向映射、CSM1
静态渲染和尺寸/格式/颜色失败门；`test_title_menu.py` 固定四张 mask 到黄色/
绿色 ramp 的量化、八个 128×32 槽写回和纹理右侧 byte-exact；
`test_ui_atlas_map_canary.py` 以同一数据表固定 chunk 2/4/5/6/7 的 mask、
组件／预览锁、单成员 ISO 及 `runtime_not_tested` 边界；
`test_ui_atlas_localization.py` 固定五张中文候选只从受审 corpus 取词、
只在各自已擦除或保留背景的 mask 内写入，逐项锁定新增文字像素、原图 delta、
TIM2 RGBA 回读、等长归档、独立 ISO 和运行映射未通过边界；
`test_ui_atlas_suite.py` 固定五张中文候选对原版 KVMDATA 的 5,568 个实际
归档字节修改互不重叠，所有权外字节保持原样；
`test_ui_test_candidate.py` 固定 P2 UI、前五关和 atlas suite 的 7 个完整成员
所有权、上游 manifest 字段锁与确定性复建；
`test_ui_test_candidate_iso.py` 固定综合 DVD 的 59 个未替换成员、7 个
replacement、两段 LBA 位移、独立 UDF 回读和运行未验收边界；
`test_ui_embedded_scenes.py` 固定延期的 275 条 SLPS UI 文本被 22 个场景
分区零遗漏／零重叠覆盖，253／17／5 条三类可见性 ratchet、真实
pointer／embedded HI/LO 所有权哈希，以及每组 fixture、路线、截图和
`not_tested` 边界；它还固定当前 P2 字库下 13 组／123 条 fixed-span ready、
5 组 font extension、4 组 allocation／owner work、六个缺字与七条 overflow；
`test_ui_embedded_candidate.py` 固定两个 fresh-boot 分区的 23 条决定、
11 条 no-op、12 条／32 target 写入、124 字节／35 段 SLPS 修改、P2 core
零重叠和三个非 SLPS 成员 byte-exact；
`test_ui_p3_test_candidate.py` 与 `test_ui_p3_test_candidate_iso.py` 固定
P3／前五关／atlas 的 7 成员所有权、完整复建、59 个未替换 ISO 成员、
独立 UDF 回读、精确镜像哈希和运行未验收边界；
`test_ui_runtime_matrix.py` 固定 14 类基础场景和两个哈希锁定扩展场景的完整
去向、21 个逐屏用例、
001～005 五个独立开场序列、世界史起点／中点／终点、五张中文 atlas 候选的
截图＋texture-delta 双门，以及六份尚未取得的原生
memory-card fixture；旧 `.p2s`
savestate 不会自动替代 `.ps2`＋SHA-256 证据；
`test_ui_runtime_evidence.py` 固定 case plan、精确 ISO、PINE Running、
fresh-process、DVD／ELF／零 TLB 日志、原生 memory-card 哈希、截图收据和
矩阵 receipt 晋级边界；草稿、失败断言或没有提交 receipt 的 `passed` 状态
必须失败；
`test_inject_srwz_tim2.py` 固定
archive/report 输出边界；`test_mapname.py` 固定 Shift-JIS/NUL/全零 padding。
真实图片清单、MAPNAME 聚合计数、PCSX2 图片 canary 的 351-pixel 精确 RGBA
替换，以及标题四项中文的两种光标状态/运行时纹理一致性由 manifest 测试固定。
`test_ui_p0_fixed_slps.py` 与 `test_ui_p0_fixed_compdata.py` 另固定 P0
fixed-span 选择 ratchet、指针／非目标字节不变、组件哈希和压缩回解；两者均
明确要求运行状态仍为 `not_tested`。
`test_display_names.py` 固定 COMPDATA 人物／机体表几何、稳定 ID、指针归并、
零 padding 和 hash-only 提交投影；`test_display_name_coverage.py` 固定
researched 精确源词的 1,262 字段选择、1,166 个当前字库直通项、96 个缺字
项／21 个编码缺字、33 个 renderer 缺字、其中 4 个退役 assignment 复用与
29 个新 allocation、29 个统一重绘汉字、19 个预计剩余槽、零 projected
allocation 溢出、2,800 行审核 TSV 和提交清单不含原始日文；
`test_ui_p0_display_names.py` 固定开场
45 个名称决策、原 allocation 写回、人物 ID／机体指针／非目标字节不变和
压缩流精确回解，并要求 ISO／运行状态仍未测试。
`test_ui_p2_display_name_font.py` 固定 P2 对 P1 账本的无重排继承、29 个新增
assignment、4 个退役 assignment 复用、29 个重绘项、1,262 个字段零
renderer 缺字和 19 槽余量；`test_ui_p2_display_names.py` 固定 1,307 项
选择、1,213 项写入、94 项 no-op、完整重解析和不含译文 payload 的清单；
`test_ui_p2_core.py` 固定 P2 世界史／四成员组合、ISO 替换、两段 LBA 位移、
镜像 golden 和 `not_tested` 运行边界。
`test_summary_layout.py` 固定世界史 28 条、146 行、22 格、14 个空行、
三个跨记录连续组、零 allocation overflow、字库短缺和未运行边界，并检查
提交语料的标点禁则与 `UN` 术语引用随重分配记录移动。
`test_ui_p1_summary_font.py` 另固定 P1 对 P0 账本的无重排继承、41 个新增字、
53 个统一重绘汉字、650 个合法 Shift-JIS 安全候选与 86 个 raw-trail
可寻址空隙的分栏统计、490 条零缺字和 `not_tested` 运行边界。
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
