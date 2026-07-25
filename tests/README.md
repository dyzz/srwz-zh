# 测试范围

当前单元测试统一位于 `tests/test_*.py`，按被测模块命名。编码、布局、
round-trip 和 PINE 协议均已落到可自动运行的测试文件，不再保留空的分类
占位目录。PCSX2 正常流程和截图属于独立运行证据，记录在 manifest 和
`docs/ISO_BUILD_AND_PCSX2.md`。

静态测试通过不能替代运行验证；涉及渲染和流程的结论必须有对应运行记录。

`test_project.py` 固定生产输入层的正向和负向契约：source hash 漂移、中文源
重复日文正文、编辑状态不足、未使用 codebook assignment 和编码结果都会被
检查。`test_canary.py` 另确认旧 canary 配置不再拥有译文/字形事实源，并且
正式 profile 仍生成同一个 E0 golden。

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
真实 ISO 工具构建、镜像构建与 66 项逐成员校验单独运行：

```bash
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_canary_iso.py
```

PCSX2 已启用 PINE 且当前 canary 正在运行时，完整读取游戏解压后的字库并
只保存地址、尺寸和哈希：

```bash
python3 tools/verify_pcsx2_font_runtime.py --force
```
