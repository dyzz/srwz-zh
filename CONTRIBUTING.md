# 贡献与发布约定

本仓库同时包含 clean-room 工具、中文语料和可复现构建配置。提交前必须区分
可审查源数据、可重建中间态和只能由用户本地持有的原版数据。

## 修改边界

- 只修改独立的 `srwz-zh` 仓库；相邻上游仓库必须保持干净。
- `rom/`、`work/`、`build/`、`outputs/` 和 `font/generated/` 永不提交。
- 不提交 ISO、原版成员、存档、解压内容或其他可还原游戏数据。
- 不提交或执行 `SRWZ.exe`、`SRWZ.dll`、`CompressTool.exe`，也不使用 Wine
  或 Mono。
- 固定上游快照只能保留已登记来源、提交和选择范围；不得复制无许可证的额外
  上游源码。
- `corpus/zh/` 保存中文决策，`corpus/glossary/` 保存 canonical 术语，
  `config/` 保存可复现输入，`manifests/` 保存不含游戏字节的验收投影。
  不得直接修改 `work/` 或 `build/` 产物来制造“修复”。

## 翻译决策

专有名词依次采用官方简中译名、可靠中文社区共识和自然中文本地化。没有官方
或稳定社区译名时，如果字面直译会像错字、术语或说明文字，应提出可读的专名
音译候选，并在 glossary 备注保留原义、外文拼写、检索依据和无共识边界。
存在实质取舍的用字进入人工复核；确认后同时更新正文、简称、词表和测试。

日文原文、控制符和 source hash 不得人工改写。英文稿和社区 WIKI 只用于核对，
不能覆盖日文语境或冒充官方定名。

## 验证分层

基础源码检查不运行游戏：

```bash
python3 tools/verify_codec_samples.py
ruff check tools tests
python3 -m compileall -q tools tests
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/compare_upstream_snapshot.py
git diff --check
```

前五关生产候选还必须依次完成：

```bash
python3 tools/review_srwz_translations.py
python3 tools/reflow_first_five_dialogue.py --force
python3 tools/audit_first_five_language_quality.py --force
python3 tools/audit_first_five_upstream_english.py --force
python3 tools/fetch_first_five_font.py
python3 tools/audit_first_five_writeback.py --force
python3 tools/build_first_five_font.py --force
python3 tools/audit_first_five_font_coverage.py --force
python3 tools/build_first_five_stage.py \
  --force \
  --stages 1-5 \
  --strategy greedy \
  --min-match-length 4 \
  --max-match-chain 256 \
  --lazy-matching
python3 tools/build_canary_iso.py \
  --config config/iso/first-five-build.json
python3 tools/verify_first_five_iso_content.py --force
```

静态回读、renderer 覆盖、模拟器启动、实际画面和完整玩法是不同证据层。
组件、字体、STAGE 或 ISO 发生变化后，旧候选的 PCSX2 证据不得转移到新候选。
当前边界和精确哈希以 `manifests/first-five-validation.json` 为准。

## 提交与推送

1. 用 `git status -sb`、`git diff --stat` 和 `git diff --check` 复核完整范围。
2. 确认没有秘密、原版字节、大型生成物或相邻仓库改动。
3. 只暂存当前里程碑需要的源码、语料、配置、测试、文档和 byte-free manifest。
4. 运行与改动相称的验证；失败或未执行的运行证据必须明确记录。
5. 使用简短、能概括完整差异的提交信息；只有在用户明确授权后才推送。

发布补丁属于 M5 的独立工作。本仓库当前生成的本地 ISO 不是可分发发布物。
