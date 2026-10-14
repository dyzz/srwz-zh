# SP 事件演出鉴赏候选

第七版集中改善字幕：字号32，保留底部居中、白字黑描边、透明底；4倍显示尺寸的渲染结果直接平均缩到512×20原生像素，GS按1:1采样，避免40行纹理运行时丢掉隔行。详见 `docs/SP_EVENT_SUBTITLE_QUALITY_V7_20261013.md`。鉴赏完整性按用户要求暂缓，缺项见 `docs/SP_EVENT_COMPLETENESS_BACKLOG_20261013.md`。

第六版补齐魔神Z末尾原生单位替换与返回后的数据恢复，修正0x870对应2160帧，并补齐脉冲、DX、巨神Σ、盖塔龙的模型初始状态。37句采用润色稿，12标题采用用户确认版；字幕按4倍尺寸渲染后缩回，字号26、底部居中、白字黑描边透明底。LRPS2冷启动13轮覆盖12项，详情见 `docs/SP_EVENT_STAGE_AND_SUBTITLES_V6_20261013.md`。流程通过不表示完整原关卡单位配置均已移植。

第四版历史修复：字幕图片改为仅追加，纹理引用保守覆盖所有绘制记录，修复effect256图片被中文图集覆盖；地图初始化前清空显示缓冲，处理点击时旧列表变形。14轮LRPS2流程覆盖全部12项，本轮按用户指定以LRPS2验收，未做第四版ARMSX2人工验收。见 `docs/SP_EVENT_GALLERY_FIXES_20261013.md`。

2026-10-13字幕扩展：37句听校稿已完成，字号26并下移。资源包末尾缺少结束偏移导致的美玲无声及266加载内存破坏已修复；257屏幕反馈中的字幕残影已修复。最终候选已完成14轮原生输入的自然播放返回，覆盖全部12项；ARMSX2人工检查单独记录。详见 `docs/SP_EVENT_SUBTITLES_PROGRESS_20261013.md`。

基于当前 SP 汉化 ISO，在特别剧场增加第五张“事件演出”横幅及原生单页12项列表。列表回调选择独立地图与演出脚本，演出完成后恢复同一个列表对象和选中项。当前功能以独立候选交付。

## 构建

```sh
python3 tools/special_disc/event_gallery/build.py
```

默认输入为 `build/iso/special-disc/sp-current.iso`，输出 `work/iso/sp-event-gallery-zh.iso`，构建记录写入 `work/build/sp-event-gallery/receipt.json`。参数支持 `--source`、`--output`、`--workdir`、`--config`；生产 SP 及 rom 目录不能作为输出。构建完成所有回读后才将临时文件替换成最终候选。

核对已保存的原生流程日志：

```sh
python3 tools/special_disc/event_gallery/verify_flow.py \
  docs/issue-assets/sp-event-subtitles-20261013/runtime-final/commands.jsonl \
  --output /tmp/sp-event-gallery-flow.json
```

该检查要求全部条目完成请求、播放、自然结束、返回链路；截图会按实际状态关联，不能用原始截图名称判断场景。画面仍需人工检查。

依赖：项目 Python 工具、MIPS little-endian binutils、ImageMagick（当前字幕适配器使用 `/opt/homebrew/bin/magick`）、`work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf`。横幅直接消费 `assets/manifest.json` 锁定的索引纹理和 CLUT，不实时重绘。

## 实现与验证边界

- `menu.py` 保留原生标题、导航、帮助、原有页面及壁纸解锁替换，新增 page6。五个横幅缩短为60像素，原UV保持80像素。
- `runtime.S` 的帧入口只替换特别剧场 case0x46 的 `0x143ea8` callsite。普通状态调用原 UI；播放状态加载原地图并运行原生事件解释器；等待效果结束后释放地图、恢复 VRAM 和列表。
- `runtime.py` 从 `config/products/special-disc/event-gallery.json` 生成12条地图、镜头、脚本。脉冲串联273和274。原地图物件动作覆盖273、266、267、269；前置模型初始化另包含255，269末尾使用原生地图单位。其余独立关卡单位及关卡BGM还需另行还原。
- 257原剧情继承单位现场坐标，鉴赏明确采用独立锚点 `(13,7)`；各项初始镜头方向显式配置为3。流程测试不等于所有原关卡构图完全还原。
- `subtitles.py` 为12段演出的37句字幕按4倍显示尺寸生成后平均缩到原生透明纹理，1:1点采样，字号32、白字黑描边阴影，位于640×448画面的x64～576、y388～428。原动画、语音和模型记录保持字节一致；`runtime.S` 在原生演出和画面处理之后叠加字幕，使用独立屏幕坐标及关闭深度测试的图元。
- `transcribe.py` 从原生CCC时间轴提取37段原音，支持本地Whisper识别。`config/products/special-disc/event-subtitles.json` 保存原始识别、整理候选、中文字幕草稿及术语来源。全部字幕仍待用户听校。`render_review.py` 生成带内嵌原音的离线听校页面和Markdown文稿。
- 列表专用绘制钩子将12项放在一页，保留原字体大小，并将文字位置固定到原生整数坐标，避开入场滑动期间的模糊采样。
- ELF鉴赏段单独保留0x820000～0x8b0000，文件载荷仍为64KiB，后续BSS用于原生单位/驾驶员数据快照；原生堆起点由0x81c600调整至0x8b0000，原主线程栈保持。避免地图加载时使用高位临时内存覆盖鉴赏状态。
- AID块2扩展后，同步两套原生offset/decoded-size表。ELF与AID附加到候选ISO末尾，其余成员LBA和尺寸保持；同步ISO9660、UDF，以及游戏实际读取的 `VMAP.DAT` AID扇区记录。
- 静态与ISO回读、LRPS2冷启动流程、PCSX2人工验收分别记录。最新运行记录见 `docs/SP_EVENT_SUBTITLES_PROGRESS_20261013.md`；不能用LRPS2结果替代PCSX2人工验收。

横幅第二版采用“美玲＋脉冲出场”底图及原入口的黑色粗体标题，构建和新版冷启动检查见 `docs/SP_EVENT_GALLERY_BANNER_20261013.md`。第二版历史候选为 `work/iso/sp-event-gallery-ui-v2.iso`。底图、提示词和显式作者工具均在本目录保存；普通构建只消费锁定快照。

## 本轮边界修复

原生记录读取函数用下一条offset减去当前offset得到长度，末条也必须有结束offset。`subtitles.py` 的记录重打包补齐n+1个表项，避免末条CCC被跳过或按错误的超大长度复制；七条及八条资源包回归检查见 `tests/test_sp_event_gallery_records.py`。

257使用两个帧缓冲交替作屏幕反馈。字幕在原生画面处理后绘制；下一轮反馈读取前临时恢复无字幕背景，读取后还原显示内容，避免把字幕带入反复扭曲。仅257使用预留VRAM背景区，构建记录检查纹理分配不与背景区重叠。

本篇与SP的逐资源比较见 `docs/SP_EVENT_RESOURCE_COMPARISON_20261013.md`。原effect一致不能替代原关卡的舞台、单位及镜头逐段核对。

## 本篇机体、镜头与BGM对齐（2026-10-14）

每项配置的 `fidelity` 块是从Original STAGE脚本窗口逐条移植的时间线（BGM、缩放、单位出场/显隐/撤下、舞台模型、叠色渐暗、占位单位表），由 `fidelity.py` 编译为SP原生脚本记录；场景脚本位于字幕表之后的 `0x826800`。单位与驾驶员用SP定义编号，Original编号与映射依据随配置保存。`gallery_prepare_units` 用剧场名册模板或原生定义加载函数初始化空位，返回时由快照恢复；剧场BGM在场景声音请求空闲后原生重播。指令含义、逐段清单和LRPS2验收见 `docs/SP_EVENT_FIDELITY_20261014.md`。

## 并入统一构建（2026-10-14）

`apply.py` 是纯成员变换：输入全文本补丁后的 `SLPS_259.20`、原生 `AID_DATA/AIDDATA.BIN` 与
`EFF/VEFF2DX.BIN`，输出三个加入鉴赏的成员和绑定全部输入哈希的回执。`writeback/build_full_text.py`
在指令覆盖之后调用它，再由 `special_disc/iso_relocation.py` 把三个变大的成员追加到基线镜像后并
同步目录、`VMAP.DAT` 与 UDF；独立回读通过 `verify_gallery_members` 核对钩子、载荷段和 12 个字幕块。
日常入口就是 `python3 tools/build_editions.py --editions sp`，产物为 `build/iso/special-disc/sp-current.iso`。

`build.py` 仅保留为隔离实验包装：从一张已合成的 SP 镜像读出三个成员、做同样的变换并写到
`work/iso/` 下的候选；不写生产路径。菜单文案与写入器共用锁定码表
`work/build/special-disc/text-candidate/font/proposal.json`，字幕字体
`work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf` 已登记到 `config/editions/sp/inputs.json`。
