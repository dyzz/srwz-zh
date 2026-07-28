# Super Robot Wars Z 中文化工程

本仓库用于从日文原版开始建立《超级机器人大战 Z》的独立中文化工具链、译文、字体、补丁和验证记录。

当前状态：clean-room 数据、字库、写回、ISO 和运行验证链已经打通；菜单、
MTV_PROS 摘要和 STAGE 剧情三类中文 canary 已从正式
surface/fixture/codebook/profile 生成，并分别通过静态、PCSX2 运行和画面验证。
系统 UI 的 P0 静态范围另已覆盖 418 条 SLPS 与 44 条 COMPDATA 文本，并由
独立 fixed-span 组件通过离线回读。COMPDATA 动态名称表也已完成全结构解析，
并将开场路线 45 个节子／丹泽尔／托比及巴尔戈拉名称字段写入独立组件；
MTV_PROS 的 28 条世界史文本也已完成 22 格中文断行、段落空行和定长
allocation 审计。该布局仍是 28 条 `draft`；相对当前 P0 字库真实缺 41 个字
（27 个未映射、14 个码表存在但原解析器不可达），三个安全槽仍短缺 38 个。
独立 P1 字库候选现已继承 P0、追加这 41 个字并统一重绘另 53 个原版汉字，
从候选组件重读 490 条 P0＋世界史文本后缺字为零，尚余 48 个
renderer-addressable 候选槽。不过其中 38 个新分配使用非 Shift-JIS 尾字节
空隙：原 SLPS 指令窗口证明可寻址，只有 `0x7F` 类已有单字 canary 运行先例，
`0xFD` 类和整张 P1 候选仍待实机验证。28 条世界史现已进入完整 MTV_PROS
组件；标题四项、462 条 P0 文本、开场 45 个动态名称字段、P1 字库和世界史
也已通过无冲突组合，生成静态验证的 `ui-p1-core` ISO。该镜像尚未绑定当前
环境中的 PCSX2 逐屏证据，也不包含前五关 STAGE；其余人物／机体名和信息页
atlas 同样仍待完成。信息页 `SHIP`、战场 `COMMAND MENU` 与幕间标题现各有
一张隔离映射 canary：组件和单成员、零 LBA 位移 ISO 均已静态锁定，但尚无
截图／texture dump 双证据，因此都不计为正式运行映射或中文 atlas。
尚未生成或发布正式游戏补丁。

翻译生产已进入 v1：28 条世界历史摘要、全部 2,415 条菜单文本、558 条剧情
胜利／败北／SR 条件、全部 8,469 条剧情说话人记录，以及第 001～005 关全部
1,711 条剧情正文已有完整简体中文首轮译稿。菜单部分包括 903 条菜单／系统 UI、122 条
关卡标题、711 条武器名称、382 条原上游未分类文本和 297 条战斗退场台词。
当前合计 13,181 条译文；1,687 个跨作品、系统、人物、机体、技能、精神指令、
强化部件、特殊能力和武器术语已独立登记并逐条引用。说话人批次覆盖 425 个
唯一显示名，340 个新增人物／身份词条单独列出，538 条空白、玩家名或未知身份
槽位显式保留。第 001～005 关正文分别覆盖 288、321、36、469 和 280 个唯一句，新增 112 个
关卡专名，并保留 `$n/$F` 玩家名和原文黑圆点遮蔽结构。第 002 关另对
军械库一号、第二阶段系列、幻象化粒子、Evidence 01、三架被夺机体和脉冲高达
出击系统建立了独立术语决策；第 004 关继续固定 BLOCK WORD、轰击型剪影、
白色基地、阿克西斯、格里普斯、平行世界等交汇剧情术语；第 005 关新增
古连泰沙、杜克·弗里德、骷髅月基地、MidiFO、第二次雅金·杜威攻防战、
PLANT评议会议长、藤泽与骏河湾等独立决定。前五关合计 1,711 条记录、
按关内去重的 1,394 个译文决定（跨关再去重为 1,359 段原文）已经逐句二校并
全部提升为 `reviewed`；“古连泰沙”和
“弗里德星”也已有官方简中依据。用户指定 Biligame 为本切片高达名称口径后，
其中 4 项官方简中异名已显式决定保留当前 Biligame 口径，另 5 项继续作为
人工选择题；所有改名均由术语 ID 传播，没有无记录的字符串替换；
112 项关卡术语中 109 项已完成来源研究，剩余 3 项为 Gunnery Carver
全称、简称和 MidiFO，均保留证据边界与备选方案供人工定名；
固定上游前五关 XML 本身没有英语译文；现有英语稿只按“其他关卡日文完全相同”
建立辅助核对表，不能替代本关日文上下文或官方术语来源；
前五关语言质量门另检查假名残留、结构占位符、引号／括号、混合标点和
24 字符显示行宽、最多 3 行及中文标点禁则，当前硬错误为 0；中文重排把
1,711 条正文从 3,124 行收敛到 2,160 行，三行记录从 395 条降到 4 条；
4 组同源语气或省略句的 14 次语境异译均已逐条写明保留理由；
技术 canary 已移到 `corpus/fixtures/`，不会再被误计为正式翻译。

节子路线前五个 STAGE 块现已形成受限生产候选：1,711 条正文、21 条条件和
101 条实际说话人记录共 1,833 条内容已写回。当前字体候选固定使用
LXGW Neo XiHei Screen：追加式账本共登记 638 个码位，其中 630 个在用、
8 个退役且不复用，另有 12 个安全候选；806 个原字库可达汉字也使用同一字体
重绘，共登记 1,436 个 glyph assignment，其中空格槽为预期 no-op。假名、原有
拉丁字符、既有可达标点以及本切片之外的字形保持原样；前五关实际出现的普通
ASCII 另走双字节 glyph，`$n/$F` 玩家名占位符保持原始运行语义。字形默认以
22pt 栅格化；实机截图确认“班”在 24×24 小字号下视觉偏小，因此只对该字使用
配置锁定的 22.1pt 最小光学校正：只补回取整丢失的一列像素，不增加栅格高度，
码位和 glyph 槽位不变。VT1 保持原大小，最终 ISO
的 66 个成员均保持原 LBA。最终镜像已独立回读
SLPS/HB/STAGE，并逐 ID 复核前五关全部译文；renderer 覆盖审计的缺字、
一字节 ASCII 风险和混合汉字来源均为 0。但这张新候选尚未运行 PCSX2，上一
候选的运行证据不能沿用。第二至第五关也未完整游玩，不能把静态回读称为五关
通关测试。完整边界和哈希见
`manifests/first-five-validation.json`。

已完成第一批基础设施迁移：可以从 ISO 只读提取指定成员、按固定 offset
切分 `STAGE.BIN`，并使用严格的 clean-room 解码器解析菜单、数据库、剧情和摘要。
当前 94,189 条文本可按结构逐条对照固定上游 XML，结果完全一致。可复用的上游
Python 源码也已按固定提交保存在 `vendor/upstream-python/`。
此外，首轮图片/遗漏文本扫描已严格识别 706 个 TIM2 记录、1,146 个 picture，
并新增解析 `MAP/MAPNAME.BIN` 的 195 条固定 Shift-JIS 地图名。外部 TIM2
writer 调查已确定没有候选同时满足当前许可证、原生 macOS CLI 和真实 4-bpp
CLUT fixture。当前已实现严格原位、保留既有 CLUT 的 4-bpp 注入器，以及
固定 VT1 标题记录的 8-bpp index writer。真实 `KVMDATA` chunk 5 no-op
已证明整个 3,335,408-byte 归档 byte-identical；VT1 标题 canary 已完成
重压缩、ISO 回包、PCSX2/PINE 截图和运行时纹理转储验证。坐标级 PSMT8
写回现已把标题四项改为 `开始/读取/继续/资料库`；第一项和第四项选中态均已
实机截图，PCSX2 转储纹理与离线构建预览逐像素一致。

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
MTV_PROS 定长 writer、STAGE allocation/pointer writer 和保留原流前缀的
suffix 重编码已经进入完整 canary 构建。四张 UDF/ISO9660 镜像均保持原盘
3,758,358,528-byte 大小和原成员 LBA；PCSX2/PINE 已确认游戏内完整解压字库，
三条独立 fixture 分别显示菜单 `测试`、世界史 `测试。` 和 Denzel 的两行增长
文本，且日志均无 TLB miss。完整组合镜像还通过菜单、摘要和剧情加载 smoke。

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
corpus/fixtures/    仅用于验证写回/运行链的技术 canary
corpus/releases/    翻译语料版本范围、来源哈希和审核策略
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
`tools/README.md`；提交范围、验证分层和发布前检查见 `CONTRIBUTING.md`。

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
图片资源、地图名和复杂字体边界见 `docs/ASSET_ANALYSIS.md`。

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
python3 tools/review_srwz_translations.py
python3 tools/audit_first_five_language_quality.py --force
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
地址和 `测/试` 字形分配分别来自 `corpus/fixtures/menu-canary.json`、
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

生成 E2 三类 surface 的隔离组件和完整组合镜像：

```bash
python3 tools/build_complete_canary.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/canary-summary-build.json
python3 tools/build_canary_iso.py \
  --config config/iso/canary-story-build.json
python3 tools/build_canary_iso.py \
  --config config/iso/canary-complete-build.json
```

最终组合镜像位于
`build/iso/canary-complete/srwz-canary-complete.iso`；三个独立运行
fixture 和组合 smoke 的 byte-free 记录见
`manifests/canary-complete-validation.json`。

构建已经通过运行时验证的图片 canary：

```bash
python3 tools/build_tim2_runtime_canary.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/image-canary-build.json
```

输出位于
`build/iso/canary-image-vt1-title/srwz-image-canary.iso`；组件、ISO、PCSX2
截图和纹理直方图的 byte-free 验收记录见
`manifests/image-canary-validation.json`。

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
