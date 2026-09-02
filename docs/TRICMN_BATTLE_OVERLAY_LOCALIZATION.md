# TRICMN 战斗浮层贴图中文化

本文记录 `BTL/TRICMN.BIN` 中战斗浮层文字的所有权、4-bpp 索引语义、确定性生成
方法和验收边界。这里的文字已经预绘制进 TIM2，不是运行时字库文本；导出的 RGBA
PNG 只能用于观察，生产写回的事实源仍是原始索引图、共享 CLUT 和登记矩形。

## 1. 文件与图集结构

| 项目 | 当前值 |
| --- | --- |
| 成员 | `BTL/TRICMN.BIN` |
| 原版大小 | 677,424 bytes |
| 原版 SHA-256 | `3350ca529599ddc884b718eed635d067159e14ade3d642909b199138225ebac5` |
| SEG | `BTL/TRICMN.SEG`，24 bytes，保持 byte-exact |
| SEG offsets | `0, 32, 486704, 548960, 617728, 677424` |
| 文字 TIM2 record | member offset `222560`，size `264144` |
| picture | 4 张 `512×256` PSMT4；前三张含文字，picture 3 保持不变 |
| 背景索引 | `0`，28 个 CLUT bank 中均透明 |
| 侧壁／暗部 | indexes `1..7` |
| 亮面 | indexes `8..15` |
| CLUT | 28 个共享 bank，写回时全部保持 byte-exact |

同一索引在不同 CLUT bank 中会显示成不同颜色和透明度。游戏运行时仍会经过 GS
纹理采样；因此“导出 PNG 看起来相同”不代表索引可互换。索引范围承担材质层级，
不能先合成 RGBA 再任意量化回 4-bpp。

完整目标共 51 项：

| picture | 分组 | 数量 | 典型内容 |
| ---: | --- | ---: | --- |
| 0 | 大号队形／攻击标题 | 12 | `TRI队形`、`单体攻击`、`援护攻击` |
| 1 | 大号提示／不可用原因 | 10 | `待机`、`无目标`、`（弹数）` |
| 1 | 右侧状态提示 | 10 | `运动性下降`、`EN下降`、`完全抗性` |
| 2 | 能力名与括号框 | 19 | `盾牌防御`、`VPS装甲`、`精神感应力场` |

picture 3、record `89840` 的两张非文字效果图、数字、Latin 标识、`CRITICAL`、箭头、
括号模板和非目标像素均不属于自由重绘区域。

## 2. 大号队形／攻击标题的最终材质

2026-08-31 的实机比较确认，大标题不是普通描边字。日版表现接近旧式 WordArt：
纯平高亮正面、下右方向的深色挤出、正面外缘的浅色反光，以及透明背景上的柔和
光晕。黑色毛刺的根因不是字体本身，而是把承担深色侧壁的索引写到透明边界后，
GS 线性过滤把该 texel 扩散到轮廓外。

当前 `source_wordart_3d_index_layers` 按以下顺序构造原生索引图：

1. 在 8 倍分辨率渲染矢量字形和描边；
2. 建立正交高度场、右下挤出、外部低覆盖光晕和正面平台；
3. 一次性将完整几何层映射到 PSMT4 索引，而不是逐点修复成图；
4. `1..7` 仅用于从边界向内的侧壁／挤出；
5. 源 halo 中像素数最多的亮层用于硬反光边，去除它后像素数最多的亮层用于柔化外缘；当前 12 个标题均得到 `12` 软边、`14` 硬边，不能把零星覆盖样本按索引大小误判成独立材质层；
6. 正面斜边统一使用源图中占比最高的次亮面索引 `13`；
7. 真正的平顶使用最亮索引 `15`；
8. `13/15` 的面积比例逐标题读取日版源图正面分布，用平台高度分组映射；
9. 最后下采样到原生 `512×256`，不执行 TEX1 反向搜索，也不做结果级单像素修补。

配置中的最终大标题参数为：

| 参数 | 队形标题 | 攻击标题 |
| --- | ---: | ---: |
| point size | 31 | 30 |
| outline stroke | 3.0 | 3.0 |
| fill stroke | 0.8 | 0.8 |
| 默认字距 | 5.0 | 6.0 |
| 斜度 | 8° | 8° |
| supersample | 8× | 8× |
| shadow offset | `(2,2)` | `(2,2)` |

`单体攻击` 的字距单独为 `7.0`。大标题的结构断言要求：

- 最外边界只能出现该源图的浅色 fringe/rim 索引；
- `1..7` 的最小边界深度至少为 2；
- 正面必须同时存在 `13` 和 `15`，两者不能退化为单一平面；
- 所有等高／等覆盖像素共享同一索引，禁止在同一几何层内任意切割；
- CLUT、TIM2 header、其他 picture 和矩形外像素保持 byte-exact。

代表性源图比例已经在输出中复现：

| 标签 | 日版正面 index 15 占比 | 中文输出占比 |
| --- | ---: | ---: |
| `TRI队形` | 约 47% | 47% |
| `单体攻击` | 约 51% | 51% |

这会保留日版最高亮度，但缩小运行时被采样成纯白的面积；不得通过修改共享 CLUT
来单独压暗某个标题。

## 3. 其余三类材质的分组生成规则

其余 39 项仍共享 PSMT4 和 CLUT，但不能直接复用大标题的 `13/15` 双层平面：

### 3.1 大号提示／不可用原因（10 项）

这组的几何仍是纯平正面、右下挤出和柔化外缘，但活动 CLUT bank 0 将正面
indexes `8..15` 解释为一套非单调蓝色材质，而不是可以按 index 大小排序的灰阶：

```text
8  323541ca    9  363b51f6   10 04237aff   11 132d7bff
12 4c5575ff   13 34406cff   14 293a76ff   15 1f3479ff
```

因此这组继续采用 `source_wordart_3d` 的结构化分区量化：每个日版标签分别统计
halo、side、face 的源索引直方图；中文矢量几何以 8 倍分辨率生成后，将相同空间
评分的像素作为一个整体分配到源图的索引份额。正面必须保留完整 `8..15`，最外
低覆盖 fringe 使用源图的深色 halo index `1`。不得启用 `heightfield_flat_face`，
也不得按显示亮度重排这八个蓝色索引。

其中 6 条括号原因统一使用零额外 fill stroke。28px 中文字体本身已经提供完整字面；
继续追加 0.9px 会让“缺”“气”“射”“能”等内部结构在原生分辨率下粘连。4 条大号
战斗提示仍保留各自 `prompt`／`prompt-long` 的 0.9px 参数，不受这一子组调整影响。

`（欠員）` 译作槽位等宽、较自然的 `（缺人）`；`（成员不足）` 会超出原生
`106×40` 固定矩形，不能靠缩小字号破坏同排一致性。

### 3.2 右侧状态（10 项）

状态字只有 24px 高，并与 15px 箭头模板组合。它的材质顺序与大标题不同：日版
原始贴图是深色字芯、亮色包边，字芯使用 `1..7`，包边与 halo 使用 `8..15`。
因此这组采用 `source_wordart_3d_dark_core`，在下采样前明确把字体 fill 作为深芯、
outline 作为亮面；不能将实心中文字体整个量化为亮色 face，否则活动紫色 CLUT 下
会出现白色噪块。各层内部仍逐标签复用源索引比例。

矢量描边、挤出和 glow 全部在 8 倍分辨率完成，原生分辨率只做一次下采样和一圈
连通低覆盖 edge filter。原版状态字的最外层是浅色反光，因此 anti-alias fringe
只允许使用源图的 `12/14`。箭头在清空整个 128×24 slot 后
从日版模板 byte-exact 复制，避免残留日文字素。

2026-09-01 的 `运动性下降` 实机截图又确认中文状态字比日版字面偏小，但额外
`0.6px` fill stroke 令内部笔画更粗。日版同槽、同一活动紫色 CLUT 和线性采样下的
并排对照最终统一采用 19px、1.2px 外描边、零额外 fill stroke 和 0.6px 字距；这会
把 `运动性下降` 的字面宽度从 90px 提到 100px，同时保留复杂汉字的内部负空间。
随后 `运动性下降`、`瞄准值下降` 两张实机截图确认字芯和字号已经合适，但中文的
白色柔光仍比日版少约一圈；状态组只将 glow radius 从 1px 增至 2px，不再改变字面
尺寸、描边、字重或紫色材质分层。

十行日版三角标记的几何相同，但边缘有 19 个位置存在轻微 palette index 差异。
模板不能把所有“不完全一致”的位置清为透明，否则右尖端两个多数为 index 4 的阴影
像素会被挖空，旁边的 index 7 就会成为孤立深点。当前按十个日版样本逐像素取众数，
平票时取较高索引；再将这个模板复制到十行，以连续保留原版尖端阴影和柔化边缘。

### 3.3 能力名与括号框（19 项）

能力名位于三个固定 160×24 框模板内，文字只允许写入各自 128×24 inset；括号、
空槽和三种模板不得由字体渲染器重建。它们同样使用 8 倍矢量效果和一圈连通边缘
滤镜，但 halo 必须逐标签从源图读取，不能套用状态字的浅色外缘。三类剩余标签均
保持 `dark_component_minimum_pixels=1`，即不启用结果级“寻找黑点再替换”的修补；
边缘由生成方法一次完成。

19 个能力名同为 24px 高小字。连续轮廓字体即使取消额外 fill stroke，复杂字的斜边
仍会在最终线性采样中形成局部模糊或深色毛刺。当前能力组改用锁定的 Fusion Pixel
12px Proportional zh_hans 2026.05.07：字身按原生 12px 整数像素栅格直接生成，描边、
字符附加间距、超采样和 indexed edge filter 全部关闭。字形 mask 因而只有 `0/255`
两级覆盖；材质层继续复用每条日版自己的源索引直方图，外加 3px glow 和右下 2px
阴影。三种括号框仍从原版空模板 byte-exact 恢复。

## 4. 事实源、实现与重建

- 译文：`corpus/zh/ui-atlas/tricmn-battle-overlays-v1.json`
- 结构、矩形、字体与渲染参数：`config/assets/tricmn-battle-overlays-zh.json`
- writer：`tools/srwz/tricmn_battle_overlay.py`
- 构建入口：`tools/build_tricmn_battle_overlays.py`
- 静态结果：`manifests/tricmn-battle-overlays-zh-validation.json`
- 回归测试：`tests/test_tricmn_battle_overlays.py`

单独重建：

```bash
python3 tools/build_tricmn_battle_overlays.py --force --refresh-manifest
python3 -m unittest tests.test_tricmn_battle_overlays
```

合入当前组件并写 ISO：

```bash
python3 tools/compose_full_story_library_components.py
python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json \
  --refresh-output-locks
python3 tools/verify_full_story_iso_content.py --force
```

## 5. 当前验收边界

用户在 2026-08-31 对当前大标题方案给出“完美”的运行观感确认。对应候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   a9992f514e73a05da32f43421035ab66ddd2f317fe8b45ecd93c7930ddd35807
TRICMN:    02cf8c527fc6bc1599dc6bfefeba01092469dae738822d7ed344cd7bc40e7fc4
```

这项确认只覆盖 12 个大号队形／攻击标题的当前材质方向，不能自动关闭其余 39 项的
运行验收。

2026-08-31 又完成了其余三组的结构化边缘与材质分层，当前待实机测试候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   d02813daf64fc47b24c017794b40ae16bcc9db59758802a9f58096b246a07812
TRICMN:    838f3128ac1c718cd518f29b6b3630ea6129f35218765b4a48fcfec5fed3b098
```

当前候选已通过 17 项组件回归、固定 LBA／sector budget 构建和最终 ISO 独立成员读回；
`BTL/TRICMN.BIN` 从 ISO 读回与组件 byte-exact。组件仍保持 `runtime_pending`，直到
大号提示、右侧状态、能力框、随机动画成员和所有活动 CLUT bank 的透明度分别得到
该精确 ISO 的截图验证。

2026-09-01 的运行截图确认其余攻击标题可接受，但发现三个窄问题：`TRI攻击` 仍有
黑点、`瞄准值下降` 不清晰、`（射程）` 的“射”字笔画粘连。索引对照给出的根因与
修复如下：

- `TRI攻击` 日版 halo 只有 2 个 index 13 覆盖样本；旧规则按索引大小把它扩展成
  整圈 362 个软边像素。新规则按源层人口选择，软边固定回主导 index 12，输出
  外边界只含 `12/14`。
- 日版状态字是 `1..7` 深芯、`8..15` 亮边，而此前中文把实心字面当作亮面。整组
  状态改为结构化暗字芯模式；随后再按日版字面尺度统一为 19px，取消额外 fill
  stroke，并将亮边收窄到 1.2px。
- 6 条括号原因保留完整蓝色正面 `8..15` 和字号，统一去掉额外 0.9px fill stroke，
  避免“缺”“气”“射”“能”等复杂字的内部笔画粘连。

修正后的待实机复测候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   12398ce814468407fcfa014b4dd37834fe2c64d4078a52d9227c252bac3fb85e
TRICMN:    2f9f3ad2057f69ede8eb5608cbeae13b3769f5566be93046e4ff10889288b395
```

该候选通过 17 项组件回归、固定 LBA／sector budget 构建及最终 ISO 内容验证；ISO
清单中的 `BTL/TRICMN.BIN` 大小为 677424、SHA-256 与组件一致。以上三项的新运行
观感仍为 `runtime_pending`，不能用贴图预览或 ISO 读回代替截图验收。

同日后续的 `运动性下降` 截图显示状态组已经可读，但中文字面仍比日版小且笔画略粗。
按日版同槽、活动紫色 CLUT 和线性采样对照，将十条右侧状态统一放大并减重；本轮只改
picture 1 的十个状态文字矩形，箭头、大标题、不可用原因、能力框和共享 CLUT 均不变。
待实机复测候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   c3e242f41871c5640cbeecdf50894ce040beaa11dc55828e3bb4e3fcbb9f325c
TRICMN:    7efa86073f3df019e195c8d5018c75329953e41e37584ad740f258ccf9f7e607
```

该组件通过 17 项专门回归；从当前 ISO 直接提取的 `BTL/TRICMN.BIN` 与组件 byte-exact，
相邻 `BTL/OP2.BIN` 和 `BTL/SRVC.BIN` 写入前后哈希不变。由于工作区另有未闭环的
SRVC 输入漂移，本轮采用固定 LBA 单成员写回，没有把这项截图验收表述成全盘生产验证。

上述 ISO 的 `运动性下降`、`瞄准值下降` 两张实机截图确认 19px 字面、零额外 fill
stroke 与内部负空间已经合适；同时截图仍显示中文白色柔光比日版少约一圈，且共享
三角标记的右尖端有一个孤立深色点。后者不是单独坏像素，而是旧模板把十个日版样本
中 19 个色阶不完全一致的位置全部清为透明，误删了 12 个多数前景像素所致。

状态组最终候选将 glow radius 从 1px 增至 2px，并把三角模板改为十个日版样本的
逐像素众数（平票取较高索引）。其余字号、字重、紫色分层与其他 41 项贴图不变：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   df975ef58b045117a293aca524a03af5132197be16d5467942438eeb1f37d457
TRICMN:    d06cb1059a3b34f5277a929af14d1f26f30825f8ec832eb12b808d03c736f6d4
```

该候选通过 17 项专门回归；ISO 固定 LBA 直接读回与组件 byte-exact。写入前后
`BTL/OP2.BIN` 分别保持 `d9835799…7fadf`，`BTL/SRVC.BIN` 分别保持
`fb0fc670…6a36b`，因此本轮仍只证明 TRICMN 单成员写回，不替代全盘验证或新一轮
PCSX2 截图验收。

同日继续按日版同槽、活动粉色 CLUT 和游戏线性采样对照处理 19 个机体特殊能力名。
旧版能力组的 0.6px 额外 fill stroke 会压缩“盾／斩／分／潜／层／镜／场”等复杂
字的内部负空间，而 1px glow 又不足以形成日版那种连续浅色外圈。最终保留 17px
字面、1.8px 外描边、逐标签源 halo 索引和三种 byte-exact 括号框，只将额外 fill
stroke 归零并把 glow radius 扩至 2px。线性过滤同尺寸对照位于：

```text
work/review/tricmn-battle-overlays-zh/ability-tuning/reference-vs-candidate-bank11-linear-2x.png
```

写入后的待实机复测候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   a621a01ba08a4ceea26734a22bdef0f9ea8e0b4daaaa129b2b79ab366beab7fc
TRICMN:    c8669aff6e3dfead6093ac3ed8bcd02cfbaf30e77cd2480f1b5d15e30bb16c23
```

该候选通过 17 项专门回归；报告确认能力框从日版空模板恢复、替换像素未越过锁定
矩形、CLUT／alpha／TIM2 头／非目标逻辑像素均保持。ISO 固定 LBA 直接读回与组件
byte-exact，写入前后 `BTL/OP2.BIN` 与 `BTL/SRVC.BIN` 哈希不变。本轮仍是
TRICMN 单成员静态写回，19 个能力名的最终观感保持 `runtime_pending`，需要在游戏中
触发相应机体特殊能力后截图确认。

随后的运行反馈要求这些小字的高亮正面笔画严格保持 1px，并避免连续字体在斜边产生
毛刺。能力组因此改用官方 Fusion Pixel 12px Proportional `zh_hans` 2026.05.07。
生成器按 profile 加载独立、锁定的字体 flavor；能力字面关闭描边、额外 fill stroke、
超采样和 indexed edge filter。构建报告与回归测试同时要求每条能力名的 fill mask
不存在 `1..254` 灰阶覆盖，而且输出 face 像素数必须与原生字体的 `255` 覆盖像素数
完全相等。3px glow 与右下 2px shadow 仅写入字面之外的材质层，不得扩张 1px 高亮
字面。最终线性过滤对照位于：

```text
work/review/tricmn-battle-overlays-zh/ability-fusion12/reference-vs-candidate-glow3-bank11-linear-2x.png
```

写入后的待实机复测候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   ca07c0f15fdacef0ef682e00b16a8c4c2254218c87c0c0f3e3835ff57d7aad2f
TRICMN:    164ab4c4c7b66faddd2fc32a6c8c894163d2c192b16815fd3ff231d5ab2fe80a
Fusion:    7dda18bac79c841a9a545c45b3c2d9d00f1cbbca3217fd8d291dd27298932bbb
```

该候选通过 17 项 TRICMN 专门回归，独立组件与全故事集成组件 byte-exact；ISO 固定
LBA 直接读回也与组件一致。写入前后 `BTL/OP2.BIN` 与 `BTL/SRVC.BIN` 哈希保持
不变。以上仍为静态和 ISO 回读证明，能力名的最终线性采样观感保持
`runtime_pending`，等待实际特殊能力提示截图。

同日的状态组整图对照又发现中文文字的左侧光晕与共享三角尖之间多留了 1 个逻辑
像素。状态 profile 的 `ink_left` 因此从 1 改为 0：十条中文状态文字整体左移 1px，
而 `status-chevron` 仍从日版模板逐字节复制，标记矩形、文字矩形、字号、字重、光晕、
共享 CLUT 和其余 41 项标签均不变。像素级日版／中文对照位于：

```text
work/review/tricmn-battle-overlays-zh/status-left-join/reference-vs-candidate-bank11-nearest4x.png
```

写入后的待实机复测候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   2ee2409d16f1153affe0dec045d8099543a2c157010a870ab942a09604922d49
TRICMN:    5b1dc1e1c6cf9b2df8f16c226c58214764257df09439d14dbd4e7e8c6ecfe899
```

十条状态文字的 `render_ink_bounds.left` 均锁定为 0；17 项 TRICMN 专门回归通过，
独立组件与全故事集成组件 byte-exact。ISO 固定 LBA 读回与组件一致，写入前后
`BTL/OP2.BIN` 保持 `d9835799…7fadf`，`BTL/SRVC.BIN` 保持
`fb0fc670…6a36b`。本轮仍只证明 TRICMN 单成员静态写回，连接处的游戏内线性采样
观感保持 `runtime_pending`，等待该精确 ISO 的新截图确认。

随后的能力小字实机反馈否定了 Fusion 12px 候选，并进一步明确日版的结构不是像素字
直接描边，而是先生成细字面，再贴着字面生成一层底，最后只对底层做轻微向下浮雕。
原始 4bpp 索引和活动粉色 CLUT 的分工为：

- `0`：透明；
- `1..4`：贴字的半透明光晕／外缘；
- `5..7`：较实的粉色向下侧面；
- `8..15`：高亮字面，index 15 接近白色。

旧的按几何外边界推断源层方法会把被矩形裁切的日文长词字面误当成 halo，使亮色
`8..15` 偶尔跑到中文外围。新 `source_wordart_tight_down_layers` 改为先锁定上述索引
角色，再按 `透明 → 贴字光晕 → 向下侧面 → 高亮字面` 顺序生成；19 条能力名的最外
边界只能出现 `1..4`，侧面只能出现 `5..7`，字面只能出现 `8..15`。这是一项生成
规则，不是逐像素修补。

能力 profile 同时切回项目统一的 HarmonyOS Sans SC Regular，使用 17px 字号、0.6px
外层、零额外 fill stroke、1px 光晕、仅向下 1px 的侧面、8x 矢量超采样和 1px 索引
边缘滤镜；“援护”按本轮编辑决定改为“防御”。日版、废弃 Fusion 候选和新候选的
同尺寸线性采样对照位于：

```text
work/review/tricmn-battle-overlays-zh/ability-harmony17-thin-down1/reference-vs-fusion-vs-candidate-semantic-layers-bank11-linear2x.png
```

写入后的待实机复测候选为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   187341ec7be0a1ad32908db04741193f94e49e824da423816e2ca58b32c2e9db
TRICMN:    6e343660db8fa4177afe2dabf74c4a41621c40710a78fc5a3529a74f856792d4
HarmonyOS: 297b088424be212207df2ce8b98e335468b782aa6b96832af0b8b773d711e2b1
```

17 项 TRICMN 专门回归通过，独立组件与全故事集成组件 byte-exact；ISO 固定 LBA
读回与组件一致。写入前后 `BTL/OP2.BIN` 保持 `d9835799…7fadf`，
`BTL/SRVC.BIN` 保持 `fb0fc670…6a36b`。新能力小字的最终游戏内观感仍为
`runtime_pending`，需要在该精确 ISO 中触发能力提示后截图确认。

### 5.9 能力小字：按原版边界深度扩展暗色光晕（2026-09-01）

上一候选的实机截图已确认字形、笔画和向下浮雕基本正确；剩余差异集中在光晕：中文
内圈偏亮、覆盖偏窄，而日版还多一圈更暗的颜色。重新统计 19 条日版能力名的索引
边界深度后确认，活动粉色 CLUT 的 `1..4` 并非可以互换的普通描边色：最外层主要由
半透明的 `1..3` 构成，较亮、较不透明的 index `4` 主要位于第二层。以“防御”的日版
源区域为例，深度 1 的 `1/2/3/4` 像素数分别为 `82/52/49/5`；此前按整区直方图
量化会把过多 index `4` 放到最外边界，因此形成“更亮但更窄”的观感。

`source_wordart_tight_down_layers` 现进一步按源边界深度生成能力名光晕：实体贴字层继续
使用 `1..4`，但 2px 索引边缘滤镜生成的额外软边只使用 `1..3`，并在最终写回前把
最外边界重新投影到该暗色 ramp。19 条能力名均满足：最外边界只出现 `1..3`，index
`4` 退回内圈，向下侧面仍严格使用 `5..7`，高亮字面仍严格使用 `8..15`。字体、
17px 字号、0.6px 外层、1px 向下浮雕、括号模板和共享 CLUT 均未改变，也没有逐像素
结果修补。

日版／上一中文候选／新候选的同尺寸线性采样对照位于：

```text
work/review/tricmn-battle-overlays-zh/ability-harmony17-wide-dark-halo/reference-vs-previous-vs-candidate-bank11-linear2x.png
```

写入 current 测试 ISO 的精确产物为：

```text
ISO:       build/iso/zh-release-full-story/srwz-zh-current.iso
ISO SHA:   c4a7dc43276da4e68243e415582b58eb11b1b2e2b0f23cc3833f7fbac17f74ab
TRICMN:    a9be4fd270d64b994045def0d1ee675c5f404cdad3059addd1fa3cf1b22d6805
```

17 项 TRICMN 专门回归通过，独立组件与集成组件 byte-exact。当前全量 ISO builder 被
并行的 `srvc_battle_text_corpus` 输入漂移挡住，因此本轮没有重建或覆盖 SRVC，而是在
确认 `677424 <= 331 sectors` 后只向 LBA `1312883` 写入 TRICMN。固定 LBA 回读与组件
一致；前邻 `BTL/OP2.BIN` 仍为 `d9835799…7fadf`，后邻 `BTL/SRVC.BIN` 仍为
`fb0fc670…6a36b`。上一版 TRICMN 已备份至
`work/review/tricmn-battle-overlays-zh/ability-harmony17-wide-dark-halo/current-iso-before-write/TRICMN.BIN`
（SHA-256 `6e343660…792d4`）。新光晕的游戏内观感仍为 `runtime_pending`，等待从上述
精确 ISO 截取同一能力提示进行最终确认。

### 5.10 十条状态提示的同路径 LRPS2 运行态目测夹具（2026-09-01）

ARMSX2 当前记忆卡提供了一条能稳定触发 `瞄准值下降` 的战斗路线。该路线已固化为
`work/runtime/lrps2/sequences/tricmn-status-overlay-verify.json`，从 Continue 后依次执行：

1. `↓` 选中卡缪的高达 Mk-II；
2. 确认默认“移动”，向前（`↑`）移动 1 格并确认；
3. 确认默认“攻击”，确认第一项武器“火神炮”；
4. `↑` 选中相邻的堕天翅，确认默认 `TRI队形`；
5. 将“演出”从 OFF 切换为 ON，选择“开始战斗”；
6. 在 frame `5022` 截取完整显示的状态提示。

为了让其余九条状态也经过完全相同的战斗场景、缩放、活动 CLUT 和 GS 线性采样，
`tools/build_tricmn_status_runtime_variant.py` 不重新绘字，而是从已批准的中文 TRICMN
组件中取出目标状态已经生成好的完整 `128×24` PSMT4 索引行（包括 15px 三角标记），
复制到实际会被火神炮触发的 `tricmn/accuracy-down` 行。工具拒绝非当前组件哈希，且
断言目标槽之外的逻辑像素和 picture 之外的成员字节保持不变。

十个测试 ISO 均从 current ISO 通过 APFS copy-on-write 克隆，只在原固定 LBA
`1312883` 写入对应的临时 TRICMN；current ISO 和 ARMSX2 源记忆卡没有被修改。结果位于：

```text
work/runtime/lrps2/tricmn-status-overlay-sweep-20260901/
  variants/*/variant.json
  isos/*.iso
  runs/*/receipt.json
  status-overlay-contact-sheet.png
```

`运动性下降`、`装甲下降`、`瞄准值下降`、`EN下降`、`能力下降`、`战斗不能`、
`气力下降`、`SP下降`、`精神防御`、`完全抗性` 十轮 LRPS2 均在 frame `5022`
通过并得到互不相同的左上角裁图像素哈希；每份 receipt 也确认隔离记忆卡运行前后
源卡未变化。该结果证明十张已经生成的索引贴图都能在同一游戏调用路径中正确显示，
但仍属于 LRPS2 运行态目测证据，不替代 PCSX2／ARMSX2 的最终人工画面验收。

### 5.11 `EN`／`SP` 拉丁字母定点亮边（2026-09-01）

十条状态提示的同路径对照确认其余八条可以接受，剩余差异仅为 `EN下降` 的 `N` 和
`SP下降` 的 `S` 实体亮边偏暗。两者的轮廓、外层半透明柔边和字符间距均完整，因此
没有扩大描边或逐点修补结果图；生成器根据 fill mask 的字符列间空隙自动分割字符，
只在指定字符跨度内把核心 halo 中低于 index `14` 的亮色索引提升到 `14`。最外层
anti-alias fringe、深色字芯、中文、三角标记以及相邻 `E`／`P` 均保持原生成逻辑。

`N` 共提升 15 个实体亮边像素，自动字符跨度为 `[13,27)`；`S` 共提升 17 个，跨度为
`[0,14)`。17 项 TRICMN 专门回归通过，独立组件与全故事集成组件 byte-exact：

```text
TRICMN: 416320b21239a1aa8e0b7c8ffb6bbee3f3273b0f479dd0426b81e104ada6ce7b
ISO:    25f130f435afde6c72767b9cda47123ba4c0b19eb6dfc2f7e85fed095b14f5eb
```

current ISO 仍仅在固定 LBA `1312883` 定点写入该 TRICMN，写后回读 byte-exact；写入前的
上一组件备份在：

```text
work/review/tricmn-battle-overlays-zh/status-latin-bright-edge/current-iso-before-write/TRICMN.BIN
```

复用 5.10 的操作序列分别把 `EN下降`、`SP下降` 放入瞄准值槽位，两轮均在 frame
`5022` 通过，源 ARMSX2 记忆卡保持不变。运行态前后对照位于：

```text
work/runtime/lrps2/tricmn-status-latin-bright-edge-20260901/runtime-before-after.png
```

该结果完成 LRPS2 运行态确认；PCSX2／ARMSX2 人工画面仍是最终验收边界。

### 5.12 能力小字复用状态提示清晰度，并匹配日版原词宽度（2026-09-02）

能力名的实机反馈进一步确认：索引分层与暗色外圈已经正确，剩余差异是中文字比日文
原词集中、字号偏小，细笔画因此不够清楚。本轮复用 5.10 已经通过 LRPS2 对照的
`瞄准值下降` 状态提示几何参数，而不复用它的颜色材质：能力 profile 调整为 19px
字号、1.2px 外层、2px 光晕、8x 矢量超采样和 1px 索引边缘滤镜。随后用 BIG-O
“防护力场”的固定 LRPS2 路线对黑色字骨做 0.5px／0.8px 同帧 A/B；0.5px 在“防、护、
场”的笔画交界仍被亮边吃掉，最终采用 0.8px。材质改为
`source_wordart_tight_down_dark_core_layers`：`1..4` 仍是贴字暗光晕，`1..7` 共同构成
较粗黑色字骨，`8..15` 只负责紧贴字骨的高亮反射边，仍使用能力专用粉色 CLUT。

为了参考日版每项能力各自的实际宽度，生成器先测量该槽日文源词的非透明 ink bounds，
再逐字生成中文 mask，并把各字中心等距分布到日文源词左右边界之间。整个中文组合仍
在原 `128x24` 区域内居中；过宽源词只在左右各保留 1px 安全边界后截限。因此
“防御”等短词不会缩成一团，“防护力场”等四字词也不会靠机械固定字距挤在中央。
报告新增 `source_target_ink_width` 和 `effective_character_spacing`，测试锁定中文结果宽度
与对应日文宽度之差不超过 1px（达到安全边界时按可用宽度截限）。这仍是统一生成规则，
没有对单个字或毛刺逐点修补。

静态同尺寸线性采样预览位于：

```text
work/review/tricmn-battle-overlays-zh/picture2-localized-source-width-2x.png
```

本轮精确产物为：

```text
TRICMN:       e5375ac8595a9550efb0cc7680e2131d66dfbfada9ae4534a5188e7dc8e07615
current ISO:  d05a13aaa2c49d0f32a4ce777a23ff10acd936d18717d31ef16fa2be4a7aa9a9
BIG-O ISO:    aef74221655edca2fed889d2249406e3d92269ea221fd90e7195303018f8c258
```

17 项 TRICMN 专门回归全部通过。全量 current ISO builder 仍被并行的
`srvc_battle_text_corpus` 输入漂移挡住，因此 current ISO 只在固定 LBA `1312883`
写入并回读该 TRICMN；专用 BIG-O ISO 则重新构建，并在 COMPDATA 中给所有 BIG-O
变体配置“防护力场”。

最新 ARMSX2 存档下，BIG-O 第一武器路线的敌方反击即使预测为 97%，在 LRPS2 的确定性
运行里仍会固定闪避。最终可复现序列改用第二武器“格斗”，其余路径保持不变：Continue
后 `down/circle` 选 BIG-O，`down/circle` 打开武器，`down/circle` 选第二武器，
`right/right/circle` 选择附近堕天翅，打开战斗演出并开始。该序列已固化为：

```text
config/runtime/lrps2-big-o-barrier-ability-sequence.json
```

LRPS2 在 frame `6429`（开战后 2760 帧）捕获完整的 `[ 防 护 力 场 ]`：

```text
work/runtime/lrps2/big-o-ability-source-width/final-sequence/
  frames/06429-big-o-barrier-field-visible.png
  big-o-barrier-field-runtime-4x.png
  receipt.json
```

该帧确认能力贴图经过游戏调用、活动 CLUT 和 GS 采样后仍保持分散居中、0.8px 黑色
字骨连续、亮边紧贴和暗色宽光晕；这是 LRPS2 运行态证据。PCSX2／ARMSX2 人工画面
仍保留为最终验收边界。

### 5.13 十九条机体特殊能力的同路径 LRPS2 运行态扫图（2026-09-02）

为了确认其余能力名的真实游戏采样效果，本轮不再为每项能力寻找不同机体和原生触发
条件。`tools/build_tricmn_ability_runtime_variant.py` 从已经批准的 0.8px 黑字骨 TRICMN
中取出某条能力已经生成好的 `128x24` 索引文字区，逐行复制到 BIG-O 会稳定显示的
`tricmn/barrier-field` 区域 `[336,120,128,24]`。工具不重新绘字，不复制槽外像素，
所以目标槽左右方括号、活动 CLUT、COMPDATA 和游戏调用路径全部保持不变。

`tools/run_tricmn_ability_runtime_sweep.py` 再从固定 BIG-O ISO 做 APFS copy-on-write 临时
克隆，只在 LBA `1312883` 写入该轮 TRICMN，并复用 5.12 的第二武器序列。为缩短运行
时间，十九轮按 7／6／6 分成三个隔离 LRPS2 进程；每个进程有独立输出目录和独立
记忆卡副本。每轮均在 frame `6429` 得到完整能力提示，临时 ISO 随该轮结束删除，
只保留 variant 报告、receipt、原始帧和裁图。基准 ISO 与源 ARMSX2 记忆卡运行前后
哈希均未变化。

通过的十九项按贴图顺序为：`防御`、`盾牌防御`、`斩切`、`分身`、`马赫特技`、
`亚空间突入`、`超限技`、`滑空技巧`、`光束涂层`、`PS装甲`、`VPS装甲`、`积层装甲`、
`八咫镜`、`精神感应力场`、`I力场`、`阳电子反射器`、`光束屏障`、`光子垫`、
`防护力场`。短词、六字长词、纯汉字和 Latin 混排均未发生截断或槽外污染。

统一运行态总览和逐项证据位于：

```text
work/runtime/lrps2/tricmn-ability-overlay-sweep-20260902/
  ability-overlay-contact-sheet-4x.png
  summary.json
  parts/*/variants/*/variant.json
  parts/*/runs/*/receipt.json
  parts/*/runs/*/frames/06429-big-o-barrier-field-visible.png
  parts/*/crops/*.png
```

总览 SHA-256 为
`870b9f34a8420c6ea30e2bfd33e2726e4ec1bdebf9e6eb522fe65c527577c4a5`；summary
锁定序列哈希 `4048794fa1634f7f9356fa111d178ad8fbbeb9b6dea679958b92efaf00e93bcc`、
正式 TRICMN 哈希 `e5375ac8595a9550efb0cc7680e2131d66dfbfada9ae4534a5188e7dc8e07615`、
基准 BIG-O ISO 哈希 `aef74221655edca2fed889d2249406e3d92269ea221fd90e7195303018f8c258`
以及源记忆卡哈希 `184b6106324f04520fb25eac36a25e93225766ed9692f789a2d2ad70030d4059`。
这十九份均为 LRPS2 运行态证据；PCSX2／ARMSX2 人工画面仍是最终验收边界。

### 5.14 最终运行验收与冻结构建（2026-09-02）

十九项能力扫图之后，用户又完成了 ARMSX2／实际战斗动画人工复核，并确认本成员的
大号队形／攻击提示、不可用原因、十条状态文字及十九条机体特殊能力均可接受。因此
TRICMN 的最终状态由 `runtime_pending` 提升为运行验收完成，冻结成员为：

```text
size:    677424
sha256:  e5375ac8595a9550efb0cc7680e2131d66dfbfada9ae4534a5188e7dc8e07615
```

正式构建不再从字体重新生成这张贴图。审核后的 picture 0、1、2 三个 PSMT4 原始图像
区间以 zlib 压缩和 base64 编码保存在
`config/assets/tricmn-battle-overlays-zh-render-snapshot.json`；picture 3、TIM2 header、共享
CLUT、其他动画成员和 SEG 继续继承哈希锁定的原版成员。普通
`tools/build_tricmn_battle_overlays.py` 只解码这三个冻结区间、写入原版前像，并校验上面的
完整成员哈希。因此生产构建不依赖字体版本、ImageMagick 或矢量栅格化结果。

为便于日后维护，`config/assets/tricmn-battle-overlays-zh.json`、中文语料、分层索引生成器
和 TEX1 本地采样模拟仍然保留。只有显式 `--live-render` 才会重新绘制；新的候选经审图
和实机验收后，还必须显式 `--refreeze-snapshot` 才能替换冻结像素。该流程拒绝任何不等于
配置中审核成员哈希的候选，防止普通全量构建无意中改变已验收画面。
