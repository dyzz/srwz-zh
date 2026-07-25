# LESSONS_LEARNED — 错误路径目录

这份文档沿用参考项目的事故记录方法：不是罗列最终结论，而是记录一个看似合理
的判断怎样被证据推翻，以及哪一道自动门防止它复发。新增条目必须对应真实实验、
失败产物或运行证据；规划中的风险不写成“已学到的教训”。

条目格式：

> **曾以为** → **为什么看似合理** → **如何被推翻** → **事实** → **守门**

---

## A. 压缩和游戏运行语法

### A1. Clean-room round-trip 通过，不等于游戏解压器可运行

- **曾以为：** 只要 `decode(encode(data)) == data`，新 VT1 压缩流就可由游戏
  使用。
- **为什么看似合理：** clean-room 解码器能够严格解出候选流，解码内容和目标
  字库完全一致；旧候选的压缩尺寸变化也提供了一个看似合理的 32 MiB 边界解释。
- **如何被推翻：** PCSX2 在游戏解压器 `0x001C6DE8` 发生 TLB miss；块统计发现
  旧流 175,385 个 block 中有 139,993 个 zero-literal block，第一个位于输入
  offset 48、输出 offset 576。
- **事实：** 游戏 literal/match copy 是 post-tested loop。literal count 为
  0 会先减成 `0xFFFFFFFF` 再失控复制；这是游戏运行语法约束，不是普通
  round-trip 属性。
- **守门：** `tools/srwz/codec.py` 拒绝 zero-literal 和未结束输出前的
  zero-match；单元测试固定故障；greedy 构建还必须通过游戏内完整 decoded-font
  SHA-256。

## B. ISO 容器和模拟器判定

### B1. 成员内容正确，不等于 PS2 DVD 镜像正确

- **曾以为：** 只要重建 ISO 中 66 个成员可读、替换成员哈希正确，通用
  `mkisofs` 输出就可用于 PCSX2。
- **为什么看似合理：** ISO9660/UDF 目录和成员内容都能被静态工具读取，文件级
  diff 没有发现错误。
- **如何被推翻：** PCSX2 v2.6.3 把该镜像识别为 CD，随后错误读取扇区并产生
  宿主崩溃；输出根目录 data length 为 2048，而原盘为 960。
- **事实：** PS2 容器验收包含介质类型、目录形态、成员顺序/LBA、UDF 识别和
  模拟器判定，不能退化为“文件能打开”。
- **守门：** 正式后端固定为 `mkps2iso v1.1.1`；构建器独立验证 66 个成员、
  ISO9660/UDF、根目录 960、DVD 判定、LBA shift 和整镜像 SHA-256；`mkisofs`
  不再是发布后端。

## C. 字库和码位分配

### C1. 空白 glyph 和未引用 code 只是候选，不是安全槽位

- **曾以为：** 原版字形为空、且固定码表/语料没有引用的 code，可以直接当作
  中文容量。
- **为什么看似合理：** 静态扫描得到连续空白 glyph，94,189 条已解析语料没有
  对应 token，码表也没有冲突。
- **如何被推翻：** 静态结果只能说明当前样本没有已知引用；它不能证明所有
  renderer 分支、动态构造文本、存档或未覆盖流程都不会使用这些位置。
- **事实：** “候选”“已分配”“在某个 surface 运行验证”是三种不同状态。当前
  `987E/987F` 只批准给开场菜单的 `测/试`，不能外推为整段安全容量。
- **守门：** `config/encoding/codebook.json` 是唯一分配账本；BuildProfile
  只能选择显式 `assigned` 项；code/glyph/raster/owner 全部固定，冲突扫描、
  运行内存哈希和 surface 截图分别保留。

## D. 工程事实源

### D1. 验证成功的临时 canary 不能继续承担生产数据职责

- **曾以为：** 把 `glyphs`、`source_text`、`replacement_text` 和 offsets 放在
  一个 canary JSON 中，最容易保住已验证结果。
- **为什么看似合理：** 两字纵向切片很小，单文件可直接驱动 writer，也已经有
  输出 SHA-256 和运行截图。
- **如何被推翻：** 同一 entry 的地址、译文和字形分配开始分别出现在构建器、
  PINE 验证器、manifest 和文档；扩大到第二个 surface 会形成多个可修改事实源。
- **事实：** canary 是 golden 和验收夹具，不是语料库或 layout registry。
  生产含义应由 SurfaceSpec、`corpus/zh`、codebook 和 BuildProfile 分工持有。
- **守门：** canary 配置已移除 `glyphs` 和 `text_patch`；静态 writer 与 PINE
  都调用 `load_build_profile()`；单元测试明确拒绝事实源回流，并验证新链生成
  与 E0 完全相同的 SLPS、VT1 和预览 SHA-256。
