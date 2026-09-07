# 当前 BEST 源码构建

2026-09-05。`build_editions.py` 已接入 `best-current-source-v1` 后端。一次构建固定一份源文件快照，产生 Original 和 BEST 两个独立产物。当前 BEST 编译不读取 `best-alpha1` 的中文组件、地址分析缓存或冻结语料，也没有旧文字的临时替换规则。

## 构建结构与依赖

本轮采用 **共用中文编译前端 + 版本后端**。Original 现有完整构建链负责本批译文、字码、字体、索引图片和中文排版的编译，且执行现有完整 ISO 语义回读。BEST 后端消费这个同批次、哈希锁定的中间结果与两版原盘，按已审核的 BEST 契约重建最终资源。

因此 `--editions best` 仍需要两版原盘，并先运行一次 Original 前端；它不依赖上次已生成的 Original ISO。反向指定 `best,original` 同样只执行一次前端。此实现完成当前双构建入口，但不是“每个原有底层构建器都已经独立参数化”的实现；将 BEST 前端完全独立、减少中间 ISO 和优化增量缓存，仍可后续演进。

```text
本次配置/语料/字码/工具快照
    → Original 完整编译与语义回读
        → Original 独立 ISO
        → 同批中文组件 + BEST 原盘 + BEST 来源/布局契约
            → BEST 资源写回、结构及文本回读
            → BEST ISO 全字节边界检查
    → 同输入双产物批次记录验证
```

相关实现：

| 文件 | 责任 |
| --- | --- |
| `config/editions/best/edition.json` | BEST 原盘、ELF 身份及后端选择 |
| `config/editions/best/source-layout.json` | 195 段地址映射、59 个中文指令写入位置、13 张归档表、19 条 STAGE 和 18 条战斗字幕原文修订绑定；不含中文译文快照 |
| `tools/srwz/best_build.py` | 本版字段写回、文本引用验证、资源重组和固定布局 ISO 生成 |
| `tools/build_best_current.py` | 严格验证同批中文前端凭据并启动 BEST 后端 |
| `tools/build_editions.py` | 两版输入预检、共同前端调度、隔离输出及批次凭据 |
| `tools/verify_editions.py` | 验证真实 ISO、输入快照、本版回读和共同前端之间的绑定 |

历史分析只用于一次性整理可审查的源码契约。构建时直接检查锁定原盘与明确地址，不运行相似度匹配，不应用统一地址差。中文原文哈希先由合法 Original 来源校验；BEST 修订使用额外的本版原文绑定，未知变体立即失败。

## 保留及写回规则

- **ELF／字体／界面文字**：从 BEST 原生 ELF 开始，应用映射后的本批中文指令、字码及目录数据。重定位的两个字段访问使用 BEST 地址。连携攻击说明按共享语料核对并写入本版短槽，沿用已审核的标点别名字码。
- **官方程序修改**：所有声明写入范围外的 ELF 字节与 BEST 原盘相同；模式初始化调用单独校验保留。
- **图鉴全开放**：关键词、剧情流程、人物和机体四处查询补丁采用现有全开放语义，保留无效 ID 分支，不通过写入存档解锁标志实现。
- **COMPDATA**：保留 BEST 内嵌代码、`0x6D7000` 基址和四处正确字段，按完整字段宽度验证。两条能力说明及两个 NPC 名称直接使用本批中文，不再匹配旧的 `10EN` 或硬编码“奥古兵”。
- **STAGE**：解析器直接识别 BEST 的三条条件表指令；205 个块逐一重建。26、111、150、161 的布局使用显式契约，所有已解析文本引用、说话人和控制字节与同批中文结果一致，包含 `$n`。
- **人物图鉴**：中文字段来自本批输入，VOIC 来自 BEST 原生记录；已回迁的声优署名不再次交换。
- **SRVC**：58,751 条记录重新绑定中文，额外 11 条原生记录必须有明确译文来源；保留各记录元数据及未索引尾部。
- **TWP、音频、视频与盘内元数据**：本版原生资源保留。所有替换成员都保持 BEST 原生字节长度和 LBA；验证 ISO 内替换范围之外的每个字节与原盘相同。

## 使用方式

仓库根目录：

```sh
python3 tools/build_editions.py --editions original,best
python3 tools/build_editions.py --editions best
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best.json
```

改造保真验证可增加 `--require-legacy-equivalence`，要求 Original 的 23 个替换成员和 ISO 与快照中的旧生产锁相同。正常润色预期改变输出时省略该选项。

BEST 当前产物为 `build/iso/zh-release-best/current-best.iso`，身份凭据为 `manifests/editions/best/current.json`。Original 的隔离对照产物使用 `build/iso/zh-release-original/current-original.iso`；当前生产槽位仍是 `build/iso/zh-release-full-story/current-original.iso`。

正式产物仅在完整构建和静态回读通过后替换。批次记录保留各版输入哈希、ISO 哈希及独立回读位置。任一版本失败，批次状态为失败；不输出双版本通过。发行 xdelta 双补丁打包与 PCSX2 完整发布回归属于后续发布步骤。

## 2026-09-07 剧情与战斗润色定稿后的当前构建

当前对应源码提交 `1ccd07054e7292028a878e1f4991034cee995741`。相对 `f5137cb`，累计写回232条译文：剧情185条、战斗47条；其中此前批准26条，本轮低成本排查206条。不动主问句定为“双手合十，其间有什么？”，同步5处问句及回引，另1处原译保留。西利乌斯“以我的骄傲，亲手”两处原样保留。

| 项目 | 当前结果 |
| --- | --- |
| 输入快照 | `52b5dd4084b8a3066e1d286ca994b1542f05382ed1052742ea76b2eec37067b4` |
| Original SHA-256 | `8b108e7915750ef4d7f26fd6c72ec5fc05519b15a01cb10967868a2412523762` |
| BEST SHA-256 | `1d63d03fc2d5e5634e293e0489af0087878cc557405a52758fbeed2d35004c7c` |
| 双版本构建及最终ISO语义回读 | 通过 |
| 批次、输入、实际ISO与回读凭据绑定 | 通过 |
| 完整测试 | 245项通过 |
| 字库覆盖 | 新增“舅”至96B7／glyph 4151，旧映射不变，缺字0 |

Original生产槽位、两个版本输出和当前manifest均已同步。两个版本使用同一份冻结输入；根目录23个组件与隔离Original构建逐字节一致。完整凭据见[本轮构建记录](../manifests/editions/text-closeout-20260907.json)。下方旧批次的用户运行验收仍仅绑定旧ISO，本轮新哈希只登记构建和静态回读。

## 2026-09-07 人物审校修正后的历史构建

用户认可具体候选后，已写回26条（剧情15条、战斗11条），并在排除无关试验文件的隔离工作树中完成同批双版本构建。当前镜像已同步到各版输出目录，Original生产槽位也已更新。

| 项目 | 当前结果 |
| --- | --- |
| 输入快照 | `19afde6ea4a4b4fe19b2e718cd05bc575ec4f060aad2e643db46d368591d2614` |
| ORIGINAL | 3,758,358,528字节；`b5dca662d4bd8e6124b133a99db26536ccc1ba26409fe957c7cc96eb73381275` |
| BEST | 3,755,081,728字节；`4a1ad707b0732a82148e8750b157c69e87b1438fb3de8eaf3c89cadbfe22c691` |
| 验证 | 双版本静态语义回读及实际ISO批次绑定通过；245项自动测试通过 |
| 运行证据 | 新镜像未另跑模拟器；下方用户实测验收继续绑定修改前批次 |

详见[人物修正记录](CHARACTER_PERSONALITY_APPLICATION_20260907.md)与[本批双版本构建记录](../manifests/editions/personality-polish-20260907.json)。

## 2026-09-07 构建入口改造复验（历史批次）

本次从 `ae5d2ad` 加双版本待提交文件的隔离工作树运行完整构建，包含已提交的最新剧情、战斗和梅尔文字游戏修正。输入冻结后与验证工作树逐文件核对一致；其他未提交的扩容审计及润色试验不在本次提交范围。

```sh
python3 tools/build_editions.py --editions original,best --require-legacy-equivalence
python3 tools/verify_editions.py --manifest work/editions/c5fbc6cdcabc1a4cd130174c45d5bae7e741ce8f974b7297f3a991f1351601a3/original-best.json
python3 -m unittest discover -s tests
```

| 项目 | 该批次结果 |
| --- | --- |
| 输入快照 | `c5fbc6cdcabc1a4cd130174c45d5bae7e741ce8f974b7297f3a991f1351601a3` |
| Original | 3,758,358,528 字节；`6339a3f09d61ef35b9d1fd9a08946c49d14351a4acda75ee3ef3f86d0f6be760` |
| BEST | 3,755,081,728 字节；`54eac67cb927ba92fb810e2a391ca782d868f63afc72c065ae94962eeab6ed23` |
| Original 保真 | 23 个替换成员及 ISO 与既有生产锁逐字节一致；170 个 STAGE、93,071 条译文回读通过 |
| BEST 回读 | 205 个 STAGE 块、84,338 个文本引用、58,751 条战斗字幕通过；23 个替换成员、原生成员大小和 LBA、全部未替换 ISO 字节通过 |
| 批次绑定 | `edition_batch_receipt_integrity_passed`，`both_editions=true`；两版 ISO 均绑定到同一冻结输入和共同前端 |
| 自动测试 | 242 项通过；包含新增的 SR 点数坐标映射及原生相邻指针保护回归 |
| 运行验证 | 本次没有运行 PCSX2 或 LRPS2；2026-09-05 的 LRPS2 记录属于旧哈希，不适用于此次 BEST ISO |

首次验证发现，既有“SR 点数”标签横坐标调整尚未进入 BEST 指令映射。现补齐 Original 文件偏移 `0x253924` → BEST `0x253F24` 的显式契约：两版原生指令均为 `ECFF0526`（`addiu a1, s0, -20`），中文输出使用 `F4FF0526`（-12）。两版调用点都引用原生“ＳＲポイント”字符串，但字符串指针分别为 `0x4420D8` 与 `0x4428C8`；BEST 的相邻指针保持原值。最终从两版实际 ISO 再次读回指令、标签及 `SYSTEM.CNF`，确认身份分别为 `SLPS_258.87` / 1.04 与 `SLPS_732.70` / 2.00。

机器可读汇总见 [双版本验证记录](../manifests/editions/verification-20260907.json)，各版当前记录位于 `manifests/editions/original/current.json` 和 `manifests/editions/best/current.json`。完整日志和映射核对证据保存在本地 `work/review/dual-build-verify-20260907/`。

## 2026-09-07 用户运行验收

用户在双版本构建提交 `3761b7a` 推送后确认：“补双版本运行验收 可以认为通过，我自己跑过”。本批 Original 与 BEST 的运行验收据此记为 **通过（用户实测）**，不再作为继续人物审校的待办。

本次确认绑定构建入口改造复验表的两版 ISO 与输入快照，见 [用户实测验收记录](../manifests/editions/runtime-user-acceptance-20260907.json)。用户未细分模拟器配置或逐项场景，记录保留总体确认的原始口径；构建器当时未执行模拟器的历史事实不变。

## 2026-09-05 历史证据

完整双构建日志、测试日志和批次复核位于 `work/analysis/best-current-build-20260905/`；`completion.json` 汇总本轮结果。

| 项目 | 结果 |
| --- | --- |
| 输入快照 | `6830228fe417ae77093ea770a23dd168bd2d55f0c66c6bb0fcf9e53507d82a84`；完成后与当前实际源输入一致 |
| BEST ISO | `build/iso/zh-release-best/current-best.iso`，3,755,081,728 字节 |
| BEST SHA-256 | `ed0c2e04b60db631593dae6da0ef556561883fcc37d588187c82f97b21383825` |
| Original 保真 | 23 个成员及 ISO 哈希仍为原生产锁；当前生产 Original 镜像字节未变 |
| 构建重现对照 | 独立后端试跑与最终完整双构建的 BEST ISO 哈希相同 |
| 自动测试 | `python3 -m unittest discover -s tests`：225 项通过 |
| 双产物验证 | `edition_batch_receipt_integrity_passed`，`both_editions=true` |
| BEST 静态回读 | 205 个 STAGE 块、84,338 个文本引用、58,751 条战斗字幕、23 个替换成员及整个 ISO 的其余字节 |
| LRPS2 | 相同 ISO 哈希进入中文路线选择及节子 STAGE 001，三屏中文对话连续推进；已查看截图，源记忆卡未改变 |
| PCSX2／完整发布回归 | 未执行；男主新游戏、普通读档及保存重载、B-Save 弹数、战斗音画和图鉴运行回归仍单列待验收 |

本版静态身份记录为 `manifests/editions/best/current.json`，本轮 LRPS2 记录为 `manifests/editions/best/runtime-20260905.json`。LRPS2 实际运行的是独立试跑副本，记录中的哈希与最终 `current-best.iso` 完全一致。构建凭据继续标记静态验证，部分 LRPS2 观察不等于完整运行验收。
