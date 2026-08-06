# Super Robot Wars Z 中文化工程

本仓库从日文原版构建《超级机器人大战 Z》的简体中文译文、字库、写回组件、
ISO 和验证记录。工程采用 clean-room、配置驱动和 fail-closed 的生产方式；
原版游戏数据、完整 ISO、存档和本地运行证据均不进入 Git。

## 当前结论

- 中文语料覆盖菜单、世界史、人物／机体／武器数据库，以及 154 个已选择 STAGE
  剧情块的 82719 条对白、558 条条件文本和 8469 个说话人；发布状态仍是
  `in_progress`。
- 当前单一测试镜像为
  `ui-p10-full-story`，包含 P10 UI core、五张中文 atlas、全文字库和全部 154 个
  剧情块，共替换 7 个 ISO 成员；其余 59 个成员保持原字节，所有成员保持原
  LBA。
- 当前 ISO 大小为 3,758,358,528 字节，SHA-256 为
  `21b00c2de1d25ca668f21b1c9d95486c223aa7f55d610d684495ca463eead4cc`。
  它已通过两次确定性构建、静态成员回读、UDF/ISO9660、154 个 STAGE 解码和
  91746 条译文回读。现有 fresh-process 收据绑定前一张 `383e51...` 镜像；当前
  精确哈希的正式运行验收仍未完成。
- 生产压缩统一使用仓内 Rust codec；Python 实现只作为严格解码、round-trip
  和回归 oracle。
- P10 与全文剧情统一字库以造字工房典黑细体作为当前本地测试主字体，对其缺少的
  34 个字符显式回退到 Noto Sans CJK SC 2.004；两者统一以 22px 写入 24×24
  字槽并全局上移 1px。当前共有 3859 个最终 glyph assignment，覆盖已纳入语料
  的 91746 条剧情文本及旧存档主角名时缺字为 0，候选槽仍余 794。
  该静态结论不能替代目标画面 glyph、截断和布局验收。
- 战斗动画中的语音字幕不属于上述 STAGE 全文。截图样例
  `「一気に間合いをっ！」` 已定位到 `BTL/SRVC.BIN`；该文本域尚未提取和汉化。
  当前码表以中文版完整覆盖为目标，会复用原日文字槽，因此未汉化日文出现中文
  混字属于过渡期预期现象，不作为保留原日文字形的兼容缺陷。
- 尚未生成或发布正式游戏补丁。

当前事实以 `config/`、`corpus/` 和 `manifests/` 为准；README 只提供入口，
不复制逐轮研究记录。

## 事实源

| 路径 | 作用 |
| --- | --- |
| `config/` | Surface、codebook、字体、写回、ISO 和运行矩阵配置 |
| `corpus/ja/` | 不可修改的日文语料基准 |
| `corpus/zh/` | 中文译文 |
| `corpus/glossary/` | 术语和来源决定 |
| `corpus/releases/` | 发布范围和审校策略 |
| `manifests/` | 输入、组件、ISO 与验证结果的可提交摘要 |
| `tools/` | clean-room 核心实现与命令入口 |
| `tests/` | 格式、写回、布局、构建和证据门禁 |

本地目录的所有权如下：

| 路径 | 规则 |
| --- | --- |
| `rom/` | 用户合法持有的只读原版输入；不提交、不自动修改 |
| `work/` | 可重建缓存、组件和本地运行证据；不作为唯一事实源 |
| `build/` | 当前最终候选；`build/iso/` 只保留一张 ISO |
| `font/generated/` | 可重建字库产物；不提交 |

## 常用验证

```bash
python3 tools/validate_build_profile.py
python3 tools/compare_upstream_snapshot.py
python3 tools/verify_codec_samples.py
python3 tools/review_srwz_translations.py --check-only
python3 -m unittest discover -s tests -v
git diff --check
```

解析和导出命令：

```bash
python3 tools/parse_srwz_iso_data.py --force
python3 tools/export_srwz_corpus.py --force
python3 tools/analyze_srwz_font.py --force
python3 tools/audit_full_chinese_font_plan.py --force
```

构建、单候选管理和 PCSX2 证据流程见
[`docs/BUILD_AND_RUNTIME.md`](docs/BUILD_AND_RUNTIME.md)。剧情首译批处理见
[`docs/LOCAL_MODEL_TRANSLATION_WORKFLOW.md`](docs/LOCAL_MODEL_TRANSLATION_WORKFLOW.md)。

## 不可替代的验收层

```text
语料/术语决定
  -> 编码、字库、布局和写回
  -> 组件与归档 round-trip
  -> ISO/UDF/成员/LBA
  -> 匹配 ISO 和存档的 PCSX2 目标流程
  -> 画面与交互验收
```

静态检查、可启动 ISO 和旧候选截图不能互相替代。任何“已完成”声明必须绑定
当前源码、当前组件、精确 ISO 哈希、匹配存档和目标运行路径。

## 工程边界

- 日文原版是唯一翻译源；英文和外部中文资料只作为参考或术语证据。
- 不执行上游 EXE/DLL、Wine 或 Mono；生产实现全部位于本仓库。
- 不静默截断文本、不移动未授权成员 LBA；字槽复用必须由可重建码表记录，但不对
  已被中文覆盖的原日文文本保持可读兼容。
- 不做 patch-over-patch；每张 ISO 从固定原版和当前组件一次构建。
- `runtime_verified` 只授予在精确候选上实际到达并验收的 surface。

文档入口见 [`docs/README.md`](docs/README.md)，贡献与发布检查见
[`CONTRIBUTING.md`](CONTRIBUTING.md)。
