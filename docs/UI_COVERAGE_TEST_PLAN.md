# UI 汉化覆盖与测试方案

本方案把“各种菜单、人物／机体信息页、开场滚动文本和前五关开场剧情”拆成
可追踪场景。场景选择来自当前真实语料、原版成员和构建后的前五关字库，不根据
截图猜测文本归属。

当前场景结论是 `inventory_passed_work_remaining`：场景筛选、源哈希、译文
决策、字形需求、完整动态名称结构和五份中文 atlas 候选已经通过静态审计。
增量 P0 字库候选也已达到
`offline_font_and_p0_renderer_coverage_passed_runtime_pending`。在该字库组件
上，P0 SLPS 的 418 条已全部覆盖：101 条原字节已满足决策，317 条写入 378
个目标。P0 COMPDATA 的 44 条也全部覆盖：3 条原本一致、41 条实际写入。
开场路线另有 45 个动态人物／机体名称字段完成定长写回和独立回解。
标题、上述 P0 内容、开场 45 项加 researched 1,262 项动态名称、P2 字库和
28 条世界史已经进入 `ui-p2-core`；测试专用综合候选进一步加入前五关
`HB/STAGE` 和五图 `KVMDATA` suite，并通过 7 成员 ISO 静态回读。PCSX2
逐屏路线和五张 atlas 的场景归因仍未因此自动通过。

## 1. 可重复入口

机器事实源是 `config/ui-scenes.json`，提交摘要是
`manifests/ui-surface-inventory.json`。本地详细报告和审阅表分别生成到
`work/review/ui-surface-inventory.json` 与
`work/review/ui-surface-inventory.tsv`：

```bash
python3 tools/audit_ui_coverage.py --force
python3 tools/audit_display_name_coverage.py --force
```

第一条命令会同时验证：

- 94,189 条源语料的条数和聚合 SHA-256；
- 每个 selector 的稳定 ID、条数、source hash 和翻译决策；
- 当前前五关 SLPS、VT1、codebook 与字形实际可达性；
- COMPDATA 全部动态名称记录的结构、稳定 ID、分配边界和聚合 hash；
- 45 个开场动态名称决策及 writer 清单，和三个既有探针的精确对应；
- 标题菜单已有图片证据，五份中文 atlas manifest 的状态和哈希均被锁定；
- P0 条数、缺字上限和候选槽余量；
- 提交清单与本地审计结果完全一致。

第二条命令单独重建余下动态名称的 researched 精确源词选择，验证当前
P1 字库的编码／renderer 缺口和每项原 allocation 容量，并把含日文的
2,800 行审核队列写入被忽略的 `work/review/`。该命令只拥有选择结论；
字库、COMPDATA writer、组合 component、ISO 和运行结论分别由后续 P2
profile 与清单拥有。

只有审核配置或基线变化后，才能显式更新提交清单：

```bash
python3 tools/audit_ui_coverage.py --force --refresh-manifest
git diff -- manifests/ui-surface-inventory.json
```

清单和配置不保存日文原文或游戏字节；日文语料、解码数据及详细本地报告仍留在
被忽略的 `work/`。

世界史滚动文本使用独立布局门；默认命令只检查，不修改语料：

```bash
python3 tools/reflow_world_history.py --force
```

只有人工审阅差异后才使用 `--apply`，确认再次检查为零改动后，再用
`--refresh-manifest` 更新提交清单。该命令锁定真实 SLPS、MTV_PROS、码表、
release 和当前 UI 字库候选，并将文本内容、显示宽度、空行节奏和定长
allocation 分开验证。

P0 字库候选使用独立 profile，不改变已验收的 first-five 组件：

```bash
python3 tools/audit_ui_p0_font.py --force
python3 tools/build_first_five_font.py \
  --force \
  --proposal work/writeback/ui-p0-codebook-proposal.json \
  --output-root work/build/ui-p0/components \
  --font-config config/fonts/ui-p0-font.json \
  --allocation-registry config/encoding/ui-p0-allocations.json
python3 tools/verify_ui_p0_font.py --force
```

最后一条命令会重新生成 proposal 事实、解析候选 SLPS/VT1，并要求 462 条 P0
文本的 renderer 缺字和原版汉字字形混用均为零。提交结果见
`manifests/ui-p0-font-validation.json`。

世界史 P1 字库使用通用 profile 入口，并显式继承 P0 账本和组件：

```bash
python3 tools/audit_ui_font.py \
  --config config/fonts/ui-p1-summary-font.json --force
python3 tools/build_first_five_font.py \
  --force \
  --proposal work/writeback/ui-p1-summary-codebook-proposal.json \
  --output-root work/build/ui-p1-summary/components \
  --font-config config/fonts/ui-p1-summary-font.json \
  --allocation-registry config/encoding/ui-p1-summary-allocations.json
python3 tools/verify_ui_font.py \
  --config config/fonts/ui-p1-summary-font.json --force
```

该 profile 只生成／验证离线 SLPS、VT1 和字形账本，不写 MTV_PROS，也不构建
ISO。提交结果见 `manifests/ui-p1-summary-font-validation.json`。

28 条世界史正文在 P1 字库之上使用独立 production component：

```bash
python3 tools/build_ui_p1_world_history.py --force
python3 tools/verify_ui_p1_world_history.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-p1-world-history-build.json
python3 tools/verify_ui_p1_world_history_iso.py --force
```

builder 按原 14 块 offset 表解析真实 MTV_PROS，只对含文本的 12 块执行
fixed-allocation 写回和 changed-suffix 重编码；两个无文本块保持原字节。
验证器既做确定性重建逐字节比较，也从产物 SLPS offset 表重新切分 14 块，
用 P1 codebook 重读全部 28 条。当前成员由 9,056 缩至 8,640 字节，SLPS
只允许 60 字节 MTV_PROS offset 表变化，VT1 必须与 P1 字库组件完全一致。
component 结果见 `manifests/ui-p1-world-history-validation.json`。隔离 ISO
固定为 3,758,358,528 字节，SHA-256
`49cba4170cabf17bfeaa8320518c429831abd309156e68f14d8e85b28dd6feb2`；
66 个成员、63 个未替换成员逐字节一致，三项替换均通过独立 UDF 回读。
静态容器结果见
`manifests/ui-p1-world-history-runtime-validation.json`；它不证明滚动画面或
raw-trail 新类别已通过实机验收。

这些独立组件的组合入口为：

```bash
python3 tools/build_ui_p1_core.py --force
python3 tools/verify_ui_p1_core.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-p1-core-build.json
python3 tools/verify_ui_p1_core_iso.py --force
```

集成器以 P0 字库 SLPS 为共同基线做三方补丁，要求 2,659 个菜单变化字节与
P1／世界史修改零重叠；标题只替换已验证的 VT1 chunk 6 TIM2 record，另外
13 个 VT1 chunk 保持原字节。最终 component 重新读取全部 28 条世界史和四项
输出锁。组合 ISO 为 3,758,456,832 字节，SHA-256
`5f558ae794dec6d2e95bf56f391b5a0789eba78f4c330aa441a935b13973891b`；
66 个成员中 62 个未替换成员逐字节一致，SLPS、VT1、MTV_PROS、COMPDATA
均通过独立 UDF 回读。提交结果见 `manifests/ui-p1-core-validation.json` 和
`manifests/ui-p1-core-runtime-validation.json`。该镜像不包含前五关
STAGE/HB 或信息页 atlas，运行状态仍为 `not_tested`。

当前 P2 production profile 在 P1 之上增加 researched 动态名称，完整命令为：

```bash
python3 tools/audit_ui_font.py \
  --config config/fonts/ui-p2-display-names-font.json --force
python3 tools/build_first_five_font.py \
  --force \
  --proposal work/writeback/ui-p2-display-name-codebook-proposal.json \
  --output-root work/build/ui-p2-display-name-font/components \
  --font-config config/fonts/ui-p2-display-names-font.json \
  --allocation-registry config/encoding/ui-p2-display-name-allocations.json
python3 tools/verify_ui_font.py \
  --config config/fonts/ui-p2-display-names-font.json --force
python3 tools/build_ui_display_names.py \
  --config config/ui-writeback/ui-p2-display-names.json --force
python3 tools/verify_ui_display_names.py \
  --config config/ui-writeback/ui-p2-display-names.json --force
python3 tools/build_ui_world_history.py \
  --config config/summary/world-history-p2-display-names-component.json --force
python3 tools/verify_ui_world_history.py \
  --config config/summary/world-history-p2-display-names-component.json --force
python3 tools/build_ui_core.py \
  --config config/ui-integration/p2-researched-display-names.json --force
python3 tools/verify_ui_core.py \
  --config config/ui-integration/p2-researched-display-names.json --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-p2-core-build.json
python3 tools/verify_ui_core_iso.py \
  --config config/iso/ui-p2-core-build.json \
  --component-manifest manifests/ui-p2-core-validation.json \
  --manifest manifests/ui-p2-core-runtime-validation.json \
  --report work/review/ui-p2-core-iso-validation.json --force
```

账本结果不是 33 个新槽：29 字新分配，`娅杰艾贾` 四字恢复原已登记的
code/glyph，另重绘 29 个原版汉字，余 19 槽。COMPDATA 合计 1,307 项，
1,213 项实际写入、94 项 no-op；当前 ISO 大小为 3,758,456,832 字节，
SHA-256 为
`2ce5c844cd623c1bfd2f6ec1bc7acc0aa9565fc069f451a0b736ad3e8aa13a65`。
66 个成员中 62 个未替换成员保持原字节，四项 replacement 独立 UDF 回读；
以上均为 P2 核心历史基线的静态证据，运行状态仍为 `not_tested`。当前
运行矩阵改用下文的综合测试候选，避免核心 UI 与前五关之间切换镜像。

固定长度的第一层 SLPS 写回使用独立 profile：

```bash
python3 tools/build_ui_p0_fixed_slps.py --force
python3 tools/verify_ui_p0_fixed_slps.py --force
```

writer 只选择含终止符后能装进每个原有 span 的 P0 文本，并要求共享目标的
所有解析 owner 同时入选且编码结果一致。验证器从字库候选 SLPS 重新构建并
逐字节比较，要求 101 条 byte-exact no-op、317 条／378 个写入目标共同覆盖
全部 418 条，所有指针和 MIPS HI/LO 指令字节不变、目标外字节不变、解压
字库哈希不变。提交结果见
`manifests/ui-p0-fixed-slps-validation.json`。

COMPDATA 使用同一原位写回契约，并对压缩成员执行保留前缀的确定性 suffix
重编码：

```bash
python3 tools/build_ui_p0_fixed_compdata.py --force
python3 tools/verify_ui_p0_fixed_compdata.py --force
```

当前 44 条 P0 COMPDATA 中，3 条为 byte-exact no-op，41 条／41 个目标完成
写回，没有 overflow。验证器要求 524,032 字节解码输出大小不变、所有变化
字节均位于登记 span、28,100 个指针字节不变、压缩流完整消费并精确回解。
重编码保留原流前 128,781 字节，成员由 144,990 增至 147,050 字节；ISO 层
必须显式接受并回读这个 2,060 字节增长。提交结果见
`manifests/ui-p0-fixed-compdata-validation.json`。

动态名称解析和开场切片写回使用独立配置，不把日文原文提交到仓库：

```bash
python3 tools/parse_srwz_display_names.py --force
python3 tools/build_ui_p0_display_names.py --force
python3 tools/verify_ui_p0_display_names.py --force
```

结构解析覆盖 933 条人物记录的 2,799 个固定字段，以及 808 条机体记录所引用的
348 个唯一名称槽，共形成 3,147 个稳定 ID；其中 2,800 个字段非空。开场批次从
中选择 45 个已审校字段：42 个人物字段和 3 个机体字段，全部在原 allocation
内写入。验证器要求人物 ID 字节、808 个机体指针、非目标字节和解压后结构均
不变，并从重编码流完整回解。动态名称组件在静态 P0 COMPDATA 上保留
29,093 字节压缩前缀，成员由 147,050 增至 156,161 字节；ISO 层仍须显式接受
并验证这个增长。提交结果分别见 `manifests/display-name-structure.json` 和
`manifests/ui-p0-display-names-validation.json`。

## 2. P0：下一张组合候选的范围

P0 选择开场至首个幕间可稳定访问的高频界面。七个场景共选择 462 条唯一文本
决策；标题四项另走已验证的 TIM2 图片路径。

| 场景 | 文本数 | 相对 first-five 基线的新增字 | 当前结构缺口 |
| --- | ---: | --- | --- |
| 标题主菜单 | 0，另有 4 项图片文字 | 0 | 已进入组合 ISO；既有独立运行证据不能自动沿用到新镜像 |
| 开局路线、主人公与姓名设置 | 31 | 昵、节 | 静态文本和节子默认名字段已进入组合 ISO；玩家编辑后的动态值待运行验证 |
| 幕间主菜单、系统选项与编成入口 | 121 | 养、删、编、览 | 静态文本已进入组合 ISO；`中场休息`、`新建小队` 与 `交易所` atlas 有中文隔离候选、待运行归属 |
| 人物、机体与武器信息页骨架 | 128 | 养、减、效、览、陆 | 静态文本及 1,307 个名称字段已进入 P2 组合 ISO；另有中文 `机体` atlas 独立候选，仍待运行归属 |
| 战场指令、条件与战况页面 | 80 | 陆 | 静态文本已进入组合 ISO；中文 `指令菜单` atlas 有独立候选、待运行归属 |
| 结算、升级与出击确认 | 52 | 0 | 静态文本已进入组合 ISO；中文 `新建小队` atlas 有独立候选，结算与出击路线待运行验证 |
| 搜索条件、筛选与结果 | 50 | 效 | 静态文本已进入组合 ISO；筛选行为与拼接结果待运行验证 |

合并去重后相对 first-five 基线需要新增 `养减删效昵编节览陆` 九个汉字。
`ui-p0` 增量账本已把它们稳定分配到 `86F1～86F9` / glyph
`1137～1145`；原来剩余的 12 个安全候选槽现在保留 3 个。P0 另引用的
`励培姓御恢播耗菜覆` 九个原版汉字也已用同一 LXGW 字体重绘。候选包含
639 个分配、815 个既有汉字重绘，共 1,454 个 assignment；从候选组件重读后，
P0 缺字和原版汉字混用均为零。

字库和两个 fixed-span writer 现在证明全部 462 条 P0 SLPS／COMPDATA 文本
决策均可生产，不再依赖未登记池区。动态名称的结构、开场 45 个字段及
researched 精确门选出的 1,262 个字段已形成 P2 组件；合计 1,307 项现已与
标题、P2 字库和世界史合并为静态验证的可玩候选 ISO，另有 1,493 个非空字段
仍在人工队列。信息页 atlas 已从擦除定位实验推进到独立中文候选，但尚未获得
PCSX2 截图和精确 421 像素纹理 delta，因此仍不能称为正式场景映射；组合镜像
也尚未完成逐屏运行验收。

P0 明确排除了两条含未定英语专名的后期专用提示。它们已独立归入
`menus/late-game-special-prompts`，不会为了凑开场覆盖而消耗当前三个余量槽。

## 3. 后续场景

| 优先级 | 场景 | 文本数 | 推迟原因 |
| --- | --- | ---: | --- |
| P1 | 关卡标题与路线选择 | 122 | P1 字库、容量与运行路线尚未进入独立 profile，当前还缺 36 个字符 |
| P1 | 开场／资料库世界史滚动文本 | 28 | 布局、P1 字库、完整 MTV_PROS 组件、隔离和组合 ISO 静态回读已通过；28 条仍为 `draft`，raw-trail 新类别和滚动运行待验收 |
| P1 | 前五关开场、黑屏字幕与对话 | 1,833 | ISO 静态全量回读已通过，当前精确候选仍待运行验证 |
| P1 | 其余内嵌设置、编成与提示文本 | 275 | 仍是上游 unknown 聚合，必须先按可见界面继续拆分 |
| P1 | 后期专用指令与合神提示 | 2 | 英语专名需要人工确认 |
| P2 | 零件、技能、能力、精神与武器数据库 | 1,250 | 当前追加式字库容量不足 |
| P2 | 战斗退场台词 | 297 | COMPDATA writer 和触发路线矩阵均缺失 |

世界史 28 条现已排成 146 个显示行，最大宽度 22 格；14 个段落空行保持不变，
三个跨记录连续组共 14 条按照各自原 allocation 重新分配后没有溢出。清单见
`manifests/world-history-layout.json`。这只证明逻辑正文未改变、断行可显示且
原位记录容量足够；28 条仍是 `draft`。该清单相对 P0 候选记录 27 个未映射字
和 14 个 resolver 不可达字，三个安全槽仍短缺 38 个。独立 P1 字库候选已追加
全部 41 字并统一重绘另 53 个汉字，从候选组件重读 490 条 P0＋世界史文本后
缺字与原版汉字混用均为零、余 48 个 renderer-addressable 槽。完整中文
MTV_PROS 离线组件现已写入 28/28 条：14/14 块解码往返、12 块重编码、
2 个无文本块原字节不变，输出重读未知码为零。隔离 ISO 已通过完整静态容器
校验并锁定精确 SHA-256；尚缺起点／中段／结尾运行证据。前五关 1,833 条
已写入现有候选并通过静态回读，但不能据此推导每个开场、黑屏字幕或战场触发
都已在 PCSX2 中出现。

P1 容量的 736 个候选由 650 个合法 Shift-JIS 安全候选和 86 个 raw-trail
可寻址空隙组成。当前 688 个登记字符占用后余 48 槽；新增世界史 41 字中三字
使用最后三个合法候选，38 字使用 `0x7F/0xFD` 尾字节空隙。原 SLPS 的测量和
glyph resolver 指令窗口均已哈希锁定，证明这四类空隙走同一 192-glyph 公式；
既有 `987F=试` 只为 `0x7F` 类提供一次运行先例，不能替代本 P1 组件或
`0xFD` 类的实机验收。

## 4. 当前发现的结构缺口

### 4.1 动态人物和机体名

当前菜单语料主要覆盖 SLPS 与 COMPDATA 的通用菜单文本，不能代表人物／机体
显示名已经结构化导出。审计器已在真实 COMPDATA 解码流上固定三个 hash-only
探针：

- 女主人公显示名；
- 小队长显示名；
- Vargora 01 机体显示名。

三个探针已提升为完整结构 parser 的 freshness gate。当前已确认：

- 人物表从 decoded `0x2160` 开始，共 933 条、每条 `0xB0` 字节；每条具有
  display／family／given 三个固定字段，合计 2,799 个稳定 ID；
- 机体表共 808 条记录，808 个指针归并到 348 个 8-byte 对齐的唯一名称槽；
- 所有字段均在 allocation 内以 NUL 终止，padding 为零，解析未知码为零；
- 提交清单只保存结构、计数和聚合哈希，日文名称留在被忽略的本地输出。

`corpus/zh/display-names/p0-opening.json` 首批登记 45 个 `reviewed` 决策，
覆盖节子、小原、丹泽尔·哈默、托比·沃森的重复人物字段及三台巴尔戈拉。
writer 只做原 allocation 内写回，禁止人物 ID 或机体指针变化。节子是可由玩家
改名的默认值；玩家确认新名字后的运行时值仍应由游戏自身处理，静态组件不应
覆盖该行为。

第二批现已通过 `config/display-names/researched-coverage.json` 做保守筛选：
只接受 v1 术语库中状态为 `researched` 的精确日文源词，排除一源多译冲突和
首批 45 个稳定 ID。结果从余下 2,755 个非空字段中选出 1,262 个
（1,221 人物／41 机体、307 个唯一源词），另有 1,493 个继续留在人工队列。
完整 2,800 行含日文审核表只写入
`work/review/display-name-researched-coverage.tsv`；提交清单只有源哈希、
译名来源、计数和选择哈希。当前 P1 字库已能编码其中 1,166 个字段，另外
96 个字段合计只缺 `伦侣凤凯妮姬娅岛庆户滨琪苏萝谦贾赛赞钢钱阳` 21 字，
但统一 renderer 还要为普通 ASCII `a/f/h/r/u` 和 7 个原表不可达汉字新增
字形，因此共有 33 个 renderer 缺字；账本复核确认 29 个需要新 allocation，
`娅杰艾贾` 四字复用已登记退役 assignment，并需统一重绘另 29 个原版汉字，
最终余 19 槽。全部 1,262 个 payload 均不溢出原 allocation。
该门禁不是按“同原文”盲填：只有已研究术语的一对一精确决定才进入选择；
P2 字库、COMPDATA writer 和组合 ISO 已由各自 profile 静态验证；审核晋级
和 PCSX2 运行验证仍是独立门。

### 4.2 KVMDATA UI 图片文字

固定 4-bpp TIM2 writer 已能对真实 KVMDATA fixture 做 byte-identical
no-op。五个目标都先完成了只清除原标签的隔离映射 canary，再以各自前像和
mask 为边界生成中文候选。所有组件仍是 `runtime_mapping_pending`，不能
视作已进入游戏的正式 atlas。
上游 ASM 中存在信息页布局研究，只能作为研究证据；它不是当前中文候选的
writer，也不能替代本项目自己的前像、差异和运行门禁。

离线 contact sheet 已将检索范围从 20 个 TIM2 缩至五个 256×256/4-bpp
候选，机器锁见 `config/assets/ui-atlas-candidates.json`：

| chunk | 离线可见词 | 最可能场景 | 当前证据等级 |
| ---: | --- | --- | --- |
| 2 | `SHIP / PARTS / PILOT / ROBO / SEARCH / WEAPON / MAP DATA` | 人物／机体／武器信息页、搜索、战况 | 中文 `机体` 独立候选和静态 ISO 已锁定，未做运行映射 |
| 4 | `COMMAND MENU / FORMATION / BONUS / HIT&AWAY / HP / EN` | 战场指令、结算 | 中文 `指令菜单` 独立候选和静态 ISO 已锁定，未做运行映射 |
| 5 | `バザー / 購入 / 売却 / 強化パーツ / アイテム` | 商店／交易 | 中文 `交易所` 独立候选和静态 ISO 已锁定，未做运行映射 |
| 6 | `インターミッション / オプション / 小隊編成 / データ管理` | 幕间、编成入口 | 中文 `中场休息` 独立候选和静态 ISO 已锁定，未做运行映射 |
| 7 | `Event No / Leader / Pilot / 新規編成 / リザーブへ` | 编成、出击 | 中文 `新建小队` 独立候选和静态 ISO 已锁定，未做运行映射 |

这里的“可见词”只用于定位，不是译名权威，也不能证明游戏在目标页面加载了该
chunk。五个基础 mapping canary 均只擦除 mask 内非背景像素，并逐像素保留
登记的透明或不透明背景：

- chunk 2：`SHIP` mask `80,0,49,16`，299 个逻辑像素／185 个 archive byte；
  ISO SHA-256
  `9343889dc72c6d3fc2287f0ac279912fb1ae7e1e1123ee15150f667e50bc78f6`；
- chunk 4：`COMMAND MENU` mask `2,100,164,17`，2,297 个逻辑像素／
  1,221 个 archive byte；ISO SHA-256
  `067626adbaac4ab0189df3b653c1da040d1ea18783667dc2b3ba7b598cae65c1`；
- chunk 5：大号 `バザー` mask `3,1,137,61`，2,197 个逻辑像素／1,210 个
  archive byte；ISO SHA-256
  `6805fbd0bbfe98ef613ab7a4f4eddf184517b681a800b06a3fa1ba5af2ec2d04`；
- chunk 6：幕间标题 mask `0,0,185,31`，803 个逻辑像素／509 个 archive
  byte；ISO SHA-256
  `dafe4737f797b611e02a0dcf68096a40e9b3c61ae4fa98d979b19a00ce0ca0df`；
- chunk 7：`新規編成` mask `98,26,74,20`，1,325 个逻辑像素／691 个
  archive byte；ISO SHA-256
  `5f05e41f9ba2e410d36a985ca9a87f177d6622ee4e5340d5c0f0ad1ba4fe844c`。

中文生产配置为五个 `config/assets/ui-*-atlas-zh.json`；译文分别由
`corpus/zh/ui-atlas/info-v1.json` 和
`corpus/zh/ui-atlas/core-menus-v1.json` 所有。构建器逐字节复建各自擦除
前像，使用锁定的 LXGW 字体和原图已有灰度调色板。静态锁如下：

| chunk / 标签 | 新增文字像素 | 相对原图像素 delta | 独立 ISO SHA-256 |
| --- | ---: | ---: | --- |
| 2 / `机体` | 318 | 421 | `d31f3d3dbffc59da595b2d27bb516efec34af12426bda2b3d6f2a67ffdb9ddd0` |
| 4 / `指令菜单` | 569 | 2,292 | `3e9ed4b155867cefc6b03775a20ab1ca58f7bc4c29ef7bcdfa6feceb14182dda` |
| 5 / `交易所` | 2,756 | 3,634 | `9fcf33ba40c717497d6750e303db44e3a48bf814f43f4dbdebef3639912bf363` |
| 6 / `中场休息` | 1,642 | 2,083 | `27a7563c517c155cb9fc44e2b80a06be41d1a1fb294c0f633537b19c4f9e9de2` |
| 7 / `新建小队` | 723 | 1,262 | `cc8cd7cf82583cb5ea8d52ccac6aabafa730a653ff70613ac2a07da1f763a293` |

五张中文隔离 ISO 都只替换 `KURODATA/KVMDATA.BIN`，完整归档等长，65 个
未替换成员 byte-exact、零 LBA 位移。下一轮分别检查至少两台机体的信息
子页、两台单位的战场指令菜单、可访问的商店页、首个幕间主菜单和编成／出击
页。每个用例都要求画面在原位置出现对应中文标签，且 PCSX2 texture dump
精确命中表中的原图 delta，才能把对应 `candidate_scene_ids` 升级为正式
member/chunk/record/picture 映射。静态 preview、ISO 构建通过或任意页面
变化都不能单独晋级。

下一阶段不再新增同类离线 canary，而是逐张完成截图／texture-dump 双门；
前一张 atlas 的运行归属不得推断到后一张。五图可以进入明确标为测试专用的
综合镜像以减少候选切换，但不能据此晋级生产状态，也不能替代五张隔离 ISO
的映射证据。

### 4.2.1 综合 UI／前五关／atlas 测试候选

五份中文 atlas 先以原版 `KVMDATA.BIN` 为共同基线做字节所有权合成，再与
P2 UI 四成员及前五关 `HB/STAGE` 做完整成员组合：

```bash
python3 tools/build_ui_atlas_suite.py --force
python3 tools/verify_ui_atlas_suite.py --force
python3 tools/build_ui_test_candidate.py --force
python3 tools/verify_ui_test_candidate.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-p2-first-five-atlas-test-build.json
python3 tools/verify_ui_test_candidate_iso.py --force
```

atlas suite 相对原版归档共改变 5,568 个字节，五类 owner 零重叠，所有权外
字节完全不变。综合 component 的 7 个成员也零重叠：P2 UI 拥有
SLPS／COMPDATA／MTV_PROS／VT1，前五关拥有 HB／STAGE，suite 拥有
KVMDATA。最终 DVD 大小为 3,758,456,832 字节，SHA-256 为
`af5c1c5a510db1d86bee2054935400e51c86df34902972ef2ebafa71bb3eb52a`；
59 个未替换成员 byte-exact，7 个 replacement 独立 UDF 回读，LBA 位移仅为
`DATA/NISVDATA.BIN +7` 和 `DATA/STAGE.BIN +42`。这只建立综合运行候选的
静态身份；五个 isolated atlas profile 仍是 scene mapping 的唯一归因依据。

### 4.3 SLPS/COMPDATA 文本池

`relocate_menu_texts_to_pool()` 已覆盖普通指针和 MIPS HI/LO 写回，单元测试
也已通过。P0 审计最初暴露的部分“增长”来自 `%s` 被误当普通可见 ASCII
override；序列化器现统一保留该运行时 token 的原始 ASCII 字节，并由翻译
审计保证源／译 token 集不变。其余 UI 标签采用语义等价的原生短标签后，
SLPS 418 条和 COMPDATA 44 条都能在原 span 内覆盖，不需要 P0 文本池。
未来 P1/P2 若需要搬移，仍必须先证明真实池区、所有引用者和容量。

### 4.4 运行场景矩阵

自然语言路线现已提升为独立事实源
`config/runtime/ui-test-matrix.json`，由下列命令校验，并在 `work/review/`
生成完整 JSON 和逐用例 TSV：

```bash
python3 tools/audit_ui_runtime_matrix.py --force
```

提交投影为 `manifests/ui-runtime-test-matrix.json`。它不修改
`config/ui-scenes.json` 的语料选择，只把 14 类场景绑定到精确候选、fixture、
到达步骤、截图点和证据门。当前结果是：

- 10 类进入运行测试：全部七类 P0，加关卡标题／路线、世界史滚动和前五关开场；
- 4 类显式延期：275 条未拆屏提示、两条后期专用提示、1,250 条大型数据库、
  297 条退场台词；每类都登记继续推进所需的 exit gate；
- 19 个用例：9 个 UI／路线验收、5 个 001～005 开场序列和 5 个中文 atlas
  场景映射／显示实验；
- 6 张候选 ISO 均由现有 manifest 锁定精确 SHA-256：1 张综合镜像和 5 张
  atlas 隔离镜像；
- 14 个非映射用例（核心 UI、路线与前五关）绑定同一综合镜像；5 个映射用例
  仍绑定各自隔离 atlas ISO，P1/P2 core 和 first-five 原镜像保留为历史
  可复建基线；
- 计划采集 42 张截图、6 组截图序列和 5 份 texture delta；
- fresh boot 是唯一已就绪 fixture，因此标题、玩家设置、世界史滚动和
  stage 001 开场共 4 个用例可直接执行；其余 15 个用例等待六份原生
  memory card。

所有 memory card 都必须放在被忽略的
`work/runtime/ui-fixtures/<fixture>/SLPS-25887.ps2`，登记 SHA-256 后才可
晋级。现有 `.p2s` savestate 既不满足 fresh-process 契约，也不会自动替代
原生存档。矩阵当前的 19 个 `runtime_status` 全部为 `not_tested`；
`route_ready` 只表示路线无需存档，不表示 PCSX2 已执行。

每个用例的执行链固定为：

```bash
# 1. 只生成被忽略的路线、目录和空白证据草稿，不启动模拟器
python3 tools/prepare_ui_runtime_case.py \
  --case-id core/title-main-menu --force

# 2. PCSX2 已从新进程启动精确 ISO 后，验证 ISO、PINE、DVD/ELF 和零 TLB
python3 tools/probe_ui_runtime_session.py \
  --case-id core/title-main-menu \
  --fresh-process --force

# 3. 填完 evidence-draft.json 的截图路径、断言和 verdict 后生成 hash-only 收据
python3 tools/verify_ui_runtime_evidence.py \
  --case-id core/title-main-menu --force
```

第一步现已为 `core/title-main-menu`、`core/opening-player-setup`、
`core/world-history-scroll` 和 `first-five/stage-001-opening` 建好本地工作区。
第二、三步尚未执行。session probe 必须同时确认精确 ISO、PINE
`SLPS-25887/Running`、fresh process、DVD、ELF executing 和零 TLB miss；
视觉 verifier 要求每个 capture ID 都有哈希／尺寸、每条断言为真。atlas
用例还会把运行纹理与锁定 reference PNG 做完整 256×256 RGBA 比较，只有
mask 内预期像素变化才可通过。

通过后的 receipt 先留在 `work/runtime/ui-cases/.../evidence-receipt.json`
供审阅。只有复制为 `manifests/runtime/ui-cases/*.json`、在矩阵中登记路径和
SHA-256，并重新通过矩阵审计后，`runtime_status: passed` 才成立；直接手改
状态、沿用旧候选截图或只有 session probe 都会失败。

receipt 绑定稳定的 `matrix_plan_sha256`：它覆盖路线、采集点、断言、精确
制品、fixture 和模拟器约束，只排除运行结果状态与 receipt 自身锁。完整
矩阵文件 SHA-256 仍单独写入派生 manifest 做 freshness 检查；两种哈希分工
避免“矩阵锁 receipt、receipt 又锁整个矩阵”的循环依赖。

## 5. 实施顺序

1. **已完成：**为 P0 追加九个新字符，并用统一字体重绘 P0 引用的九个原版
   汉字；code→glyph、空字形、冲突、VT1 重压缩、offset 回读和 P0 全量
   renderer coverage 已通过。
2. **已完成 SLPS P0：**101 条精确 no-op、317 条原位写回／378 个目标，
   覆盖全部 418 条；输出逐字节复建、指针／非目标字节／字库哈希不变。
3. **已完成 COMPDATA P0：**3 条精确 no-op、41 条原位写回，覆盖全部
   44 条；压缩流完成 prefix-preserving suffix 重编码和完整回解。
4. **已完成开场动态名切片：**完整解析 3,147 个稳定 ID，并对 45 个已审校
   字段执行定长写回；人物 ID、机体指针、非目标字节和完整解码往返均不变。
5. **已完成 P1 离线字库候选：**继承 P0 分配，追加世界史 41 字、重绘另
   53 个汉字，490 条选择零缺字且 VT1 大小保持不变；raw-trail 的新类别仍需
   绑定未来精确 ISO 做 PCSX2 验收。
6. **已完成 P1 世界史组件和隔离 ISO 静态验收：**28 条 fixed-allocation
   写回、14 块解码往返、SLPS offset 重读、独立全文重读、成员级 UDF 回读和
   精确 ISO hash 均通过；运行状态仍为 `not_tested`。
7. **已完成 UI core 组合 ISO 静态验收：**标题 TIM2、P0 菜单、开场动态名、
   P1 字库和世界史以明确 owner 合并；四项成员独立 UDF 回读、62 个未替换
   成员 byte-exact，并固定最终 ISO hash。
8. **已完成五项最小映射 canary 和中文候选的静态组件及隔离 ISO：**
   chunk 2 只清除 `SHIP`，chunk 4 只清除 `COMMAND MENU`，chunk 5 只清除
   大号 `バザー`，chunk 6 只清除幕间标题，chunk 7 只清除 `新規編成`；五者均受
   mask／背景色集合约束，
   完整 KVMDATA 等长、65 个未替换 ISO 成员 byte-exact、零 LBA 位移，并
   分别固定最终 ISO hash。五张受审中文候选 `机体`／`指令菜单`／`交易所`／
   `中场休息`／`新建小队` 也已锁定，相对原图分别变化
   421／2,292／3,634／2,083／1,262 个像素。
9. **已完成综合测试候选静态验收：**五图 suite 的 5,568 个实际修改字节
   所有权互斥；P2 UI、前五关和 suite 以 7 个完整成员组合，最终 ISO 的
   59 个未替换成员、两段 LBA 位移、UDF 回读和 SHA-256 均固定。
10. **已完成运行矩阵；当前执行目标：**19 个用例已绑定 1 张综合 ISO 和
   5 张隔离 atlas ISO、fixture、截图点和断言。先执行四个 fresh-boot 用例；
   取得并哈希锁定六份原生 memory card 后，用五张隔离候选分别证明中文标签
   出现与 421／2,292／3,634／2,083／1,262 像素 texture delta 同时命中；
   另用综合 ISO 完成标题、玩家设置、战场、搜索、世界史滚动和前五关路线，
   同时按官方术语扩大人物／机体名语料。

每一步都先建立可失败的门禁和最小 fixture，再扩展场景数；不直接修改
`work/` 中间产物作为生产输入。

## 6. 验证分层

### S0：选择与输入

- selector 条数、稳定 ID、source hash 和译文决策精确；
- 世界史布局清单的 28 条、22 格、14 个空行、零 allocation overflow、
  41 个缺字（27 unmapped＋14 resolver-unreachable）和 38 槽短缺 ratchet
  未漂移；
- P1 字库必须继承 P0 的 647 个登记字符，新增 41 个字符后共 688 个；
  合法 Shift-JIS 与 raw-trail 容量必须分开报告，不得把后者称为运行安全槽；
- 运行时 token 不计入字形需求；
- 所需字符全部可编码、glyph 非空且风格统一；
- 动态名称结构、已选译文、writer 清单和图片证据 manifest 未漂移。

### S1：component writer

- 原版成员 SHA-256 与 SurfaceSpec 前像一致；
- 所有新文本可重读，指针、HI/LO、终止符和对齐一致；
- 世界史 28 条必须全部留在原 allocation；12 个文本块可重编码，两个无文本
  块必须 byte-exact，SLPS 变化只能位于 MTV_PROS offset 表；
- 分配互不重叠且不越过登记池区；
- TIM2 只改变登记 picture/index/mask，CLUT 和非目标字节保持不变；
- 已知的错误前像、超长文本、重复分配和缺字 mutation 能使门禁失败。

### S2：ISO

- 只替换 profile 声明的成员；
- 未替换成员 byte-exact，成员顺序、LBA 和布局满足锁定策略；
- ISO 回读得到的 SLPS、VT1、COMPDATA、KVMDATA 和 STAGE 与 component
  manifest 完全一致；
- 记录最终 ISO 大小和 SHA-256。

### R0：运行绑定

- PCSX2 版本、BuildProfile、ISO SHA-256 和存档 SHA-256 一并记录；
- 每次执行必须命中 `ui-runtime-test-matrix` 的 case、artifact、fixture 和
  capture ID；没有到达目标状态算失败，不能记为 skipped pass；
- PINE 读取的 SLPS/字库内存哈希与当前候选一致；
- 冷启动无 TLB miss、黑屏或意外回退到旧 ISO。

### R1：逐屏视觉与导航

| 路线 | 操作切片 | 必查项 |
| --- | --- | --- |
| 标题 | 冷启动，光标遍历四项再返回 | 选中／未选中调色板、裁切、重叠 |
| 玩家设置 | START → 本篇 → 女主人公 → 姓名／生日／血型 | 动态玩家名、字段切换、默认名与编辑名基线 |
| 首个幕间 | 读取固定存档，遍历机体、驾驶员、强化、零件、编成和系统选项 | 顶层标签、说明、禁用态和按键提示 |
| 信息页 | 至少两台机体，循环机体／驾驶员／武器及能力子页 | 动态名称、数值、图标、分页、长武器名 |
| 战场 UI | 第 1 关打开战况、胜败条件、指令和攻击预览 | 条件文本、命中率／数值、目标切换 |
| 出击与结算 | 出击确认、战斗结算、升级后返回幕间 | 列表、确认提示、等级／PP／资金数值 |
| 搜索 | 打开条件，组合两个筛选并查看空结果和多结果 | 条件值、结果页、取消／确认状态 |
| 世界史滚动 | 从开头播放到结尾，另截取中点 | 中文断行、滚动边缘、首尾不丢行 |
| 前五关开场 | 依次进入 001～005 的开场、黑屏字幕和首个战场触发 | 字幕、玩家名替换、换行、场景切换 |

### R2：边界用例

- 最长可编辑玩家名、默认名和混合原有字符；
- 最长机体名、驾驶员名、武器名及多位数数值；
- 空搜索结果、满列表、禁用按钮和确认／取消来回切换；
- 世界史滚动暂停／跳过以及剧情快进；
- 存档读写后再次进入相同页面。

## 7. 验收边界

P0 只有同时满足以下条件才能标记完成：

- 462 条文本和标题四项都由同一候选 profile 生成；
- 九个新字符与九个重绘原版汉字通过静态和离线视觉检查；
- 动态人物／机体名及目标信息页 atlas 已进入正式 writer；
- S0、S1、S2 全绿；
- R0、R1、R2 使用同一精确 ISO hash 留下日志与截图摘要。

静态审计通过只能支持“候选范围可实现且输入未漂移”；不能表述为“UI 已汉化”
或“游戏内显示已验收”。
