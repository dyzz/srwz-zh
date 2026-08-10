# 《超级机器人大战 Z》简体中文版

这是《超级机器人大战 Z》PS2 日文版的非官方简体中文化项目。

当前版本为 **v0.1.0 测试版**。游戏的主要剧情、常用菜单、人物与机体名称以及
大部分战斗相关文本已经完成中文化。我们仍在进行实际游玩测试，并会继续修正
残留日文、错别字、术语不统一和显示问题。

## v0.1.0 汉化内容

- 154 个剧情关卡的对白、说话人、关卡条件和关卡概要；
- 人物名、机体名和武器名；
- 强化零件、换装部件、机体特殊能力和驾驶员特殊技能；
- 精神指令、战斗指令、队长能力、搜索菜单和胜败条件；
- 战斗动画中的语音字幕；
- 世界地图地名、场景选择标题和中场休息菜单；
- 统一整理并润色了高频人名、机体名、武器名及相关术语；
- 统一中文字形、标点和全角空格，修复了一批乱码及文本污染问题。

## 当前状态

v0.1.0 已完成自动检查和镜像内容回读，但尚未完成覆盖所有路线的完整通关测试。
正常游玩中仍可能遇到以下情况：

- 少量界面或特殊流程中残留日文；
- 个别文本的换行、长度或显示位置不理想；
- 人物图鉴正文、机体图鉴正文、名词解释（用语列表）和游戏内教程均尚未汉化，
  不属于 v0.1.0 的完成范围；
- 某些战斗字幕或较少触发的分支事件仍需实际画面确认。

如果你更看重稳定体验，建议等待后续版本；如果愿意协助测试，欢迎记录发生问题的
关卡、操作步骤和画面截图并通过
[GitHub Issues](https://github.com/dyzz/srwz-zh/issues) 反馈。

## 下载与使用

本项目不会提供或分发游戏 ISO、存档及其他原版游戏数据。你需要自行合法持有
《超级机器人大战 Z》PS2 日文原版。补丁和源码构建统一以
[Redump Disc 4932](https://redump.info/disc/4932/) 的原始版镜像为基准。

目前 v0.1.0 仍在准备可分发补丁包。补丁通过最终运行检查后，将在
[GitHub Releases](https://github.com/dyzz/srwz-zh/releases) 提供下载、校验值和
具体使用说明。使用补丁前请备份原版镜像和存档，并以对应发布页面的说明为准。

## 从源码构建

普通玩家不需要自行构建，发布版补丁会附带单独的使用说明。以下流程面向希望参与
开发或复验结果的贡献者。

构建需要 Python 3、Git、CMake、Rust／Cargo、7-Zip 和 ImageMagick 7，并需要
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

在已经完成本地原版成员和 `release-base-ui` 基线准备的项目工作区中执行：

```bash
python3 tools/verify_original_disc.py
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_rust_compressor.py

python3 tools/fetch_zh_font.py
python3 tools/fetch_zh_font.py \
  --flavor config/fonts/zh-localization-font-light.json
python3 tools/rebuild_zh_font.py --skip-fetch

python3 tools/build_iso.py \
  --config config/iso/zh-release-full-story-build.json
python3 tools/verify_full_story_iso_content.py --force
python3 tools/build_release.py \
  --config config/release/v0.1.0.json
```

构建成功后，镜像位于：

```text
build/iso/v0.1.0/srwz-zh-v0.1.0.iso
```

本地完整 ISO 只用于开发和运行验证，不进入发布包。可分发文件位于：

```text
build/release/v0.1.0/srwz-zh-v0.1.0.zip
```

其中只包含 xdelta 补丁、使用说明、发布清单和 SHA-256 校验值，不包含游戏 ISO。

当前构建采用固定原版和一次性组件组合，不应在旧汉化镜像上重复打补丁。首次环境
准备、原版成员提取、构建缓存和详细验证规则见
[构建与运行验收](docs/BUILD_AND_RUNTIME.md)。

## 致谢

特别感谢 [fortiersteven/Super-Robot-Wars-Z](https://github.com/fortiersteven/Super-Robot-Wars-Z)
提供的早期研究与工具基础。本项目参考并固定引用了该项目提交
[`a6cefe8b51dfd949e16000442084d24594841e8f`](https://github.com/fortiersteven/Super-Robot-Wars-Z/commit/a6cefe8b51dfd949e16000442084d24594841e8f)
中的部分归档成员定义和文本表结构。

ISO 构建使用 [mkps2iso](https://github.com/N4gtan/mkps2iso)。中文字体使用
HarmonyOS Sans，并对少数字符使用 Noto Sans CJK；第三方字体及许可信息见
[第三方字体说明](docs/THIRD_PARTY_FONTS.md)。

也感谢所有参与翻译、术语考证、测试和问题反馈的贡献者与玩家。

## 项目说明

本项目是非官方、非商业的爱好者项目，与原作权利方不存在隶属或授权关系。
《超级机器人大战 Z》及相关作品、角色和名称的权利归各自权利方所有。

<details>
<summary>v0.1.0 当前候选的技术信息</summary>

- 汉化版本：`v0.1.0`
- 原版 ISO 大小：`3,758,358,528` 字节
- Redump：Disc `4932`，文件名 `Super Robot Taisen Z (Japan, Korea).iso`
- 原版 ISO SHA-256：`ddbedefc0061213c50928fb213a7fb277c0345f01dab7386adc0383638a78cd2`
- 当前候选 ISO SHA-256：`40ddc19e752cde0eaa1e9c3baaa98ca52a15c9e169f1676ab315297f33a61c2c`
- 当前候选已通过确定性构建、ISO 结构检查和最终文本回读；精确镜像的完整运行
  验收仍在进行中。

这里的校验值用于锁定开发中的当前候选，不代表已经发布的补丁文件。正式下载请以
对应 Releases 页面的文件名和校验值为准。

</details>

开发、构建与验证资料见 [项目文档](docs/README.md)，参与贡献前请阅读
[贡献与发布约定](CONTRIBUTING.md)。
