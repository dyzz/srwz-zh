# 许可范围 / License scope

The [MIT license](../LICENSE) covers the original work in this repository: the build
tools, analysis and patching scripts, the music player (`tools/special_disc/`),
tests, and the documentation written for this project.

[MIT 许可证](../LICENSE)适用于本仓库的原创部分：构建工具、分析与改版脚本、音乐播放器
(`tools/special_disc/`)、测试，以及本项目自行撰写的文档。

## Not covered / 不在许可范围内

1. **Game data and text derived from Super Robot Wars Z.** The Japanese source
   text under `corpus/ja/`, and the Chinese translations under `corpus/zh/`,
   `config/editorial/` and `manifests/` that are derived from it, are based on
   copyrighted material owned by Bandai Namco Entertainment / Banpresto. They
   are included only to make this fan translation reproducible, and are not
   licensed for reuse. No game assets or disc images are distributed here.

   **源自《超级机器人大战 Z》的游戏数据与文本。** `corpus/ja/` 下的日文原文，
   以及由其衍生的 `corpus/zh/`、`config/editorial/`、`manifests/` 中的中文译文，
   基于万代南梦宫娱乐／Banpresto 拥有版权的素材。这些内容仅为使本汉化可复现而
   收录，不授予再利用许可。本仓库不分发任何游戏素材或光盘镜像。

2. **Third-party code and fonts**, which keep their own licenses — including
   Tremor and libogg (fetched at build time; see
   `tools/special_disc/vocal_bgm/licenses/`), the pinned mkps2iso toolchain
   (GPL, fetched at build time), and the fonts documented in `README.md`.

   **第三方代码与字体**，各自保留原有许可证——包括 Tremor 与 libogg（构建时下载，
   见 `tools/special_disc/vocal_bgm/licenses/`）、锁定版本的 mkps2iso 工具链
   （GPL，构建时下载），以及 `README.md` 中记录的字体。

Using this repository requires a legally obtained copy of the original
Japanese game.

使用本仓库需自行合法持有日文原版游戏。
