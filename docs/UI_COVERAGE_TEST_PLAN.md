# UI 汉化覆盖与测试方案

本方案把“各种菜单、人物／机体信息页、开场滚动文本和前五关开场剧情”拆成
可追踪场景。场景选择来自当前真实语料、原版成员和构建后的前五关字库，不根据
截图猜测文本归属。

当前场景结论是 `inventory_passed_work_remaining`：场景筛选、源哈希、译文
决策、字形需求和三个动态名称探针已经通过静态审计。增量 P0 字库候选也已达到
`offline_font_and_p0_renderer_coverage_passed_runtime_pending`。在该字库组件
上，P0 SLPS 的 418 条已全部覆盖：101 条原字节已满足决策，317 条写入 378
个目标。P0 COMPDATA 的 44 条也全部覆盖：3 条原本一致、41 条实际写入。
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
- COMPDATA 三个动态显示名的 offset、长度和原文 hash；
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

## 2. P0：下一张组合候选的范围

P0 选择开场至首个幕间可稳定访问的高频界面。七个场景共选择 462 条唯一文本
决策；标题四项另走已验证的 TIM2 图片路径。

| 场景 | 文本数 | 相对 first-five 基线的新增字 | 当前结构缺口 |
| --- | ---: | --- | --- |
| 标题主菜单 | 0，另有 4 项图片文字 | 0 | 已有独立运行证据，尚未合并进下一张 UI ISO |
| 开局路线、主人公与姓名设置 | 31 | 昵、节 | 静态文本组件已覆盖；可编辑／默认玩家名记录仍待 parser/writer |
| 幕间主菜单、系统选项与编成入口 | 121 | 养、删、编、览 | 静态文本组件已覆盖；组合 ISO 与逐页运行验证待完成 |
| 人物、机体与武器信息页骨架 | 128 | 养、减、效、览、陆 | 静态文本组件已覆盖；动态名表 parser/writer 与具体信息页 atlas 均缺失 |
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
决策均可生产，不再依赖未登记池区。但这仍不包括动态人物／机体名、信息页
atlas，也尚无包含这些新增字符和文本的可玩组合 ISO。

P0 明确排除了两条含未定英语专名的后期专用提示。它们已独立归入
`menus/late-game-special-prompts`，不会为了凑开场覆盖而消耗当前三个余量槽。

## 3. 后续场景

| 优先级 | 场景 | 文本数 | 推迟原因 |
| --- | --- | ---: | --- |
| P1 | 关卡标题与路线选择 | 122 | P1 字库、容量与运行路线尚未进入独立 profile，当前还缺 36 个字符 |
| P1 | 开场／资料库世界史滚动文本 | 28 | 全量中文断行未完成，当前还缺 43 个字符 |
| P1 | 前五关开场、黑屏字幕与对话 | 1,833 | ISO 静态全量回读已通过，当前精确候选仍待运行验证 |
| P1 | 其余内嵌设置、编成与提示文本 | 275 | 仍是上游 unknown 聚合，必须先按可见界面继续拆分 |
| P1 | 后期专用指令与合神提示 | 2 | 英语专名需要人工确认 |
| P2 | 零件、技能、能力、精神与武器数据库 | 1,250 | 当前追加式字库容量不足 |
| P2 | 战斗退场台词 | 297 | COMPDATA writer 和触发路线矩阵均缺失 |

世界史 28 条已有译文和定长 writer 基础，但只验证过一条 canary；完整滚动画面
必须重新进行中文断行，并在起点、中段和结尾分别检查。前五关 1,833 条已写入
现有候选并通过静态回读，但不能据此推导每个开场、黑屏字幕或战场触发都已在
PCSX2 中出现。

## 4. 当前发现的结构缺口

### 4.1 动态人物和机体名

当前菜单语料主要覆盖 SLPS 与 COMPDATA 的通用菜单文本，不能代表人物／机体
显示名已经结构化导出。审计器已在真实 COMPDATA 解码流上固定三个 hash-only
探针：

- 女主人公显示名；
- 小队长显示名；
- Vargora 01 机体显示名。

三处 offset、终止长度和原文 SHA-256 都精确匹配，但专用记录 parser、稳定 ID、
译文语料和 writer 尚未实现。探针只证明定位没有漂移，不证明整个名称表的记录
尺寸、索引关系或可增长空间。

### 4.2 信息页图片文字

通用 TIM2 writer 已能对真实 KVMDATA fixture 做 byte-identical no-op，
但人物／机体／武器信息页的具体 TIM2 记录尚未逐屏归属，也没有中文 atlas。
上游 ASM 中存在信息页布局研究，只能作为研究证据；它不是当前中文候选的
writer，也不能替代本项目自己的前像、差异和运行门禁。

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
4. **当前下一步：**实现 COMPDATA 动态人物／机体名的完整记录 parser、
   稳定语料和定长或搬移
   writer；用三个现有探针作为 freshness gate。
5. 通过运行时纹理转储和离线预览，把人物／机体／武器信息页 atlas 精确映射到
   archive/member/record/picture，再制作中文图像。
6. 合并标题 TIM2、P0 字库、P0 文本、动态名和前五关 STAGE；只从同一个
   profile 构建一张候选 ISO。

每一步都先建立可失败的门禁和最小 fixture，再扩展场景数；不直接修改
`work/` 中间产物作为生产输入。

## 6. 验证分层

### S0：选择与输入

- selector 条数、稳定 ID、source hash 和译文决策精确；
- 运行时 token 不计入字形需求；
- 所需字符全部可编码、glyph 非空且风格统一；
- 动态探针和图片证据 manifest 未漂移。

### S1：component writer

- 原版成员 SHA-256 与 SurfaceSpec 前像一致；
- 所有新文本可重读，指针、HI/LO、终止符和对齐一致；
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
