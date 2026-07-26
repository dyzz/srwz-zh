# PS2 ISO 打包工具链调研

状态：2026-07-24 已完成源码、许可证、macOS 构建、真实 SRWZ 往返和 PCSX2
对照验证。正式 canary 构建后端采用 `mkps2iso v1.1.1`。

## 为什么重新调研

第一版 canary 使用 `cdrtools mkisofs 3.02a09` 从目录树重建 ISO9660/UDF
镜像。66 个成员、内容哈希和 UDF 独立读取都通过，但 PCSX2 v2.6.3 把镜像
识别为 `CD`，载入 ELF 后随即进入 `pc=0/4` 的 TLB 异常循环，并导致 PCSX2
宿主进程崩溃。

PCSX2 v2.6.3 的 `InputIsoFile::tryIsoType()` 对 2048-byte sector 镜像使用
一个历史兼容判定：ISO9660 PVD 根目录 data length 的低 16 位恰好为 2048
时判为 CD，否则判为 DVD。原盘根目录长度为 960；`mkisofs` 输出恰好为
2048。因此这个失败不是字体数据本身造成的，而是通用 ISO 生成器没有复现
PS2 DVD 的卷布局特征。

核对源码：

- <https://github.com/PCSX2/pcsx2/blob/v2.6.3/pcsx2/CDVD/InputIsoFile.cpp>
- 本地只读研究副本位于 `work/research/pcsx2-v2.6.3/`。

## 上游项目的实际做法

相邻上游的调用链为：

```text
tools/python/main.py
  -> SRWZ.pack_* / patch_binaries / update_slps_offsets
  -> SRWZ.build_ps2_iso()
  -> tools/python/isotool.py::rebuild_iso()
```

`isotool.py` 不从空目录树生成文件系统。它：

1. 从原 ISO 保留系统区、ISO/UDF 元数据头和末尾 anchor sector；
2. 根据 `tools/python/files.txt` 给出的 ISO9660 directory-record offset
   和文件顺序，依次写入 `New_files/` 成员；
3. 每个成员按 2048 字节对齐；
4. 改写 ISO9660 directory record 中的双端 LBA 和 size；
5. 将卷对齐到 `0x8000`，可选增加 20 MiB padding；
6. 写回 footer，并更新 PVD volume sector count 与末尾 anchor LBA。

SRWZ 调用使用 `padding=0`。因此上游可以容纳变大的文件，后续成员会向后
移动，并不是只能原位替换。它保留原 PVD 根目录长度，所以不会触发 PCSX2
的 CD 误判。

边界：

- 上游 `isotool.py` 顶部没有可确认的开源许可证，不能复制进本仓库；
- 它扫描 UDF 项来确定保留头部的末端，但实际逐文件改写点来自 ISO9660
  directory record；没有看到同步重建每个 UDF file entry 的逻辑；
- 因此它可以作为行为参考，但不能作为本项目的长期 clean-room 后端。

## 开源方案比较

| 方案 | 许可证/平台 | 能力 | 对 SRWZ 的结论 |
| --- | --- | --- | --- |
| `cdrtools mkisofs` | CDDL-1.0；macOS/Homebrew | 从目录树生成 ISO9660/UDF | 内容正确，但根目录长度 2048 触发 PCSX2 CD 判定；不再作为正式后端 |
| `mkpsxiso` | GPL-2.0；跨平台 | 精确 LBA、XML、PS1 CD/XA/CUE | 工具成熟，但目标是 PlayStation CD，不是 PS2 DVD/UDF |
| `Ps2IsoTools` | MIT；.NET | UDF reader/builder/editor，可替换增长文件 | 只面向 UDF；官方说明 rebuild 会丢失时间元数据且可能占用约 2 倍 ISO RAM，不适合作为当前主链 |
| `mkps2iso` | GPL-2.0；Windows/Linux/macOS | PS2 DVD-5/9、ISO9660/UDF、XML、显式 LBA/空洞、boot logo、CDVDGEN 风格布局 | 与需求完全匹配，采用 v1.1.1 固定提交 |

主要来源：

- `mkps2iso`：<https://github.com/N4gtan/mkps2iso>
- `mkps2iso v1.1.1`：<https://github.com/N4gtan/mkps2iso/releases/tag/v1.1.1>
- `mkpsxiso`：<https://github.com/Lameguy64/mkpsxiso>
- `Ps2IsoTools`：<https://www.nuget.org/packages/Ps2IsoTools>

## `mkps2iso` 真实 SRWZ 验证

固定版本：

```text
repository  https://github.com/N4gtan/mkps2iso.git
tag         v1.1.1
commit      f9a3dea18b67dc5f10093e72114a16283d277af0
license     GPL-2.0-only
```

在当前 macOS 上从源码构建成功。`dumps2iso` 能从原盘解析 66 个文件、12 个
目录、原始文件顺序、两个内部 gap、一个 297,605-sector gap 和末尾
10,240-sector dummy，并导出 24 KiB boot logo。

原文件往返对照：

- 输出被 PCSX2 识别为 DVD；
- ELF CRC 保持 `321C5C3B`；
- IOP 模块和 NTSC 帧循环正常；
- 13 秒 smoke run 无 TLB miss、无宿主崩溃。

canary 构建：

- 输出尺寸 `3,758,358,528` bytes，`1,835,136` sectors；
- 根目录长度 960，PCSX2 判定 DVD；
- 66 个成员路径、顺序完全一致；
- 所有 66 个成员保持原 LBA；扩大的 `DATA/VT1.BIN` 仍落在原 sector
  allocation；
- 64 个未替换成员 byte-exact；
- ISO9660 读取和独立 7-Zip UDF 读取的关键成员哈希一致；
- PCSX2 载入开场可见 canary ELF `CRC 9F0B1015`、完成 IOP 模块加载并进入
  NTSC 帧循环；256 秒运行没有 TLB miss 或宿主崩溃；
- PINE 读取游戏解压后的完整 1,290,240-byte 字库，SHA-256 与构建预期一致。
- PINE 同时确认开场说明字符串在 `0x0043A2EA` 与构建预期逐字节一致；
  命令行进入 `SELECT SCENARIO` 后保存了实际渲染截图。

旧 canary 曾在 `pc=0x001C6DE8` 对 `0x02000000` 产生 TLB miss。进一步读取
故障存档、反汇编游戏 core 和统计旧流后确认：旧流有 139,993 个零 literal
block，而游戏 literal copy 是 post-tested loop；计数 0 会下溢。先前
“较大的 980,561-byte 输入自然跨过 EE RAM 边界”的解释已被此直接证据取代。
当前 599,742-byte suffix 重编码字库流没有零 literal block，并取得游戏内
完整输出哈希。

这些结果说明 ISO 回包链、当前压缩流和开场菜单中文字均已通过对应的运行
验证；战斗、存档和长时间流程仍未覆盖。

## 采用方式

工具源码和构建结果只放在被 Git 忽略的 `work/`：

```bash
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_canary_iso.py
```

bootstrap 会固定 tag、完整 commit 和版本行；不复制上游源码到受版本控制的
项目目录。构建器用 `dumps2iso` 建立原盘布局缓存，替换两个 canary 成员，
再由 `mkps2iso` 同步生成 ISO9660/UDF。它不会执行 Windows 工具、Wine、
Mono 或 PCSX2。
