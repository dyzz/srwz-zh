# 图片、地图名与图像写回结论

## 资源范围

固定本地化资产清单覆盖 14 个归档和 3 个直接成员：

- 发现 712 个原始 TIM2 magic；
- 706 个形成完整 TIM2 record；
- 共 1,146 个 picture；
- `VEFF2DX` 的 6 个剩余 magic 未通过完整记录边界，不计入覆盖。

机器事实源为 `manifests/asset-inventory.json`。该范围不等于原盘所有图像：PSS、
模型纹理、BTL/SEG 和其他未知格式仍需独立处理。

```bash
python3 tools/inventory_srwz_assets.py --force
python3 tools/export_srwz_images.py \
  --output work/assets/images-by-bin --jobs 8 --force
python3 tools/build_image_dashboard.py --force
```

导出的 TIM2、PNG、offset、格式、调色板和哈希只写入 `work/`。PNG 是浏览／审校
视图，不是可直接改名回填的 TIM2。

## 已确认的文字资源

### VT1 标题 atlas

标题 `START/LOAD/CONTINUE/LIBRARY` 已定位到：

```text
DATA/VT1.BIN / chunk 6 / TIM2 record 1 / picture 0
```

坐标级 PSMT8 writer 已将其替换为 `开始／读取／继续／资料库`：

- 同时覆盖选中与未选中状态；
- 只使用原有 CLUT index；
- 不改变 CLUT、其他 picture 或 TIM2 metadata；
- 运行纹理与离线 RGBA 哈希一致；
- PCSX2 v2.6.3 已取得标题画面与 texture dump 证据。

固定结果见 `manifests/title-menu-zh-validation.json`。该历史 canary 证明 writer
能力；当前综合 ISO 仍需重新执行目标画面验收。

### KVMDATA UI atlas

当前五张中文候选：

| chunk | 中文标签 | 目标场景 |
| ---: | --- | --- |
| 2 | 机体 | 信息页 |
| 4 | 指令菜单 | 战场命令 |
| 5 | 交易所 | 商店／Bazaar |
| 6 | 中场休息 | 幕间菜单 |
| 7 | 新建小队 | 编成 |

每张图都使用独立 mask、固定 container geometry 和 byte-exact 非目标区检查。
组件与单成员 ISO 的静态门已通过；五张图在当前综合 ISO 上的场景归属、截图和
texture delta 仍待验收。

### JTIM 与其他 TIM2

- `DATA/JTIM.BIN` 的 24 个有效 record 可渲染，包含标题副标、option、攻略、
  角色事典、用语事典、音响选择等图片文字。
- `DATA/MTV_ITEM.BIN` 的 8 个 record 可渲染，当前未确认必须翻译的栅格文字。
- VT1 其他 TIM2 主要是背景和普通纹理，没有证据表明存在第二套可扩展文字字库。

图片内文字必须逐 atlas 翻译和写回；扩展主字库不会改变这些像素。

## MAPNAME

`MAP/MAPNAME.BIN` 是 195 个固定 256-byte record：

```text
Shift-JIS payload + NUL + zero padding
```

当前结论：

- 195/195 条结构有效；
- 195 个稳定 ID，189 个唯一文本；
- 最长 payload 30 bytes；
- parser 已完成，writer 尚未晋级；
- 需要先证明目标运行路径使用主 codebook／renderer。

```bash
python3 tools/parse_srwz_map_names.py \
  --manifest-output manifests/map-name-parse.json --force
```

## Writer 能力与门禁

当前 clean-room writer 已支持：

- 固定 4-bpp 与 8-bpp indexed TIM2 读取、no-op 和受限原位写回；
- PS2 swizzle／unswizzle 与坐标级 index 编辑；
- shared CLUT／multi-picture 固定布局；
- mask 外 byte-exact、container size、metadata 和 CLUT 检查；
- 重新渲染 RGBA 与目标 PNG 对比；
- 归档重建、Rust 重压缩、SLPS offset 重读和 ISO 回包。

任何新图必须登记：

1. 成员、chunk、record、picture 和像素格式；
2. 文字 owner、译文、字体来源和布局；
3. 可修改 mask、允许的 palette/index 和原始前像；
4. no-op、byte delta、RGBA delta 和非目标区检查；
5. 当前 ISO 上的目标场景截图与 texture dump。

不得复制上游预制 `KVMDATA.BIN` 作为中文生产输入，也不得从离线外观猜测运行
场景归属。配置与可提交结论以 `config/assets/`、`config/canary/` 和对应
`manifests/` 为准。
