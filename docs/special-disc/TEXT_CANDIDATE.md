# SP 首批文本候选

同日后续已完成 [当前译稿全量候选](FULL_TEXT_CANDIDATE.md)。本文保留首批候选当时的范围、统计和运行证据。

2026-09-19：已完成两个关卡的实际文本写回和独立 ISO 合成。译稿保持 draft，当前不是全量汉化发布版。

## 制品与范围

- 镜像：`build/iso/special-disc/text-candidate/sp-text-canary.iso`
- SHA-256：`4ecc53fb34dd195fedc4018dbcb09306ee929eaf5d1f1fa1b4859242524ff953`
- 大小：3,791,781,888 字节。
- 镜像报告：相邻 `sp-text-canary.json`。
- 组件与逐条绑定：`work/build/special-disc/text-candidate/stage/report.json`。
- 保留基线：`build/iso/special-disc/preview/sp-image-preview.iso`，SHA-256 `51a819a426ce049a0ee6ae5c696bb48290445cd8322bf192e2cc45271d1e4a8b`。

| 关卡 | 对白／场景标签 | 说话人 | 胜败／SR 条件 | 压缩大小／原槽 |
| --- | ---: | ---: | ---: | ---: |
| chunk 001 / stg_001 | 223 | 19 | 3 | 11,535 / 12,416 字节 |
| chunk 039 / stg_200 | 40 | 12 | 4 | 5,273 / 5,424 字节 |

301 条绑定中，254 条按 SP 原生位置命中，40 条采用本篇唯一答案，7 条保留空白或占位符；293 条使用 draft，1 条 reviewed，7 条 preserved。说话人数是逻辑名称数，实际前缀随各条对白写入。

19 处歧义／缺少复用答案的位置已登记到 `config/editorial/special-disc/stage-native-overrides.json`，包含原文哈希、选择理由和 draft 状态。原有五份 SP 译稿未修改。

## 共享码表和字库

继续使用本篇 `config/encoding/zh-release-font-assignments.json` 与 `config/fonts/zh-release-font.json`。新增 42 个普通宽度映射后，主映射从 3,476 增至 3,518，候选位从 75 减至 33。原有主映射逐项相同。

先前统计的 14 字只是编码缺字；正式共享字库审计还发现 28 个字符未纳入汉化字形分配。新旧 SP 字库解压比对确认，**恰好只有这 42 个新增槽的字形改变**，没有其他槽位变化。兼容核对记录在 `work/build/special-disc/text-candidate/font-compatibility.json`。

字体使用本篇工具生成，在候选目录保存输出，不覆盖本篇现有字库组件和验证清单。SP 仍通过 `install_font.py` 搬移音频块、借用原有零尾安装：压缩流 627,547 字节，对齐后 627,552 字节，借位 28,208 字节。新字库本次压缩结果比旧组件略小，不需要新的分配器。

主程序 `0x3B0E0`、`0x168A1C` 的范围补丁均保持 `9f820134`。既有英文、数字字形槽未改。共享源码分配表已更新；下一次构建本篇须正常重建其字库和消费者，当前本篇旧制品仍对应旧清单。

## 写回与验证

- `srwz.stage` 按显式加载基址识别 SP 的 `0x63` 控制记录及条件表，不再替换解析器源码。Original 和 BEST 的控制记录集合保持原样。
- 写回读取原盘函数表，解析到胜败条件；原试排脚本因未传函数表而漏掉这些条目。
- 按原生 ID 和原文哈希绑定，哈希有多种答案时拒绝自动选择。开发入口显式使用 `--allow-draft`。
- 复用本篇 `repack_stage_texts_in_place`。保留“说话人＋换行＋正文”结构，仅使用解析明确拥有的源串及其对齐零尾。未知同值地址或串内引用触发失败。
- 普通对白使用共享 `story_dialogue` profile；场景标签及条件保留显式分行，不套对白缩进。
- 逐条回读后再次完整解析，校验原生记录集合、指针、正文及终止符，再逐块压缩／解压。两个关卡的未拥有字节分别有 16,040 和 14,032 字节，经逐字节校验保持不变。
- ISO 合成只替换主程序、VT1、STAGE 三个成员。全部目录项、LBA、成员大小保持一致；三成员之外的 **3,581,869,320 字节**逐字节相同。VT1 合成只替换字库／音频区域；已完成图片保持基线字节。
- 完整构建入口重跑一次，镜像 SHA-256 完全一致；代码哈希与检查汇总在 `work/build/special-disc/text-candidate/validation.json`。
- 共享字体正式验证覆盖 137,869 个当前语料条目，missing=0。
- 新增 10 项绑定／解析／保护测试通过；既有 9 项 STAGE 重排安全测试通过。
- 全套 `python3 -m unittest discover -s tests`：344 项，340 通过、1 跳过、2 失败、1 错误。两项失败是本篇“逃生／脱出”和“修理屋”预期与 HEAD 语料不一致；对应测试和语料与 HEAD 相同。本篇 Z:Report 测试因本地缺少 `rom/original.iso` 出错。日志：`work/build/special-disc/text-candidate/tests.log`。没有为通过测试修改这些无关语料或测试预期。

## 复现

从仓库根目录，使用已安装项目依赖的 Python 3.12+：

```sh
python3 tools/special_disc/writeback/build_text_candidate.py
```

该入口先核对共享分配表，再调用本篇 prepare/build/verify 字库工具、SP 字库安装、两关写回和 ISO 装配。任何组件失败都会停止合成；不会将缺少关卡组件当作成功。源码分配表的新增仍由 `update_zh_release_font_snapshot.py --apply` 显式执行，不在此构建入口内自动分配。

只装配已有、验证过的候选组件：

```sh
python3 tools/special_disc/writeback/build_text_candidate.py --assemble-only
```

单独构建两关：

```sh
python3 tools/special_disc/writeback/migrate_stage_dialogue.py \
  --allow-draft \
  --proposal work/build/special-disc/text-candidate/font/proposal.json
```

## 全量绑定调查

只读调查已解析 44 个有文本的原生块，共 10,086 条记录（包括说话人与条件）。其中 9,130 条可绑定，956 条仍待处理：843 条存在多个本篇答案，113 条没有同领域复用答案；未发现 SP 位置译稿的原文哈希漂移。这是绑定清单，不是全量写回率。结果在 `work/review/special-disc/status/native-binding-inventory.json`，可用 `python3 tools/special_disc/verification/survey_stage_bindings.py` 重跑。

## 尚未覆盖

小队名补充（含本关两条 frame 译稿）、VT1 挑战简报、其他关卡、新增 123 条 SRVC 台词及其余 WB-05／06 文字面仍待接入。两个英文固定槽问题仍未处理。场景标签／条件的最终布局、完整战斗流程、存读档、审校与 PCSX2 手工验收仍待完成。

LRPS2 已使用这份精确 ISO 和独立记忆卡副本进入两关：普通挑战第 1 关显示“阿伽玛 简报室”、卡缪及对白；剧情第 1 关显示“纽瓦克基地 司令室”、捷利特／牙买加及多句中文对白。新增字形“纽”已在画面中显示。记录与截图在 `work/runtime/lrps2/sp-text-canary-20260919/`，`visual-review.json` 汇总实际观察与边界。剧情旁白与任务简报仍为日文，属于未接入面。这里只确认入场样本，不代表全关卡、完整战斗或存读档验收；PCSX2 仍待手工验收。
