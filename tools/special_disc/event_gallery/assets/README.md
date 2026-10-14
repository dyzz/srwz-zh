# 事件演出入口横幅快照

`event-banner-picture.bin` 是原生 TIM2 共享 CLUT 第 6 图的 picture header 与 GS swizzled PSMT8 像素（1024×128，131120 字节）；`event-banner-clut.bin` 是第 6 组 256 色 CSM1 CLUT（1024 字节，PS2 opaque alpha=0x80）。实际艺术区 620×78，保留原特别剧场横幅的透明轮廓。

画面为内置 image_gen 根据本地美玲、原特别剧场风格参考生成的“美玲＋脉冲出场”底图。最终无字源图位于 `source/meyrin-impulse-background.png`，提示词和生成来源见 `source/imagegen-provenance.json`。

“事件演出”标题复用 `tools/special_disc/images/rebuild_banner1.py` 已有的确定性字形模型：项目锁定的 HarmonyOS Sans SC Regular，加粗、纵向压缩、黑色字墨、米黄外光、黑色两像素下划线。字形、字距、右边界与其他入口采用同一组参数，不使用生成图中的文字。

输入和输出哈希保存在 `asset-receipt.json`；`manifest.json` 锁定构建输入。正常构建直接消费此快照，不读取生成工具或字体，不重新量化或绘图。显式重作素材使用上一级 `author_banner.py`，依赖 NumPy 和 Pillow；先输出到临时目录检查预览，再替换锁定快照。

```sh
python3 tools/special_disc/event_gallery/author_banner.py \
  --background tools/special_disc/event_gallery/assets/source/meyrin-impulse-background.png \
  --crop 0 220 2169 293 \
  --outdir work/authoring/sp-event-gallery-ui-v2
```

`--crop` 为源图的左、上、宽、高；实际范围为 `(0,220)-(2169,513)`。来源模板和原字形参数路径记录在回执中，可通过命令行指定替代路径。

`event-banner.png` 与 `event-banner-preview@2x.png` 仅供视觉检查。横幅索引为 picture 5、palette bank 5。`banner.append` 将 CLUT 加入原 picture 0 的共享 CLUT 区，再追加 picture 5，保留原 5 图和原 5 组调色板。
