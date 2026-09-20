# Special Disc 关卡开场标题图片补齐

2026-09-20。用户反馈关卡开始时标题未汉化。

同日按用户要求收敛为唯一镜像：`build/iso/special-disc/sp-current.iso`。
下文候选路径是验证时的历史名称；提升为 current 后内容与 SHA-256 未变。

## 原因与范围

当前候选的 `DATA/VT1.BIN` 第 9 组（`0x4AA3910–0x4B0CFE0`）与日文原盘逐字节相同。
此前 `frame-text` 的话名写入了 COMPDATA 和流程图文本，未消费开场标题图片。新的写回器
在全量构建装配时消费冻结索引图，验证器从最终 ISO 重新检查。

原生组内有 27 个压缩流；前 6 个保留，后 21 个是 512×64 的 4bpp 标题。
内部偏移表在原生 ELF `0x3763E0`，关卡记录的 selector 对应内部流 `selector + 5`。
COMPDATA 的 24 个有效关卡记录对应 21 个 selector；重复分支共用一张标题图。
原生记录和译文 ID 一同锁定在 `config/assets/special-disc/stage-title-graphics.json`。

旧清单的“20 张”不能作为槽数：21 个槽中第 16、17 个日文像素完全重复，另有原生英文标题。
第 17 个 selector 属于“序章”，原图却重复了“この想いを君に”；现按其记录绑定写入“序章”，
这不代表已证明正常流程会显示该槽。第 15 个 `at the risk of pride` 保留原始压缩流。
其余 20 个槽使用审校后的话名，`Keep On Movin'` 保留完整英文和撇号。

## 构建约束

- `tools/special_disc/writeback/stage_titles.py` 只读冻结像素，普通构建不渲染字体。
- 作者入口 `tools/special_disc/images/freeze_stage_titles.py` 显式读取当前共享字库和审校语料，
  生成前后对照图供视觉检查；空白 ASCII 撇号使用共享字库中已分配的撇号。
- 沿用本篇 24 像素字模、横向二倍采样与居中规则。第 3、16 个槽用 8 级量化以满足
  原槽容量，其余新图为 16 级；不移动任何槽、ELF 表项、ISO 成员或后续 LBA。
- TIM2 头、CLUT、尾数据和非标题资源保持原字节。校验译文、原图、表、分支 selector、
  压缩结果与最终 ISO 回读；漂移拒绝构建。

## 对应表

| selector | STAGE 块 | 写入话名 |
| --- | --- | --- |
| 1 | 1 | 发令 |
| 2 | 2 | 接触 |
| 3 | 3 | 迷途 |
| 4 | 4 | 意义 |
| 5 | 5 | 黑之意志 |
| 6 | 7, 8 | 少年啊，胸怀大志！ |
| 7 | 9 | Keep On Movin' |
| 8 | 11 | 在这世界的正中央 |
| 9 | 13 | 热斗！战士的休息 |
| 10 | 14 | 迪拉尔的决意 |
| 11 | 15 | 被掘开的墓所 |
| 12 | 16 | 拭泪之翼 |
| 13 | 18 | 想吃，所以合体 |
| 14 | 19 | 奋战吧！阿蒂特老师 |
| 15 | 20 | at the risk of pride |
| 16 | 21 | 将这份心意献给你 |
| 17 | 23 | 序章 |
| 18 | 24, 25 | 沉眠的威胁 |
| 19 | 26, 27 | 悄然逼近的黑暗 |
| 20 | 28 | 执行者 |
| 21 | 29 | 跨越黑历史 |

## 验证记录

- 专项与本篇标题回归：18 项通过。
- 已逐张审看冻结图对照：`work/analysis/sp-stage-titles-20260920/frozen/contact.png`。
- 独立标题候选已完成 ISO 回读与受保护范围逐字节验证。21 个槽全部通过，20 个改写；
  其余 ISO 字节均与当前可用基线相同，文件大小、目录、成员 LBA 与内部表不变。
- 候选：`build/iso/special-disc/stage-titles/sp-zh-stage-titles.iso`，SHA-256
  `100b3dc442878247176e6585332462d63d3ef13b47a8cf00c890b2de72aa3f4f`。
- 全量构建接入已实现，但本轮全量重建没有完成：现有 frame-text 引发 HSFC 超过 3 行、
  旁白 14/13 行、梗概含共享字库未映射的“讥”。日志位于
  `work/analysis/sp-stage-titles-20260920/full-build-frame-errors.log`。未改写这些译文或放宽门禁。
  本轮输出由 `build_stage_title_candidate.py` 从保留的可用候选增量制作，不能当作当前
  全部语料已重新写入的证据；原 `full-text/sp-zh-full-text.iso` 保留不变。
- LRPS2 两轮从冷启动进入第一关：第一轮到达对白，第二轮推进战前对白后捕获中文
  **发令**，并正常进入地图。实际标题帧：
  `work/runtime/lrps2/sp-stage-titles-20260920/transition/frames/11100-transition-11100.png`。
  已直接审看标题和进图画面；原存储卡两轮均未变化。运行回执和逐图判断位于同目录
  `run/receipt.json`、`transition/receipt.json`、`visual-review.json`。
- 以上是第一关的 LRPS2 证据，不是全部 21 个标题逐关验证；PCSX2／用户人工验收仍待进行。
- 保留本轮之前的候选及清单于 `work/analysis/sp-stage-titles-20260920/before.*`。
