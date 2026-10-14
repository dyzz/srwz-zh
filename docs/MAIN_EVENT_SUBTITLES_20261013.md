# 本篇 Original / Best 原生事件字幕（2026-10-13）

> 2026-10-14 更新：用户确认字幕稿可接受后，本功能已并入 Original 与 Best 的统一构建（`build_editions.apply_main_event_subtitles`），当前镜像直接包含字幕；并入方式与结果见[构建整合记录](SP_EVENT_GALLERY_BUILD_INTEGRATION_20261014.md)。原关卡自然触发时的字幕显示仍待用户手打验收，本页其余内容保留为当时的记录。

## 范围和当前状态

本篇两版只给原关卡中的事件演出增加中文字幕，不增加鉴赏菜单，不移植 SP 的独立舞台或播放脚本。继续使用各自原版的关卡触发、镜头、单位、声音和 BGM。SP 鉴赏完整性的后续事项仍见原有 backlog，本次不扩大范围。

两个 V2 候选已构建并通过目标成员及 13 个 effect 的解码回读；**原关卡字幕实际显示尚未验收通过，不应替换生产 ISO 或发布为已完成版本。**

## 哪些文件可以共用

- 共用字幕源稿、字体、栅格化规则及运行时汇编源；字幕保持 SP V7 的白字黑描边、透明底、底部居中样式。
- Original 与 Best 的 13 个目标 effect 中，12 个连压缩流都相同。effect256 解码后仅在 `0x2107be` 差一字节：第710帧 CCC20354 / CCC20358；两编号对应音频完全相同。
- 两版本篇38段实际音频中，37段逐字节相同。巨神Σ第360帧 CCC68 的编码和长度不同；这不能证明台词改变。
- SP 的 CCC 编号重排，且 effect256 第710帧是停止语音，本篇两版则为2.735秒有声片段。不得直接复制整份 SP effect 覆盖本篇。
- ELF、资源地址表、效果池、GS状态地址等分别配置。Best 的链接差异不是单一固定偏移；不得共用已补丁的 ELF 二进制。

详细证据见[资源比较](SP_EVENT_RESOURCE_COMPARISON_20261013.md)、[Original/Best effect 记录](issue-assets/main-event-subtitles-20261013/original-best-effects.json)与[38段音频比较](issue-assets/main-event-subtitles-20261013/original-best-38-voices.json)。

## 文稿和字幕实现

沿用 `config/products/special-disc/event-subtitles.json` 的37句稿；`config/event-subtitles/main-only-captions.json` 为本篇增加一条第710～830帧拟声字幕“呜……啊……”，本地 Whisper 原识别为 `うおぉ… / あ~…`，**仍待用户听校**。SP37句不改。补充原音和稿件见[听校页](issue-assets/main-event-subtitles-20261013/supplemental-review.html)。

新增字幕 TIM2 记录附加到各版原 effect，保留原动画、模型及语音记录。V7 以4倍显示分辨率制作后降采样到512×20纹理，字号32，实际显示约40像素高，GS按1:1点采样绘制到画面底部。没有新增黑底。

独立字幕代码位于 `0x790000～0x7a0000`，不含鉴赏驱动；最终绘制钩子为 `0x143830`，反馈绘制钩子为 `0x143800`。反馈保护只在 effect257 活动时启用。分配器起点向后移，原启动 BSS 清零边界保持不动，避免把新增代码清零。

## 候选与构建

生产输入：

- `build/iso/zh-release-original/current-original.iso`
- `build/iso/zh-release-best/current-best.iso`

隔离候选：

- `work/iso/event-subtitles-original-v2-review.iso`，ELF SHA256 `d000e75d47bf0451a2c325b748f0cbb6e5fceb17795a3cb7754094bc8c550760`
- `work/iso/event-subtitles-best-v2-review.iso`，ELF SHA256 `37b04085ad7cd88bd25db9b13a409e22a43be7c3b7b848d2b90c92e00de0c766`

构建入口 `tools/event_subtitles/build.py --edition original|best`；请显式指定 `--output` 和 `--workdir` 为 V2 或后续独立实验路径，默认仍为 V1 实验名称。构建收据在 `work/build/event-subtitles-{original,best}-v2/receipt.json`，记录源 ELF 哈希、字幕源哈希、资源表更新、UDF/VMAP 迁移和回读断言。

只迁移 ELF 和 VEFF；VMAP 中继承的非目标差异保持原状并列入收据。关卡脚本、地图和音频成员保持不变。生产 ISO 未替换，SP V7 未改。

## 验证边界与剩余工作

静态及 ISO 回读已完成：两版本构建成功，目标资源解码一致，原语音记录保留，非目标 effect 流保留，新增 ELF 段不与原加载段重叠，UDF与ISO9660目标位置同步。

LRPS2 当前只使用 V1（37句）进行原关卡路径实验：从隔离测试卡进入 STAGE002，确认目标钩子、字幕代码和绘制头实际载入。为绕过后续战斗条件，在隔离 RAM 设置关卡标志20/21，原事件扫描执行了原关卡 A370 脚本和奥尔对话；随后停留在水面镜头，目标273尚未观测到活动，字幕计数仍为0。**这不能作为自然触发流程或字幕显示通过的证据。**测试卡仅改下一关编号及校验，未改用户存档；其完整队伍状态并非本关自然开局，可能影响原舞台前置条件。

V2 比 V1 仅增加本篇额外语音字幕及 effect256 的一行图集；运行时代码相同。V2 尚未取得实际字幕画面。下一步应取得正确 STAGE002 原生现场或按原流程推进，避免继续强制不完整的舞台状态；再验证脉冲完整演出和字幕显示，并对4位贴图与鸫反馈扭曲段单独验收。12段原关卡逐项覆盖尚未完成，SP 已通过的鉴赏验收不能替代这里的验证。

原始 LRPS2 日志与截图位于 `work/analysis/main-event-subtitles-20261013/{original,best}-stage002-runtime/`。静态、ISO回读与运行画面必须分别报告。

## 用户手打交付与本轮停止点

用户最新决定：第二关由用户手打验证；Claude只接手SP剧场的必要机体、镜头、舞台和BGM对齐，使用LRPS2。不要继续扩大本篇验证的反编译/测试注入路线。

本轮已取得Original V1通过原生资源加载器单独播放273时的字幕画面，见 `issue-assets/main-event-subtitles-20261013/original-v1-component-caption.png`；这是受控组件验证，不是原关卡自然触发。V2 Original/Best均已冷启动并读入第二话，日志在 `work/analysis/main-event-subtitles-20261013/{original,best}-v2-early-party/`。提前设置剧情标志进入A370的实验仍未观测到原脚本创建273，所需457/461/465单位未出现在当时的活动单位表；后来直接进入AB40的实验也没有证明该前置已经补齐。不得把“AB40=初始化阶段3”或“连续确认必然跳过effect”等调试假设写成已证实结论。原生第二话自然触发字幕仍待用户手打。

已停止本轮的四个LRPS2测试进程。未修改候选ISO、生产ISO或用户记忆卡。

独立交付在 `work/handoff/main-event-subtitles-20261013/`：`srwz-setsuko-stage02-slot6.ps2`、同名PSU、README与来源收据。它是仅保留第6格的干净记忆卡，读档后从中场休息选择下一地图进入第二话。来源为派生测试存档，不声称自然第二话队伍；原数据已在两版V2中加载，清理后做了导入/导出和校验回读，没有再重复整段运行。

SP交接文件：`docs/CLAUDE_HANDOFF_SP_EVENT_FIDELITY_20261013.md`。
