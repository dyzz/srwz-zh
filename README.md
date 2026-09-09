# 《超级机器人大战 Z》简体中文版

这是《超级机器人大战 Z》PS2 日文版的非官方简体中文化项目。

当前版本为 **v0.4.0**，同时支持 Original（初版）和 The Best（廉价版）。
本次整合 v0.3.0 发布后的玩家反馈，集中校订剧情、战斗台词和图鉴，并修复多处
动态姓名、战斗提示及界面排版问题。完整内容见 [v0.4.0 发布说明](docs/RELEASE_NOTES_V0.4.0.md)。

## 本次更新

- 双版本支持：两版复用同一套中文内容；Original 回迁部分 The Best 文字和数据订正，
  The Best 保留本版的程序、动画、语音及片尾修订。
- 文本校对：相较 v0.3.0，审阅站可追踪的剧情、战斗及名称更新共 4,901 条；
  另通读全部 784 个图鉴条目，并校订关键词和攻略 Q&A。
- 动态文字：全名统一为“小原节子”，恢复姓名颜色区分，修正武器分类和战舰类型显示。
- 战斗与界面：补齐简略战斗提示及完整演出文字，修复章节字卡乱码，调整集市、
  系统帮助、编成说明、SR 点数及通关模式界面的显示。
- 通关模式：进入通关后的模式选择界面即可选择特殊模式，无需双主角通关。

[机战 Z 中文化审阅站](https://srwz.dreamquest.club) 支持中日文对照、全文搜索、
逐条改稿建议和更新追踪。运行问题也可通过 [GitHub Issues](https://github.com/dyzz/srwz-zh/issues)
提交，请附版本、设备或模拟器、关卡路线、触发步骤、截图，以及问题发生前的记忆卡存档。

## 下载与使用

前往 [v0.4.0 GitHub Release](https://github.com/dyzz/srwz-zh/releases/tag/v0.4.0)，
按自己持有的日文原盘选择 **一个** 补丁：

| 原盘 | 补丁 |
| --- | --- |
| Original 初版，SLPS-25887 / 1.04 | `srwz-zh-v0.4.0-original.xdelta` |
| The Best 廉价版，SLPS-73270 / 2.00 | `srwz-zh-v0.4.0-best.xdelta` |

两个补丁分别从对应日文原盘生成完整中文版本。请勿在旧汉化版或其他修改版镜像上
重复打补丁，操作前请备份镜像和存档。原盘及成品校验值、xdelta3 命令见
[安装与校验](docs/RELEASE_NOTES_V0.4.0.md#6-安装与校验)。

本项目只分发 xdelta 补丁，不提供游戏 ISO、存档或其他原版游戏数据。
两版最终镜像已完成构建、静态内容回读和补丁还原校验；精确发布镜像未重新执行
PCSX2 人工验收，全路线运行测试仍在继续。

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

在项目工作区中执行：

```bash
python3 tools/verify_original_disc.py
python3 tools/extract_iso_member.py --force \
  SLPS_258.87 \
  MAP/MAPMODEL.BIN EFF/VEFF2DX.BIN \
  BTL/OP0.BIN BTL/OP0.SEG BTL/OP1.BIN BTL/OP1.SEG \
  BTL/OP2.BIN BTL/OP2.SEG BTL/SRVC.BIN BTL/SRVC.SEG \
  DATA/COMPDATA.BN DATA/HSFC.BIN DATA/JTIM.BIN \
  DATA/MTV_PROP.BIN DATA/MTV_PROS.BIN \
  DATA/MTVZKNKW.BIN DATA/MTVZKNPT.BIN DATA/MTVZKNRT.BIN \
  DATA/NISVDATA.BIN DATA/STAGE.BIN DATA/VT1.BIN
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_rust_compressor.py

python3 tools/fetch_zh_font.py
python3 tools/fetch_zh_font.py \
  --flavor config/fonts/zh-localization-font-light.json
python3 tools/rebuild_zh_font.py --skip-fetch --force-rebuild

python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json
python3 tools/verify_full_story_iso_content.py --force
```

构建成功后，镜像位于：

```text
build/iso/zh-release-full-story/current-original.iso
```

同批构建 Original 与 BEST 时，另需 `rom/best.iso`，再运行
`python3 tools/build_editions.py --editions original,best`。此入口冻结同一份中文输入，
为两版生成独立 ISO 和回读记录；原盘身份、输出位置及运行验证边界见
[当前 BEST 构建](docs/BEST_CURRENT_BUILD.md)。

本地完整 ISO 只用于开发和运行验证，不进入发布包。v0.4.0 发布要求先完成
同批双版本构建，并将两版结果复制到锁定的版本目录；具体冻结路径、发布配置和
验证边界见 [v0.4.0 构建与发布记录](docs/RELEASE_BUILD_V0.4.0.md)。

```bash
python3 tools/build_release.py --config config/release/v0.4.0.json
```

可分发补丁位于 `build/release/v0.4.0/`。发布工具逐个从对应日文原盘实际还原并
验证成品哈希，目录中只保留两个 xdelta、说明、清单和 SHA-256 校验值。

当前构建采用固定原版和一次性组件组合，不应在旧汉化镜像上重复打补丁。首次环境
准备、原版成员提取、构建缓存和详细验证规则见
[构建与运行验收](docs/BUILD_AND_RUNTIME.md)。

## 致谢

特别感谢以下玩家在测试、文本校对、术语考证、问题复现和截图反馈等方面提供的帮助：

要开心💛、天敌Nep、Fanta-_、巨蟹fhhfhh、爱笑的ll206、贴吧用户_7EyM723、
AL-E、丸子行者、yagamitmd、紫荆花火、八翼大天使小鹿、苏苏千层饼、
Selkie诗依路、EVA高达、往常99、木扣螺丝、菠蘿达、qw3r4y、jegun、
蒙古王者风行烈、帝王松哥、贴吧用户_aZMJb7Q、白鸟九十九、bgcnh、
bili1040142989、内阁学士、审阅站用户「兰德与桑德曼」、hhbbghjjbbhhhg。

也感谢所有参与测试、提供反馈并持续关注项目的玩家。大家的帮助让许多低频路线、
特殊界面和文本细节得以被发现和完善。

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

发布镜像的精确身份见 [v0.4.0 发布验证清单](manifests/releases/v0.4.0/validation.json)。
`current-original.iso` 与 `current-best.iso` 用于后续开发，版本化发布镜像保持独立。

开发、构建与验证资料见 [项目文档](docs/README.md)，参与贡献前请阅读
[贡献与发布约定](CONTRIBUTING.md)。
