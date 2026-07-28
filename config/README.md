# 配置与事实源

`config/` 同时包含不可漂移的外部锁和中文生产输入。新字段必须先确定唯一
所有者，不得为了某个 CLI 方便而复制一份可修改事实。

| 路径 | 所有权 |
| --- | --- |
| `upstream.lock.json` | 固定上游 Python 快照及授权/来源边界 |
| `toolchain/`、`fonts/` | 第三方工具、字体来源、版本和哈希 |
| `surfaces/` | 原版成员、稳定 entry ID、地址、allocation、codec/render/writer |
| `display-names/` | COMPDATA 人物／机体名称表几何、固定前像和结构 ratchet |
| `encoding/codebook.json` | 中文字符到游戏 code/glyph 的唯一分配账本 |
| `build-profiles/` | 构建选择集、最低编辑状态和必需 gates |
| `ui-scenes.json` | UI 场景 selector、优先级、运行路线、容量 ratchet 和动态名称 hash-only 探针 |
| `ui-embedded-scenes.json` | 将延期的 275 条 SLPS embedded UI 零遗漏／零重叠拆成 22 个静态屏幕候选；登记 fixture、路线、截图点和晋级门，不直接选择生产写回 |
| `runtime/ui-test-matrix.json` | 选定 UI 场景到精确 ISO、原生存档 fixture、截图点和运行证据门的绑定；不保存存档或截图 |
| `ui-writeback/` | UI 文本写回选择策略、锁定输入、容量 ratchet 和输出位置；不包含游戏字节 |
| `ui-integration/` | 已验证 UI 组件的所有权、三方合并、依赖哈希、输出 golden 和运行边界 |
| `summary/` | MTV_PROS 世界史中文断行、原 allocation、字库容量和运行边界 |
| `assets/ui-atlas-candidates.json` | 信息页、战场、商店、幕间和编成文字 atlas 的离线候选及运行映射门禁 |
| `canary/` | 验证切片的原版输入、构建参数和 golden；文本 canary 不拥有译文/码位，TIM2 探索 profile 暂存固定视觉标签 |
| `iso/` | PS2 DVD 容器工具链、profile workspace、最终输出和布局锁 |
| `patches/` | ASM/二进制前像、允许差异和写入所有者 |
| `assets/` | 图片归档成员、压缩标志、SLPS offset 表范围和中文图集生产参数；不包含游戏字节或译文 |

`ui-scenes.json` 可以实时读取下游动态名称 writer 的状态和覆盖计数，但提交的
`ui-surface-inventory` 只投影这些语义 ratchet，不回写下游 manifest 的整文件
哈希。否则会形成“场景清单 → 字库 → COMPDATA writer → 场景清单”的哈希环，
导致每次合法重建都产生新的 freshness 漂移；详细本地报告仍保留下游哈希。

`ui-embedded-scenes.json` 是 production selector 之前的研究层。22 组共同
精确覆盖 `menus/extended-embedded-dialogs` 的 275 条决定，审计时绑定
`work/corpus` 中真实 SLPS target、普通指针和 MIPS HI/LO 引用。组名来自静态
语义聚类，因此状态统一为运行归因待定；只有取得登记 fixture、画面证据并把
混合组继续拆净后，单组 ID 才能晋级到 writer 配置。`writeback_readiness`
另锁定当前 P2 字库 proposal 和真实 SLPS span，只量化整组编码、容量和共享
owner 闭包；它能筛出 fixed-span 首选批次，但不拥有实际 writer 输出。

`runtime/ui-test-matrix.json` 不改变上述生产选择。它锁定
`ui-scenes.json`、当前 P3 综合 UI／前五关／atlas 测试镜像及五张隔离中文
atlas 候选的提交清单；两个已晋级的 fresh-boot 分区另通过
`scene_extensions` 锁定 `ui-embedded-scene-map.json`，不会反向改写基础
14 类 inventory。矩阵为
每个运行用例登记 fixture 状态、到达步骤、截图点和证据要求。存档必须位于
被忽略的 `work/runtime/ui-fixtures/`，只有原生 `.ps2` memory card 和 SHA-256
都登记后才能从 `not_acquired` 晋级；已有 `.p2s` savestate 不会被自动当作
可替代证据。用例只有在 `manifests/runtime/ui-cases/` 下存在通过校验的
hash-only receipt，并由矩阵锁定 receipt SHA-256 后，才允许把
`runtime_status` 改为 `passed`。

每类生产 JSON 都必须显式声明自己的 `schema_version`，由对应 loader
fail-closed 校验；不同领域的 schema 独立演进，不能假设全仓库共用同一版本。
SurfaceSpec、BuildProfile 和语料当前使用 v1，前五关 ISO 构建配置使用 v2。
最小端到端实例是
`build-profiles/canary-menu.json`；E2 还包括 `canary-summary.json`、
`canary-story.json` 和组合选择 `canary-complete.json`。执行：

```bash
python3 tools/validate_build_profile.py
python3 tools/build_complete_canary.py --force
```

详细字段、数据流和新增 surface 步骤见
`docs/PRODUCTION_PIPELINE.md`。
ISO 的 `rom/work/build` 所有权见 `docs/ISO_DIRECTORY_LAYOUT.md`。

节子路线前五关的追加式码位账本、字体参数和 ISO 配置分别位于
`encoding/first-five-allocations.json`、`fonts/first-five-font.json` 和
`iso/first-five-build.json`。码位只允许追加，退役槽不复用；字体与工具来源
由相邻 lock 固定，当前候选的精确组件和镜像哈希只记录在
`manifests/first-five-validation.json`。

P0 UI 字库通过 `encoding/ui-p0-allocations.json` 和
`fonts/ui-p0-font.json` 增量引用并锁定上述基线，不修改 first-five 账本。
九个新增汉字只追加到组合 registry，栅格器继续由 first-five 字体配置单点拥有；
离线候选和 coverage 结果见 `manifests/ui-p0-font-validation.json`。
世界史 P1 字库通过 `encoding/ui-p1-summary-allocations.json` 继续继承 P0，
只追加相对 P0 缺失的 41 字；`fonts/ui-p1-summary-font.json` 单独锁定普通
renderer 的测量／glyph 解析指令窗口与 `987F=试` 运行先例。合法 Shift-JIS
安全候选和 raw-trail 公式可寻址空隙必须分栏统计；后者不会因为进入离线
proposal 就自动升级为运行安全。结果见
`manifests/ui-p1-summary-font-validation.json`。
第一层 P0 SLPS 写回由 `ui-writeback/ui-p0-slps-fixed.json` 锁定；它只允许
原 span 内写回，禁止修改指针；当前 P0 无增长文本。
`ui-writeback/ui-p0-compdata-fixed.json` 对压缩 COMPDATA 采用相同 span
契约，并锁定 preserve-prefix suffix 重编码参数和成员增长 ratchet；当前
P0 同样无 overflow。
`ui-writeback/ui-p0-display-names.json` 在该静态组件之上选择
`corpus/zh/display-names/p0-opening.json` 的 45 个已审校字段；只允许原
allocation 内写回，人物 ID、机体指针和非目标字节均不可修改。完整结构和
组件结果分别锁定在 `manifests/display-name-structure.json` 与
`manifests/ui-p0-display-names-validation.json`。
`display-names/researched-coverage.json` 则在完整结构上只接受 v1 术语库
中 `researched` 的精确源词匹配，排除上述 45 项及一源多译冲突；它生成
被忽略的 2,800 行审核 TSV，并把 1,262 个候选、21 个编码缺字、33 个
renderer 缺字、29 个统一重绘汉字和零定长溢出收敛为不含日文的提交清单。
其中 `娅杰艾贾` 四字复用 `encoding/first-five-allocations.json` 中已登记
但退役的 code/glyph，`encoding/ui-p2-display-name-allocations.json`
只新增其余 29 个 allocation；P2 组合账本余 19 槽。
`fonts/ui-p2-display-names-font.json` 将这 33 字和 29 个重绘字形组成统一
renderer，`ui-writeback/ui-p2-display-names.json` 再把开场 45 项与
researched 1,262 项合并为 1,307 项 fixed-allocation COMPDATA 组件。

`summary/world-history-layout.json` 锁定 28 条世界史的真实 MTV_PROS 输入、
22 格显示宽度、14 个原版空行和跨记录定长分配策略。它只允许生成布局报告和
byte-free 清单，不拥有字形分配，也不把布局通过升级为组件、ISO 或运行验收。
`summary/world-history-component.json` 在已验证 P1 SLPS/VT1 上拥有完整
MTV_PROS 离线写回：锁定 28 条译文、布局清单、字库清单、14 块 codec 策略、
输出哈希和运行边界；它不拥有 ISO 构建或 PCSX2 验收。
`iso/ui-p1-world-history-build.json` 只负责把该组件绑定到隔离 DVD 镜像；
静态容器证据见
`manifests/ui-p1-world-history-runtime-validation.json`，其中运行门禁仍保持
未通过。

`ui-integration/p1-core.json` 将已验证的标题 TIM2、P0 固定菜单、开场动态
名称、P1 字库和世界史组件合并为一个确定性候选。SLPS 菜单采用以 P0 字库
SLPS 为共同基线的三方字节补丁，必须证明与 P1／世界史修改零重叠；标题只
替换 VT1 chunk 6 的已登记 TIM2 record，并重写、回读 offset 表。输出只由
`iso/ui-p1-core-build.json` 放入 `ui-p1-core` 镜像；该 profile 不拥有
STAGE、信息页 atlas 或 PCSX2 运行结论。

`summary/world-history-p2-display-names-component.json` 复用 P2 字库写入同一
28 条世界史；`ui-integration/p2-researched-display-names.json` 合并标题、
P0 菜单、1,307 项动态名称、P2 字库和世界史。最终只由
`iso/ui-p2-core-build.json` 放入 `ui-p2-core` 镜像；四个 replacement、
两段 LBA 位移和镜像 golden 均固定，但运行状态仍为 `not_tested`。

`ui-writeback/ui-p3-fresh-boot-slps.json` 只从上述 22 组研究层选择两个
`fixed_span_ready` 的 fresh-boot 分区，共 23 条决定，并要求它们与完整
P2 core 的 SLPS 修改零重叠、每个写入偏移的 P2 前像精确、指针和解码字库
不变。`ui-integration/p3-fresh-boot-first-five-atlas-test.json` 再将这份
P3 UI 四成员与前五关 `HB/STAGE`、五图 suite 合成 7 成员测试组件；
`iso/ui-p3-fresh-boot-first-five-atlas-test-build.json` 是当前运行矩阵绑定
的综合 DVD。旧 P2 综合 profile 仍保留为可复建历史基线。

`assets/ui-atlas-suite-zh.json` 只在测试域内将五份已验证中文 atlas 对
原版 `KVMDATA.BIN` 的互不相交字节所有权合并；它不改变任何单图的
`runtime_mapping_pending`。五张隔离 ISO 继续是场景归因的唯一证据，综合
ISO 只减少逐屏测试时的候选切换。

`assets/archive-inventory.json` 由 `tools/srwz/assets.py` 独立执行严格 schema
检查：未知字段、重复 member、路径穿越、archive/direct 重叠、未知 storage
模式和非法上游提交都会失败。TIM2 外部工具选择尚未形成 lock；准入条件见
`docs/TIM2_TOOLCHAIN_ACCEPTANCE.md`。`canary/tim2-vt1-title-index.json`
固定已通过运行验证的 VT1 标题 index canary，`iso/image-canary-build.json`
固定其独立组件、ISO 路径和 golden hash；两者都不拥有正式图片译文。
`canary/tim2-vt1-title-zh.json` 登记标题四项中文、OFL 字体、ImageMagick
参数和 mask/output golden，`iso/title-menu-zh-build.json` 固定对应独立
ISO；这是当前首个坐标级 8-bpp 图片汉化 profile。
`canary/tim2-kvm2-info-map.json` 则固定信息页候选 chunk 2 的最小定位实验：
只擦除 `SHIP` mask 内的非背景像素，并锁定背景色集合、像素集合、完整
KVMDATA 输出和确定性 PNG 预览。
`assets/ui-info-atlas-zh.json` 在复建该定位前像后，从
`corpus/zh/ui-atlas/info-v1.json` 取得唯一受审译文；其余
`assets/ui-battle-command-atlas-zh.json`、
`assets/ui-bazaar-atlas-zh.json`、
`assets/ui-intermission-atlas-zh.json` 和
`assets/ui-formation-atlas-zh.json` 从
`corpus/zh/ui-atlas/core-menus-v1.json` 取得四条受审译文。五者都锁定
LXGW 字体、ImageMagick 版本、灰度 mask、原调色板 ramp 和输出哈希，并在
各自原 mask 内生成中文候选。译文本身只由 corpus 拥有，提交的 component
manifest 只保存哈希、坐标、计数和渲染参数。
`canary/tim2-kvm4-battle-command-map.json` 以同一契约固定 chunk 4 的
`COMMAND MENU` 战场候选。
`canary/tim2-kvm5-bazaar-map.json` 固定 chunk 5 的大号 `バザー` 商店候选。
`canary/tim2-kvm6-intermission-map.json` 以相同契约固定 chunk 6 顶部幕间
标题，分别保留透明黑与不透明黑背景。
`canary/tim2-kvm7-formation-map.json` 则固定 chunk 7 的 `新規編成`。
对应的
`iso/ui-info-atlas-map-canary-build.json`、
`iso/ui-battle-command-atlas-map-canary-build.json`、
`iso/ui-bazaar-atlas-map-canary-build.json`、
`iso/ui-intermission-atlas-map-canary-build.json`、
`iso/ui-formation-atlas-map-canary-build.json` 都只写入一个等长成员。
五个 `iso/ui-*-atlas-zh-build.json` 以相同容器约束分别绑定中文候选。
五项状态均为
`static_localization_iso_validated_runtime_mapping_pending`，都还没有运行
场景归属结论；旧定位配置不拥有译文，继续作为擦除前像和 mask 证据。
