# 测试范围

当前单元测试统一位于 `tests/test_*.py`，按被测模块命名。编码、布局、
round-trip 和 PINE 协议均已落到可自动运行的测试文件，不再保留空的分类
占位目录。PCSX2 正常流程和截图属于独立运行证据，记录在 manifest 和
`docs/BUILD_AND_RUNTIME.md`。

静态测试通过不能替代运行验证；涉及渲染和流程的结论必须有对应运行记录。
`test_pcsx2_boot_smoke.py` 固定 DVD／ELF／TLB 日志解析和证据边界；
`test_pcsx2_session.py` 固定 portable 会话不接触系统 memory card、精确
ISO／PCSX2／INI 输入锁、候选存档的 exploratory 边界、savestate＋配套
card snapshot 收据、`-statefile` 重载计划、输入漂移失败和稳定日志／截图
回收；savestate 收据只能声明 `acceleration_only`；
`test_ui_iso_incremental.py` 强制实读当前六级 ISO、构建报告、PINE receipt
和日志，只允许晋级 `first-five-noncompdata-ui`。已经清理、但可由配置重建
的旧大 ISO 未物化时，其历史 ISO 重读用例明确 skip；对应 component 与
manifest 测试仍执行。

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
`maximum` 压缩组合的确定性／完整回解／游戏 block 语法，以及 armips 来源锁
和补丁差异/覆盖失败门：

`test_maximum_match_accelerator.py` 在临时目录编译独立 C 加速器，并要求其
distance/length/gain table 与纯 Python fallback 逐项一致；没有 clang 时明确
skip，不把本地 `work/` 动态库当作测试前提。

`test_rust_compressor.py` 通过正式 build helper 构建仓库自有 Rust 压缩器，
用 Python 严格解码器检查确定性、suffix 写回，并在本地原始素材存在时要求
标题 VT1 修改块压入原 468,320 字节槽位。

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

除当前增量 ISO 审计和显式 ISO 集成测试外，单元测试不读取大镜像；测试不会
运行任何上游 Windows 二进制。真实编码器验证单独运行：

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
`test_ui_p4_intermission_candidate.py` 固定 P4 从 P3 前像晋级两组 24 条
决定、6 条 no-op、18 条／30 target 写入、408 字节／38 段修改、P3
零重叠和三个非 SLPS 成员 byte-exact；
`test_ui_p4_test_candidate.py` 与 `test_ui_p4_test_candidate_iso.py` 固定
P4／前五关／atlas 的 7 成员所有权、完整复建、59 个未替换 ISO 成员、
独立 UDF 回读、精确镜像哈希和运行未验收边界；
`test_ui_p5_battle_menus_candidate.py` 固定 P5 从 P4 前像晋级四组 38 条
决定、5 条 no-op、33 条／37 target 写入、1,024 字节／60 段修改、P4
零重叠和三个非 SLPS 成员 byte-exact；
`test_ui_p5_test_candidate.py` 与 `test_ui_p5_test_candidate_iso.py` 固定
P5／前五关／atlas 的 7 成员所有权、完整复建、59 个未替换 ISO 成员、
独立 UDF 回读、精确镜像哈希和运行未验收边界；
`test_ui_p6_deployment_candidate.py` 固定 P6 从 P5 前像晋级出击选择组的
16 条决定、13 条 no-op、3 条／3 target 写入、44 字节／5 段修改、P5
零重叠和三个非 SLPS 成员 byte-exact；
`test_ui_p6_test_candidate.py` 与 `test_ui_p6_test_candidate_iso.py` 固定
P6／前五关／atlas 的 7 成员所有权、完整复建、59 个未替换 ISO 成员、
独立 UDF 回读、精确镜像哈希和运行未验收边界；
`test_ui_p7_embedded_font.py` 固定 P7 对 P2 字库账本的无重排继承、七个
allocation、四个统一重绘字形、93 条文本零 renderer 缺字与 12 槽余量；
`test_ui_p7_embedded_font_groups_candidate.py` 固定五组 93 条决定、20 条
no-op、73 条／86 target 写入、VT1 只替换字体 chunk 2、其余 13 个 chunk
byte-exact，以及字体 offset／文本／P6 core 三方零冲突；
`test_ui_p7_test_candidate.py` 与 `test_ui_p7_test_candidate_iso.py` 固定
P7／前五关／atlas 的 7 成员所有权、59 个未替换 ISO 成员、`+7/+43` LBA
位移、独立 UDF 回读、精确镜像哈希和运行未验收边界；
`test_ui_p8_remaining_user_facing_candidate.py` 固定余下四个纯玩家可见
分区的 59 条决定、19 条 no-op、40 条／47 target 写入和 418 字节／61 段
有界修改；`test_ui_p8_test_candidate.py` 与
`test_ui_p8_test_candidate_iso.py` 固定 P8 7 成员组合、精确 ISO 哈希及运行
未验收边界；
`test_ui_p9_mixed_user_facing_subset_candidate.py` 固定两个混合组的 9 条
玩家标签、34 个 target、174 字节／36 段修改和 13 条明确排除项；
`test_ui_p9_test_candidate.py` 与 `test_ui_p9_test_candidate_iso.py` 固定
P9 7 成员组合、精确 ISO 哈希及运行未验收边界；
`test_ui_database_selection.py` 固定 P10 从 1,250 条数据库中选择五家族
1,113 条（含全部 711 个武器名）、延期 137 条、四项受保护排除及定长／术语门；
`test_ui_p10_database_font.py` 固定 85 个 allocation、97 个统一重绘字形、
四项受审同码位替换、数据库／前五话标题／双主人公简介 renderer 零缺字和
2,109 个剩余候选槽；
`test_ui_p10_database_candidate.py` 固定 SLPS 233 条、COMPDATA 880 条选择、
全部 348 个 pointer-backed 机体显示名、
preserve-prefix 回解、指针／非目标字节与非字体 chunk 不变；
`test_ui_p10_test_candidate.py` 与 `test_ui_p10_test_candidate_iso.py` 固定
P10 7 成员组合、59 个未替换成员、零 LBA 位移、独立 UDF 回读、精确
镜像哈希、boot smoke 通过及逐屏运行未验收边界；
`test_full_chinese_font_plan.py` 固定 4,480 格 standard resolver 双射、95 个
ASCII 保留槽、从 glyph 287 起连续的 4,193 格最终中文容量、当前 1,899 字符
需求／2,294 格余量及
全量 profile 仍需运行 canary 的边界；
`test_ui_runtime_matrix.py` 固定 14 类基础场景、十八个整组扩展场景、两个逐条
子集和五个数据库家族的完整去向、47 个逐屏用例、
001～005 五个独立开场序列、世界史起点／中点／终点、五张中文 atlas 候选的
截图＋texture-delta 双门，以及七份尚未取得的原生
memory-card fixture；旧 `.p2s`
savestate 不会自动替代 `.ps2`＋SHA-256 证据；
`test_ui_runtime_evidence.py` 固定 case plan、精确 ISO、PINE Running、
fresh-process、DVD／ELF／零 TLB 日志、原生 memory-card 哈希、截图收据和
矩阵 receipt 晋级边界；草稿、失败断言或没有提交 receipt 的 `passed` 状态
必须失败；`test_ui_runtime_host.py` 固定宿主预检必须锁定当前四个尚未执行的
route-ready 用例和非 COMPDATA 晋级 ISO，并在 arm64 主机使用 x86_64
PCSX2、但 Rosetta 缺失时 fail closed；宿主预检本身不改变任何用例运行状态；
`test_ui_runtime_fixtures.py` 固定 528-byte page 卡格式、全 `0xFF` 空卡、
`SLPS-25887` 候选标记、重复哈希、七类 fixture 的 34 个阻塞用例优先级，
并禁止仅凭发现候选卡自动晋级；
`test_inject_srwz_tim2.py` 固定
archive/report 输出边界；`test_mapname.py` 固定 Shift-JIS/NUL/全零 padding。
真实图片清单、MAPNAME 聚合计数、PCSX2 图片 canary 的 351-pixel 精确 RGBA
替换，以及标题四项中文的两种光标状态/运行时纹理一致性由 manifest 测试固定。
`test_ui_p0_fixed_slps.py` 与 `test_ui_p0_fixed_compdata.py` 另固定 P0
fixed-span 选择 ratchet、指针／非目标字节不变、组件哈希和压缩回解；两者均
明确要求运行状态仍为 `not_tested`。
`test_compdata_incremental.py` 固定单场景 COMPDATA 选择、原始压缩流不变的
最小 71→72 sector 零尾控制，以及 71-sector 重编码按钮组件启动通过、
72-sector 纯 LBA 控制和完整 P0 组件以同一 `0x1c6ea0/0x02000000` TLB
签名失败的因果清单。
`test_single_iso_candidate.py` 固定单候选 ISO 工作流：已有镜像时默认拒绝继续
构建，只有显式替换才删除旧候选；构建后只能删除精确的
`work/build/<profile>/iso/{original,staging}` 整盘工作树；同时固定 SLPS
offset 表与 VT1 字体段的构建前兼容门，错误配对必须在删除当前 ISO 之前失败。
`test_display_names.py` 固定 COMPDATA 人物／机体表几何、稳定 ID、指针归并、
零 padding 和 hash-only 提交投影；`test_display_name_coverage.py` 固定
researched 精确源词的 1,262 字段选择、1,166 个当前字库直通项、96 个缺字
项／21 个编码缺字、28 个 renderer 缺字、其中 4 个退役 assignment 复用与
24 个活跃新 allocation、5 个误分配 ASCII 槽退休保留、29 个统一重绘汉字、
19 个预计剩余槽、零 projected
allocation 溢出、2,800 行审核 TSV 和提交清单不含原始日文；
`test_ui_p0_display_names.py` 固定开场
45 个名称决策、原 allocation 写回、人物 ID／机体指针／非目标字节不变和
压缩流精确回解，并要求 ISO／运行状态仍未测试。
`test_ui_p2_display_name_font.py` 固定 P2 对 P1 账本的无重排继承、24 个新增
assignment、4 个退役 assignment 复用、5 个 ASCII 槽退休保留、29 个重绘项、1,262 个字段零
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
