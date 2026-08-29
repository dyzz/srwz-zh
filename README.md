# 《超级机器人大战 Z》简体中文版

这是《超级机器人大战 Z》PS2 日文版的非官方简体中文化项目。

当前版本为 **v0.3.0 测试版**。v0.3.0 主要补齐攻略与教学内容，集中处理
v0.2.0 发布后的玩家反馈，并对剧情、战斗、资料库和系统界面进行新一轮校对与完善。

## 内容补全

- 完成攻略 Q&A 的首轮汉化与整理，改善问题、答案、编号和分项内容的排版。
- 完成教学关卡相关标题、说明文字和操作提示的汉化，清理残留日文。
- 补充部分路线章节标题、场间剧情、隐藏市场字幕、特殊报告、奖励提示，以及只在
  特定路线、章节或条件下出现的漏翻内容。
- 同步更新关卡概要、路线说明和攻略资料。

## 文本校对与润色

本次文本润色重点参考了 v0.2.0 发布后大家提供的截图、场景信息和校对建议。除了
修正反馈中指出的台词，也进一步检查了同一角色、同一术语和相近场景中的相关文本，
尽量避免只修改截图中的单独一句。

- 剧情对白：修正误译、直译和上下文衔接问题，使中文表达更加自然。
- 角色口吻与称呼：根据人物性格和彼此关系调整语气，统一昵称、敬称、职务及敌对称呼。
- 战斗台词：修正攻击、受击、回避、反击和击坠等场景中的语气问题，并调整部分喊招
  与战斗口令。
- 名称与术语：参考玩家提供的系列译名和作品用语，继续统一人物、机体、武器、招式、
  组织及世界观术语，减少剧情、菜单、战斗和资料库之间的译名差异。
- 图鉴与说明：调整人物图鉴、机体图鉴及各类说明文字中的病句、断句和不自然表达。
- 修正“应援”、武器特殊效果等界面名称，并处理部分英文口号被直接音译的问题。
- 根据大家对梅尔台词的集中反馈，校对相关剧情中的误听、说反、俗语和冷笑话，尽量
  在中文中保留原有笑点。
- 统一“达令”“甜心”“THE CRUSHER”等反复称呼，并调整梅尔与兰德互动、共同驾驶
  及关键情感台词，使人物口吻和前后呼应更加自然。

## LIBRARY 与系统界面

- 完善剧情流程、音乐选择等深层界面的中文标题。
- 调整 LIBRARY 六个入口的位置和对齐，修正标题背景、透明效果及日文残影。
- 机体图鉴、角色事典、术语事典和剧情流程默认开放，方便直接查看相关资料。
- 调整搜索界面的精神指令、特殊技能、队长效果、特殊能力和小队奖励等标签。
- 继续清理出击、编队、换乘、强化零件、市场、快捷命令和技能查询等界面的残留日文。
- 补充自动编队相关中文文本，并修正剩余小队数量的格式显示。
- 修正部分资料库条目中的名称、声优、简介和正文对应问题。

## 显示与排版修正

- 修正教学关卡标题出现黑边、残留日文或位置偏移的问题。
- 改善攻略 Q&A 中编号、选项和分项内容的间距。
- 修正少量汉字显示错误、字符宽度异常和文字居中偏差。
- 改善长句、窄框提示、多行说明以及数字与英文单位的间距。
- 修正队形说明、战术换装、战斗预报和部分确认框中的乱码或排版问题。

由于游戏包含大量路线分支、条件台词和低频界面，仍可能存在未发现的问题。反馈时请
尽量附上所用版本、关卡、路线、触发步骤和画面截图，并通过
[GitHub Issues](https://github.com/dyzz/srwz-zh/issues) 提交。完整改动说明见
[v0.3.0 发布说明](docs/RELEASE_NOTES_V0.3.0.md)，LIBRARY 技术范围见
[LIBRARY 汉化范围](docs/LIBRARY_V02_SCOPE.md)。

## 下载与使用

本项目不会提供或分发游戏 ISO、存档及其他原版游戏数据。你需要自行合法持有
《超级机器人大战 Z》PS2 日文原版。补丁和源码构建统一以
[Redump Disc 4932](https://redump.info/disc/4932/) 的原始版镜像为基准。

v0.3.0 可分发补丁包已通过 xdelta 还原校验，并在
[GitHub Releases](https://github.com/dyzz/srwz-zh/releases) 提供下载、校验值和
具体使用说明。使用补丁前请备份原版镜像和存档，并以对应发布页面的说明为准。

## 从源码构建

普通玩家不需要自行构建，发布版补丁会附带单独的使用说明。以下流程面向希望参与
开发或复验结果的贡献者。

构建需要 Python 3、Git、CMake、Rust／Cargo、xdelta3、7-Zip 和 ImageMagick 7，并需要
联网下载锁定版本的开源构建工具与字体。将自己合法持有的日文原版镜像放到：

```text
rom/Super Robot Taisen Z (Japan, Korea).iso
```

原版镜像应为 `3,758,358,528` 字节，SHA-256 为：

```text
ddbedefc0061213c50928fb213a7fb277c0345f01dab7386adc0383638a78cd2
```

文件名必须保持为 Redump 规范名称
`Super Robot Taisen Z (Japan, Korea).iso`；发布补丁附带的 xdelta 命令也固定使用
这个文件名。Redump 校验值为 CRC-32 `0d9deb37`、MD5
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
python3 tools/rebuild_zh_font.py --skip-fetch

python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json
python3 tools/verify_full_story_iso_content.py --force
python3 tools/build_release.py \
  --config config/release/v0.3.0.json
```

构建成功后，镜像位于：

```text
build/iso/zh-release-full-story/srwz-zh-current.iso
```

本地完整 ISO 只用于开发和运行验证，不进入发布包。可分发文件位于：

```text
build/release/v0.3.0/srwz-zh-v0.3.0.zip
```

其中只包含 xdelta 补丁、使用说明、发布清单和 SHA-256 校验值，不包含游戏 ISO。

v0.3.0 从锁定原版成员直接重建，不依赖旧汉化成员或内部 xdelta。组件阶段按物理
文件收敛为三个构建组：可执行文件／字体／核心 UI、文本与资料归档、战斗／地图／
特效归档；随后只进行 ISO 组合、静态回读和发布包生成。同一个物理文件只属于一个
构建组；同一压缩流先解压，批量完成该流的全部写入，最后统一压缩。详细边界和完整命令见
[`docs/BUILD_AND_RUNTIME.md`](docs/BUILD_AND_RUNTIME.md)。

当前构建采用固定原版和一次性组件组合，不应在旧汉化镜像上重复打补丁。首次环境
准备、原版成员提取、构建缓存和详细验证规则见
[构建与运行验收](docs/BUILD_AND_RUNTIME.md)。

## 致谢

特别感谢以下玩家在测试、文本校对、术语考证、问题复现和截图反馈等方面提供的帮助：

要开心💛、天敌Nep、Fanta-_、巨蟹fhhfhh、爱笑的ll206、贴吧用户_7EyM723、
AL-E、丸子行者、yagamitmd、紫荆花火、八翼大天使小鹿、苏苏千层饼、
Selkie诗依路、EVA高达、往常99、木扣螺丝、菠蘿达、qw3r4y 与 jegun。

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

<details>
<summary>当前开发候选的技术信息</summary>

- 汉化基线：`v0.3.0`
- 原版 ISO 大小：`3,758,358,528` 字节
- Redump：Disc `4932`，文件名 `Super Robot Taisen Z (Japan, Korea).iso`
- 原版 ISO SHA-256：`ddbedefc0061213c50928fb213a7fb277c0345f01dab7386adc0383638a78cd2`
- 当前候选 ISO SHA-256：`64b42bf2134b368037fcfdd20abc068a417f95817ff10fb801d06fd6f28961f9`
- 当前候选已通过确定性构建、ISO 结构检查和最终文本回读；精确镜像的完整运行
  验收仍在进行中。

这里的校验值用于锁定开发中的当前候选，不代表已经发布的补丁文件。正式下载请以
对应 Releases 页面的文件名和校验值为准。

</details>

开发、构建与验证资料见 [项目文档](docs/README.md)，参与贡献前请阅读
[贡献与发布约定](CONTRIBUTING.md)。
