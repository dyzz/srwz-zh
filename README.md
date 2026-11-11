# 《超级机器人大战 Z》简体中文版

这是《超级机器人大战 Z》PS2 日文版的非官方简体中文化项目。

当前版本为 **v0.5.0 正式版**，支持 Original（初版）、The Best（廉价版），并首次正式加入 SP 特别盘汉化。
依赖 Original（初版）金手指的玩家可继续选择 Original 补丁。
完整内容见 [v0.5.0 发布说明](docs/RELEASE_NOTES_V0.5.0.md)。

想了解官方原盘改了什么，见 [初版与 The Best 详细差异（面向玩家）](docs/BEST_VERSION_GUIDE.md)，
一篇看完程序、战斗演出、音库修正，以及剧情、字幕、说明和图鉴的前后差异。

## 本次更新

- SP 特别盘新增中文剧情、挑战、图鉴及鉴赏内容，名场面集可选择播放演出或连同对白观看。
- 本篇原关卡的部分事件演出补上中文字幕，三版同步更新译文、战斗台词、术语及排版。
- 三版内置方块 skip，战斗动画中按住方块键（□）可跳到下一个阶段。
- Original 与 The Best 的图鉴和梗概按原版进度解锁，并提供两组独立的[可选全开金手指](docs/LIBRARY_UNLOCK_TEST_CHEATS_20261106.md)。

[机战 Z 中文化审阅站](https://srwz.dreamquest.club) 支持中日文对照、全文搜索、
逐条改稿建议和更新追踪。运行问题也可通过 [GitHub Issues](https://github.com/dyzz/srwz-zh/issues)
提交，请附版本、设备或模拟器、关卡路线、触发步骤、截图，以及问题发生前的记忆卡存档。

## 下载与使用

前往 [v0.5.0 GitHub Release](https://github.com/dyzz/srwz-zh/releases/tag/v0.5.0)，
按自己持有的日文原盘选择 **一个** 补丁：

| 日文原盘 | 补丁 |
| --- | --- |
| Original 初版，SLPS-25887 / 1.04 | `srwz-zh-v0.5.0-original.xdelta` |
| The Best 廉价版，SLPS-73270 / 2.00 | `srwz-zh-v0.5.0-best.xdelta` |
| SP 特别盘，SLPS-25920 / 1.01 | `srwz-zh-v0.5.0-sp.xdelta` |

请备份原盘与记忆卡存档，直接使用对应的未修改日文 ISO 打补丁。操作示例和校验方式见
[选择补丁与校验](docs/RELEASE_NOTES_V0.5.0.md#选择补丁与校验)。发行附件为 xdelta 补丁及说明。

## 从源码构建

普通玩家不需要自行构建，发布版补丁会附带单独的使用说明。以下流程面向希望参与
开发或复验结果的贡献者。

构建需要 Python 3、Git、CMake、Rust／Cargo、xdelta3 和 ImageMagick 7，并需要
联网下载锁定版本的开源构建工具与字体。将自己合法持有的日文原版镜像放到：

```text
rom/original.iso
```

原版镜像应为 `3,758,358,528` 字节，SHA-256 为：

```text
ddbedefc0061213c50928fb213a7fb277c0345f01dab7386adc0383638a78cd2
```

工作区统一使用本地文件名 `original.iso`；Redump 规范名称
`Super Robot Taisen Z (Japan, Korea).iso` 仍保留在来源元数据和玩家补丁说明中。
Redump 校验值为 CRC-32 `0d9deb37`、MD5
`b8ea8ff82ce2d6e09aa550635a5f61b4`、SHA-1
`e8dbe37e88afe8f82d48889b0775274ccde3cf99`。

唯一的生产构建入口是统一入口，它会自行完成原盘校验、成员提取、工具链、字体、
组件、封盘和整盘回读，并按版本写出独立 ISO 与回执：

```bash
python3 tools/build_editions.py                      # 默认构建 Original、The Best 和 SP
python3 tools/build_editions.py --release-version 0.5.0
python3 tools/build_editions.py --editions original,best
python3 tools/build_editions.py --editions sp
python3 tools/build_editions.py --force-rebuild      # 不复用任何组件与文件身份记录，完整重算（内容寻址的压缩结果缓存仍可命中）
```

输入未变时直接复用已验证的当前 ISO；只改语料时沿用上一批的已验证组件缓存，
只重建受影响组件。Original 支持成员级增量封盘，SP 仍完整合成 ISO 并独立回读。
The Best 使用 Original 共享前端。单独构建 The Best 时，Original 只作为构建中间步骤。
各版当前镜像的路径如下。

```text
build/iso/zh-release-original/current-original.iso
build/iso/zh-release-best/current-best.iso
build/iso/special-disc/sp-current.iso
```

SP 需要日文原盘、xdelta3 和锁定的字体／基线组件；准备方法、输出路径、缓存规则与
验证命令见 [三版本构建](docs/BUILD_EDITIONS.md)。本篇原盘身份及运行验证边界见
[当前 BEST 构建](docs/BEST_CURRENT_BUILD.md)。统一入口内部调用的分步工具
（`rebuild_zh_font.py`、`build_iso.py`、`verify_full_story_iso_content.py` 等）
只用于排错和资源维护，见 [构建与运行验收](docs/BUILD_AND_RUNTIME.md)。

本地完整 ISO 用于开发和运行验证。release 固定包含
Original、The Best 和 SP，三版全部内置方块 skip，每版一份补丁。先冻结同一批次的
三版已验证镜像并回读 skip hook，再生成发布包：

```bash
python3 tools/freeze_release.py --manifest work/editions/<摘要>/original-best-sp.json --version <x.y.z>
python3 tools/build_release.py --config config/release/v<x.y.z>.json
```

可分发补丁位于 `build/release/v<x.y.z>/`，文件名分别以 `-original.xdelta`、`-best.xdelta`、
`-sp.xdelta` 结尾。发布工具逐个从对应日文原盘实际还原并验证成品哈希，目录中只保留
三个 xdelta、说明、清单和 SHA-256 校验值。SP 补丁必须用于 SP 日文原盘。
v0.4.2 的历史四补丁配置仍可重建，流程见 [v0.4.2 构建与发布记录](docs/RELEASE_BUILD_V0.4.2.md)。

当前构建采用固定原版和一次性组件组合，不应在旧汉化镜像上重复打补丁。首次环境
准备、原版成员提取、构建缓存和详细验证规则见
[构建与运行验收](docs/BUILD_AND_RUNTIME.md)。

## 致谢

感谢 **黑泽小皮** 参与文本校对、战斗台词审阅和游戏测试反馈。
特别感谢 **尼禄卡奥斯** 授权参考其《机战 Z》汉化实况译文资料，帮助我们校对和润色文本。

特别感谢以下玩家在测试、文本校对、术语考证、问题复现和截图反馈等方面提供的帮助：

要开心💛、天敌Nep、Fanta-_、巨蟹fhhfhh、爱笑的ll206、贴吧用户_7EyM723、
AL-E、丸子行者、yagamitmd、紫荆花火、八翼大天使小鹿、苏苏千层饼、
Selkie诗依路、EVA高达、往常99、木扣螺丝、菠蘿达、qw3r4y、jegun、
蒙古王者风行烈、帝王松哥、贴吧用户_aZMJb7Q、白鸟九十九、bgcnh、
bili1040142989、内阁学士、hhbbghjjbbhhhg、大根1112、ReniMil、贴吧用户_a6bM8ty。

审阅站（含历史昵称）：

兰德与桑德曼、兰德、桑德曼、巨蟹、优莱卡、理惠、平成鱼、蒂珐、
丹泽尔、卡洛德、艾法、卡缪、亚伯、史黛拉、裘露。

也感谢 Ae1b 的留言鼓励，以及所有参与测试、提供反馈并持续关注项目的朋友。
大家的帮助让许多低频路线、特殊界面和文本细节得以被发现和完善。

特别感谢 [fortiersteven/Super-Robot-Wars-Z](https://github.com/fortiersteven/Super-Robot-Wars-Z)
提供的早期研究与工具基础。本项目参考并固定引用了该项目提交
[`a6cefe8b51dfd949e16000442084d24594841e8f`](https://github.com/fortiersteven/Super-Robot-Wars-Z/commit/a6cefe8b51dfd949e16000442084d24594841e8f)
中的部分归档成员定义和文本表结构。

ISO 构建使用 [mkps2iso](https://github.com/N4gtan/mkps2iso)。中文字体使用
HarmonyOS Sans，并对少数字符使用 Noto Sans CJK；第三方字体及许可信息见
[第三方字体说明](docs/THIRD_PARTY_FONTS.md)。

也感谢所有参与翻译、术语考证和开发工作的贡献者。

## 项目说明

本项目是非官方、非商业的爱好者项目，与原作权利方不存在隶属或授权关系。
《超级机器人大战 Z》及相关作品、角色和名称的权利归各自权利方所有。

发布镜像的精确身份和验收范围见 [v0.5.0 构建与发布记录](docs/RELEASE_BUILD_V0.5.0.md)。

开发、构建与验证资料见 [项目文档](docs/README.md)，参与贡献前请阅读
[贡献与发布约定](CONTRIBUTING.md)。
