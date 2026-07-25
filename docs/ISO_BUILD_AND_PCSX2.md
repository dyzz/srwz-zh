# Canary ISO 构建与 PCSX2 调试

状态：`mkps2iso v1.1.1` 构建和 PCSX2 v2.6.3/PINE 游戏内字库解压验证已
完成。镜像不触发 TLB miss，完整运行时字库和开场文本与构建预期一致；
`SELECT SCENARIO` 的中文字已完成实际渲染截图。

## 镜像位置

```text
原盘：  rom/srwz.iso
canary：build/iso/canary-menu/srwz-canary.iso
```

当前 canary：

```text
size     3,758,456,832 bytes
sectors  1,835,184
SHA-256  7b1817421d408e39117cd1c335bf79a4872cfc51f2599fd53a995928b130844d
```

它包含与原盘相同的 66 个普通文件：

- `SLPS_258.87` 把开场上项说明中的 `本編` 等长替换为 `测试`，并使用新
  VT1 offset 表；
- `DATA/VT1.BIN` 使用 glyph 4478/4479 的 `测`、`试` 字形；
- 另外 64 个成员的尺寸和 SHA-256 与原盘逐项相同；
- `SYSTEM.CNF` byte-exact；
- ISO9660 和 UDF 两套目录均为 `NSR02`，独立 UDF 读取的四个关键成员哈希
  正确；
- 文件顺序不变，`DATA/VT1.BIN` 及之前的文件保留原 LBA；
- 扩大的 VT1 占用多 50 sectors，从 `DATA/STAGE.BIN` 起的 5 个成员统一
  后移 50 sectors；
- 原盘的主要 gap 和末尾 10,240-sector dummy 得到保留。

## 构建工具

正式后端为 GPL-2.0 的 `mkps2iso v1.1.1`：

```text
repository  https://github.com/N4gtan/mkps2iso.git
tag         v1.1.1
commit      f9a3dea18b67dc5f10093e72114a16283d277af0
```

它是 PS2 DVD/ISO9660/UDF 专用工具。旧 `mkisofs` 产物虽然文件内容正确，
但根目录 data length 恰好为 2048，PCSX2 v2.6.3 因历史兼容判定将其识别
成 CD，随后发生错误扇区读取和宿主崩溃。完整比较见
`docs/ISO_TOOLCHAIN_RESEARCH.md`。

工具源码和构建结果只写入被 Git 忽略的 `work/toolchain/`：

```bash
python3 tools/bootstrap_mkps2iso.py
```

bootstrap 验证完整 commit 和两个可执行文件的版本行。它需要本机已有
Git、CMake 和 Apple Clang；不执行任何 Windows、Wine 或 Mono 工具。

## 重新构建

先生成两个 canary 成员，再生成 ISO：

```bash
python3 tools/fetch_canary_font.py
python3 tools/build_static_canary.py --force
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_canary_iso.py
```

首次构建用 `dumps2iso` 从原盘提取 66 个成员、layout XML 和 24 KiB boot
logo 到：

```text
work/build/canary-menu/iso/original/
```

后续构建复用该缓存并建立 hardlink staging tree。重新解析原盘：

```bash
python3 tools/build_canary_iso.py --refresh-extraction
```

构建器 fail-closed 检查：

- 原盘尺寸、SHA-256、成员数、ISO9660/UDF 特征；
- `mkps2iso`/`dumps2iso` v1.1.1 和固定源码 commit；
- 原盘提取缓存的 66 个成员逐项 byte-exact；
- 两个替换成员的尺寸和 SHA-256；
- 输出路径集合、数据顺序和固定 LBA shift；
- 根目录长度 960，按 PCSX2 v2.6.3 规则必须判定为 DVD；
- 64 个未替换成员、两个替换成员和 `SYSTEM.CNF`；
- 7-Zip 独立 UDF 读取的 `SYSTEM.CNF`、SLPS、VT1 和 STAGE；
- 固定成员摘要、输出尺寸和整个 ISO SHA-256。

构建报告：

```text
build/iso/canary-menu/iso-validation.json
```

## PCSX2/PINE 游戏内解压结果

使用本机 PCSX2 v2.6.3：

```text
-portable -nogui -fastboot -nofullscreen
```

原文件 `mkps2iso` 往返对照运行 13 秒：

- `Image type = DVD`；
- ELF CRC `321C5C3B`；
- IOP 模块和 NTSC 帧循环正常；
- 无 TLB miss、无新 crash report。

当前开场可见 canary 运行 256 秒：

- `Image type = DVD`；
- ELF CRC `9F0B1015`，entry `0x00100008`；
- 完成 IOP 模块加载并进入 59.94 Hz NTSC 帧循环；
- 日志中没有 TLB miss；
- PCSX2 正常响应 Ctrl-C 并退出，没有新宿主 crash report。

PINE 进一步读取了游戏实际使用的解压目标：

- 游戏 ID `SLPS-25887`，读取前后状态均为 Running；
- 原版解压 core `0x001C6D70` 和 literal loop `0x001C6DE8` 的指令字与
  静态反汇编一致；
- 字库目标指针为 `0x009AE610`，尺寸为 1,290,240；
- 完整目标缓冲区 SHA-256 为
  `cc44fa82d1581c3eb1c5852d017efbcbe8e454d4cbd9f374688c408fb236a119`，
  与构建前修改字库完全一致。
- 开场说明位于 `0x0043A2EA`，27 字节运行时 SHA-256 为
  `d672e7dab676be4a323ae16efe42e313966e61b6cb7889bc9070ff5d14880743`，
  与 `ゲーム测试をプレイします。` 的构建预期完全一致。

命令行键盘映射进入 Start 后的 `SELECT SCENARIO` 并由 PCSX2 自身保存截图：

```text
work/runtime/canary-menu/screenshots/opening-select-scenario-canary.png
```

截图为 1280×960，SHA-256
`d2f02c7d83a0f79f0550e657b77ecba07983d9252430c27e0fd7f512589432e2`。
`测试` 两字完整可见、基线一致，没有挤压、重叠或截断。

运行日志：

```text
work/runtime/canary-menu/logs/pcsx2-original-control.log
work/runtime/canary-menu/logs/pcsx2-mkps2iso-roundtrip-control.log
work/runtime/canary-menu/logs/pcsx2-visible-opening-canary.log
work/runtime/canary-menu/pine/font-runtime-validation.json
```

旧 canary 的 TLB 原因已经修正：旧 greedy 为每个 match 生成独立块，其中
139,993 个块的 literal count 为 0。游戏在 `0x001C6DE8` 使用 post-tested
copy loop，0 会先减成 `0xFFFFFFFF` 再继续复制。先前“仅因 980,561-byte
输入跨过 32 MiB”的推断已被运行时存档、反汇编和块统计取代。新版编码器把
一个非空 literal 后的连续 match 合并，新字库流为 702,899 字节且没有零
literal block。

当前 runtime 结论为：

```text
DVD 识别 + ELF/IOP/视频初始化 + 完整字库哈希一致
+ 开场文本内存一致 + SELECT SCENARIO 实际截图 + 无 TLB
```

尚未证明：

- 存档、战斗和长时间流程正常。

PINE 复验（需先按上述参数启动当前 canary）：

```bash
python3 tools/verify_pcsx2_font_runtime.py --force
```

## macOS 安装 PCSX2

Homebrew：

```bash
brew install --cask pcsx2
open -a PCSX2
```

也可使用 [PCSX2 官方下载页](https://pcsx2.net/downloads/)。Apple Silicon
当前通过 Rosetta 2 运行；需要时：

```bash
softwareupdate --install-rosetta --agree-to-license
```

PCSX2 必须使用从自己合法持有的 PS2 主机导出的 BIOS。官方步骤：
[Dumping BIOS](https://pcsx2.net/docs/setup/bios/)。

将以下目录加入 Game List：

```text
/Users/nate/Super-Robot-Wars-Z/srwz-zh/build/iso/canary-menu
```

启动 `srwz-canary.iso`，不要再使用旧的 `srwz-canary-mkps2iso.iso` 或
`srwz-roundtrip-mkps2iso.iso` 研究副本。

## 调试器和符号

启用：

```text
Tools -> Show Advanced Settings
Debug -> Open Debugger
```

选择 `R5900` 调试 EE 主 CPU；`R3000` 是 IOP。仓库提供：

```text
debug/srwz-canary.sym
```

关键标签：

| 地址 | 标签 | 用途 |
| --- | --- | --- |
| `0x0013A5F8` | `srwz_text_decode_pair` | 组合双字节 code |
| `0x0013A898` | `srwz_glyph_resolver` | code → glyph 解析 |
| `0x0013C5C0` | `srwz_glyph_copy` | 复制 288-byte glyph |
| `0x0043A2EA` | `srwz_canary_opening_description` | 完整 27-byte 开场说明 |
| `0x0043A2F0` | `srwz_canary_opening_test_characters` | `98 7E 98 7F` |

当前开场验证：

1. 当前 canary 已进入 Start 后的 `SELECT SCENARIO`；
2. PINE 已确认完整开场字符串与构建预期一致；
3. PINE 已确认运行时字库包含固定 glyph 4478/4479；
4. 截图已确认菜单显示 `测试`、两字可见且无错位。

PCSX2 用于回答运行时实际读取与执行路径；Ghidra/objdump 用于静态交叉引用、
函数边界和反汇编。两类证据需要交叉验证。
