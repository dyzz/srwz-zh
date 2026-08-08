# Super Robot Wars Z 中文化工程

本仓库从日文原版构建《超级机器人大战 Z》的简体中文译文、字库、写回组件、
ISO 和验证记录。工程采用 clean-room、配置驱动和 fail-closed 的生产方式；
原版游戏数据、完整 ISO、存档和本地运行证据均不进入 Git。

## 当前结论

- 中文语料覆盖菜单、世界史、人物／机体／武器数据库中已经登记的名称和字段，
  以及 154 个已选择 STAGE 剧情块的 82719 条对白、558 条条件文本和 8469 个
  说话人；发布状态仍是 `in_progress`。
- 当前单一测试镜像为 `zh-release-full-story`，包含全局字库、菜单／数据库、
  五张中文 KVMDATA atlas、154 个 STAGE 剧情块、STAGE/HSFC 概要、完整 SRVC
  战斗字幕和 VEFF2DX 场景选择标题，共替换 11 个 ISO 成员；其余 55 个成员保持
  原字节，所有成员保持原 LBA。
- 当前 ISO 大小为 3,758,358,528 字节，SHA-256 为
  `dea0d931699f84ac134b30eb144ec204955a0517cbec90541b79a06240571497`。
  它已通过两次确定性构建、静态成员回读、UDF/ISO9660、154 个 STAGE 解码和
  91746 条译文回读，以及 58,740 个 SRVC 记录回读。当前精确哈希的正式
  fresh-process 新游戏／读档 STAGE 入口收据仍未完成。
- 生产压缩统一使用仓内 Rust codec；Python 实现只作为严格解码、round-trip
  和回归 oracle。
- 当前动态中文字库统一使用 HarmonyOS Sans SC Regular 1.0；`〜∀♪` 显式回退
  Noto Sans CJK SC 2.004。动态 CJK 以 22px 写入 24×24 字槽并全局 `y=+1`，
  当前有 3261 个主映射和 701 个 surface-safe 别名，默认宽度追加候选槽剩余 1 个。
  固定的中场休息图集仍属同一 HarmonyOS Sans 家族，但标题和七个菜单使用 Light
  字重；它不改变 VT1 动态字库。
- 战斗动画语音字幕属于独立的 `BTL/SRVC.BIN` 域。当前已写入并从最终 ISO 回读
  25,708 条唯一译文、58,740 个索引记录和 353 个块；SEG、块边界、元数据、
  空块和未索引尾部保持原样。该静态结果仍需目标战斗画面的运行验收。
- 尚未生成或发布正式游戏补丁。
- 按当前实机观察，后续汉化分成两类：优先处理正常流程中零散出现的残留日文；
  较低优先级的高文本量范围是人物／机体图鉴正文、用语列表和游戏内教程。

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

## 常用验证

```bash
python3 tools/verify_original_disc.py
python3 -m compileall -q tools tests
python3 -m unittest discover -s tests -v
git diff --check
```

首次准备本地原版成员：

```bash
python3 tools/extract_iso_member.py \
  SLPS_258.87 DATA/VT1.BIN DATA/STAGE.BIN DATA/COMPDATA.BN \
  DATA/HSFC.BIN BTL/SRVC.BIN BTL/SRVC.SEG EFF/VEFF2DX.BIN
```

构建、单候选管理和 PCSX2 证据流程见
[`docs/BUILD_AND_RUNTIME.md`](docs/BUILD_AND_RUNTIME.md)。

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
