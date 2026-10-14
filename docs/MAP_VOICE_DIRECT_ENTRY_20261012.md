# 地图语音演出直接入口验证（2026-10-12）

已在 Original 的另一张地图上直接播放节子第二话的脉冲出击前半段（effect 273），没有调用第二话事件脚本或满足原关卡触发条件。LRPS2 冷启动验证成功；从初始化后的核心恢复地图快照，自动入口连续播放两次成功，演出对象每次均释放。运行录音中的四句指令也由本地 Whisper large-v3 识别两遍。

这证明演出可以由独立调用入口启动。当前仍需要已初始化的地图环境，尚不是脱离地图的播放器或已集成的 SP 鉴赏菜单。

## 证据与原型

原型目录：`work/analysis/map-voice-direct-entry-20261012/`。

- `direct_effect.py`：独立请求演出，模拟 Original `FUN_001a8d80` / `FUN_001a88e0` 的动态加载路径。校验 Original 函数签名、基础缓存数量、加载器及演出池空闲状态。拒绝直接套用 BEST/SP 地址。
- `drive_stdio.py`：隔离 LRPS2 驱动；复制测试记忆卡，标准输入命令，不接触用户前台模拟器。支持 `effect 273`，记录命令及 48 kHz 双声道运行音频。
- `runtime/validated-run.jsonl`：最终成功运行的命令和结果。较早失败实验保留在总日志中，不算成功证据。
- `runtime/final-first-240.png` / `final-repeat-240.png`：两次播放截图。
- `runtime/final-first-ended.png`：播放结束回到地图。
- `runtime/runtime-audio.wav`：包含两次 273 和一次 274 的运行录音。
- `runtime/runtime-audio-16k.wav.txt`：运行录音的本地 Whisper 识别结果。
- `receipt.json`：证据摘要及产物 SHA-256。

地图基线来自 Original ISO 冷启动后读取测试记忆卡，进入 STAGE index 111；目标演出原始调用位于 STAGE index 2。正式 ISO、生产补丁及原测试记忆卡均未修改。

入口使用演出池 `0x59f7b0`、资源缓存 `0x5a0460` 和异步加载器状态 `0x5a0658`，加载、贴图、时间表及语音仍由游戏处理。动态请求编号 273 对应 VEFF chunk 274；编号 274 对应 chunk 275。

## 复现

在项目根目录运行（模拟器 JIT 需要宿主允许）：

```sh
arch -x86_64 srwz-zh/work/runtime/lrps2/python-x86_64-3.12.14/bin/python3 \
  srwz-zh/work/analysis/map-voice-direct-entry-20261012/drive_stdio.py \
  srwz-zh/rom/original.iso \
  srwz-zh/work/runtime/lrps2/v042-original/save/srwz-zh-v0.4.2-original.ps2 \
  /tmp/srwz-map-voice-replay /tmp/unused
```

先将已验证的 `runtime/unrelated-map.sav` 复制到输出目录，再输入：

```text
run 60
load unrelated-map
effect 273
run 240
shot first
run 1350
effect 273
run 240
shot second
run 1350
quit
```

恢复地图快照前必须先运行核心，最终成功记录使用 60 帧。只运行 1 帧后恢复曾导致光盘异步加载一直等待。地图菜单中启动也可能停在加载等待；原型要求使用上述经过验证的地图基线。失败后恢复原始基线，不能接着把未完成请求视为已播放。

## SRWZ-native 成果的使用

使用本地固定版本 `srwz-vita-research/upstream`（`d45c45ed91b3fc1beec685cda0ec2b25ed015869`）：

- `config/srwz-ram.md` 的地图单位表/坐标资料，用于核对独立地图环境。
- PS2Recomp `ps2_audio_vag.cpp` 的 ADPCM 滤波及半字节解码，作为提取 CCC 原始音频的交叉参考。CCC 片段没有 VAG 文件头，因此另行读取 MSH 目录定位。

没有将 native 项目自测视为本次运行证据，也未为本任务构建 native 游戏运行时；当前画面/声音证据均来自 LRPS2。

## SP 已有资源

`compare_sp.py` 直接读取 Original 和 SP 原盘。SP VEFF 共 305 块。此前审计的 13 个有定时语音资源，在同号块中全部与 Original 相同，差异仅为语音时间表中的 CCC 编号；39 个引用中 37 个原始音频字节一致。

脉冲前半段 chunk 274 仅有 8 字节变化：四个语音编号从 `55/56/57/58` 改为 `339/340/341/342`。触发帧仍是 `176/438/720/1034`，四个音频的原始字节逐个相同。后半段 chunk 275 完全一致。因此可以优先调用 SP 现有资源，不必先搬运脉冲画面资源。

两处语音原始字节不一致：Aquarion effect 256 的 `20354 → 30896`，God Sigma effect 266 的 `68 → 383`；未据此判断内容相同。明细见 `sp-resource-comparison.json`。这些是静态比较，SP 播放入口、菜单和镜头尚未运行验证。

## 本地字幕准备

`extract_audio.py` 从 Original CCC 目录提取四个片段；本地构建 whisper.cpp CLI，使用已有 `ggml-large-v3.bin`，无需上传音频。`whisper-transcribe.sh` 可重跑。

| 演出帧 | 日文识别初稿 | 中文草稿 |
| --- | --- | --- |
| 176 | コアスプレンダー発進、どうぞ! | 核心飞梭，请起飞！ |
| 438 | シルエットフライヤー射出、どうぞ! | 魅影战机，请弹射！ |
| 720 | 続いて、チェストフライヤー射出。どうぞ。 | 接下来，胸部飞行器，请弹射！ |
| 1034 | レッグフライヤー射出、どうぞ! | 腿部飞行器，请弹射！ |

`impulse-subtitles-draft.json` / `.srt` 按游戏资源触发帧对齐，时间原点是演出内部第 0 帧。加载等待时间应在播放器中另行处理。核心飞梭、胸部/腿部飞行器沿用当前词表；魅影战机名称及全段措辞仍需校对。

独立 CCC 解码暂按 22050 Hz，速率仍需音频加载代码进一步核对；因此暂不把识别的片段结束时间当作最终字幕时长。运行录音为实际核心输出 48000 Hz，Whisper 已确认四句指令随两次直接调用出现。字幕尚未嵌入游戏。

## 尚未通过的范围与下一步

- effect 274 可以加载并结束，但测试时截到的画面很暗，没有验证到预期完整构图。原脚本还控制镜头、单位显隐和等待；后半段需要补齐这些场景条件。
- 当前背景为另一关地图，尚未复现第二话港口布景。SP 鉴赏应准备独立舞台及镜头，或恢复该场景所需布景。
- SP 的演出启动函数、池及异步加载地址需要独立定位，不能套用 Original 常量。
- 没有 PCSX2 人工验收，没有完成整个演出的无地图播放器、SP 菜单或游戏内中文字幕。

优先继续：补齐场景所需的最小舞台/镜头条件，定位 SP 同源入口，用 SP 自带的脉冲资源做直接播放验证；之后再接鉴赏列表和字幕绘制。

## 2026-10-12 SP 港口舞台与底部字幕实验更新

本节更新上文的后续事项。实验目录为 `work/analysis/map-voice-sp-player-20261012/`，候选 ISO 为 `work/iso/sp-map-voice-gallery-prototype.iso`。正式发布 ISO 未改动。

- 已独立定位 SP 的演出入口，并直接播放 SP effect 273、274。
- 港口地图 ID 为 30。通过独立地图初始化脚本准备舞台，隐藏测试关卡无关单位；不依赖原第二话剧情条件。
- 后半段在港口舞台运行，已看到部件飞行、空中组合与完整脉冲；证据来自隔离 LRPS2。
- 四句中文按语音触发帧 176、438、720、1034 加入原生 VEFF 贴图序列。所有原演出四边形逐帧保留，字幕另加。

字幕原先只在美玲头像区域露出，并不意味着字幕必须附着于头像。初次将其归因于深度测试并不完整：GS TEST 同时启用了目标透明度测试（DATE），该条件限制了地图区域的显示。单独调整 Z 测试及深度写入均未解决。当前实验只对新增字幕的 mode byte bit7 标记分支设置 TEST=0x30000（ATE=0、DATE=0、ZTE=1、ZTST=ALWAYS），原演出图元维持原逻辑。字幕使用屏幕坐标，横向范围 64..576、中心 x=320；最终布局 y=384..416，距 448 高画面底部 32 像素。白字黑底，文字约 22 像素高。

补丁实现见实验目录 `subtitle_layer.py`，资源生成见 `subtitle_resource.py`，固定容量 ISO 写入见 `build_candidate.py`。字幕资源压缩后 204202 字节，小于原块 250272 字节预算；所有 ISO 成员 LBA 和文件大小保持不变。补丁代码暂放原型保留 RAM 0x1f00100，经 ELF 空闲头部填充及一个原空 PT_LOAD 映射，正式集成前仍需统一保留内存管理。

运行记录 `runtime-subtitle-bottom-final/commands.jsonl` 和四张 `bottom-1.png` 至 `bottom-4.png` 对应最终布局；`second-420.png` 和 `ended.png` 用于检查后半段及结束状态。验证使用旧港口快照，快照会恢复旧代码，因此恢复后显式写回同版字幕钩子与代码；此证据是候选资源加运行时补丁的 LRPS2 验证，不能当作已完成的冷启动游戏内入口或 PCSX2 人工验收。

尚未完成：SP 内可选择入口及返回菜单、冷启动完整链路、正式 UI 适配、中文措辞审校、PCSX2 人工验收。当前入口仍是外部实验驱动器；不能称为已经完成 SP 鉴赏菜单。

最终布局的四句截图均已人工查看：文字完整横跨地图区域、底部居中，后半段与结束画面正常。可随仓库审阅的副本保存在 `docs/issue-assets/map-voice-subtitles-20261012/`，其中也保存了本次字幕钩子源码及候选构建回执；源码副本用于审查，不是独立构建入口。
