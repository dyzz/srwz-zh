# macOS 工具链探索与后续路线

本文记录 2026-07-24 在 macOS arm64 上完成的只读探索和 clean-room 工具实施。
所有游戏文件、
汇编副本、Ghidra 工程和工具源码都位于被 Git 忽略的 `work/`；没有执行
`SRWZ.exe`、`SRWZ.dll`、`CompressTool.exe`、Wine 或 Mono，也没有修改相邻
上游仓库。

## 已验证基线

### clean-room 数据工具

- `python3 tools/verify_codec_samples.py`：`STAGE.BIN` 和 0、1、2 号样本哈希全部通过。
- `python3 tools/scan_stage_streams.py --force`：真实 `STAGE.BIN` 共 205 段，
  205 段解码成功、0 段失败；声明解码总量 11,687,504 字节，尾部填充
  1,478 字节且全部为零。
- `python3 tools/validate_srwz_encoder.py --strategy greedy --force`：STAGE、
  COMPDATA、MTV_PROS 和 VT1 共 232 条真实可解码流全部重编码往返成功。
- `python3 tools/export_srwz_corpus.py --force`：导出 94,189 条稳定语料；全部
  日文文本经严格序列化后可无损解码。
- `python3 tools/analyze_srwz_font.py --force`：确认 decoded 字库包含 4,480 个
  `24×24/4-bpp` glyph；候选变更落在 glyph 167..286，其中 100 个 glyph
  实际改变；并从原版 SLPS 解析普通公式和 229 项扩展表，确认固定码表中
  3,704 个码值有静态 glyph 映射。
- `python3 tools/render_srwz_font.py --force`：按确认的 288-byte glyph 格式
  渲染出可辨认的完整候选 ASCII 表。
- `python3 tools/render_srwz_font.py --source original --all-mapped ...`：
  渲染 3,704 项原版受支持码位，并生成逐格 code/字符/glyph index 元数据。
- `python3 tools/validate_srwz_archive_rebuild.py --force`：真实 STAGE 205 块和
  MTV_PROS 14 块重建后 decoded 内容全部一致；MTV_PROS 的 SLPS offset 表
  内存写回后可精确重读。

### macOS 原生 armips

armips 使用官方 MIT 许可源码构建，没有执行上游的 Windows 二进制：

| 构建 | 源码提交 | 本机结果 |
| --- | --- | --- |
| 与上游 Windows 文件时间最接近的版本 | `a8d71f0f279eb0d30ecf6af51473b66ae0cf8e8d`，2023-09-21 | CTest 1/1 通过 |
| 当前官方源码 | `2d7f351e640ec260b43943f07a00c57211940378`，2026-07-07 | CTest 1/1 通过 |

两版原生 armips 分别在原版文件副本上汇编 `main.asm` 和 `kuro_stage.asm`，
两组输出都逐字节一致。由此确认当前 macOS 不缺 ASM 汇编能力；后续仍应固定
源码提交并记录许可证、构建命令和工具哈希。

### 上游补丁行为审计

| 文件 | 原版 SHA-256 | 汇编后 SHA-256 | 尺寸 | 实际改变 |
| --- | --- | --- | ---: | ---: |
| `SLPS_258.87` | `6c4c81c4e5aa3db1f52d70b8183ce11c01fc6b265ae4d53fa4d6a657c5019b50` | `ca465f4498720f8df29e425ad1e086d75773389d26f155c22d23b9b1f92011a6` | 3,471,624 | 1,573 字节 |
| `KVPDATA.BIN` | `39caf7f108b6f98226d9bd5860fc6287389e5ba69a69f3e443434ccec55c5e2a` | `1cb263b7cd08a4a393ef38eae58470914696cb77a83112cff4535b82486629bd` | 239,664 | 4 字节 |

`kuro_stage.asm` 声明写入 5 个 `0xFF`，其中 `0xBDCD13` 原本已经是 `0xFF`，
所以二进制差异只有 4 字节。两份输出都保持原尺寸。

`main.asm` 共包含 20 个实际启用的 ASM 文件。逐文件汇编后，所有独立差异的并集
与最终输出的 1,573 个差异字节完全一致。发现两类顺序依赖：

- `menu_agil.asm` 与 `menu_stats.asm` 内容逐字节相同，属于重复包含。
- `menu_search.asm` 和随后包含的 `menu_search_skills_select.asm` 都写
  `0x37180C`；前者写 `0x0C`，后者最终覆盖为 `0x13`。

中文工程不能隐式依赖 include 顺序。未来补丁必须为每一处写入声明唯一所有者，
或显式登记允许覆盖及最终值。

### `SLPS_258.87` 布局与代码窗口

该文件是 ELF32、小端、R5900/MIPS III，入口 `0x100008`。主可加载段的文件偏移
与虚拟地址满足：

```text
file_offset = virtual_address - 0x000FE580
```

上游新增代码写在 `0x3F5820..0x3F5AC3`，共 676 字节。原版文件中的更大连续
零区是 `0x3F575C..0x3F72A7`，但不能把整段视为代码洞：

- `0x3F5800` 是一个 24 字节运行时结构，原程序会清零到 `0x3F5817`；
- 新代码从 `0x3F5820` 开始，与该结构末尾保留 8 字节间隔；
- 新代码窗口内部未发现原版静态入引用；
- 下一处已引用数据块从 `0x3F6400` 开始。

因此只能把精确的 `0x3F5820..0x3F5AC3` 作为已观察窗口，并用原始字节、
边界和引用检查保护它；不能推广为整段零区都可分配。

补丁涉及的三个主要原版函数入口可由 R5900 反汇编确认：

- `0x139B00`：字符串长度/字符扫描路径，改写点为 `0x139B78` 和 `0x139BE8`；
- `0x13A290`：文本绘制路径，ASCII 钩子位于 `0x13A968`；
- `0x38FF80`：武器信息界面路径，改写点为 `0x390290` 和 `0x390460`。

Ghidra 12.1.2 会按 ELF 标志错误地自动选择 MIPS Release 6。正确的研究基线是
强制使用 `MIPS:LE:64:64-32addr` 和 `o32`。Ghidra 仍不能完整识别少量 R5900
专有指令，因此关键地址必须同时用
`mipsel-linux-gnu-objdump -m mips:5900` 复核。

## 当前工具状态

已经可用：

- Python 3.9、7-Zip、CMake、Ninja；
- GNU Binutils 2.46.1 的 `mipsel-linux-gnu-*` 工具；
- Ghidra 12.1.2 与 OpenJDK 21；
- 从 MIT 许可官方源码构建的 macOS arm64 armips；
- 从 GPL-2.0 官方源码固定构建的 `mkps2iso`/`dumps2iso v1.1.1`。

当前系统 Python 没有安装上游整套 `lxml`、`pandas`、`pycdlib`、`tqdm`、
`pyjson5` 和 `numpy`。clean-room 解码器及现有测试不需要它们；只有开始迁移
旧 XML/ISO 总流水线时才应在项目专用虚拟环境中安装。

`xorriso`、`xdelta3`、`bsdiff` 当前也未安装。`mkps2iso` 已满足 PS2 DVD
回包；前者不再阻塞。`xdelta3`/`bsdiff` 只在最终发布不携带原版数据的补丁时
再选型。上游纯 Python ISO 重建器只作行为参考，不复制或执行。

## 后续实施顺序

### P0：固定可重复工具链（已完成）

1. `config/toolchain/armips.lock.json` 已记录官方仓库、MIT 许可证、两个固定
   提交、提交时间和当前 macOS arm64 预期构建哈希。
2. `tools/check_armips_toolchain.py` 已实现本机 source-only bootstrap/check；
   缺源码时只有显式 `--bootstrap-missing` 才会克隆固定官方仓库，从不查找或
   执行上游 Windows 二进制。
3. `config/patches/upstream-asm-audit.json`、`tools/audit_binary_patch.py`
   和 `tools/srwz/patch_audit.py` 已固定输入/输出 SHA-256、尺寸、精确差异
   offset 集合、差异位置的原始/结果字节摘要、每个写入所有者、允许区间和两处
   显式覆盖。

2026-07-24 验证结果：

- `reference_2023` 两次构建均为
  `7c7554f2b9712cc63604a0e6da189dd52a9029cd4e6a340c0d73ae6617af4787`；
- `selected` 两次构建均为
  `386fb58a03e53f6f67ef6c027dde85c11b72bc98c1d8f702d7797aaf97730b5c`；
- 四次官方 CTest 均为 1/1 通过；
- 两版对 `main.asm` 的输出均为
  `ca465f4498720f8df29e425ad1e086d75773389d26f155c22d23b9b1f92011a6`，
  对 `kuro_stage.asm` 的输出均为
  `1cb263b7cd08a4a393ef38eae58470914696cb77a83112cff4535b82486629bd`；
- 未知输入、越界写入、隐式覆盖、所有者并集不等于最终差异和文件扩容均有
  单元测试并立即失败。

完整复验命令：

```bash
python3 tools/check_armips_toolchain.py --force
# 以下命令仅复核已保留的 work/research/patch-audit 研究产物
python3 tools/audit_binary_patch.py --force
```

第一条命令自身已经在临时目录中逐 owner 重跑并完成全部补丁审计；第二条只是
给保留研究产物时使用的独立复核入口。

### P1：独立建立中文 canary 的运行时补丁（字库解压运行验证已完成）

1. 不复制无许可证 ASM；依据原版反汇编和已记录行为，独立定义中文项目需要的
   最小钩子。
2. 先标注 `0x139B00`、`0x13A290` 和字体/字宽数据引用，确认每个寄存器、
   delay slot、返回地址和调用约定。
3. 选择一个菜单标签，生成只包含其字符的最小中文字库和稳定码位。
4. 只生成 `SLPS`、字体和数据文件的本地副本；本阶段仍不重建 ISO。

当前第一步采用更小的无 hook 路线：`0x987E/0x987F` 已由原版双字节解析器和
普通 glyph 公式支持，所以没有修改任何指令，也没有使用上游 ASM。Start 后
`SELECT SCENARIO` 上项说明中的 `本編` 已等长替换为 `测试`；VT1 第 2 段
只改变 glyph 4478/4479，其他 13 个 chunk 保持压缩字节完全一致。
PCSX2/PINE 已确认游戏内完整 1,290,240-byte 解压字库和开场文本内存与构建
预期一致，并保存了 `ゲーム测试をプレイします。` 的实际渲染截图。详细证据和限制见
`STATIC_CANARY.md` 与 `ISO_BUILD_AND_PCSX2.md`。

完成门：

- 每个钩子有原版指令前像、反汇编后像和允许差异清单；
- 字库、码表和宽度表可确定性重建；
- 缺字、码位冲突、文本池溢出和补丁窗口冲突由静态测试拦截。

### P2：实现 clean-room 编码与归档回包

编码器核心、通用 archive 重建、STAGE/MTV_PROS 归档 writer 和 MTV_PROS
定长文本 writer 已完成真实 dry-run。

1. 已从验证后的格式契约实现确定性 `literal` 和 `greedy` 编码，不移植
   Windows 工具或无许可证实现。
2. 已增加 `decode(encode(data)) == data`、边界、overlap、坏流和确定性测试。
3. 已对 232 条真实流做内存重编码验证；STAGE/MTV_PROS 已进一步完成归档级
   offset、alignment 和逐块回解验证。新编码的 539,875 个 block 没有零
   literal 或非最终零 match block。
4. E2 已实现 STAGE allocation/arena、SLPS/COMPDATA 文本池、HB offset
   前像和 VT1 第 2 段 writer；文本池普通 pointer 与 MIPS HI/LO 已有合成门禁。
5. E3 将登记真实批量池区并扩展全量 STAGE/VT1 policy；writer 仍只返回独立
   component bytes 和 metadata，由 ISO 层负责最终组装。

### P3：ISO 重建与运行验证（打包链和游戏内解压验证已完成）

1. 第一版 `mkisofs 3.02a09` 镜像虽通过成员和 UDF 静态检查，但 PCSX2
   v2.6.3 将其误判为 CD，载入 ELF 后发生 `pc=0/4` TLB 循环并导致宿主
   崩溃；该路线已淘汰。
2. 已固定 GPL-2.0 `mkps2iso v1.1.1` 提交
   `f9a3dea18b67dc5f10093e72114a16283d277af0`，在 macOS 从源码构建。
3. 新镜像同步生成 ISO9660/UDF，保留 66 项顺序、原始 gap、VT1 之前 LBA
   和 10,240-sector 尾部 dummy；64 项未替换内容及独立 UDF 读取通过。
4. 原文件往返对照与 canary 都被 PCSX2 识别为 DVD。当前可见 canary 完成
   ELF/IOP/NTSC 初始化并运行 256 秒，无 TLB miss 或宿主崩溃。
5. 旧 canary 的 `pc=0x001C6DE8` TLB 已定位为零 literal count 触发游戏
   post-tested copy loop 下溢；新版编码器已禁止该语法并合并连续 match。
6. PINE 已读取游戏实际解压后的完整字库和开场文本，尺寸、字节和 SHA-256
   均与预期一致；菜单 `测试` 字形已实际截图。战斗和存档仍需运行验证。

完整调研和证据见 `ISO_TOOLCHAIN_RESEARCH.md` 与
`ISO_BUILD_AND_PCSX2.md`。

### P4：发布补丁

在工具链、编码器、ISO 和运行验证均稳定后，再选择并安装 `xdelta3` 或其他
不携带原版数据的补丁格式，完成许可证、来源、复现和双构建一致性检查。

## 暂缓事项

- 不安装完整上游 Python 环境来“跑通一切”；
- 不扩展本项目为通用 ISO 编辑器；PS2 DVD 回包只使用固定 `mkps2iso`
  工作流，正式成员 writer 仍受严格写回契约约束；
- 不迁移全部英文菜单坐标微调；
- 不依赖 Ghidra 全程序伪 C，R5900 指令以 GNU 反汇编和原始字节为准；
- 不修改或在相邻上游仓库中建立临时文件。
