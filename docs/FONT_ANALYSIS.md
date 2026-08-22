# VT1 字库、码位与容量结论

## 字库格式

主字库位于 VT1 第 2 段：

- decoded size：1,290,240 bytes；
- glyph 数：4,480；
- 每个 glyph：`24×24`、4-bpp、288 bytes；
- 每行 12 bytes，共 24 行；
- 每字节低 nibble 是左像素，高 nibble 是右像素。

`decode_glyph()`、`encode_glyph()` 和 `replace_glyph()` 已有 byte-exact round-trip
测试。VT1 内其他 TIM2 是背景／纹理，不是第二套主文字字库。

这些结构结论由 `tools/srwz/font.py` 的 byte-exact 单测和当前
`manifests/zh-release-font-validation.json` 固定；原版 decoded 字库与临时渲染图
只位于被忽略的 `work/`。

## Renderer 映射

普通双字节路径：

```text
glyph = (lead - 0x81) × 192 + (trail - 0x40)
```

`0x989F` 及以上进入 SLPS 的扩展查找表。固定原版文本表共有 6,860 个双字节
映射，其中 3,488 个普通 code 加 216 个扩展 code，共 3,704 个 code 已静态
映射到 3,704 个不同 glyph。

4,480 个 glyph 中未被该文本表引用的 776 格不等于安全槽：它们仍可能被硬编码
UI、raw trail 或 direct-index 路径使用。

单字节可打印 ASCII 使用固定索引 191–286，并跳过 253；这 95 格必须保留其
renderer 身份。`$n/$F` 和 printf token 保持原始 ASCII 运行语义，不走中文
override。

## 全局发布字库

当前唯一活动字库使用 append-only 分配账本和同一生产字体／几何规则：

- 新 assignment 只追加，不重排已有字符；
- 已占用映射不重排；未被当前发布映射占用的原日文双字节位置可作为后续中文
  候选。ASCII、控制码、已占用主映射／别名和结构兼容映射继续保留；
- 字符、code、glyph、字体、前进宽度和使用者均由 config／manifest 固定；
- VT1 offset 表与字库内容原子更新；
- 字体需求必须从实际写回闭包计算，不能只扫描被选语料文件。

基础 UI 以 `release-base-ui` 四成员基线输入，不拥有独立发布字库。

## 字槽方案

标准 resolver 对 4,480 个 glyph 可建立完整顺序映射：

```text
glyph 0    -> code 8140
glyph 191  -> code 81FF
glyph 192  -> code 8240
glyph 4479 -> code 987F
```

最终布局：

- glyph 191–286：保留 95 个可打印 ASCII 固定索引；
- glyph 287 起：按 glyph index 连续建立中文 registry；
- 可用连续中文槽：4,193；
- 当前主映射：3,450；
- surface-safe 别名：48；
- 可回收双字节追加候选余量：101；
- 当前语料静态可容纳。

初始 registry 一旦冻结便只追加，不因语料集合或排序变化而重排。原日文字形身份
不是容量门，但实际 direct-index 非文本 glyph 必须先进入显式保留表。

## 晋级门禁

全量字库进入生产 ISO 前必须：

1. 物化 append-only registry 和固定 ASCII glyph；
2. 覆盖每个 standard resolver 行；
3. 覆盖实际使用的 `0x7F/0xFD/0xFE/0xFF` raw trail 类；
4. 扫描 MAPNAME、硬编码 UI 和 direct-index 读取；
5. 验证完整 decoded-font SHA-256；
6. 在当前精确 ISO 上检查代表性中文、ASCII、标点、数字和边界 glyph；
7. 分开记录“完整字库加载通过”和“目标画面显示正确”。

容量、`missing=0`、离线渲染和旧候选截图都不能替代上述 runtime／visual 门。
