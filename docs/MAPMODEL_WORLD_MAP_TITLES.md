# MAPMODEL 世界地图地名贴图

本文记录 WORLD MAP 地名从女主线第一关脚本调用到 `MAP/MAPMODEL.BIN` 像素写回的
完整静态证据。结论是：开场滚动字幕结束后出现的“月面 地球联邦军卢特提姆基地”
及同系统其他地名是 MAPMODEL 成员中的固定 4-bpp 贴图，不是游戏运行时排版文本。

## 1. 女主线第一关调用链

女主线第一关对应 decoded STAGE chunk 001。WORLD MAP 命令记录位于 decoded
`0x2BA0`，opcode 为 `0x0F`：

- 记录 `+0x04` 的值是 `5`，不是 MAPMODEL 参数；
- 记录 `+0x08` 的实际参数是 `0`；
- SLPS 虚拟地址 `0x1E5BD0` 的 handler 通过 `lw a0, 8(s2)` 读取该参数；
- `0x1C71E0(0)` 把内部选择值设为 `0x50`；
- `0x143CF0` 的资源加载路径再加 `1`，最终选择 MAPMODEL member `81`。

因此不能把命令 `+0x04` 的 `5` 直接当成资源编号。member 81 才是截图中的
“月面 地球連邦軍ルテチウム基地”贴图，也是女主线第一关的实际静态资源前像。

相关锁定输入：

| 输入 | 大小 | SHA-256 |
| --- | ---: | --- |
| `work/disc/SLPS_258.87` | 3,471,624 | `6c4c81c4e5aa3db1f52d70b8183ce11c01fc6b265ae4d53fa4d6a657c5019b50` |
| `work/disc/MAP/MAPMODEL.BIN` | 55,136,688 | `e33a7c33346de4be04fce50401dd62d294eb521e588188821c1b5a99267700e2` |

## 2. MAPMODEL 顶层成员表

SLPS 文件偏移 `0x2FAAD0` 保存 197 个 little-endian `u32` offset。它们描述
MAPMODEL 的 196 个定长 allocation；最后一个值等于 archive 总大小。整张 offset
表共 788 bytes，SHA-256 为
`17a89f2432d916bd9f2bafa960f06eb6aa1bc4d8b54a31f5645daf6daff4d599`。

地名标题连续使用 member `81..195`：

- 115 个成员，无缺号；
- 每个成员是独立 SRWZ 压缩流并带 16-byte 对齐的固定 allocation；
- member 81 stored 区间为 `[0x020E9440, 0x0211F580)`，allocation 大小
  `0x36140` / 221,504 bytes；
- member 81 decoded 大小为 `0x14ECE0` / 1,371,360 bytes。

生产 writer 不改 SLPS offset 表，也不重排或改变任何 member allocation。

## 3. 地名和英文副标题的像素格式

所有 member `81..195` 都在相同 decoded 偏移保存两块 `512×32`、4-bpp 原始像素：

| 内容 | decoded raw 区间 | 大小 |
| --- | --- | ---: |
| 日文地名 | `[0x1DE0, 0x3DE0)` | 8,192 bytes |
| 英文副标题 | `[0x3E40, 0x5E40)` | 8,192 bytes |

像素格式为 linear、low-nibble-first：每字节低 nibble 是左像素，高 nibble 是右
像素。stored row 顺序与画面上下方向相反，解包时必须把 32 行翻转为 top-down；
它不是 TIM2，也不是 PSMT4 swizzle。

英文副标题在 115 个成员中完全相同，其 raw SHA-256 固定为
`b43fb034de38ce22b1c8c5b26715a323bef5ba6abe56a0442af53755a6f9f61d`。
writer 将其作为受保护前像，任何一位改变都直接失败。

member 81 的日文 raw SHA-256 是
`0d6ed03699af05d1dbccbfe640683dd13889971497f04e44e8b0e3a151a803f9`；
翻转后的非零包围框为 `(x=60..451, y=4..29)`。

## 4. 语料覆盖

机器可读事实源是
`corpus/zh/ui-atlas/world-map-titles-v1.json`。它按日文 raw SHA-256 合并重复贴图，
并逐项登记 member、日文来源和简体中文：

- 78 个唯一日文 raw；
- 覆盖 member `81..195` 的全部 115 个成员，每个恰好一次；
- 70 个唯一标题需要重绘，对应 101 个成员；
- 8 个标题中日显示相同，对应 14 个成员，整段 stored bytes 保持不变；
- 英文 `WORLD MAP` 副标题不属于翻译语料。

第一项固定为：

```text
source:      月面 地球連邦軍ルテチウム基地
translation: 月面 地球联邦军卢特提姆基地
member:      81
```

其余地名不在本文复制第二份列表，避免与 JSON 事实源漂移。

## 5. 擦除、重绘和定长回写

实现位于 `tools/srwz/world_map_titles.py`，由
`tools/build_full_story_components.py` 调用。配置入口是
`config/full-story-components.json` 的 `world_map_titles`。

地图标题的渲染结果已冻结在
`config/world-map-title-render-snapshot.json`。普通 build 只验证快照与语料、字体和
渲染配置的锁，并读取其中的 4bpp raw；不会启动 ImageMagick。只有显式运行
`python3 tools/freeze_world_map_title_renders.py --force` 时才按以下规则重新生成：

1. 验证该 member 的日文 raw SHA-256 和共享英文 raw SHA-256；
2. 解包日文 4-bpp raw，计算原文字全部非零像素的紧包围框；
3. 只把该包围框清为索引 0，框外像素不变；
4. 使用锁定的 HarmonyOS Sans SC Light 1.0 和锁定 ImageMagick 版本渲染；
5. 从 point size 26 向下搜索到 18，并按 kerning `2, 1.5, 1, 0.5, 0`
   尝试，选择第一组能完整装入原包围框的参数；
6. 把中文紧包围框居中写入原包围框，量化回 16 级索引；
7. 重新翻转行并按 low-nibble-first 打包，只替换 decoded 日文 raw 区间；
8. 使用 `rust-fit`、`min_match_length=2`、`max_match_chain=1024` 重压完整
   decoded payload；超过原 allocation 时失败，绝不截断；
9. 在原 allocation 尾部补零，并由 Rust decoder 完整回读。

同文 no-op 标题不经过渲染或重压。重复 raw 共用同一个冻结重绘结果，但每个 member
仍独立解压、验证、重压和回读；标题成员与地形名成员不重叠，同一成员不会在两个
阶段重复解压或压缩。

## 6. 当前静态结果

当前组件输出：

| 制品 | 大小 | SHA-256 |
| --- | ---: | --- |
| `work/build/zh-release-full-story/components/MAP/MAPMODEL.BIN` | 55,136,688 | `6d766567b4e36082fbe8532baf59c4cfc4994718b30e349602f9da95a37d7957` |

`manifests/full-story-components-validation.json` 的 `world_map_titles` 已证明：

- 78 / 115 的语料与 member 覆盖准确；
- 101 个翻译 member 全部定长装回，最小压缩余量 14,191 bytes；
- 14 个同文 member stored bytes 完全不变；
- 日文 raw 以外的 decoded bytes 完全不变；
- 英文副标题完全不变；
- archive 总大小和全部顶层 offset 不变；
- 所有重压流均完整 round-trip。

预览位于：

```text
work/build/zh-release-full-story/components/previews/world-map-titles/
  world-map-titles-contact-sheet.png
```

预览 PNG 是审校产物，不是生产写回输入。

当前 v0.1.0 ISO 为：

```text
build/iso/v0.1.0/srwz-zh-v0.1.0.iso
size:   3,758,358,528 bytes
sha256: d65bfca8469582105357b2f71d8627490513c9e4aef346672bbcb4dcfd518146
```

ISO 已连续构建两次得到相同哈希。静态报告
`build/iso/v0.1.0/iso-validation-v0.1.0.json` 独立回读
`MAP/MAPMODEL.BIN`，并确认 66 个成员路径和顺序不变、53 个未替换成员
byte-exact、16 个 replacement byte-exact、shifted member count 为 0。

## 7. 验证命令与运行边界

```bash
python3 -m unittest tests.test_world_map_titles tests.test_zh_release_iso -v
python3 tools/build_full_story_components.py --force --refresh-manifest
python3 tools/build_iso.py \
  --config config/iso/zh-release-full-story-build.json
```

这些结果只构成静态证据。ISO builder 不执行 PCSX2；当前尚未为 v0.1.0 精确哈希登记
女主线新游戏、开场滚动字幕结束、WORLD MAP 地名出现这一目标流的 fresh-process
运行收据。旧候选截图和仅启动到标题画面的结果不能替代该验证。
