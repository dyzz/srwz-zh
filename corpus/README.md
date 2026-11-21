# 语料约定

`ja/` 是固定原版的日文基准，不得人工改写；完整提取结果只保存在忽略的
`work/corpus/`。`zh/` 保存中文译文，`glossary/` 保存 canonical 术语，
`releases/` 固定发布选择。

每条正式译文必须保留稳定 ID、日文 source hash、中文、编辑状态和必要的术语
引用。日文正文、控制码、printf 占位符和 `$c/$f/$l/$n/$F` 等运行结构不得被
误当作字形或普通文本修改。

当前正式范围包括：

- 菜单、系统 UI、人物／机体／武器／能力数据库；
- 世界史、关卡标题、STAGE 与 HSFC 概要；
- 154 个 STAGE 剧情块的对白、说话人和条件；
- `COMPDATA.BN` 战斗退场台词；
- `BTL/SRVC.BIN` 全索引战斗字幕；
- KVMDATA 与 VEFF2DX 图片文字的受审标签。

专有名词按官方简中、可靠中文共识、自然本地化的顺序决定。没有可靠定名时在
glossary 中保留原文、外文拼写、依据和不确定性，不把机器检索结果冒充定稿。

```bash
python3 tools/prepare_zh_release_font.py --force
```

## 三份语料的维护约定

| 语言 | 译文（含 SP） | 术语表 | 运行时关键词 |
| --- | --- | --- | --- |
| 简体 | `zh/` | `glossary/` | `runtime/` |
| 台湾 | `zh-hant/` | `glossary-zh-hant/` | `runtime-zh-hant/` |
| 香港 | `zh-hant-hk/` | `glossary-zh-hant-hk/` | `runtime-zh-hant-hk/` |

三份现有文本是各自的编辑底稿。改译文或术语时只改所属语言，保留日文依据、稳定 ID 和审校状态。
新增条目在需要它的各语言中分别填写。缺译由工具报出，禁止通过简繁转换、台港字形替换、
术语批量替换或另一语言回填。简体改动记录只用于提示复核。

港台共用图片、繁体码表，以及 `config/zh-hant/hk-uses-taiwan.json` 明列的 8 个图片文字文件。本篇和 BEST 的关卡名、地形名从各自的 `menu/` 语料读取，港台共用的关卡标题图单独绑定台湾图稿。
SP 的地区正文（包括 VT1 页面）以各自的 `special-disc/` 语料为准。组盘去重只比较编译后的字节。
SP 香港关卡名和流程表读香港正文，关卡标题图使用港台共用图稿。数据链接奖励说明按本语言的产品文案核验。

从项目根目录运行 `python3 tools/zh_hant/sync_corpus.py --check` 检查缺项和来源变更；
运行 `.venv/bin/python tools/zh_hant/preflight.py` 检查字库、版式和文本约束。
