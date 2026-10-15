# 路线 A 静态转换：首版产出与回归（2026-10-15）

转换器 `textures/tools/convert_static.py`，规则见 [裁剪与命名规范](HD_TEXTURE_PACK_CONVERSION_SPEC_20261015.md)。输入：`btl/{twp,trb,tci,tbg}`、旧高清包、静态清单（`twp_parts_manifest.json`、`trb_tci_parts_manifest.json`、`tbg_tiles_manifest.json`）。产出目录 `textures/SLPS-25887/replacements/`，附 `convert_static_manifest.tsv`（每条矩形一行：新名、归档/块/组/picture、矩形、旧包源文件、状态）。BEST 盘用同一份：`ln -s SLPS-25887 textures/SLPS-73270`。

## 1. 产出

| 目录 | 文件数 | 体积 | 来源 |
| --- | ---: | ---: | --- |
| `BA-regions/` | 211,600 | 15 GB | twp 193,580 + trb 18,020 条矩形（含同一子图的不同调色板名） |
| `BAC-regions/` | 8,964 | 2.4 GB | tci 切入图 |
| `maps-regions/` | 63,361 | 4.0 GB | tbg 整瓦片 |
| 合计 | 283,925 | 21.4 GB | 全量跑 23 分钟 |

文件数比按贴图去重的估算（约 10 万）多，是因为同一个子矩形要为图集的每组调色板各出一个名字（PSMT8 每包 2 到 5 组，PSMT4 按窗口 × CSA），文件内容相同。

未产出的矩形（清单里有状态）：

| 状态 | 条数 | 含义 |
| --- | ---: | --- |
| `no-hd-source` | 95,271 | 图集在旧包里没有高清源（twp 77,668、trb 13,947、tci 654、tbg 3,002），按原生分辨率显示 |
| `no-such-picture` | 607 | picture 序号超出 TIM2 包张数（含 154 个 (0,0,8,8) 初始化占位） |
| `out-of-atlas` | 402 | 矩形超出图集边界，需要页回绕哈希，首版跳过 |
| `mode1-inset` | 11 | CLAMP 模式 1（内缩/镜像），首版跳过 |
| 整图 | 200 | region 覆盖整张图，旧包原名直接适用 |

## 2. 回归（`textures/tools/regress_static.py`）

| 样本 | 结果 |
| --- | --- |
| 696 张精灵 dump 名（2.6.3 实机） | 产出 678，缺 18；缺的全部是静态表里没有的动态矩形 |
| 1,070 张背景 dump 名 | 产出 500；386 张是滚动裁切零头（预期不产出）；182 张整瓦片的图集在旧包里没有高清源；2 张待查 |
| 50 张切入图 dump（PSMT8 512×512） | 产出 13；37 张不在静态部件表里（切入图滑入时宽度逐帧变化，如 (320,0,185,96)、(320,0,192,96)） |

精灵部分比静态交叉验证（635/696）多出 43 张，是因为同一子图在共用调色板的同机体其他块里也被引用，转换器对所有块都产出。

## 3. 关键修正

- tci 有 23 个包两张 picture 各带 CLUT，首轮把后一张的调色板套给了两张；现在每张用自己的 CLUT，没有 CLUT 的沿用同包前一张，PSMT8 名字按包内全部调色板组生成。
- 关键帧插值（`FUN_002ecfb0`，标志位第 5 位对宽高和 UV 做单精度线性插值）已在 `twp_parts.tween_parts` 里实现并试跑：生成 97 万个中间矩形，但一张 dump 都解释不了，默认关闭。残留的动态矩形不是这条规则产生的。

## 4. 残留与下一步

- 动态矩形：精灵 18 张（占 dump 样本 2.6%）、切入图 37/50、背景裁切零头 386/1,070。它们在任何块的部件表里都没有相等或包含的矩形，生成规则要靠路线 B 的小样本日志定位（钩子记帧时间、对象种类、流位置、滚动值）。
- `out-of-atlas` 402 条和 `mode1-inset` 11 条按规范第 5.2、5.3 节补做。
- `no-such-picture` 里 371 个非占位矩形的组/picture 语义待查。
- 验收：把 `textures/SLPS-25887` 链接到 ARMSX2 / PCSX2 的 `textures/` 下，开 `OsdShowTextureReplacements`，跑一场战斗看替换计数与边缘接缝。

## 5. 实机验收配置（2026-10-15 已就绪）

- PCSX2 v2.8.2（`/Applications/PCSX2.app`）与 ARMSX2 的 `textures/SLPS-25887/replacements/` 和 `textures/SLPS-73270/replacements/` 下各放了四个符号链接：`BA-regions`、`BAC-regions`、`maps-regions` → `textures/SLPS-25887/replacements/`，`face-r513` → `textures/SLPS-73270/replacements/face-r513`。
- PCSX2 ini（备份 `PCSX2.ini.bak-20261015-textures`）：`LoadTextureReplacements = true`、`OsdShowTextureReplacements = true`、`DumpReplaceableTextures = false`、`PrecacheTextureReplacements = false`（28 万个文件不要预缓存）。ARMSX2 只多开了 OSD。
- PCSX2 记忆卡槽 1 改为 `Mcd001-from-ARMSX2-20261015.ps2`（ARMSX2 当前 Mcd001 的 APFS 克隆，PCSX2 原卡未动）。
- ISO：`srwz-zh/build/iso/zh-release-original/current-original.iso`（当前汉化本体，序列号 SLPS-25887）；对照原版用 `srwz-zh/build/iso/sources/original.iso`。两者都在 PCSX2 的游戏列表路径里。
- 看什么：OSD 左上角的替换计数，战斗里机体部件是否高清、部件边缘有无接缝，背景整瓦片高清而滚动边缘一两格原生属正常；切入图目前只有约四分之一会命中。

### 5.1 首次验收结果

- 中场 PILOT 计数为 0 的原因：`textures/SLPS-73270/replacements/face-r513/`（9 月生成的 1,295 张头像）在 10-13 的磁盘清理中被删，链接指向空目标。已用 `convert_faces_r513.py` 重新生成（1,295 张），这个目录不要再清。
- 战斗：开 dump 跑一场后，带机体调色板的新 dump 只有 64 张，全部是块 155 的动态矩形（横向展开的 124×176、155×176、174×176 窗口和 26×24 之类的插值小块）；静态部件一张都没被 dump，说明它们都已命中替换。2.8.2 的 region 名与 2.6.3 一致（64/64 哈希重算相同）。
- 新 dump 归档在 PCSX2 `textures/SLPS-25887/dumps-20261015-282/`，旧的在 `dumps-20260726/`；ini 的 dump 已关回。
