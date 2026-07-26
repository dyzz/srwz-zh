# 全量 TIM2 图片导出

`tools/export_srwz_images.py` 只读扫描原版 ISO，把严格通过结构校验的 TIM2
记录按来源成员和归档 chunk 导出到被忽略的 `work/assets/`。它不会修改 ISO、
BIN 或仓库内的原始输入。

## 运行

```bash
python3 tools/export_srwz_images.py \
  --output work/assets/images-by-bin \
  --jobs 8
```

已有输出时显式加 `--force` 重建。也可重复传入
`--member BTL/TWP.BIN` 做限定成员的检查。

目录层级为：

```text
by-member/<ISO member>/<chunk|direct>/<stored|decoded>/
  record-<index>_o<offset>/
    record.tm2
    picture-<index>.png
```

- `record.tm2` 是存储态或解压 payload 中经校验的原始 TIM2 记录，字节不变；
- `picture-*.png` 是每个 picture 的 PNG32 浏览预览；
- `manifest.json` 保存来源、offset、hash、TIM2 元数据和失败记录；
- `images.csv` 每个 picture 一行，适合按 BIN、尺寸、像素格式或调色板数筛选。

## 当前全量结果

当前输出位于 `work/assets/images-by-bin/`：

- 扫描 66 个 ISO 成员；
- 21 个成员含有效 TIM2；
- 2,641 个直接或归档 payload；
- 4,455 个 TIM2 记录；
- 9,999 个 picture，已生成 9,999 张 PNG，失败 0；
- 多调色板 picture 合计可形成 142,363 个 picture/palette-bank 视图。

## 本地图片 Dashboard

全量导出完成后，可生成不依赖服务器或外部 CDN 的单文件 Dashboard：

```bash
python3 tools/build_image_dashboard.py
```

输出为 `work/assets/images-by-bin/index.html`。页面直接引用同目录下的
`by-member/` 图片，提供 BIN、BPP、尺寸、存储视图和调色板筛选，支持隐藏重复
PNG、分批加载缩略图，以及在详情视图中打开原 PNG/TIM2 和复制路径。数据被内嵌
在 HTML 中，所以通过本地文件直接打开时不需要 `fetch()` 或本地服务。

## 多调色板与“近黑”预览

很多 4-bpp TIM2 记录保存多个 16 色调色板 bank。若把完整 CLUT 直接交给
ImageMagick，其 CSM1 调色板重排会把不同 bank 混在一起，picture 的 0–15
索引因而可能落到不相干的深色颜色上。这里没有做自动提亮或改像素，而是在每张
预览的临时单-picture TIM2 中隔离 bank 0：

- 4-bpp：16 色；
- 8-bpp：256 色。

因此 PNG 表示 bank 0 的原始颜色；精确的 `record.tm2` 仍保留全部 bank，
`manifest.json` 和 `images.csv` 的 `palette_bank_count` 可用于以后选择性导出
其他配色。

## 覆盖边界

当前“全量”指：所有原始 ISO 成员中的有效 TIM2、配置中的 SLPS offset
归档，以及全部成对的 BTL `.SEG`/`.BIN` 归档。PSS 视频、VT1 的 4,480 字形
原始字库、模型数据和尚无严格解析器的非 TIM2 图像格式不伪装成 PNG，统一记录为
coverage gap。
