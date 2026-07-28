# UI 汉化覆盖与测试方案

本方案把“各种菜单、人物／机体信息页、开场滚动文本和前五关开场剧情”拆成
可追踪场景。场景选择来自当前真实语料、原版成员和构建后的前五关字库，不根据
截图猜测文本归属。

当前场景结论是 `inventory_passed_work_remaining`：场景筛选、源哈希、译文
决策、字形需求和完整动态名称结构已经通过静态审计。增量 P0 字库候选也已达到
`offline_font_and_p0_renderer_coverage_passed_runtime_pending`。在该字库组件
上，P0 SLPS 的 418 条已全部覆盖：101 条原字节已满足决策，317 条写入 378
个目标。P0 COMPDATA 的 44 条也全部覆盖：3 条原本一致、41 条实际写入。
开场路线另有 45 个动态人物／机体名称字段完成定长写回和独立回解。
组合 ISO 和 PCSX2 路线仍未因此自动通过。

## 1. 可重复入口

机器事实源是 `config/ui-scenes.json`，提交摘要是
`manifests/ui-surface-inventory.json`。本地详细报告和审阅表分别生成到
`work/review/ui-surface-inventory.json` 与
`work/review/ui-surface-inventory.tsv`：

```bash
python3 tools/audit_ui_coverage.py --force
```

该命令会同时验证：

- 94,189 条源语料的条数和聚合 SHA-256；
- 每个 selector 的稳定 ID、条数、source hash 和翻译决策；
- 当前前五关 SLPS、VT1、codebook 与字形实际可达性；
- COMPDATA 全部动态名称记录的结构、稳定 ID、分配边界和聚合 hash；
- 45 个开场动态名称决策及 writer 清单，和三个既有探针的精确对应；
- 标题菜单已有图片证据；
- P0 条数、缺字上限和候选槽余量；
- 提交清单与本地审计结果完全一致。

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
| 标题主菜单 | 0，另有 4 项图片文字 | 0 | 已有独立运行证据，尚未合并进下一张 UI ISO |
| 开局路线、主人公与姓名设置 | 31 | 昵、节 | 静态文本和节子默认名字段已进入组件；玩家编辑后的动态值待运行验证 |
| 幕间主菜单、系统选项与编成入口 | 121 | 养、删、编、览 | 静态文本组件已覆盖；组合 ISO 与逐页运行验证待完成 |
| 人物、机体与武器信息页骨架 | 128 | 养、减、效、览、陆 | 静态文本及开场 45 个名称字段已覆盖；全名表译文与具体信息页 atlas 仍缺失 |
| 战场指令、条件与战况页面 | 80 | 陆 | 静态文本组件已覆盖；战斗菜单 atlas 与运行路线待接入 |
| 结算、升级与出击确认 | 52 | 0 | 静态文本组件已覆盖；结算／出击 atlas 与运行路线待接入 |
| 搜索条件、筛选与结果 | 50 | 效 | SLPS／COMPDATA 静态文本均覆盖；筛选行为与拼接结果待运行验证 |

合并去重后相对 first-five 基线需要新增 `养减删效昵编节览陆` 九个汉字。
`ui-p0` 增量账本已把它们稳定分配到 `86F1～86F9` / glyph
`1137～1145`；原来剩余的 12 个安全候选槽现在保留 3 个。P0 另引用的
`励培姓御恢播耗菜覆` 九个原版汉字也已用同一 LXGW 字体重绘。候选包含
639 个分配、815 个既有汉字重绘，共 1,454 个 assignment；从候选组件重读后，
P0 缺字和原版汉字混用均为零。

字库和两个 fixed-span writer 现在证明全部 462 条 P0 SLPS／COMPDATA 文本
决策均可生产，不再依赖未登记池区。动态名称的结构和开场 45 个字段也已形成
独立组件；剩余 2,755 个非空字段尚未审校选入。信息页 atlas 仍未定位，也尚无
包含这些新增字符和文本的可玩组合 ISO。

P0 明确排除了两条含未定英语专名的后期专用提示。它们已独立归入
`menus/late-game-special-prompts`，不会为了凑开场覆盖而消耗当前三个余量槽。

## 3. 后续场景

| 优先级 | 场景 | 文本数 | 推迟原因 |
| --- | --- | ---: | --- |
| P1 | 关卡标题与路线选择 | 122 | P1 字库、容量与运行路线尚未进入独立 profile，当前还缺 36 个字符 |
| P1 | 开场／资料库世界史滚动文本 | 28 | 布局、P1 字库、完整 MTV_PROS 组件和隔离 ISO 静态回读已通过；28 条仍为 `draft`，raw-trail 新类别和滚动运行待验收 |
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
覆盖该行为。剩余 2,755 个非空字段需要继续按官方／人工确认的术语批次扩展，
不能由同原文自动填充来替代审校。

### 4.2 信息页图片文字

通用 TIM2 writer 已能对真实 KVMDATA fixture 做 byte-identical no-op，
但人物／机体／武器信息页的具体 TIM2 记录尚未逐屏归属，也没有中文 atlas。
上游 ASM 中存在信息页布局研究，只能作为研究证据；它不是当前中文候选的
writer，也不能替代本项目自己的前像、差异和运行门禁。

离线 contact sheet 已将检索范围从 20 个 TIM2 缩至五个 256×256/4-bpp
候选，机器锁见 `config/assets/ui-atlas-candidates.json`：

| chunk | 离线可见词 | 最可能场景 | 当前证据等级 |
| ---: | --- | --- | --- |
| 2 | `SHIP / PARTS / PILOT / ROBO / SEARCH / WEAPON / MAP DATA` | 人物／机体／武器信息页、搜索、战况 | 离线候选，未做运行映射 |
| 4 | `COMMAND MENU / FORMATION / BONUS / HIT&AWAY / HP / EN` | 战场指令、结算 | 离线候选，未做运行映射 |
| 5 | `バザー / 購入 / 売却 / 強化パーツ / アイテム` | 商店／交易 | 上游修改过的离线候选，未做运行映射 |
| 6 | `インターミッション / オプション / 小隊編成 / データ管理` | 幕间、编成入口 | 上游修改过的离线候选，未做运行映射 |
| 7 | `Event No / Leader / Pilot / 新規編成 / リザーブへ` | 编成、出击 | 离线候选，未做运行映射 |

这里的“可见词”只用于定位，不是译名权威，也不能证明游戏在目标页面加载了该
chunk。下一轮必须用原版 ISO 在信息页逐页做 PCSX2 texture dump，以尺寸、
调色板和 index 直方图唯一匹配 stored picture；匹配后再做一个只覆盖目标词
mask 的可逆颜色 canary，要求画面变化与运行时纹理 delta 同时命中，才能把
`candidate_scene_ids` 升级为正式 member/chunk/record/picture 映射。

### 4.3 SLPS/COMPDATA 文本池

`relocate_menu_texts_to_pool()` 已覆盖普通指针和 MIPS HI/LO 写回，单元测试
也已通过。P0 审计最初暴露的部分“增长”来自 `%s` 被误当普通可见 ASCII
override；序列化器现统一保留该运行时 token 的原始 ASCII 字节，并由翻译
审计保证源／译 token 集不变。其余 UI 标签采用语义等价的原生短标签后，
SLPS 418 条和 COMPDATA 44 条都能在原 span 内覆盖，不需要 P0 文本池。
未来 P1/P2 若需要搬移，仍必须先证明真实池区、所有引用者和容量。

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
7. **当前下一步：**把 28 条世界史从 `draft` 提升到已审校状态并用当前
   隔离 ISO 完成滚动运行验收；同时按官方术语扩大人物／机体名语料，
   通过运行时纹理转储和离线预览，把人物／机体／武器信息页 atlas 精确映射到
   archive/member/record/picture。
8. 合并标题 TIM2、P0 字库、P0 文本、动态名、P1 世界史和前五关 STAGE；只从同一个
   profile 构建一张候选 ISO。

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
