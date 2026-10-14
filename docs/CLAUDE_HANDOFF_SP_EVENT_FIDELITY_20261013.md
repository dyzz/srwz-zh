# Claude 交接：SP 特别剧场事件演出与本篇对齐

## 用户最终要求及工作范围

工作目录：`/Users/nate/Super-Robot-Wars-Z/srwz-zh`，这是嵌套 Git 仓库。日期：2026-10-13。

用户希望 Claude 接手 **SP 汉化版特别剧场的12段事件演出保真工作**：反编译厘清原机制，按本篇原场景补齐必要机体及形态、镜头、舞台前置状态和 BGM。运行验证明确使用 **LRPS2**。

用户刚才的原话：

> 我想让claude去对齐sp里的剧场内容，和本篇要对齐必要机体，镜头，BGM。第二关你给我存档就行，不用claude去做
>
> 让claude使用LRPS2

早先“鉴赏完整性先记录、后面再做”的暂缓安排，已经由这次明确交接推进的要求更新。旧文档中的“本轮不做音乐/单位”是当时边界，不应继续当作禁令。

**不属于 Claude 本次任务：** 本篇 Original/Best 字幕移植、第二关存档制作或手打验证、再扩展鉴赏菜单/新条目。用户会自己用第二关存档手打。不要继续本篇测试中提前设置剧情标志、注入原脚本的排查路线。

目标是每段鉴赏在其选定片段内呈现原关卡所需的单位、形态、舞台动作、镜头及音乐；不要求把整关剧情、完整敌我军和关卡战斗全部复制进 SP。

## 从当前 V7 基线开始

现用 SP 鉴赏候选：

- `/Users/nate/Super-Robot-Wars-Z/srwz-zh/build/iso/special-disc/event-gallery/sp-event-gallery-subtitles-v7.iso`
- ISO SHA256：`c54b6a51a0042a22597a432b09a941b6078985b56b1dc56a2a7f0d23789595e7`
- ELF SHA256：`13155fd42d5cb96261978546cbdfcbd97fc56e078f5abdb02a73153a5d6dfb34`
- 兼容软链接：`work/iso/sp-event-gallery-review.iso`，指向该 V7。
- SP 生产输入：`build/iso/special-disc/sp-current.iso`，没有被鉴赏候选替换。

V7 的场景运行脚本与菜单数据和 V6 逐字节相同；V7 只改善字幕质量。V7 已用 LRPS2 Software 冷启动、隔离记忆卡、原生控制器输入完成14轮播放返回，覆盖12项。这个结果证明入口、列表、播放和自然返回链路，不证明所有机体、镜头、BGM 都已与本篇一致。

V7 来源、流程与截图：

- `docs/SP_EVENT_SUBTITLE_QUALITY_V7_20261013.md`
- `docs/issue-assets/sp-event-subtitles-20261013/v7-quality/provenance.json`
- 同目录 `flow-report.json`、`build-receipt.json`、`comparison.html`

必须保留现有 UI 和字幕成果：

- 特别剧场“事件演出”入口，单页12项列表。
- 点击播放；自然结束自动回同一列表并保留选中项。
- 白字、黑色描边、轻阴影、透明背景，底部居中；字号32。
- 显示区域 `x64～576, y388～428`，按显示空间4倍渲染后平均到512×20原生纹理，GS 1:1点采样。不要退回40行纹理运行时压到20行的旧方法。
- 已确认的12个标题和37句润色稿；听校仍由用户完成，不在这次保真工作中改写台词。
- 阿克艾里昂原人物图保留、字幕贴图仅追加；鸫的反馈扭曲不能把字幕带入残影。
- 已修复的入口文字短暂模糊问题不能回归。

## 先读这些代码和证据

主要实现目录 `tools/special_disc/event_gallery/`：

| 文件 | 作用 |
| --- | --- |
| `runtime.S` | 原生播放状态机、地图加载、物件初始化、原生单位绑定、快照与恢复、字幕最终绘制和257反馈保护 |
| `runtime.py` | 从配置生成每段地图/镜头/原生脚本和来源收据；主要扩展点 |
| `build.py` | 独立候选构建、指令前像校验、资源表及 ISO/UDF/VMAP 更新与回读 |
| `menu.py`、`aid.py` | 已完成的入口和列表；本次一般无需修改 |
| `subtitles.py` | 已完成的 V7 字幕生成和原资源保留；本次一般无需修改 |
| `verify_flow.py` | 读取 LRPS2 原生状态日志，验证请求→播放→完成→返回，拒绝宿主写入等干预日志 |

配置：

- `config/products/special-disc/event-gallery.json`：12项、原 STAGE 来源、地图、锚点、镜头、模型初始状态。
- `config/products/special-disc/event-subtitles.json`：37句稿及 V7 样式；SHA256 `5c5596a643b2b6911f7feba81b60e0322f16d6151385d80e3dc60a76af1215e8`。

最重要的缺项/来源文档：

1. `docs/SP_EVENT_COMPLETENESS_BACKLOG_20261013.md`：已经确认的缺项，避免重新泛查。
2. `docs/SP_EVENT_STAGE_AND_SUBTITLES_V6_20261013.md`：魔神Z末尾单位替换、数据恢复及其他模型初始化已完成的证据。
3. `docs/issue-assets/sp-event-subtitles-20261013/v6-stage-subtitles/stage-readback.json`：原盘 STAGE 回读。
4. 同目录 `all-stage-dependencies.json`：310条可达脚本记录，包含片段前后剧情；不能把310条全当作需要移植的缺项。
5. 同目录 `native-unit-and-restoration.json`：原生单位出场和返回后逐字节恢复。
6. `docs/SP_EVENT_RESOURCE_COMPARISON_20261013.md`：本篇与 SP 的目标 effect 画面/动画资源比较。资源近似一致，不能把舞台构图差异都归咎于 effect 版本。

`docs/SP_EVENT_MAZINGER_STAGE_20261013.md` 是 V5 历史页；其中“末尾单位替换未完成”和2128帧已经过时，应以 V6 为准：目标帧是 `0x870 = 2160`。

## 12项来源和具体待办

下表 STAGE 是归档索引，不应直接称为游戏的“第几话”。偏移是该 STAGE 解码块内的原脚本偏移。

| 列表标题 | Effect / 地图 | Original STAGE / 调用偏移 | 当前缺项或核对重点 |
| --- | --- | --- | --- |
| 脉冲高达出击 | 273→274 / 30 | 002 / `0xa7c0`，根 `0xa370` | 已有两段串联及部件模型显隐；必要脉冲、密涅瓦等现场单位，274附近单位显隐与交接、镜头与音乐仍需对齐。 |
| 双卫星加农炮发射 | 255 / 3 | 126 / `0xb850`，根 `0xb340` | `0xb750` 出场，表 `0x8840`，DX位于(20,23)；地图单位未建立。模型0～4初态已有。 |
| 阿克艾里昂合体 | 256 / 13 | 021 / `0x8890`，根 `0x7d60` | `0x88a0～0x8900` 三对象/队伍处理与合体后原生出场表 `0x75d480` 尚未完整移植。不得覆盖原人物图。 |
| 爆爱无限光 | 257 / 74 | 117 / `0x12c80`，根 `0x12440` | 本篇继承单位616实时位置；当前固定(13,7)。明确攻击者/目标和必要坐标、镜头；保留字幕反馈保护。 |
| 天使剑 | 258 / 70 | 128 / `0x10930`，根 `0xfe40` | 当前只有 effect 和选定位置；补片段可见攻击者、目标及必要前后动作，核对镜头与音乐。 |
| 无限叱责掌 | 259 / 63 | 107 / `0x144a0`，根 `0x13d30` | 同上，原完整攻击现场尚未建立。 |
| 格兰维昂合神 | 264 / 8 | 007 / `0x9440`，根 `0x8ef0` | `0x9460～0x94f0` 对象显隐、退场和队伍相关处理未完整移植。 |
| 真·超重斩 | 265 / 63 | 107 / `0x156b0`，根 `0x14cf0` | `0x15710` 后的 `0x1395` 系列需先反编译解释，再确定必要显示/对象/形态动作；现阶段不能擅自给未明指令命名。 |
| 巨神Σ合体 | 266 / 45 | 026 / `0xa470`，根 `0xa320` | 模型1初态已有；`0xa4c0～0xa4f0` 队伍/驾驶员及出场表 `0x75ef20`，合体后原生单位仍缺。 |
| 盖塔龙合体 | 267 / 26 | 043 / `0xb920`，根 `0xb790` | 模型0初态及动作已有；`0xb990～0xb9b0` 状态及出场表 `0x75f2d0`、合体后地图单位仍缺。 |
| 魔神Z出击 | 269 / 72 | 047 / `0x9f70`，根 `0x9f00` | 继承1600帧姿态、1724/2160/3240/3399动作、末尾隐藏模型5并在(32,13)生成原生单位均已完成。以此作为单位准备/恢复范例；复查镜头及BGM，不重复“补末尾单位”。 |
| 泰坦3登场 | 282 / 22 | 069 / `0x12f60`，根 `0x12450` | 原镜头按在场单位定位，当前固定坐标；重建必要单位和对应镜头、音乐。 |

全部12项目前都没有完成按原场景逐段选曲、停曲/切换和返回剧场音乐的实现。已有部分选曲控制记录，另一些继承上文音乐状态。数字曲号和 SP 曲目映射尚未逐项核验，**不要凭机体主题曲印象填写 BGM**。

## 反编译及实现原则

先把原场景拆成：可见前置状态→effect/舞台动作→单位或形态交接→结束与音乐恢复。对每项记录“原指令、函数含义、Original定义、SP映射、实施状态、验证证据”。只补所选片段需要的内容。

Original 与 SP 的部分机体/驾驶员编号不同，不能复制数字ID。按定义确认对应机体与驾驶员，再用 SP 原生可用状态、绑定、出场和形态切换机制建立临时现场。不能依赖剧场测试存档恰好解锁了某台机体。

舞台模型帧、战术单位、镜头锚点是不同对象，分别核对。原生脚本调用前可能继承早先 effect 的模型姿态，魔神Z就是已有范例。不要靠截图猜一个坐标或加一个站立模型就称为对齐。

当前配置里多个 `map_view: 3` 只是初始配置或已查到的方向；不能据此声称整段镜头完全一致。遇到 `0x41`、`0x43`、`0x4b` 等指令时要核实实际处理函数，尤其不要把未解明的数值状态误称为“剧情阶段”或已确认的选曲。

音乐需核对：本篇进入片段时继承的曲目、片段内切换/停曲、SP对应资源，及返回列表恢复。两盘编号相同不代表曲目相同；“能听到音乐”不是对齐证据。

临时单位/驾驶员状态必须恢复。现有 V6 范例在播放前快照，返回后 `0x5a5080～0x61b9c0` 共485696字节逐字节恢复。新增形态/编队/音乐状态要明确所有权和恢复顺序；不能污染剧场存档或影响下一项。

现有 SP 私有段 `0x820000～0x8b0000`，运行入口 `0x822100`，帧钩子 callsite `0x143ea8`，状态 `0x821f00`。如果扩容必须核对堆、主线程栈、模型加载、单位快照和原生缓冲区边界，不使用任意高位 RAM 当作永久空间。

## 使用 LRPS2 验证

用户指定 LRPS2。无需 Finder、ARMSX2 或等待 Mac 解锁；优先直接文件操作与终端驱动。

已有驱动：`work/analysis/map-voice-sp-player-20261012/drive_watch.py`。

运行环境：

- Python：`work/runtime/lrps2/python-x86_64-3.12.14/bin/python3`
- Core：`work/runtime/lrps2/core-x86_64/pcsx2_libretro.dylib`
- BIOS/system：`work/runtime/lrps2/system`
- 既有隔离记忆卡：`work/analysis/sp-gallery-subtitles-20261013/v7-quality-runtime/save/sp-event-gallery-v7-review.ps2`（交接时已核实存在）。不要拿本篇第二关卡用于SP。

示例（从上述仓库目录执行）：

```sh
arch -x86_64 work/runtime/lrps2/python-x86_64-3.12.14/bin/python3 \
  work/analysis/map-voice-sp-player-20261012/drive_watch.py \
  work/iso/sp-event-gallery-fidelity-review.iso \
  work/analysis/sp-gallery-subtitles-20261013/v7-quality-runtime/save/sp-event-gallery-v7-review.ps2 \
  work/analysis/sp-event-fidelity-20261013/runtime \
  /tmp/srwz-sp-fidelity.sock
```

驱动实际通过标准输入接收命令；最后的 socket 参数是历史接口。驱动会复制输入卡到输出目录，不接触用户正在用的卡。

常用命令：`run N`、`press circle 3`、`press down 3`、`shot name`、`watch 821f00 16`、`mem 地址 长度`、`dump 地址 十六进制长度 文件名`、`quit`。列表状态0→1→2→3→0，必须连续观察。

调试可以另行保存即时状态或做受控实验，但最终验收日志应从实际候选 ISO 冷启动，使用原生按键从特别剧场点击播放，完整自然结束并返回；不要把宿主 `poke`/`call`/`effect` 或即时状态恢复的实验当作正式菜单链路验收。`verify_flow.py` 会拒绝这些干预。

每项拍摄对齐所需的关键帧：必要机体进场、形态切换前后、镜头衔接、演出末尾、回到列表。录音核对BGM和语音；保留原场景对应脚本/画面依据。

完成一项后检查返回时数据和音乐恢复，再播放另一项，至少验证一次重复播放。最后全12项完整回归；重点重测魔神Z单位恢复、脉冲273→274、阿克艾里昂4位纹理原图、鸫反馈与字幕消失、列表点击过渡和返回。

## 构建与交付

先 `git status --short`。当前大量 gallery 源码/配置/文档尚未提交；不得 reset/clean，不得把无关文本编辑混进来。特别保留已有并行改动：`corpus/zh/story-dialogue/stage-007.json`、`stage-013.json`、`docs/V0.4.2_POST_RELEASE_ISSUES.md`、`tools/build_editions.py`、`tools/prune_edition_workspaces.py`、`config/editorial/community-20261013-accepted.json`。

`tools/event_subtitles/`、`config/event-subtitles/`、`tests/test_main_event_subtitles.py` 和 `docs/MAIN_EVENT_SUBTITLES_20261013.md` 是另一路本篇字幕工作，**本次不要修改或接手**。共享 `udf.py` 已有主版本显式白名单参数，保留默认 SP 行为。

建立新的独立候选，不覆盖 V7 或生产输入，也不要把已补丁 V7 当作构建源重复打补丁：

```sh
python3 tools/special_disc/event_gallery/build.py \
  --source build/iso/special-disc/sp-current.iso \
  --output work/iso/sp-event-gallery-fidelity-review.iso \
  --workdir work/build/sp-event-gallery-fidelity

python3 -m unittest -v \
  tests.test_sp_event_gallery_records \
  tests.test_sp_event_gallery_textures

python3 tools/special_disc/event_gallery/verify_flow.py \
  work/analysis/sp-event-fidelity-20261013/runtime/commands.jsonl \
  --output work/analysis/sp-event-fidelity-20261013/flow-report.json
```

按变化补有意义的映射/恢复/边界检查。静态测试、ISO回读、LRPS2自然流程、原场景画面及音频对齐必须分别记录。不要以“全12项能返回”代替机体、镜头和BGM保真。

交付新的候选路径与精确哈希、12项对齐清单、关键帧/音频和可复查来源、返回恢复证据，以及仍未完成的具体项目。本次用户没有要求 commit/push；不要擅自发布或覆盖生产 ISO。
