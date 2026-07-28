# 正式生产流水线

状态：E1 最小纵向切片已实现。当前 `canary-menu` 通过
`SurfaceSpec + corpus/fixtures + codebook + BuildProfile` 进入原有、已验证的
canary writer；技术 fixture 与正式 `corpus/zh` 译文已经分离。

本文规定当前可运行入口，也规定后续菜单、摘要和剧情 writer 必须接入的输入
契约。字段设计的完整方向见 `ENGINEERING_PLAN.md`；本文只描述已经实现、可以
执行和测试的部分。

## 1. 数据流

```text
固定原版 SLPS/VT1 + 固定上游码表
                  |
                  v
          BuildProfile 选择集
             /      |       \
            v       v        v
     SurfaceSpec  corpus/zh 或 fixtures  codebook
            \       |        /
             v      v       v
       profile reconciliation
                  |
                  v
       原版 surface 解码/哈希前像
                  |
                  v
      编码、字形、定长和布局门禁
                  |
                  v
       work/build/<profile>/components
                  |
                  v
       build/iso/<profile> -> PCSX2/PINE/截图
```

`config/canary/minimal-slps-font.json` 只保留 E0 构建环境、原版输入、
rasterizer、字库段和 golden 输出。生产语义来自下面四类文件。

## 2. 四类生产输入

### 2.1 SurfaceSpec

当前实例：`config/surfaces/menu-slps-opening.json`

必需事实：

- `surface_id`：渲染/写回 surface 的稳定 ID；
- `source_member`：原版容器成员；
- `record.entry_id`：和中文语料连接的稳定记录 ID；
- `record.source_text_sha256`：日文原文的 UTF-8 SHA-256，不保存第二份原文；
- `layout.offsets`：原版内写回位置；
- `layout.encoded_size_with_terminator`：包含终止符的分配大小；
- `codec_profile`、`render.profile`：编码和渲染语义；
- `writer.kind` 及其定长要求；
- `runtime_fixture`：运行证据应覆盖的场景。

地址只允许由 SurfaceSpec 持有。writer、中文语料和 PINE 验证器不得再各自复制
同一 offset。

### 2.2 中文语料

正式翻译实例：`corpus/zh/summary.json`

技术 canary 实例：`corpus/fixtures/menu-canary.json`

每条记录只保存：

- `id`；
- `source_text_sha256`；
- `translation`；
- `editorial_status`；
- `glossary_refs`（正式翻译批次必需）；
- 可选 `notes`。

`corpus/zh` 不重复提交日文正文。技术 fixture 不计入翻译覆盖率，也不能作为
术语或编辑质量的事实源。v1 的来源集合与日文聚合哈希由
`corpus/releases/v1.json` 固定。

当前 profile 支持：

```text
todo < draft < reviewed < final
```

profile 的 `minimum_editorial_status` 是构建门。运行验证是证据属性，不在修改
字体、writer 或 ISO 后自动沿用为新的编辑状态。

### 2.3 Codebook

当前实例：`config/encoding/codebook.json`

每个可编码中文字符必须有显式 assignment：

- 唯一 assignment ID、字符、两字节 code 和 glyph index；
- `mapping=standard`，并满足原版 `standard_glyph_index(code)`；
- `status=assigned`；
- 字体 raster 三层 SHA-256；
- allocation owner、依据和空白前像。

未登记 code、空白 glyph 和“码表没有引用”的位置都不是自动可用空间。
BuildProfile 只能选择 `assigned` 项；选了但译文未使用的 assignment 也会失败。

### 2.4 BuildProfile

当前实例：`config/build-profiles/canary-menu.json`

profile 只做显式选择：

- SurfaceSpec 集合；
- 中文语料源；
- codebook 及 assignment ID；
- 最低编辑状态；
- 必须满足的 gate 名称。

构建报告把这份选择投影为 `production_inputs`，静态与运行证据因此可以回指相同
输入，而不把某个本地 `work/` 文件当作事实源。

## 3. Fail-closed reconciliation

`tools/srwz/project.py` 和 `tools/validate_build_profile.py` 当前拒绝：

- profile 或其引用路径逃出项目根目录、缺失或 schema 不受支持；
- 重复 surface、translation、assignment、字符、code 或 glyph；
- SurfaceSpec 与中文记录的 source hash 不一致；
- 中文记录包含第二份 `source_text`；
- 编辑状态低于 profile 门；
- 未登记或非 `assigned` 的 codebook 项；
- code 与 glyph 公式不一致、code 低字节为 `00`；
- 与固定日文码表冲突的 code 或重复已有字符；
- 无法编码、定长不符或选中却未使用的字形。

canary writer 另从固定原版 SLPS 解码 source，验证：

- 实际解码长度等于 SurfaceSpec allocation；
- 实际日文文本 SHA-256 等于 SurfaceSpec；
- 多 offset surface 的原文一致；
- 原始编码字节与写回前像一致；
- 替换前后 width class 一致；
- 只有登记 glyph、SLPS 文本和 VT1 offset 表发生允许的变化。

## 4. 当前命令

先验证所有生产输入，不读取 ISO：

```bash
python3 tools/validate_build_profile.py
```

再从固定原版成员重建同一个 E0 golden：

```bash
python3 tools/fetch_canary_font.py
python3 tools/build_static_canary.py --force
```

继续构建和验证 ISO：

```bash
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_canary_iso.py
```

PCSX2 已启动当前候选后，PINE 验证器也从同一个 BuildProfile 取得 codebook、
译文和 surface offset：

```bash
python3 tools/verify_pcsx2_font_runtime.py --force
```

单元与结构门：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

### 4.1 节子路线前五关

当前受限生产切片只选择 STAGE 001～005，不包含 006，也不把关卡标题菜单算进
剧情正文范围。构建顺序如下：

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

最终 ISO 位于 `build/iso/first-five/srwz-first-five.iso`。最后一条命令不读取
组件目录中的 STAGE 数据，而是从最终 ISO 自身读取 SLPS、HB 和 STAGE，重新
读取 206 项 offset、解压前五个块，并把 1,833 条正文、条件和说话人逐 ID
比对中文语料。

字体源由 `config/fonts/lxgw-neo-xihei-screen.lock.json` 固定到明确版本、提交、
字体 SHA-256 和 IPA 许可证。`config/encoding/first-five-allocations.json`
是追加式分配账本：已分配字符不会因译文删改而换码，退役字符保留槽位，新字符
只能追加。当前 638 个已登记槽位中 630 个在用、8 个退役，安全候选还剩 12 个。
构建另把前五关译文使用的 806 个原字库可达汉字用同一字体重绘；连同自定义
码位，共登记 1,436 个 glyph assignment，其中空格槽为预期 no-op。假名、原有
拉丁字符、既有可达标点、控制符及本切片之外的字形保持原样。
默认栅格字号为 22pt；`config/fonts/first-five-font.json` 另把截图确认视觉
偏小的“班”固定为 22.1pt。该最小光学校正只补回 22pt 取整时丢失的一列像素，
不增加 20px 栅格高度；它保留原码位和 glyph 槽位，并随每字的 point size 与
raster hash 一同写进 proposal 和构建报告。

下面的诊断是正式通过门：

```bash
python3 tools/audit_first_five_font_coverage.py --force
```

固定码表中 121 个原本无法由 renderer 解析到 glyph 的字符，现已通过追加式
override 进入游戏原生双字节标准分支。普通 ASCII 也分配双字节 glyph，只有
`$n/$F` 玩家名占位符保留原始字节，因此不需要采用无许可证上游的 ASCII ASM。
当前报告的 renderer 不可达字、普通一字节 ASCII、可达汉字字体混用均为 0。
扩容只追加原标准公式支持但固定表未使用的 `0x85xx` 码位，不搬移扩展表。

P0 UI 不修改上述 first-five 账本或组件，而是由
`config/encoding/ui-p0-allocations.json` 以 hash-locked base registry
追加九个字符，并由 `config/fonts/ui-p0-font.json` 继承同一字体源、栅格器和
“班”光学校正。独立候选构建和回读命令见
`docs/UI_COVERAGE_TEST_PLAN.md`。当前候选为 1,454 个 assignment，VT1 大小
不变，462 条 P0 文本的 renderer 缺字与原版汉字混用均为 0。

`config/ui-writeback/ui-p0-slps-fixed.json` 在该字体组件上建立第一层真实
SLPS 写回。它只选择含终止符后能装进所有原 span 的条目：

```bash
python3 tools/build_ui_p0_fixed_slps.py --force
python3 tools/verify_ui_p0_fixed_slps.py --force
```

当前确定性 SLPS 组件记录 101 条 byte-exact no-op，并将其余 317 条写入
378 个去重目标；全部 418 条均覆盖。所有目标可重读，指针、MIPS HI/LO、
非目标字节和解压字库哈希均不变。44 条 P0 COMPDATA 文本由独立 profile
处理。

COMPDATA 第一层由 `config/ui-writeback/ui-p0-compdata-fixed.json` 驱动：

```bash
python3 tools/build_ui_p0_fixed_compdata.py --force
python3 tools/verify_ui_p0_fixed_compdata.py --force
```

44 条中 3 条为原字节已满足决策的 no-op，41 条完成原位写回，无 overflow。
压缩成员使用原生 prefix-preserving suffix 重编码，保留 128,781 字节压缩
前缀并精确回解；输出增长 2,060 字节。SLPS 与 COMPDATA 两项组件结果都不能
单独当作组合 ISO 或 PCSX2 验收。`ui-p1-core` ISO profile 已显式处理最终
COMPDATA 的累计增长和后续成员 LBA 位移；运行验收仍是另一层证据。

COMPDATA 动态人物／机体名称由独立结构配置和语料批次叠加在上述静态组件上：

```bash
python3 tools/parse_srwz_display_names.py --force
python3 tools/build_ui_p0_display_names.py --force
python3 tools/verify_ui_p0_display_names.py --force
```

完整 parser 输出 3,147 个稳定字段 ID：933 条人物记录的 2,799 个字段，以及
808 条机体记录引用的 348 个唯一名称槽。提交清单只保存结构和聚合哈希，带
日文原文的完整解析留在 `work/parsed/`。首批
`corpus/zh/display-names/p0-opening.json` 选择 45 个已审校字段，writer
禁止修改人物 ID、机体指针和非目标字节，并要求所有文本在原 allocation 内
终止。组件已完成压缩流重编码和精确回解，并作为 `ui-p1-core` 的 COMPDATA
唯一来源进入组合 ISO；这仍不构成 PCSX2 运行证明。

### 4.2 世界史滚动文本布局

`config/summary/world-history-layout.json` 锁定真实 SLPS、MTV_PROS、上游码表、
语料 release 和当前 UI P0 字库清单。检查模式不会改写语料：

```bash
python3 tools/reflow_world_history.py --force
```

排版器以人工换行和段落缩进为优先事实，只对超过 22 格的行自动重排；术语、
ASCII 词组和中文标点禁则不会被拆开。MTV_PROS 中三个跨记录连续组不能按普通
段落处理，因此会在保持完整逻辑正文的同时，按每条原始字节 allocation 求解
新的记录边界。当前 28 条共 146 行，14 个空行与原版一致，最大宽度 22 格，
全部定长记录 overflow 为 0。

这项门禁不分配字形。当前 28 条仍为 `draft`，相对 UI P0 字库缺 41 个字符：
27 个未映射、14 个在码表中但原 glyph resolver 不可达；只剩 3 个合法安全
候选槽，短缺 38 个。独立 `ui-p1-summary` profile 已继承 P0、补齐这 41 字并
对 490 条选择取得零缺字离线结果。随后
`config/summary/world-history-component.json` 已把 28/28 条写入完整 MTV_PROS：
12 个文本块执行 changed-suffix 重编码，两个无文本块 byte-exact，14/14 块
解码往返且独立全文重读一致；SLPS 只改变 MTV_PROS offset 表，VT1 与 P1
字库组件一致。隔离 ISO 已完成 66 成员静态容器校验、三项替换独立 UDF
回读并固定最终 SHA-256；raw-trail 新类别和滚动运行状态仍为 `not_tested`。
只有人工审阅报告后才能运行 `--apply`，再次取得零
差异后才可用 `--refresh-manifest` 更新 `manifests/world-history-layout.json`。
该布局清单证明布局和相对 P0 的容量需求，不证明完整中文组件、ISO 或滚动
起点／中段／结尾的实机效果。

组件的可重复入口为：

```bash
python3 tools/build_ui_p1_world_history.py --force
python3 tools/verify_ui_p1_world_history.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-p1-world-history-build.json
python3 tools/verify_ui_p1_world_history_iso.py --force
```

component 提交门禁是 `manifests/ui-p1-world-history-validation.json`。
隔离 ISO 提交门禁是
`manifests/ui-p1-world-history-runtime-validation.json`：它已固定 66 个成员、
63 个未替换成员逐字节一致、三项替换独立 UDF 回读、DVD/NSR02 和最终 ISO
SHA-256；PCSX2 滚动起点／中段／结尾及 raw-trail 新类别仍未验收。

### 4.3 UI P1 core 组合

`config/ui-integration/p1-core.json` 不重新实现各 domain writer，而是锁定并
组合已经独立验证的五层输入：

- 标题四项中文 TIM2；
- P0 统一字库和 418 条固定 SLPS 文本；
- 44 条固定 COMPDATA 文本及其上的 45 个开场动态名称字段；
- P1 统一字库；
- 28 条世界史及其 MTV_PROS。

SLPS 不是按“最后一个文件覆盖前一个文件”合并。集成器以 P0 字库 SLPS 为
共同基线，提取 P0 菜单组件的 2,659 个变化字节，并要求它们与 P1 字库、
MTV_PROS offset 表修改零重叠后才应用。标题层只替换
`VT1 chunk 6 / record 1`，13 个非标题 chunk 必须 byte-exact；重压缩后
SLPS 中的 VT1 offset 表必须重新读取一致。最终还会从组合 SLPS/MTV_PROS
独立重读全部 28 条文本。

可重复入口为：

```bash
python3 tools/build_ui_p1_core.py --force
python3 tools/verify_ui_p1_core.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-p1-core-build.json
python3 tools/verify_ui_p1_core_iso.py --force
```

component 清单是 `manifests/ui-p1-core-validation.json`。静态 ISO 清单是
`manifests/ui-p1-core-runtime-validation.json`：镜像大小为
3,758,456,832 字节，SHA-256 为
`5f558ae794dec6d2e95bf56f391b5a0789eba78f4c330aa441a935b13973891b`；
66 个成员中 62 个未替换成员逐字节一致，SLPS、VT1、MTV_PROS 和 COMPDATA
四项替换均由 UDF 独立回读。该 profile 不包含 first-five STAGE/HB，也没有
信息页 atlas；PCSX2 标题、玩家设置、幕间、信息页、战场、搜索和世界史路线
全部保持 `not_tested`。

### 4.4 UI atlas 映射 canary

图片文字尚未进入中文生产 profile。为避免在场景归属不明时先制作整张中文图，
当前有两个互相隔离的可逆定位实验：

- `config/canary/tim2-kvm2-info-map.json`：chunk 2 顶行 `SHIP`；
- `config/canary/tim2-kvm6-intermission-map.json`：chunk 6 顶部幕间标题。

两者都只把 mask 内非背景像素替换为原图已有颜色，并显式登记必须保持的背景
RGBA 集合。通用入口接受对应配置；信息页默认配置可直接运行：

```bash
python3 tools/build_ui_atlas_map_canary.py --force
python3 tools/verify_ui_atlas_map_canary.py --force
python3 tools/build_canary_iso.py \
  --config config/iso/ui-info-atlas-map-canary-build.json
python3 tools/verify_ui_atlas_map_canary_iso.py --force
```

component 门证明 299 个逻辑像素变化全部在 mask 内、185 个 archive byte
变化、TIM2 header/CLUT/padding 和其他 chunk byte-exact，完整 KVMDATA 等长。
ISO 门只接受这一项 replacement；固定结果有 66 个成员、65 个未替换成员、
零 LBA 位移和独立 UDF 回读。两级清单分别为
`manifests/ui-info-atlas-map-canary-validation.json` 与
`manifests/ui-info-atlas-map-canary-runtime-validation.json`。

幕间配置同样运行四步入口并显式传入
`config/canary/tim2-kvm6-intermission-map.json` 与
`config/iso/ui-intermission-atlas-map-canary-build.json`。其 component
改变 803 个逻辑像素／509 个 archive byte；ISO 有 65 个未替换成员、零 LBA
位移，SHA-256 为
`dafe4737f797b611e02a0dcf68096a40e9b3c61ae4fa98d979b19a00ce0ca0df`。
两级清单使用 `ui-intermission-atlas-map-canary` 同名路径。

两个 profile 的状态都有意保持
`static_mapping_iso_validated_runtime_not_tested`。只有同一 ISO 的目标页面截图
显示相应标签消失，且 PCSX2 texture dump 精确匹配各自 299／803 像素集合，
才可登记正式运行映射。它们不拥有译名、中文 atlas 或 `ui-p1-core` 集成结论。

菜单文本中的 `%s` 属于游戏运行时格式 token。`encode_text()` 即使收到完整
ASCII glyph override，也必须原样写出 `%s` 的 ASCII 字节；翻译审计同时要求
源文和译文的格式 token multiset 完全一致。这个门禁不能用“最终显示看起来
像 `%s`”代替。

中文布局命令必须以检查模式返回零改动；它将日文原行形视为可参考的语义候选，
而不是强制行数。当前规则按 24 个 glyph cell、最多 3 行重排，`$n/$F` 按
运行时最长 6 格预算，术语、标题和 ASCII 词组不可拆分，续行不得以闭标点或
语气助词开头。1,711 条正文由 3,124 行降为 2,160 行，只有 4 条保留三行。

语言质量命令只覆盖 STAGE 001～005 的 1,711 条正文。它在写回前阻止假名残留、
结构占位符漂移、标点结构错误、超过 24 字符或 3 行的显示串和没有显式说明的同源异译；
当前 4 组同源语境差异涉及 14 条记录，均以“跨关同源”备注说明，硬错误为 0。
这项机械检查不能替代人工逐句校对。

上游英语审计严格验证相邻上游仍是固定提交且工作树干净。当前 001～005 XML
没有直接英语译文；工具只将其他已英译关卡中日文完全相同的句子写入
`work/review/first-five-upstream-english-reference.tsv`，并明确标为跨关
参考。它用于发现语义可能性，不把上游英文当官方术语，也不把短句的异关语气
自动套回本关。

验收边界必须分开表述：上一字体候选曾在 PCSX2 v2.6.3 通过 ISO 启动、完整
字库解压和无 TLB miss 验证；STAGE 001 的中文剧情截图也来自更早候选。这些
证据不能沿用到当前 LXGW 字体 ISO。STAGE 001～005 当前均通过最终 ISO 静态
回读、解压和重解析，但当前镜像尚未运行 PCSX2，更不能表述为五场战斗已完整
游玩。完整清单见 `manifests/first-five-validation.json`。

## 5. 新增一个 surface 的顺序

1. 从固定原版解析结果确认实际读取源、稳定 ID、位置、allocation、codec 和
   render path。
2. 新建 SurfaceSpec；只登记已证实的事实，未知语义保持未知。
3. 在 `corpus/zh/<domain>.json` 增加同 ID 和 source hash 的中文决策。
4. 对所有新字符先完成 codebook allocation、字形锁和冲突/活性证据。
5. 将 surface、语料源和所需 assignment 加入一个小 profile。
6. 先运行 profile validation，再运行对应 component writer。
7. 检查 component diff、归档重读和 ISO 布局。
8. 为该 surface 建立独立 PCSX2 fixture；运行时内存一致和实际可见截图分别
   验收。

不得通过复制 canary 配置、在脚本中硬编码 offset，或直接修改 `work/` 输出来
新增汉化内容。

## 6. 当前边界

E2 已把 SLPS 菜单、MTV_PROS 摘要和 STAGE 剧情接入正式
SurfaceSpec/corpus/codebook/profile，并生成隔离 component manifest 和
PCSX2 fixture。`canary-complete` 只组合这三个已登记 surface，不代表数据库、
剧情或全游戏已经可批量写回。

此外，节子路线 STAGE 001～005 已形成一个边界明确的生产候选：全部 1,833 条
正文、条件和说话人已写回，630 个在用自定义码位与 806 个原有可达汉字已统一
使用固定的 LXGW 字体；VT1 与所有 ISO 成员 LBA 保持原值，最终 ISO 回读及
renderer 覆盖验证通过。当前镜像的 PCSX2 验证、第 2～5 关完整玩法回归、关卡
标题菜单和后续关卡仍不在完成声明内。

`relocate_menu_texts_to_pool()` 已提供通用 SLPS/COMPDATA 普通 pointer 与
MIPS HI/LO 写回门禁。P0 的 462 条静态菜单文本当前都能在原 span 内覆盖，
因此没有为它们虚构池区。标题、P0 文本、开场动态名、P1 字库和世界史已进入
同一个静态验证的 `ui-p1-core` ISO；后续 P1/P2 只有出现真实增长项时才登记
池区。E3 还需完成：

- 全量 extraction freshness 与双向 reconciliation 的规模化运行；
- 扩展 COMPDATA 动态人物／机体名的全量审校语料；当前只完成开场 45 个字段；
- 用已锁定的 `SHIP` canary 完成人物／机体信息页 atlas 运行归属，再制作中文
  atlas、把前五关 STAGE/HB 合并到候选并完成逐屏 PCSX2 路线；
- 全量 STAGE arena policy 和通用 VT1 writer；
- offline render oracle、coverage ratchet 和 clean-copy deterministic build。
