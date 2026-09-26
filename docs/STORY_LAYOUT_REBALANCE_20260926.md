# 剧情对白断行重排与排版词库（2026-09-26）

主线剧情对白的换行写在语料里，构建时只要不超过 21 格 × 3 行就原样写入。排查发现 34,263 条多行对白里有 1,439 条把词拆到了两行，比如“战／争”“目／标”“楚／楚动人”，全篇各段比例一致，约 4%。排版引擎本身按单字选断点，只认 10 个写死的保护词，所以构建时被迫重排的句子同样会拆词。本轮给引擎接入词库、统一主线与 Special Disc 的排版档，并按新规则重排语料。

## 排版档统一为 21 格 × 3 行

`story_dialogue` 档原为首行 21 格、续行 20 格，只有 Special Disc 工具使用；主线构建不传档，按默认 21／21 处理。依据日文原文核对续行宽度：原盘剧情有 915 条续行在缩进后为 21 个字符，其中 47 条只含普通假名汉字，说明对话框每行可显示缩进后 21 格。主线语料已发布的 78 条 21 格续行与此一致。现将该档改为首行 21、续行 21、最多 3 行，主线构建、ISO 内容回读、第 1 话容量 canary 和 SD 工具统一使用同一档。本轮未做 PCSX2 或 LRPS2 画面验收；依据是原盘文本宽度与既有发布结果。

## 词库

| 文件 | 内容 |
| --- | --- |
| [zh-story-common-words.txt](../config/text-layout/zh-story-common-words.txt) | 738 个常用词，人工维护。来自被拆开的 853 个词：按通用词频筛出 632 个，再从 221 个低频项里人工保留成词的部分，去掉“利亚”“布拉”等专名碎片；重排后复查又补入“生存”“无所谓”等 6 个词。 |
| [zh-story-proper-names.txt](../config/text-layout/zh-story-proper-names.txt) | 31 个语料词表里没有独立条目、或只有更长形式、但对白中单独出现过的专名，如“帕普提马斯”“卡奔塔利亚”“阿纳海姆”。 |
| [zh-story-unbroken-words.json](../config/text-layout/zh-story-unbroken-words.json) | 生成文件：738 个常用词加 1,721 个专名。专名由生成器从 `story-speakers.json`、`corpus/glossary/*.json` 和机体显示名收集。 |

词表通过 `story_dialogue` 档新增的 `unbroken_terms_files` 字段引用，在该档内作为不可拆分单元参与断行；图鉴、流程图等其他档不受影响。修改任一文本文件或语料专名后重新生成：

```sh
python3 tools/text_layout/build_story_unbroken_words.py
python3 tools/text_layout/build_story_unbroken_words.py --check
```

词库只覆盖到目前为止被拆过的词。主线换行是手动写在语料里的，引擎只在超框时重排，所以后续新文本仍可能拆到别的词，可用同样方法增量补词。

## 语料重排

`tools/text_layout/rebalance_story_dialogue.py` 找出断行落在词库单元内部的记录，用引擎重新选点，逻辑文本不变；超出 21 格 × 3 行、此前在构建时被静默重排的记录也一并按同一档写回语料，使语料与游戏显示一致。

| 项目 | 数量 |
| --- | ---: |
| 拆词断行改正 | 1,354 |
| 超框记录按构建结果写回 | 123 |
| 涉及关卡文件 | 144 |
| 引擎放不下或未改动 | 0 |
| 重排后仍拆词 | 0 |

全部 1,477 条的前后文本、行宽、被拆的词和日文源哈希记录在 [story-layout-rebalance-20260926.json](../config/editorial/story-layout-rebalance-20260926.json)。重排后 83,668 条对白按新档全部可放下。行数变化：1,345 条保持两行，82 条由一行变两行，25 条由两行变三行，20 条保持三行，5 条减少行数。引擎按最少行数选布局，超框记录不会为了更自然的断点改用三行，例如“是亚空间力场……！人工太阳正／利用过剩的能量……”仍是两行。

## 排版门禁

语料必须存最终显示的断行，构建不再静默重排。三处使用同一个检查 `dialogue_layout_issues`：行数超过 3、任一行超过 21 格、断点落在词库单元内部，任一条成立即失败并指向重排工具。

| 位置 | 行为 |
| --- | --- |
| `build_story_component.py` | 组件构建时逐条检查，失败即终止，`build_editions.py` 因此同样受门禁约束 |
| `verify_full_story_iso_content.py` | ISO 内容回读前做同样检查 |
| `tools/text_layout/check_story_dialogue_layout.py` | 写回后独立运行，列出全部问题记录并以 1 退出；关键词链接标志从原盘日文取 |
| `tests/test_story_dialogue_layout_words.py` | 单元测试断言当前语料无问题 |

写回流程的顺序固定为：写回语料 → `check_story_dialogue_layout.py` → 有问题则 `rebalance_story_dialogue.py` 并复查 → 构建。社区批次、字幕对照和术语同步脚本都应在写回后运行检查。

## 构建与验证

- `build_story_component.py` 的缓存签名和 manifest inputs 新增排版档与词库文件，两者变化会使全部 STAGE 块重建。
- 新增 `tests/test_story_dialogue_layout_words.py`：档参数、词库生成一致性、常用词与专名不被拆、超框行为，以及语料内不存在落在词内的断行。`tests/test_release_workflow.py` 里 11 条历史定稿的换行位置随语料更新，措辞不变。
- SD 校验器的提示文案由“21/20字×3行”改为“21字×3行”。
- 关键词链接标志以日文原文为准：构建器按日文是否含“《”决定 `stage_keyword_links`，翻译里单独出现的“《超级机器人大战Z》”是普通书名号，占显示格。重排工具与 ISO 回读器都从锁定的原盘 STAGE 归档解码日文来取这个标志；首轮误按译文判断时，第 186 话教程一句在 ISO 回读中暴露为构建与语料不一致，已按日文标志重排修正。
- 525 项单元测试运行通过，5 项按条件跳过。加入门禁后 Original / Best 统一构建及内置内容回读通过，耗时约 2 分 33 秒，日常 skip 副本随构建更新；批次回执见 [story-layout-rebalance-20260926.json](../manifests/editions/story-layout-rebalance-20260926.json)。未做 PCSX2 或 LRPS2 画面验收。
