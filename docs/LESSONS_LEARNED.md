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

### A2. 能表达 extended distance，不等于使用了最短表示

- **曾以为：** distance 大于 8 时把 token seed 写成 0，再写完整 coded integer，
  已经是合法且足够接近原版的编码。
- **为什么看似合理：** strict decoder 能完整回解，按钮子集也能在 71 sectors
  内启动；继续增加 match chain 看起来才是压缩率优化方向。
- **如何被推翻：** DLL CIL 显示最高 7-bit 组小于 8 时会放入三 bit seed；原版
  COMPDATA 的 12,521 个合格 token 全部这样编码。旧完整 P0 后缀有 1,796 个
  合格 token 把 seed 写成 0，逐个多占 1 byte。
- **事实：** coded integer 的 seed 是压缩决策的一部分。原始后缀 1,930-byte
  差距中，compact seed 单独收回 1,808 bytes；完整 P0 从 147,050 降至
  145,237，恢复 71-sector 原位布局。
- **守门：** `greedy` 保持旧字节行为；`size-constrained` 用真实序列化成本和
  compact seed，并以 `max_output_size=145408` 失败关闭。真实流 manifest
  固定 missed-seed 数、cost 总和、71-sector gate 和 PCSX2/PINE 0 TLB。

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

### B2. 归档总长度可容纳，不等于可以移动后续成员 LBA

- **曾以为：** VT1 字库扩展后，只要 ISO 能容纳增长量、成员哈希和目录都正确，
  就可以把后续 `STAGE.BIN` 顺延。
- **为什么看似合理：** `mkps2iso` 重建出的 UDF/ISO9660 完整，字体和剧情压缩流
  都能被 clean-room 解码器往返；顺移版本也保持整镜像大小不变。
- **如何被推翻：** 带原版 HB/STAGE、只把 VT1 扩大并令 STAGE 后移 86 sector
  的控制镜像，仍在 `pc=0x0019DD94` 访问 `0x02000000` 时 TLB miss；同一份
  大字库在 VT1 总长和后续 LBA 恢复原值后可以进入第一关并显示中文。
- **事实：** 本游戏至少有读取路径依赖原盘的后续文件物理 LBA，目录记录正确
  不能替代原位置。当前 first-five profile 必须保持所有成员 LBA 不变。
- **守门：** 当前字体增长只借用 VT1 前一 chunk 已验证的 12,320-byte 全零尾部，
  VT1 总长保持 127,501,728；前五关 STAGE 使用 Rust suffix 压缩并落在
  原扇区间隙内；ISO 清单要求 `shifted_member_count=0`、`shift_sectors=0`，
  最终还要在 PCSX2 中通过无 TLB 的第一关可见文本验证。

## C. 字库和码位分配

### C1. 空白 glyph 和未引用 code 只是候选，不是安全槽位

- **曾以为：** 原版字形为空、且固定码表/语料没有引用的 code，可以直接当作
  中文容量。
- **为什么看似合理：** 静态扫描得到连续空白 glyph，94,189 条已解析语料没有
  对应 token，码表也没有冲突。
- **如何被推翻：** 静态结果只能说明当前样本没有已知引用；它不能证明所有
  renderer 分支、动态构造文本、存档或未覆盖流程都不会使用这些位置。
- **事实：** “公式可寻址候选”“已分配”“在某个 surface 运行验证”是三种
  不同状态。当前 `987E/987F` 只批准给开场菜单的 `测/试`；P1 可以依据锁定
  指令窗口生成 raw-trail 离线候选，但不能把一次 `987F` 运行成功外推成
  `0xFD/0xFE/0xFF` 或整张组件的安全结论。
- **守门：** `config/encoding/codebook.json` 是唯一分配账本；BuildProfile
  只能选择显式 `assigned` 项；code/glyph/raster/owner 全部固定，冲突扫描、
  运行内存哈希和 surface 截图分别保留。

### C2. 缺字集合排序不是稳定的码位分配

- **曾以为：** 每次按当前译文缺字排序，再顺序填入候选槽位，可以得到确定性
  codebook。
- **为什么看似合理：** 同一份语料重复构建时顺序稳定，所有字符也都能编码，
  单次字体和 STAGE 往返检查均会通过。
- **如何被推翻：** 删除两个旧字并新增一个字后，排序位置改变，后续数百个字符
  全部换码；STAGE 压缩结果因此增长一个 sector，ISO 后续成员 LBA 随之漂移。
- **事实：** 确定性排序只保证“同输入同输出”，不保证版本间码位稳定。已经
  发布到文本或存档里的字符编码必须具有持续身份。
- **守门：** `config/encoding/first-five-allocations.json` 采用追加式账本；
  退役字符保留槽位，新字符只追加，proposal、字体构建和 STAGE 构建都验证账本
  SHA-256。

### C3. “码表能编码”和单字节可打印都不是 renderer 契约

- **曾以为：** 固定表里存在字符即可直接写入；普通 ASCII 也能按单字节原样
  输出。
- **为什么看似合理：** clean-room 文本解码器可以把这些字节还原为同样文本，
  最终 ISO 回读也不会报告未知码。
- **如何被推翻：** 运行截图中“隶、仗、估、儿”等字符留空；`10` 的 `0x30`
  又进入游戏控制语法，使“我在10天前到任”的后半句错位。静态反查确认 121 个
  固定表 code 不在 renderer 扩展表，普通 ASCII 则与控制字节空间重叠。
- **事实：** 文本 codec、renderer code→glyph 和控制语法是三份不同契约。
  最终文本相等不能证明画面可达。
- **守门：** 前五关所有普通 ASCII 和 121 个 table-only 字符都使用显式双字节
  override；`$n/$F` 在编码器中先于 override 识别并保留；覆盖审计要求不可达
  glyph、普通单字节 ASCII 和混合汉字来源同时为 0。

### C4. 沿用日文行数不是中文布局

- **曾以为：** 逐条保持日文原文的换行数量，可以避免文本框溢出并保留演出节奏。
- **为什么看似合理：** 每条译文最多三行，旧的 26 字符长度检查也全部通过。
- **如何被推翻：** PCSX2 画面出现大量不必要的短行；去掉行数耦合后，第一版
  自动平衡又把“我们、开发、刚才、兵器、项目”等中文词拆开。
- **事实：** 日文换行只能作为可选语义提示，不能决定中文行数。合格布局必须
  同时考虑中文标点、词语边界、专名、运行时玩家名展开宽度和文本框容量。
- **守门：** `reflow_first_five_dialogue.py` 按 24 glyph cell、最多 3 行生成；
  `$n/$F` 预算 6 格，术语、标题、ASCII 词组及已审出的常用词不可拆分，闭标点
  和语气助词不得落在续行开头。检查模式必须零改动；语言审计再次独立验证宽度、
  行数和禁则。前五关由 3,124 行降为 2,160 行，系统中文分词辅助审查为
  0 个词内断行。

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

## E. 图片索引和渲染

### E1. PNG8 默认抖动会破坏源 index 到 RGBA 的一对一关系

- **曾以为：** ImageMagick 读取 indexed TIM2 后直接输出 `PNG8:`，同一个
  palette index 在整张图中自然会得到同一个 RGBA。
- **为什么看似合理：** chunk 2、4、6 的灰阶 CLUT 都满足该假设，定位
  canary 能 byte-exact 回写。
- **如何被推翻：** chunk 7 的轻微色偏 CLUT 触发默认 palette dithering；
  同一个源 index 4 被量化成多个灰度，严格 writer 在 `(22,30)` 主动拒绝。
- **事实：** PNG8 颜色量化是渲染步骤，不是源 TIM2 索引事实；抖动后的 RGBA
  不能作为可逆索引映射。
- **守门：** `render_tim2_png8()` 强制传入 `+dither`；单元测试固定命令，
  原三项 profile 必须保持全部输出锁不变，chunk 7 还必须证明 16 个源 index
  各自只有一个展开 RGBA 后才允许写回。

## F. P10 压缩、字体和证据闭包

### F1. 离线支持 `min-match-length=2`，不等于游戏支持

- **曾以为：** Rust 码流能被独立 Python decoder 完整消费、逐字节还原且体积
  更小，便可以把 COMPDATA 最小匹配长度从 3 降到 2。
- **为什么看似合理：** `min-match-length=2` 候选为 145,192 bytes，严格
  round-trip 和 145,408-byte 容量门都通过。
- **如何被推翻：** 该精确 ISO 在游戏启动路径出现 TLB miss；恢复
  `min-match-length=3` 的等价内容后，游戏接受压缩 parse。
- **事实：** clean-room decoder 的可接受集合大于游戏解压器已经证明安全的
  运行语法；压缩率不能替代运行兼容性。
- **守门：** production COMPDATA 固定使用仓库内 Rust `rust-maximum`、
  `min-match-length=3` 和 145,408-byte 硬门；Python 只作为 decoder/oracle。
  `min-match-length=2` 只保留为负面对照，不得晋级。

### F2. VT1 与 SLPS offset 表必须原子更新

- **曾以为：** 字体数据在 `DATA/VT1.BIN` 中，单独替换 VT1 就能验证新字库。
- **为什么看似合理：** VT1 的 14 个 chunk 都能由独立解析器列出，新字体 chunk
  本身也能严格回解。
- **如何被推翻：** 新 VT1 配旧 `SLPS_258.87` offset 表时，离线切片立即产生
  无效 back-reference；标题长路径随后出现 12 次 TLB miss。
- **事实：** VT1 chunk offset 还镜像在 SLPS 固定表中，两者是一个兼容单元。
- **守门：** ISO 构建器在替换旧镜像之前，必须用所选 SLPS offset 表实际解码
  所选 VT1 字体 chunk；错误配对 fail-closed，不再物化为当前测试 ISO。

### F3. `missing=0` 只证明被选语料，不证明实际写回闭包

- **曾以为：** P10 字体审计报告零缺字，所有实际写进游戏的中文都会有字形。
- **为什么看似合理：** 数据库、关卡标题和已有语料都通过同一 renderer 覆盖
  扫描，manifest 也记录了零缺字。
- **如何被推翻：** 男主人公开场简介在游戏中缺“凉／缺”，而旧报告仍然是
  `missing=0`。
- **事实：** 这四条简介会直接写入 COMPDATA，却未进入字体需求选择；审计只对
  输入集合成立，实际写回集合与字体需求之间没有闭包。
- **守门：** 所有直接写回语料必须显式进入字体 provenance。当前开场简介通过
  `additional_translation_selections` 合并，并锁定 corpus hash、scene、状态、
  entry count、entry IDs 和候选写回记录；字体与数据库候选互相核对这些绑定，
  “凉／缺”另有 assignment 单元测试。

### F4. 同一字体和统一 point size 仍会产生视觉不一致

- **曾以为：** 覆盖原字形并统一 point size 后，中文大小和宽窄会自然一致。
- **为什么看似合理：** 所有字都进入固定 24×24 槽，来源字体、码位、advance
  和栅格流程相同。
- **如何被推翻：** 运行截图中“班／任／尔”仍显得偏小或偏窄；“尔”在 23.5pt
  下仍不够宽。
- **事实：** point size 不等于墨水 bbox；字形留白、重心和 rounding 需要逐字
  度量，少数结果仍必须由运行截图裁决。
- **守门：** 自动策略在 22／22.5／23／23.5pt 中按 bbox、墨水量和边缘碰撞
  逐字选择；人工例外单独锁进配置。“尔”当前使用 25pt、bbox 22×22，码位、
  glyph 槽和 advance 不变。每个 assignment 固定 point size、bbox 和 raster
  hash，视觉结论只绑定到匹配 ISO 的截图。

## G. 运行证据和候选管理

### G1. boot smoke 不等于目标场景运行通过

- **曾以为：** fresh-process 达到 PINE Running、DVD/ELF 正常且零 TLB，就能
  把该 ISO 标成运行通过。
- **为什么看似合理：** 启动门能排除错误介质、错误 ELF 和立即发生的解压崩溃。
- **如何被推翻：** 多个候选在标题阶段正常，却在确认人物、首次剧情转场或更晚
  加载字体资源时失败。
- **事实：** boot、人物确认后转场、目标 UI 页面、剧情流程和 atlas texture/
  截图是互不替代的证据层。
- **守门：** 每份证据绑定精确 ISO SHA、PCSX2 版本、fresh-process、游戏 ID、
  save/savestate provenance、目标 surface、PINE、日志和截图哈希。旧 ISO 的
  证据不得迁移到新 SHA。当前 `310a2c5b…dcba88` 保持 `runtime=pending`。

### G2. 多张“最新 ISO”和 patch-over-patch 会破坏归因

- **曾以为：** 保留每次构建出的 ISO，并在上一候选上继续打小补丁，方便回退和
  加快验证。
- **如何被推翻：** PCSX2 测试目标、配置锁和截图 SHA 多次可能指向不同候选；
  patch-over-patch 还会丢失原版前像和差异所有权。
- **事实：** 语料、selection、allocation、profile 和原版成员是事实源；
  component、manifest、review report 和 ISO 都是可重建产物。
- **守门：** 正式构建始终从原版开始；`build/iso/` 只保留一个当前候选；生成
  manifest 后立即无刷新复核，运行前再次核对 ISO SHA。当前静态基线为
  `310a2c5bebcc0be343f5865176dec994f6951c6efbb576dee9af125ef4dcba88`。

## H. 下一批剧情的复用顺序

第 6 话及之后的剧情按固定链路推进：提取与稳定 ID → 中文决策与断行 → 实际
写回集合与字体需求闭包 → Rust 压缩和定长/LBA 门 → 单一精确 ISO → 匹配存档
的目标场景运行证据。任何一层失败，只回到该层修生产器或事实源，不用后续层的
成功掩盖前序失败。

clean-room 边界保持不变：不得执行 `SRWZ.exe`、`SRWZ.dll`、
`CompressTool.exe`、Wine 或 Mono；外部二进制只能静态检查格式事实，不复制
无许可证上游源码，也不把原版游戏数据提交到仓库。
