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

正式构建只读取 `corpus/zh/**/*.json` 的非空 `translation` 字段；审校队列、
模型输出、TSV 和网页预览均为可删除中间物，不进入当前仓库结构。
