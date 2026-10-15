# PCSX2 2.x 贴图替换命名变更与机战 Z 高清材质包适配研究

2026-10-15。研究对象是 `~/Downloads/机战ZSLPS-25887 SLPS-73270/replacements` 这份第三方 4 倍高清包（5,914 张 PNG，约 11.4 GB），目标是弄清它在 PCSX2 2.x / ARMSX2 里失效的确切原因，以及战斗动画部分能否不靠人工重做就转换到新命名。工具与中间产物在 `textures/tools/`（见那里的 README）。

**结论先行：**

1. PCSX2 从 2023-02-09（PR #8015，nightly ≥ v1.7.4050）起，凡是用 `REGION_CLAMP` / `REGION_REPEAT` 采样子矩形的绘制，贴图缓存只取子矩形，替换文件名变成 `TEX0Hash-CLUTHash-rWxH-bits.png`，哈希只覆盖子矩形像素；查找是精确匹配，没有回落到整图名的逻辑。旧包全部是整图名，所以一张都对不上。ARMSX2 2.7.2 用同一套命名。
2. 机战 Z 的战斗动画引擎把每个机体部件当作一次独立绘制，`CLAMP` 寄存器就是部件在 512×256 图集里的 UV 矩形（反编译 `FUN_002ef830` 确认）。所以新版下**每个部件一张文件**，一张旧图集会裂成几十到上百张 `-rWxH` 小图。这就是“战斗动画难转”的全部原因，不存在别的渲染差异。
3. 不需要在游戏里魔改 dump 逻辑。离线侧已经打通：旧包的 BA/BAC/maps 三个文件夹分别被还原到光盘的 `btl/twp(+trb)`、`btl/tci`、`btl/tbg` 归档（精确同名 3,169/3,213、335/583、601/625），而且对 2.6.3 实机 dump 的 697 张战斗部件小图，用解码后的图集做像素搜索找到位置后重算 region 哈希，**696 张逐一相同、0 张不符、1 张不在 twp 内**。偏移量可以离线恢复，转换 = 在旧 4 倍图上按 `(x0×4, y0×4, w×4, h×4)` 裁剪并改名。
4. 当天下午补做的静态解析（第 8 节）把两个未决点都推进了：TWP/trb/tci 的动作数据已经能 100% 解析（TWP 1,004,006 条对象流全部按格式走通），精灵部件矩形可以离线枚举，696 张实机 dump 里 602 张能在静态部件表里找到，剩下 94 张来自另一条“瓦片图层”绘制路径（背景和特效层，矩形随滚动裁切）；PSMT4 的 16 色 CLUT 分组也用 dump 反推出来了（77 个调色板解释 75 个）。另外还有一条对自家分支最省事的路线 D：在 ARMSX2-SRWZ / pcsx2-srwz 里关掉 region 优化，旧包原样可用。

## 1. PCSX2 到底改了什么

证据来自本机 `pcsx2-srwz`（v2.8.2 源码树）与 GitHub PR 页面。

### 1.1 命名格式

`pcsx2/GS/Renderers/HW/GSTextureReplacements.cpp` 第 33–38 行定义了全部格式：

| 格式 | 何时使用 |
| --- | --- |
| `%llx-%08x` / `%llx-%llx-%08x` | 无 region 的整图（旧包全部如此） |
| `%llx-r%ux%u-%08x` / `%llx-%llx-r%ux%u-%08x` | 带 region 的绘制（当前） |
| `%llx-r%llx-%08x`（OLD_REGION） | 2023 年过渡期的旧 region 写法，解析时仍接受 |

`bits` 字段是 PSM(6)、TW(4)、TH(4)、旧 TCC(1)、TA0(8)、AEM(1)、TA1(8) 的位打包；解析时 `RemoveUnusedBits()` 清掉 TCC 位，所以旧包 `00006253` 与新 dump `00002253` 等价，这一项无害。

### 1.2 region 的产生规则

`GSTextureCache::SourceRegion::Create(TEX0, CLAMP)`（`GSTextureCache.cpp` 8944 行起）只看 CLAMP 寄存器：

- `WMS == REGION_CLAMP` 且 `MAXU >= MINU`：若 `MAXU-MINU+1 < 2^TW` 或 `MAXU >= 2^TW`，region X = `[MINU, MAXU+1)`；
- `WMS == REGION_REPEAT` 且 `MINU != 0`：region X = `[MAXU, (MINU|MAXU)+1)`；
- V 方向同理。只有一个方向有 region 时名字写成 `-rWx0` / `-r0xH`，另一轴取整图尺寸。

`UserHacks_EstimateTextureRegion` 默认关闭，SLPS-25887/73270 的 GameDB 也没有开它，不是原因。

### 1.3 哈希算法

`HashCacheKey::Create` 把 `TEX0Hash` 定义为 `HashTextureLevel` 的 XXH3-64：

- 无 region、索引格式、尺寸不小于块：按 16×16（PSMT8）/ 32×16（PSMT4）块的 VRAM 顺序逐块哈希（块内为 columnTable 顺序）。这是旧包整图名的算法，**新旧版本一致**：2.6.3 的 72 张无 region dump 里，2 张 BA、6 张 ui 的名字与旧包完全相同。
- 有 region（`region.GetMaxX() > 0 || region.GetMinY() > 0`）：先把块对齐矩形展开成每像素一字节的索引图，再**逐行哈希子矩形**（PSMT8 一像素一字节，PSMT4 展开后也是一像素一字节）。`CLUTHash` 是 256（或 16）个 u32 调色板项的 XXH3，不变。

### 1.4 相关的上游动态

- PR #8015 “GS/HW: Optimize TC source size based on CLAMP”，2023-02-09 合并，维护者在讨论里确认“签名已变，旧替换不再匹配”。
- PR #14584 “texture replacement wildcard aliases”（`$-CLUTHash-rWxH-bits.png`，只按 CLUT+bits 回落）至今未合并，被排到 2.10 里程碑。即使合并也救不了战斗贴图：同一调色板下成百上千个部件尺寸重复，通配不能区分。
- 没有任何“按整图名回落”的选项或计划。

## 2. 旧包清单与来源归档

| 文件夹 | 张数 | bits | 原生格式 | PNG 尺寸 | 来源归档（本次核实） | 精确同名 |
| --- | ---: | --- | --- | --- | --- | ---: |
| BA | 3,213 | 6253 | PSMT8 512×256 | 2048×1024 | `btl/twp.bin`（1,244 块）+ `btl/trb.bin`（335 块） | 3,169 |
| BAC | 583 | 6653 / 6654 | PSMT8 / PSMT4 512×512 | 2048×2048 | `btl/tci.bin`（切入，171 块，原生 512×512） | 335（PSMT8 全中；PSMT4 241 张只对上纹理哈希） |
| maps | 625 | 6253 | PSMT8 512×256 | 2048×1024 | `btl/tbg.bin`（战斗背景，150 块） | 601 |
| face | 1,296 | 6653 | PSMT8 512×512 | 2048×2048 | `DATA/VT1.BIN`（已做，见 2026-09-14 记录） | 1,295 |
| addition | 82 | 6254 | PSMT4 512×256 | 2048×1024 | twp / trb 的 4-bpp 图（纹理哈希 82/82 命中，CLUT 未对上） | 0 |
| ui / ui2 | 50 | 6254/6214/6653/… | 多种 | 多种 | KVMDATA 等 UI 图集，本次未核 | — |
| XAN-斩 / 混沌狮子 | 65 | 6253/6653 | PSMT8 | 多种 | 混沌狮子 4 张在 tci；XAN-斩 51 张四个归档都没有 | 4 |

`textures/tools/pack_source_coverage.json` 有逐文件夹的分类计数。“精确同名”指用光盘数据重算出的 `TEX0Hash-CLUTHash` 与旧包文件名完全一致，是后面所有自动转换的前提。

### 2.1 贴图在光盘里的存法

四个归档都是 `.seg` 偏移表 + LZSS 块（`srwz.codec.decode_production` 可解）。块内是标准 TIM2：twp 每块两个 TIM2 包，PSMT8 512×256（itype 5，带 512 色 RGBA32 CLUT = 两组 256 色，后面无 CLUT 的 picture 共用）和 PSMT4 512×256（itype 4，CLUT 为 N×16 色）；tci 的 picture 原生就是 512×512。

像素不是线性存放：它们已经排成“把贴图当 PSMCT32 上传”的布局（PSMT8 512×256 = CT32 256×128，PSMT4 512×256 = CT32 256×64，页步距与 TBW=8 一致）。PSMT8 的还原沿用 VT1 头像的 `_psmt8_stored_offset`；PSMT4 的置换从 PCSX2 的 GS 地址表推导（`archive_texture_hashes.unswizzle4_any`），用 BAC 的 134 张 4-bpp 切入图纹理哈希命中做了验证。256 色 CLUT 要按 CSM1 的 8×2 交换（`csm1_palette_offset`）重排后再哈希。

## 3. 战斗动画是怎么画的（反编译）

绘制入口 `FUN_002f7060`：遍历 0x400 个图层（步距 0x24），每层一个绘制节点链表，节点 `+0x18` 是类型，0 = 精灵部件（`FUN_002ef830`），1/2/3 = 上传类节点（对应 2026-09 □ 跳过记录里“只能跳过 type 0”的结论）。

`FUN_002ef830(ctx, part, scene)` 为一个部件写 GIF A+D 包，寄存器顺序是 TEX0(6) [TEX2(0x16)] TEX1(0x14) CLAMP(8) PABE(0x49) ALPHA_1(0x42) 然后顶点。关键字段（`part` 为运行时部件记录）：

| 字段 | 含义 |
| --- | --- |
| `+0x24`, `+0x26`（short，& 0x1FF） | 部件 UV 起点 u0, v0 |
| `+0x20`, `+0x22` | 部件宽高 w, h（或 `+0x1f` 某位置位时 `+0x34/+0x36` 直接给 u1, v1） |
| `+0x3c`, `+0x2f` | 贴图组编号、组内 picture 编号（经 `FUN_002f8150` 分配 VRAM 槽得到 TBP0） |
| `+0x2e` | 低 3 位调色板槽（→ CBP），高位 >>3 = CSA（PSMT4 用 TEX2 选 16 色组） |
| `+0x1c` 低 2 位 | TFX |
| `+0x1d` | 低 2 位 = CLAMP 模式；位 2/3 = 翻转标志（选 REGION_REPEAT）；位 5 = 双线性；位 7 = PABE |
| `+0x30..+0x33` | 模式 1 下的四边内缩 |
| `+0x2c`, `+0x2d` | ALPHA 混合参数 |

默认模式下 CLAMP 的写法是：

```
WMS = WMT = REGION_CLAMP
MINU = u0, MAXU = u0 + w - 1, MINV = v0, MAXV = v0 + h - 1
```

所以 PCSX2 的 region 宽高正好是部件的 w×h，哈希就是图集里 `[v0, v0+h) × [u0, u0+w)` 这块索引。TEX0 的 TBW/TW/TH 直接取自 TIM2 头的 GsTex0（全部为 512×256，TBW=8），PSM 对 PSMT4 由 TEX2 覆盖。翻转部件走 REGION_REPEAT 分支（MINU 变成掩码、MAXU 变成偏移），PCSX2 对这种情况也会生成 region，但宽度公式不同（见 1.2），转换器要单独处理。

这解释了 2.6.3 那次 dump 的分布：2,837 张里 2,761 张带 `-r`，其中带 twp 调色板的 697 张尺寸从 8×8 到 144×160，大多是 8 的倍数但也有 33×24、37×24 这种奇数宽。

## 4. 离线验证结果

`verify_region_hash.py` 对 2.6.3 的 697 张 PSMT8 战斗 dump 做了端到端验证：按 CLUTHash 找到 twp 块 → 解码、去 swizzle、套调色板 → 在 512×256 RGBA 图集里搜索 dump 的像素块 → 对找到的子矩形按 1.3 的算法重算哈希。

| 结果 | 张数 |
| --- | ---: |
| 定位成功且哈希一致 | 696 |
| 定位成功但哈希不符 | 0 |
| 未定位（`2735cfaf…-r48x56`，调色板来自 trb，搜索范围只含 twp） | 1 |

这同时证明三件事：图集解码布局正确、region 哈希算法还原正确、**偏移量不需要游戏告诉我们**。

## 5. 适配路线

### 路线 B（推荐，立即可做）：实机收集矩形 + 离线裁剪

1. 用 PCSX2 2.x 或 ARMSX2（`DumpReplaceableTextures = true`，ARMSX2 的 ini 已开 `LoadTextureReplacements`）跑战斗。覆盖率来自跑过的内容：SP 的“战斗鉴赏·普通模式”可以指定双方机体和武器，是最省事的入口；也可以直接玩主篇。
2. 转换器：对每张 `TEX0Hash-CLUTHash-rWxH-bits.png` dump，按 CLUTHash 定位归档块、按像素定位 `(x0, y0)`（`verify_region_hash.py` 已是原型），然后在旧包对应的 4 倍整图上裁 `(4x0, 4y0, 4w, 4h)`，另存为新名。
3. 可选的省事补丁：在 `pcsx2-srwz` 的 `GSTextureReplacements::DumpTexture` 里多写一行日志（`region.GetMinX()/GetMinY()` 与整图哈希），裁剪就不用做像素搜索；但不是必需。
4. 没跑到的部件以原生分辨率显示，不会出错，之后随时增量补。

自动化思路：SP 鉴赏模式的构建器是 `FUN_00448dc0`，机体表 `0x7B9A88`；做一个“战斗结束自动换下一台机体/下一把武器”的 pnach 或 LRPS2 脚本就能整夜无人值守跑完。LRPS2 自己不能产出 2.x 命名的 dump，只能当驱动，dump 要在 PCSX2/ARMSX2 里做。

### 路线 A（补全）：解析 TWP 部件表，离线枚举全部矩形

第 8 节已经把静态格式解出来并用 dump 交叉验证：`textures/tools/twp_parts.py` 可以不开游戏枚举 TWP/trb/tci 全部精灵部件；TWP 一共 84,098 个不同的（贴图, 矩形）组合，其中 57,902 个的图集在旧包里有高清源。还没覆盖的是瓦片图层（背景 tbg 和特效层）的瓦片表，以及随滚动变化的裁切瓦片。

### 路线 D（自家分支最省事）：在模拟器里关掉 region 优化

PCSX2 的 region 只在 `GSTextureCache::LookupSource` 的两处 `SourceRegion::Create(TEX0, CLAMP)`（v2.8.2 的 `GSTextureCache.cpp` 1143、1334 行）产生。给自家的 ARMSX2-SRWZ / pcsx2-srwz 加一个按游戏序列号生效的开关，让这两处返回空 region，命名和哈希就回到整图方式，旧包一个字节不改直接可用（整图哈希算法新旧一致，第 1.3 节已验证）。代价是放弃该优化带来的显存/性能收益，对这款 2D 游戏无关紧要。缺点是只对自家分支有效，用官方 PCSX2 的人仍需要转换后的包，所以它和路线 B/A 是互补关系。

### 路线 C：游戏内 dump 魔改

不需要。PCSX2 的 dump 已经是“纯 dump”，问题只在偏移和覆盖率，两者都在上面解决了。

### UI 部分

同一机制、同一工具链。UI 图集也多用 REGION_CLAMP 画小图标，所以 `ui/ui2` 也要按 region 切；只是数量小（50 张整图），而且 KVMDATA 的页面布局已有文档，可以直接按已知矩形切。face 的 `-r513x513` 已经做完。

## 6. 未决问题与风险

- **PSMT4 CLUT 分组**：已解（第 8.5 节）：游戏每个调色板槽上传 1024 字节（256 色，CT32 16×16，CSM1），槽指针可以落在 TIM2 CLUT 的任意 16 色对齐位置；PCSX2 的 16 项 CLUTHash = 该 256 色窗口按 CSM1 重排后取 `CSA*16` 起的 16 项。77 个 PSMT4 dump 调色板里 75 个由此解释。
- **trb / 其它来源**：BA 有 197 张只在 trb、7 张四个归档都找不到；XAN-斩 51 张来源未知（可能是 BEST 盘或非 btl 归档）。
- **裁剪边缘**：旧包作者是在整图上作画，部件边界处的高清像素会被切开；原版部件在图集里不重叠，所以只影响越界的笔触。PCSX2 对替换图按 region 采样，边缘双线性与原版一致。
- **文件数量**：一张图集会变成几十上百个小 PNG，全包可能上万张。PCSX2 支持异步加载和预缓存，数量本身不是问题，但要按归档分目录便于增量。
- **区域越界的页回绕**：`MAXU >= TW` 时哈希会读到相邻 VRAM 页（头像的 513 情况）。战斗部件矩形都在图集内，目前没遇到。

## 7. 本次产出的文件

- `textures/tools/twp_texture_manifest.py`、`twp_texture_manifest.json`：twp 全部 7,007 张 picture 的哈希清单。
- `textures/tools/archive_texture_hashes.py`：tci/tici/tba/tbg/trb 的同类扫描；`psmt4_512x256_perm.npy` + `_half.npy` 为 4-bpp 去 swizzle 置换。
- `textures/tools/verify_region_hash.py`：region 哈希端到端验证（也是转换器的定位原型）。
- `textures/tools/pack_source_coverage.json`：旧包逐文件夹来源统计。
- 反编译输出（`FUN_002ef830`、`FUN_002f7060`、`FUN_002f8150`、`FUN_002ef7d0`）存在 `work/analysis/battle-texture-port-20261015/`；Ghidra headless 用的 `DecompileAddresses.java` 已重新放回 `work/analysis/ghidra/`。

Sources: [PR #8015](https://github.com/PCSX2/pcsx2/pull/8015), [PR #14584](https://github.com/PCSX2/pcsx2/pull/14584), [PR #5547](https://github.com/PCSX2/pcsx2/pull/5547).

## 8. 静态结构（当天下午补充）

目标是不开游戏枚举全部部件矩形。方法是反编译 + 数据验证：先找到绘制节点的来源（`FUN_002f7060` 的节点类型 0 = 精灵、1 = 瓦片图层），再顺着 `FUN_002f8e50`（序列启动）→ `FUN_002f9c50`（对象流定位）→ `FUN_002ecc30`（流初始化）→ `FUN_002ece80` / `FUN_002ecf40` / `FUN_002ecc80`（关键帧读取）→ `FUN_002ecc50`（事件跳过）→ `FUN_002ecee0` / `FUN_002ecfb0`（关键帧切换与插值）把格式读出来，再用块 739 的数据逐条走通。Ghidra 辅助脚本重新放回 `work/analysis/ghidra/`（`DecompileAddresses`、`DecompileRange`、`ListFunctionCallers`、`FindFunctionsWithStores`、`FindStringRefs`）。

### 8.1 归档块容器（twp / trb / tci 相同）

| 偏移 | 内容 |
| --- | --- |
| `0x00` | u32 = 2；`0x04..0x20` 指针字段 |
| `0x10` | section 0（16 字节：`0x20`、尾段偏移、块尾、0） |
| `0x24` | u32[5] 段偏移：`0x10`、事件/尾段、TIM2 包 A（PSMT8）、TIM2 包 B（PSMT4，可缺）、块尾 |
| `0x50` | u8 0、u8 nA、u8 nSeq、u8 nPairs —— 一个“表集”的头；一个块可以有多个表集首尾相接（上一集的序列哨兵处就是下一集的头），TWP 有 136 块带第二表集（受击/防御等被动动画） |
| `0x54` | (nA+1) × u32 动作选择表（u8 index, u8 flag, u16 0） |
| 之后 | nPairs × u16 子动作映射（u8, u8） |
| 之后 | (nSeq+1) × u32 序列偏移（dword 单位，相对表尾；最后一项是哨兵 = 序列区末尾） |
| 序列 blob | u8 nobj、u8 flags、u16 总帧数、u32 offs[nobj]；对象流在 `blob+8+4·nobj+4·offs[i]`；`flags&1` 时该基址本身还有一条“镜头”流 |
| 对象流 | u8 a、u8 kind、u16 nrec；kind 0x80/0x82/0x83 后跟 4 字节描述符、0x81 跟 8 字节（`FUN_002f8e50` 经 `+0x1e8` 读取）；然后 nrec 条记录 |
| 记录 | u16 time、u8 nevents、u8 x；u32 mask；mask 第 {0,1,2,3,4,6,7,8,9,10,11} 位每位 4 字节载荷（第 5 位和 ≥12 位无载荷）；然后 nevents 条事件，每条 `[u8 type][u8 ndw][u8][u8]` + ndw×4 字节 |

TWP 的 1,244 块里有 20 块是 0x40 字节的空块（727–740 一带）。tbg（战斗背景）不是这个结构，见 8.7。

### 8.2 关键帧字段（`FUN_002ecc80`，对象状态块 `+0x50..`）与绘制记录的对应

| mask 位 | 对象状态偏移 | 含义 | 到绘制记录（`FUN_002ef830` 的 `part`） |
| --- | --- | --- | --- |
| 0 | `+0x58/+0x5c` | 位置（2×s16 → float） | — |
| 1 | `+0x60` | 旋转（s32，12 位定点） | — |
| 2 | `+0x64` | RGBA 调制色（`80808080` 为中性） | `+0x14..0x17` |
| 3, 4 | `+0x50`, `+0x54` | 缩放等（2×s16） | — |
| 6 | `+0x78` | 锚点偏移（2×s16，通常 = −w/2, −h/2） | `+0x28/+0x2a` |
| 7 | `+0x70` | **w, h**（u16, u16） | `+0x20/+0x22` |
| 8 | `+0x74` | **u, v**（u16, u16，绘制时 `& 0x1ff`） | `+0x24/+0x26` |
| 9 | `+0x7c` | **ALPHA 低字节、FIX、调色板槽(&7)｜CSA<<3、贴图组(&3)｜picture<<2** | `+0x2c..0x2f` |
| 10 | `+0x80` | 四边内缩（模式 1 用） | `+0x30..0x33` |
| 11 | `+0x6c` | TFX、CLAMP 模式(&3)/双线性(bit 5)、alpha 测试、杂项 | `+0x1c..0x1f` |

第 9/11 位的对应关系是用 dump 反证的：在 696 张已验证 dump 中，picture 1/2/3 的部件其第 9 位字段末字节分别是 `0x04/0x08/0x0c`（`>>2 & 0xf`），与 TIM2 包内 picture 序号一致。CLAMP 模式统计：模式 0 共 368,597 次引用、模式 2 共 27,816 次（都走默认 REGION_CLAMP = 部件矩形）、模式 1 共 454 次（内缩/镜像：非镜像时 `MINU = u0+ins0, MAXU = u0+w−ins1`，镜像时 `WMS = REGION_REPEAT, MINU = ins0−1, MAXU = ins1`，PCSX2 region 按 1.2 的规则算），模式 3 共 2 次。

### 8.3 枚举结果

| 归档 | 非空块 | 对象流 | 全部按格式走通 | 不同的 (块, 组, picture, u, v, w, h) |
| --- | ---: | ---: | ---: | ---: |
| twp | 1,224 | 1,039,607 | 1,039,607 | 173,009 |
| trb | 334 | 168,861 | 168,861 | 37,423 |
| tci | 153 | 13,131 | 13,131 | 6,228 |
| tbg | 147 | 瓦片结构，见 8.7 | — | 17,060 个整瓦片矩形 |

按贴图哈希去重后（第一表集统计），TWP 精灵部件对应 **84,098** 个不同的（贴图, 矩形）组合（PSMT8 58,686、PSMT4 25,412），涉及 2,488 张图集，其中 57,902 个组合的图集在旧包里有高清源。525 条引用指向 TIM2 包里不存在的 picture 序号：其中 154 个不同矩形是 (0,0,8,8) 的初始化默认值（对象从未赋过真实部件），其余 371 个矩形的 picture 序号超出包内张数，语义未明，先不产出。最常见尺寸 8×8、24×24、32×24、64×64、32×32。3,036 次引用的矩形超出图集边界（`u+w>512` 或 `v+h>256`），这些会落入 PCSX2 的页回绕哈希（头像 513 的情形）。清单：`textures/tools/twp_parts_manifest.json`、`trb_tci_parts_manifest.json`。

### 8.4 与实机 dump 的交叉验证

696 张已经重算出 region 哈希的 PSMT8 dump，按“同一张 picture（贴图哈希相同）出现过的所有块”去静态部件表里找同样的矩形：

| 结果 | 张数 |
| --- | ---: |
| 在 dump 所属块的部件表里（含第二表集） | 494 |
| 在共用同一调色板的同机体其他块里 | 141 |
| 静态部件表里没有 | 61 |

没有的 61 张（8.8%）集中在少数块（329 占 31、199 占 17、658 占 10），尺寸像 33×24、37×24、21×19 这种不规则值，而且这些块及其同机体块的部件表里既没有相等的矩形，也没有能包住它们的部件（只有 24 张落在某个部件内部）。块 329 的一组 (166,104,34,24)、(169,106,33,24)、(220,144,36,24)、(231,152,37,24)、(252,168,37,24)、(274,184,38,24) 沿对角线平移、宽度递增，像是运行时按时间推进 UV 窗口的特效，不是关键帧里的静态矩形。这部分只能靠运行时 dump。

### 8.7 背景瓦片层（tbg）

`FUN_002f5bc0`（绘制节点类型 1）画的是瓦片图层。tbg 块 `0x40` 处是 `[u8][u8 层数][u16]`，随后各层首尾相接：瓦片定义 0x24 字节（s16 x、s16 y、f32、12 个零字节、u16 瓦片数 @0x14、u8 瓦片宽 @0x16、高 @0x17、列数 @0x18、行数 @0x19、@0x1a、标志 @0x1b、RGBA @0x1c、u32 @0x20），然后瓦片表（每项 8 字节：s16 u、s16 v、u8 组、u8 picture、u8、u8），然后格子索引表（列×行个 u16，补齐到 4 字节），最后是块里唯一的 TIM2。每个格子一次绘制，CLAMP = 该瓦片矩形；图层可见区的首尾列/行按滚动量裁掉一截。147 块全部解析（`tbg_tiles.py`，`tbg_tiles_manifest.json`）：103,037 次瓦片引用，17,060 个不同的整瓦片矩形，常见 64×32、32×32、128×32、128×64、64×64、128×128。验证：2.6.3 里带 tbg 调色板的 1,070 张 dump 全部在解码图集里定位到，region 哈希 1,070/1,070 一致，其中 684 张是整瓦片、386 张是裁切零头，没有一张落在瓦片表之外。TWP/trb 块里没有这种瓦片层结构。

### 8.5 PSMT4 调色板

`FUN_002ef7d0 → FUN_00136150(pkt, CBP, bw=1, PSM=CT32, src, 64 qwc, …)`：每个调色板槽固定上传 1024 字节 = 256 色，CT32 16×16，CSM1 布局；PSMT4 绘制时 TEX2 的 CSA 来自部件字段（`+0x2e >> 3`）。对 77 个 PSMT4 dump 调色板的反推：256 色窗口起点可以是 TIM2 CLUT 的任意 16 色对齐位置（只按 256 对齐时少 2 个），窗口按 CSM1 8×2 交换重排后取第 `CSA*16` 起的 16 项，XXH3 即 PCSX2 的 CLUTHash，75/77 解释。按 PCSX2 源码，PSMT4 的 region 哈希同样是展开成每像素一字节后逐行哈希；`verify_region_hash4.py` 的端到端验证写成时还在跑，结果未记录。

### 8.6 这轮新增的工具

- `textures/tools/twp_parts.py`：容器/序列/对象流/记录解析器，`block_parts()` 返回每块的部件集合；命令行可单块自检。
- `textures/tools/twp_parts_manifest.json`、`trb_tci_parts_manifest.json`：静态枚举结果。
- `textures/tools/verified_dump_rects.tsv`：696 张 dump 的（块, TIM2, picture, x, y, w, h）。
- `textures/tools/verify_region_hash4.py`：PSMT4 对应的验证。
- `srwz-zh/work/analysis/ghidra/*.java`：headless 反编译/调用关系/字段写入搜索脚本。
