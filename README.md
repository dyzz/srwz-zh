# Super Robot Wars Z 中文化工程

本仓库用于从日文原版开始建立《超级机器人大战 Z》的独立中文化工具链、译文、字体、补丁和验证记录。

当前状态：clean-room 数据、字库、写回、ISO 和运行验证链已经打通；已登记
本地日版 ISO 基线并生成可见的两字 canary 测试镜像，但尚未生成或发布正式
游戏补丁。

已完成第一批基础设施迁移：可以从 ISO 只读提取指定成员、按固定 offset
切分 `STAGE.BIN`，并使用严格的 clean-room 解码器解析菜单、数据库、剧情和摘要。
当前 94,189 条文本可按结构逐条对照固定上游 XML，结果完全一致。可复用的上游
Python 源码也已按固定提交保存在 `vendor/upstream-python/`。

当前还完成了以下写回和构建基础：

- VT1 字体段的 `24×24/4-bpp` glyph 读写，以及 3,704 项经原版 SLPS
  普通/扩展分支验证的 code→glyph 映射；
- 94,189 条稳定语料导出、严格文本序列化和带前像/所有者/边界检查的写回原语；
- 确定性的 clean-room 压缩编码器，已在 232 条真实可解码流上全部往返成功。
- 固定官方 MIT armips 源码的 macOS 原生可重复构建，以及逐写入所有者、原始
  字节摘要、允许区间和显式覆盖校验的二进制补丁审计。
- 不改运行时代码的两字简体中文静态 canary：使用原版普通 glyph 路径和两个
  固定空白槽位，把开场 `SELECT SCENARIO` 上项说明中的 `本編` 等长替换为
  `测试`，并确定性生成 VT1 和 SLPS 副本。

STAGE 205 块和 MTV_PROS 14 块也已完成内存归档重建与 decoded 往返；
MTV_PROS 有定长文本 writer。当前已生成首个 UDF/ISO9660 canary 镜像并完成
逐成员静态校验；PCSX2/PINE 已确认游戏内完整解压字库和开场文本内存均与
构建预期一致，且没有 TLB miss。命令行运行已进入 `SELECT SCENARIO` 并保存
`ゲーム测试をプレイします。` 的实际渲染截图，中文字可见且未挤压或截断。

## 工程边界

- 日文原版是唯一翻译源；现有英文译文只作为参考。
- 不提交原始 ISO、游戏文件、存档或从原版解出的二进制。
- 中文工程拥有独立 Git 历史，不修改上游英文研究仓库。
- 上游逆向成果固定到 `config/upstream.lock.json` 中记录的提交。
- 允许复用固定版本的上游源码；保留来源提交和差异，通用修复计划贡献回上游。
- 字库、编码表、补丁和构建产物必须可以从已记录的源文件确定性生成。

## 目录

```text
config/             上游版本和项目配置
corpus/ja/          不可修改的日文语料基准
corpus/zh/          中文译文
corpus/glossary/    作品、人物、机体、招式和系统术语
docs/               架构、流程和里程碑
font/source/        有明确许可证的字体及许可证记录
font/generated/     生成的字库文件，不进入 Git
manifests/          输入、字符映射和构建哈希清单
patches/asm/        中文运行时和 UI 补丁
tools/              clean-room 核心库、薄 CLI 和工具归属说明
tests/              编码、布局、round-trip 和运行验证
evidence/           可公开的截图和测试记录
rom/                用户合法持有的不可变原版输入，不进入 Git
work/               提取、按 profile 隔离的中间态和运行证据，不进入 Git
build/              按 profile 隔离的最终 ISO/补丁产物，不进入 Git
vendor/             固定提交的上游源码快照
```

## 第一阶段

1. 固定并验证原版游戏版本及关键文件哈希。
2. 复现无修改的提取、回包和启动流程。
3. 建立日文语料清单和稳定条目 ID。
4. 用一个菜单、一条数据库文本和一段剧情完成中文 canary。
5. 建立确定性的中文字库、编码和中文断行流水线。

详细计划见 `docs/ROADMAP.md`。

文档入口见 `docs/README.md`；代码模块、命令入口和第三方依赖边界见
`tools/README.md`。

## 准备压缩流样本

以下命令不会调用上游的 Windows 工具：

```bash
python3 tools/extract_iso_member.py DATA/STAGE.BIN
python3 tools/split_stage_archive.py --index 0 --index 1 --index 2
python3 tools/verify_codec_samples.py
```

第一条命令只通过 `7z` 提取明确指定的 ISO 成员；第二条命令依据 `config/stage-offsets.json` 做 byte-range 切分。所有输出都在被 Git 忽略的 `work/` 下。

上游资源评估见 `docs/UPSTREAM_REUSE.md`，压缩格式研究边界见 `docs/SRWZ_COMPRESSION.md`。
完整数据覆盖和上游对照见 `docs/SRWZ_DATA_PARSING.md`。

## 检查压缩流

诊断单个 chunk，不保存解码后的游戏数据：

```bash
python3 tools/inspect_srwz_stream.py work/stage/compressed/000.bin
```

扫描原版 `STAGE.BIN` 的全部 205 个 chunk，并将只含 metadata 和哈希的完整结果
写入已忽略的 `work/stage/codec-scan.json`：

```bash
python3 tools/scan_stage_streams.py
```

解析全部汉化相关数据并对照上游 XML：

```bash
python3 tools/parse_srwz_iso_data.py --force
```

导出稳定语料、分析/渲染字体，并验证 clean-room 编码器和归档重建：

```bash
python3 tools/export_srwz_corpus.py --force
python3 tools/analyze_srwz_font.py --force
python3 tools/render_srwz_font.py --force
python3 tools/validate_srwz_encoder.py --strategy greedy --force
python3 tools/validate_srwz_archive_rebuild.py --strategy greedy --force
```

三个阶段的边界和完成门分别见 `docs/FONT_ANALYSIS.md`、
`docs/WRITEBACK_CONTRACT.md` 和 `docs/SRWZ_COMPRESSION.md`。

生成首个静态简体中文 canary：

```bash
python3 tools/validate_build_profile.py
python3 tools/fetch_canary_font.py
python3 tools/build_static_canary.py --force
```

它只写 `work/build/canary-menu/components/`，不修改原版、不重建 ISO，也不运行游戏；具体原理、
指令前像、码位边界和验证结果见 `docs/STATIC_CANARY.md`。当前译文、surface
地址和 `测/试` 字形分配分别来自 `corpus/zh/menu.json`、
`config/surfaces/menu-slps-opening.json` 和
`config/encoding/codebook.json`，由 `canary-menu` profile 统一选择；完整
契约见 `docs/PRODUCTION_PIPELINE.md`。

生成供 PCSX2 验证的 canary ISO：

```bash
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_canary_iso.py
```

输出为被 Git 忽略的
`build/iso/canary-menu/srwz-canary.iso`。构建器逐项验证 64 个未替换
成员和 2 个替换成员，保持原盘成员顺序与 VT1 之前的绝对 LBA，并独立读取
UDF 关键成员。固定工具链调研见 `docs/ISO_TOOLCHAIN_RESEARCH.md`；安装
PCSX2、导入调试符号和运行验证步骤见 `docs/ISO_BUILD_AND_PCSX2.md`。
完整目录所有权见 `docs/ISO_DIRECTORY_LAYOUT.md`。
PCSX2 已启用 PINE 且 canary 正在运行时，可复验游戏内完整字库：

```bash
python3 tools/verify_pcsx2_font_runtime.py --force
```

验证固定 armips 源码、两次干净构建、双版本 ASM 一致性和真实补丁差异：

```bash
python3 tools/check_armips_toolchain.py --force
# 仅在已保留 work/research/patch-audit 研究产物时单独复核：
python3 tools/audit_binary_patch.py --force
```

第一条命令已经包含内存补丁审计；它在 `work/` 内临时构建官方源码、运行其
CTest，并从原版文件副本汇编，不会运行 `armips.exe` 或其他
Windows/Wine/Mono 工具。若本地没有已固定源码，可显式加
`--bootstrap-missing`，该选项只克隆
`https://github.com/Kingcom/armips.git` 的锁定提交。

## 运行静态测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/compare_upstream_snapshot.py
```

## 验证本地原版

需要系统中安装 `7z`。脚本只读访问 ISO，不会提取游戏文件：

```bash
python3 tools/verify_original_disc.py
```

基线记录位于 `manifests/original-disc.json`。
