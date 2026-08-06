# 本地模型剧情首译工作流

这条工作流把“机器首译”和“项目发布译文”彻底分开。项目先从固定的日文
clean-room 语料生成一个离线 JSONL 队列；本地模型只填写中文首译；回传后由
严格校验器检查哈希、控制码、引号、假名残留、术语和断行；最后仍需人工二校，
再交给现有的逐关构建器写入 `corpus/zh/`。模型输出不能直接进入 ISO。

## 1. 生成交付包

在 `/Users/nate/Super-Robot-Wars-Z/srwz-zh` 执行：

```bash
python3 tools/export_story_dialogue_local_model_batch.py --force
```

输出均在 Git 忽略的 `work/review/local-model/`：

- `story-dialogue-unique.jsonl`：模型输入；每个 STAGE 段内每个重复原文只出现
  一次，使用 `stage_index + unique_index + source_text_sha256` 定位；附带出现
  次数、稳定运行时 ID、说话人、场景、指针、已有译文状态、相关术语和控制码。
- `story-dialogue-records.tsv`：全部 82,719 条运行时记录，用于把去重决定展开
  回重复出现的句子；不要让模型改写此文件。
- `story-dialogue-terminology.json`：1,739 条 release 词条和 4 条临时候选词条。
  临时词条的状态是 `needs_human_review`，只能作为候选，不能当作最终定名。
- `story-dialogue-manifest.json`：来源聚合哈希、计数和机器契约。

可以用 `--stage 10`（可重复指定）生成单段交付包做小批试跑；默认命令才是
全量 154 个文本段。输入包含日文正文是因为这些文件在 `work/`，不会进入 Git。

## 2. 给本地模型的固定提示

把 `story-dialogue-unique.jsonl` 按小批分片；每个请求的 user JSON 顶层是
`items` 数组，一般一次放 8 条。模型必须对每个 item 返回一条结果，不能合并、
遗漏、复制或重排。模型只允许填写或返回下列字段：

```json
{
  "stage_index": 10,
  "unique_index": 42,
  "source_text_sha256": "固定的64位小写哈希",
  "translation": "中文首译",
  "notes": "可选：疑义、语气或需要人工核对的简短说明"
}
```

实际提示词：

> 你是 SRWZ 简体中文首译器。处理 user JSON 的 `items` 数组，不改变每个 item 的
> `stage_index`、`unique_index`、`source_text_sha256`，也不新增或删除结果。只把
> 日文 `source_text` 翻译到 `translation`；不要输出日文假名，不要保留
> `「」『』`，对话使用成对的中文引号“”。不要插入换行，之后由项目按窗口
> 宽度重排。原文中的 `{xx}`、`<name:xx>`、`$n`、`$F`、`●` 等控制/占位符
> 必须逐个原样保留，数量不能变。优先使用该行 `glossary_terms` 中的
> `translation`；`enforce=true` 的词条必须使用，临时词条只作候选并在
> `notes` 标出。若 `glossary_conflicts` 非空，不要擅自选择异译，必须在
> `notes` 标出“需人工确认”。不要自行创造人物、机体、组织的别名；拿不准时保留直译并在
> `notes` 标记“需人工确认”。返回顶层 `translations` 数组，顺序与输入相同；不要把已有
> `locked_reviewed` 行再次翻译。

模型可以参考每行的 `existing_translation`，但这只是上下文，不代表它可以
跳过校验；`locked_reviewed` 行应从模型输出中省略。

## 3. LM Studio 少量样本

当前 LM Studio 服务使用 `http://localhost:1234`。先在 LM Studio 中加载一个
真正的文本／翻译模型；`/api/v1/models` 中必须出现非空的 `loaded_instances`。
OCR 或 embedding 模型不适合作为剧情首译模型。加载后可先跑第 10 段的 20 条样本；
默认每次请求 8 条，因此只需 3 个模型请求：

```bash
python3 tools/run_lmstudio_story_dialogue_sample.py \
  --stage 10 --count 20 --batch-size 8 --force
```

工具默认调用 LM Studio 原生 `/api/v1/chat`，并将 `reasoning` 设为 `off`，避免
Qwen3.6 把推理内容混入 JSON；默认 `--max-tokens 1024` 足以容纳 8 条短句的批量
JSON；输出只进入
`work/review/local-model/lmstudio-samples/`。若服务没有加载 LLM，会明确失败，
不会自动下载或加载模型。遇到一次 JSON、引号或手动断行格式错误时，工具只做一次
带原始输出的批次格式修复重试；语义和术语错误仍交给后续校验与人工复核。需要兼容
OpenAI 端点时可加 `--api openai`。样本回传仍用同一校验器：

```bash
python3 tools/import_story_dialogue_local_model_batch.py \
  --model-output work/review/local-model/lmstudio-samples/story-dialogue-sample.jsonl \
  --allow-partial --force
```

样本只用于检查模型是否遵守格式、术语和中文引号；通过样本不代表剧情质量或
运行时可用，也不会生成正式语料。

## 4. 回传与校验

将模型 JSONL 放到 `work/` 下，然后执行：

```bash
python3 tools/import_story_dialogue_local_model_batch.py \
  --model-output work/review/local-model/model-output.jsonl \
  --force
```

校验器默认要求所有未锁定的 66,285 条都有且只有一条回传。它会拒绝：

- 不在输入队列中的 ID、重复 ID、错误源哈希或修改过的 `unique_index`；
- 日文假名、日文角引号、ASCII `...`、手工换行；
- 控制码数量变化、缺少强制术语、未知术语引用或术语例外重叠；
- 回译 `locked_reviewed` 行，或用 `reviewed/final` 冒充机器完成状态。

结果仍只写入 `work/review/local-model/validated/`：

- `story-dialogue-validated.jsonl`：逐条校验后的决定；
- `story-dialogue-validation.json`：缺失项、按段统计和可生成的完整草稿；
- `drafts/stage-NNN-unique-draft.json`：只对完整段生成，状态为 `draft`，可供
  现有逐关构建器继续做术语和发布审计。

分批运行时显式加 `--allow-partial`。此时校验器只报告缺失项，且不会为不完整的
文本段生成草稿：

```bash
python3 tools/import_story_dialogue_local_model_batch.py \
  --model-output work/review/local-model/model-output-part-01.jsonl \
  --allow-partial --force
```

## 5. 人工二校与发布边界

本地模型的 `draft` 不等于完成。人工需要按 `notes`、词表冲突和上下文逐句检查，
统一人名、机体、组织、语气和中文断行；确认后把决定写入对应的
`corpus/glossary/story-dialogue-stage-NNN-v1.json` 与
`corpus/zh/story-dialogue/stage-NNN.json`，再运行：

```bash
python3 tools/build_story_dialogue_stage_translation.py \
  --stage NNN \
  --draft work/review/local-model/validated/drafts/stage-NNN-unique-draft.json \
  --force
python3 tools/review_srwz_translations.py
python3 tools/reflow_first_five_dialogue.py --force
# 默认扫描全部已翻译关卡；确认报告后加 --apply --force 写入规范断行。
```

只有 `reviewed`/`final` 的人工结果才可进入 release、字体分配、压缩和 ISO。
本地模型过程不联网、不执行任何上游 EXE/DLL/Wine/Mono，也不实现编码器或 ISO
回包。
