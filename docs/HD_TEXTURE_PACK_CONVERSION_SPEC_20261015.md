# 旧高清包 → PCSX2 2.x 替换文件：裁剪与命名规范

2026-10-15。这是转换器要实现的规则，全部来自同日的研究与验证（[研究记录](HD_TEXTURE_PACK_PCSX2_2X_PORT_20261015.md)、[迁移方案](HD_TEXTURE_PACK_MIGRATION_PLAN_20261015.md)）。每条规则后面标注验证状态：**已验证** = 有实机 dump 逐字节对照；**源码** = 从 PCSX2 v2.8.2 源码读出、尚无 dump 对照。

## 1. 输入与输出

| 输入 | 位置 |
| --- | --- |
| 战斗归档 | `srwz-zh/work/build/zh-release-full-story/iso/original/btl/{twp,trb,tci,tbg}.bin` + 同名 `.seg`（LZSS 块，`srwz.codec.decode_production`） |
| 旧高清包 | `~/Downloads/机战ZSLPS-25887 SLPS-73270/replacements/{BA,BAC,addition,maps,face,ui}`，名字 `TEX0Hash-CLUTHash-bits.png`，4 倍整图 |
| 静态部件清单 | `textures/tools/twp_parts_manifest.json`、`trb_tci_parts_manifest.json`（`twp_parts.py` 生成） |
| 回归样本 | `textures/tools/verified_dump_rects.tsv`（696 张 2.x dump 的归档块、picture、矩形） |

输出：`textures/SLPS-25887/replacements/<来源>-regions/TEX0Hash-CLUTHash-rWxH-bits.png` 与 manifest TSV；SLPS-73270 目录指向同一份。

## 2. 图集解码（已验证）

1. 块内 TIM2：`twp_texture_manifest.tim2_pictures()`；picture 头的 `itype` 5 = PSMT8、4 = PSMT4；`ctype` 3 = RGBA32 调色板。
2. 像素不是线性的，是“当 PSMCT32 上传”的布局：
   - PSMT8 W×H：`unswizzle8_any`（`_psmt8_stored_offset`，等价于 CT32 (W/4)×H 光栅上传）。
   - PSMT4 W×H：`unswizzle4_any`（CT32 (W/2)×(H/4) 光栅，DBW = W/128；由 PCSX2 的 blockTable/columnTable 推出，`psmt4_512x256_perm.npy`）。
   得到逻辑行优先的索引图 `idx[H][W]`（PSMT4 也是一字节一像素，值 0..15）。
3. 一个 TIM2 包里没有 CLUT 的 picture 共用同包第一张的 CLUT。
4. 贴图组：块内按 TIM2 包偏移排序，第 0 组 = PSMT8 包，第 1 组 = PSMT4 包；picture 序号按包内顺序。

## 3. 整图名（旧包的名字，用来找高清源）（已验证）

- `TEX0Hash_full` = XXH3-64，按 16×16（PSMT8）/ 32×16（PSMT4）块行优先，块内按 columnTable8 / columnTable4 顺序取字节（PSMT4 两像素一字节，低 nibble 在前）。`archive_texture_hashes.hash_blocks8 / hash_blocks4`。
- 这个算法新旧 PCSX2 一致；用它把旧包 BA 3,169/3,213、BAC 335、maps 601 对回光盘图集。
- 查表：`(TEX0Hash_full, CLUTHash)` → 旧包文件；同一张图集两组调色板对应两个旧包文件，内容相同，取任一。

## 4. 部件枚举（已验证）

`twp_parts.block_parts(block)` 走容器 → 每个表集（一个块可有多个，TWP 136 块有第二表集）→ 序列 blob → 对象流 → 关键帧记录，状态在流内累积。只要状态里同时有第 7 位（w, h）和第 8 位（u, v）就产生一个部件：

| 项 | 来源 |
| --- | --- |
| u, v | 第 8 位字段两个 u16，各 `& 0x1ff` |
| w, h | 第 7 位字段两个 u16 |
| 贴图组、picture | 第 9 位字段末字节：`set = b3 & 3`，`pic = (b3 >> 2) & 0xf` |
| 调色板槽、CSA | 第 9 位字段第 3 字节：`slot = b2 & 7`，`csa = b2 >> 3` |
| CLAMP 模式、镜像 | 第 11 位字段第 2 字节：`mode = b1 & 3`，`flipX = b1 bit 2`，`flipY = b1 bit 3` |
| 内缩 | 第 10 位字段四个 u8：`ins0..ins3` |

按 `(图集哈希, region)` 去重；同一张 picture 在多个块出现时只算一次。

## 5. region 矩形

### 5.1 默认模式（mode ≠ 1，占 99.9%）（已验证）

```
region = [u, u+w) × [v, v+h)      # 游戏写 CLAMP = REGION_CLAMP, MINU=u, MAXU=u+w-1, MINV=v, MAXV=v+h-1
名字 -rWxH = -r{w}x{h}
```

PCSX2 只在 `w < 512 或 MAXU >= 512`（V 同理）时建 region；整轴覆盖时该轴写 0：`-r{w}x0`、`-r0x{h}`，整图则无 `-r` 段。

### 5.2 模式 1（内缩 / 镜像，454 次引用）（源码）

```
非镜像 X: MINU = u + ins0,  MAXU = u + w - ins1,  WMS = REGION_CLAMP  → X 区间 [MINU, MAXU+1)
镜像   X: MINU = ins0 - 1,  MAXU = ins1,          WMS = REGION_REPEAT → X 区间 [MAXU, (MINU|MAXU)+1)
V 轴用 ins2 / ins3 同理
```

转换器先把这些部件单独列出，等有 dump 对照再产出。

### 5.3 越界部件（u+w > 512 或 v+h > 256，3,036 次引用）（部分验证）

PCSX2 仍建 region，哈希会读到贴图外的 VRAM：列 512 回绕到 `(0, y+64)`（TBW=8），行 256 之后读到相邻页。头像的 `-r513x513` 已按此复现，但相邻页内容取决于运行时 VRAM 布局，战斗部件需要用 dump 确认后再定规则。先单独列出。

## 6. 子矩形哈希（已验证 PSMT8；PSMT4 为源码）

```
TEX0Hash_region = XXH3_64( idx[v:v+h, u:u+w] 按行连续的字节 )
```

- PSMT8：一像素一字节，`w` 字节一行。696/696 张 dump 一致。
- PSMT4：PCSX2 先把索引展开成一字节一像素再哈希，所以同样是 `w` 字节一行、值 0..15。`verify_region_hash4.py` 验证中。
- 只有一轴有 region 时，另一轴取整轴（u=0 宽 512 或 v=0 高 256）。
- 工具：`verify_region_hash.py` 的 `M.xxh3(np.ascontiguousarray(sub).tobytes())`。

## 7. 调色板哈希

### 7.0 调色板归属（已验证，tci 教训）

一个 TIM2 包里可能有多张 picture 各带 CLUT（tci 有 23 个包）。每张 picture 用自己的 CLUT，没有 CLUT 的沿用同包前一张；PSMT8 的名字按包内全部 256 色组各出一个（调色板槽是按包分配的，tbg 的瓦片表第 6 字节就是组号）。

### 7.1 PSMT8（已验证）

```
bank = clut[k*256 : (k+1)*256]           # TIM2 里 512 色 = 两组
entry[i] = bank[csm1(i)],  csm1(i) = (i & 0xE7) | ((i & 8) << 1) | ((i & 0x10) >> 1)
CLUTHash = XXH3_64( 256 × u32 小端 )
```

每组各出一个名字；部件的 `slot` 决定运行时用哪组，但两组都生成最稳妥（文件内容相同）。

### 7.2 PSMT4（已验证 75/77）

```
window = clut[c0 : c0+256]，c0 为 16 的倍数（槽指针可落在任意 16 色对齐处）
sw[i] = window[csm1(i)]
CLUTHash = XXH3_64( sw[csa*16 : csa*16+16] )
```

静态产出时 `c0` 的候选取 TIM2 CLUT 里所有 16 对齐起点，`csa` 取部件字段，无法确定时对同一子矩形生成全部候选名（文件内容相同，只是名字不同）。

## 8. bits 字段

`bits = PSM | TW<<6 | TH<<10 | TA0<<15 | AEM<<23 | TA1<<24`（旧包多出的 bit 14 是旧 TCC 位，新版解析时清零，产出时不写）。

| 格式 | PSM | TW/TH | bits |
| --- | --- | --- | --- |
| PSMT8 512×256 | 0x13 | 9 / 8 | `00002253` |
| PSMT8 512×512 | 0x13 | 9 / 9 | `00002653` |
| PSMT4 512×256 | 0x14 | 9 / 8 | `00002254` |
| PSMT4 512×512 | 0x14 | 9 / 9 | `00002654` |

TA0/AEM/TA1 对索引格式为 0。

## 9. 裁剪与写出（已验证规则）

```
src = 旧包 PNG（4×：2048×1024 或 2048×2048）
crop = src[4v : 4(v+h), 4u : 4(u+w)]          # 默认模式；模式 1/越界用第 5 节算出的 region 矩形
保存为 RGBA PNG，名字 {TEX0Hash_region:x}-{CLUTHash:x}-r{w}x{h}-{bits:08x}.png
```

- 不重采样、不做边缘处理；PCSX2 按 region 采样，边缘双线性与原版一致。
- 越界 region 的裁剪只取图集内部分，图集外像素透明（PCSX2 的回绕像素来自别的贴图，不属于本图）。
- 同名文件已存在则跳过（不同调色板组对应不同名，内容相同）。
- 旧包没有该图集的，不产出，记入 manifest。

## 10. 回归与验收

1. 名字回归：`verified_dump_rects.tsv` 中 602 张可静态复现的 dump 名必须出现在产出名集合里，精确字符串相等（含 `-rWx0` 形态）。
2. 抽样像素回归：对 20 张 dump，用产出 PNG 缩回 1/4 后与 dump PNG 比较，应逐像素相同。
3. 实机：PCSX2 2.8 和 ARMSX2 开 `OsdShowTextureReplacements`，一场战斗替换计数与路线 D（整图开关）接近。

## 11. 背景瓦片（tbg，maps 文件夹）（已验证）

- 枚举：`tbg_tiles.py` 解析每块的图层、瓦片表（s16 u、s16 v、u8 组、u8 picture）与格子索引，整瓦片矩形 = `[u, u+tw) × [v, v+th)`，147 块共 17,060 个不同矩形。
- 哈希、调色板、bits、裁剪规则与精灵部件完全相同（PSMT8 512×256）；1,070 张背景 dump 的 region 哈希全部一致。
- 裁切零头（图层首尾列/行被滚动量切掉一截，dump 里占 386/1,070）不静态产出，由路线 B 补。

## 12. 本规范不覆盖的部分

- 来源动态的矩形：精灵 dump 的 18/696、切入图 dump 的 37/50、背景裁切零头 386/1,070。关键帧插值（`FUN_002ecfb0`，标志第 5 位，单精度线性插值后截断）已实现为 `twp_parts.tween_parts` 但解释不了这些 dump，默认关闭；生成规则待路线 B 的小样本日志定位。
- face 中场以外的画面、ui 的 19 张未定位图。
- picture 序号超出包内张数的 371 个矩形，含义待查；(0,0,8,8) 默认占位的 154 个不产出。
