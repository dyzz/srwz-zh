# 清单

这里保存可提交的校验信息，不保存原始游戏数据。

计划中的清单包括：

- 原版文件名、大小和 SHA-256；
- 上游提取结果的来源提交；
- 日文语料来源哈希；
- 中文字符到游戏编码槽位的稳定映射；
- 字体源文件、参数和生成产物哈希；
- 每次发布构建的输入与补丁哈希。

当前已有：

- `original-disc.json`：原版 ISO 和关键成员基线。
- `canary-iso-validation.json`：`mkps2iso` UDF/ISO9660 canary 镜像的成员
  内容摘要、两项替换哈希、独立 UDF 读取结果、PCSX2/PINE 完整字库解压
  哈希、开场文本内存哈希和 `SELECT SCENARIO` 实机渲染截图摘要；同时回指
  `canary-menu` 的 production inputs。
- `canary-summary-validation.json`：MTV_PROS 世界史定长 surface 的 profile
  reconciliation、suffix 重编码、SLPS offset 重读、隔离 ISO 和 PCSX2
  `测试。` 画面证据。
- `canary-story-validation.json`：STAGE 开场剧情增长文本的 allocation、
  pointer/HB 重读、隔离 ISO 和 Denzel 两行中文 PCSX2 画面证据。
- `canary-complete-validation.json`：三类 component/ISO lock、三条独立运行
  fixture，以及最终组合 ISO 的菜单、摘要和剧情加载 smoke。
- `codec-samples.json`：本地 codec 研究样本的 index、offset、大小和 SHA-256；不包含游戏字节。
- `iso-data-parse.json`：菜单、剧情、摘要和 VT1 字库段的解析计数、哈希及
  上游 XML 精确对照结果；不包含原文或解码字节。
- `font-analysis.json`：原版/上游候选字体段的哈希、已确认
  `24×24/4-bpp` glyph 契约、差异 glyph、原版普通/扩展 code→glyph 覆盖和
  候选码位统计；不包含字体字节。
- `corpus-export.json`：94,189 条本地语料导出的 domain/kind 计数和聚合哈希；
  日文 JSONL 留在 `work/`。
- `codec-encoder-validation.json`：clean-room 编码器对真实 STAGE、COMPDATA、
  MTV_PROS 和 VT1 流的往返及游戏运行时块语法统计；不包含编码或解码数据。
- `archive-rebuild-validation.json`：真实 STAGE/MTV_PROS 归档的重编码、对齐、
  decoded 往返和 offset 表 dry-run 聚合结果；不包含重建归档数据。
- `toolchain-validation.json`：两个固定 armips 官方源码版本各两次干净构建、
  官方 CTest、项目 ASM 双版本一致性，以及 SLPS/KVPDATA 严格差异审计摘要；
  不包含原版或补丁后二进制。
- `static-canary-validation.json`：无运行时 hook 的两字简体中文 canary、
  OFL 字体来源、空白槽位、raster 哈希、SLPS 等长文本修改和 VT1 第 2 段
  重编码/offset 重读结果；`production_inputs` 和 `profile_validation` 记录
  SurfaceSpec、中文语料、codebook、gates 及实际编码摘要；不包含原版或重建
  后的游戏字节。
- `asset-inventory.json`：14 个 SLPS offset 归档和 3 个直接成员的严格
  TIM2 数量、picture 格式、成员哈希、解码状态及上游 KVMDATA 差异块；不包含
  像素或游戏字节。
- `map-name-parse.json`：`MAP/MAPNAME.BIN` 的 256-byte 固定记录几何、
  195 条稳定 ID 计数和聚合哈希；日文正文只在 `work/`。
- `tim2-writeback-noop.json`：真实 `KVMDATA` chunk 5 的固定 4-bpp 布局、
  ImageMagick 版本、byte-identical no-op、视觉 RGBA 和完整 archive 前像结果；
  不包含 TIM2、CLUT、像素或重建归档字节。
- `image-canary-validation.json`：运行时纹理转储反查到
  `VT1 chunk 6 / record 1 / picture 0` 后的固定 8-bpp 索引 canary；
  记录 351 个索引替换、重压缩/offset/ISO 静态验证、PCSX2/PINE 标题画面和
  运行时纹理直方图证据；游戏字节和 PNG 只留在 `work/`/`build/`。
- `title-menu-zh-validation.json`：标题
  `START/LOAD/CONTINUE/LIBRARY → 开始/读取/继续/资料库` 的坐标级 PSMT8
  写回；记录固定字体/mask、12,514 个像素修改、重压缩与 ISO、两种光标状态
  截图，以及 PCSX2 转储纹理与离线预览逐像素一致的运行证据。
- `ui-info-atlas-map-canary-validation.json`：信息页离线候选
  `KVMDATA chunk 2` 的最小定位组件；只清除 `SHIP` 矩形，记录 299 个逻辑
  像素／185 个 archive byte 变化、TIM2 header/CLUT/padding、非目标 chunk、
  等长归档和确定性预览锁。状态仍是 `runtime_mapping_pending`。
- `ui-info-atlas-map-canary-runtime-validation.json`：把上述组件与只替换
  `KURODATA/KVMDATA.BIN` 的隔离 DVD 静态绑定；记录 66 个成员、65 个未替换
  成员、零 LBA 位移、独立 UDF 回读和精确 ISO SHA-256，并将 `SHIP` 截图缺失
  与同一 299 像素 texture-dump delta 登记为运行晋级双门。
- `ui-info-atlas-zh-validation.json`：在逐字节复建上述擦除前像后，从受审
  corpus 取得中文标签并在同一 `49×16` mask 内栅格化；记录 318 个新增文字
  像素、相对原图 421 个像素变化、183 个 archive byte 变化、字体／许可证、
  调色板 ramp、TIM2 回读、非目标 chunk 和等长 KVMDATA 门。状态仍是
  `runtime_mapping_pending`。
- `ui-info-atlas-zh-runtime-validation.json`：把中文信息页候选绑定到只替换
  `KURODATA/KVMDATA.BIN` 的独立 DVD；固定 ISO SHA-256、65 个未替换成员、
  零 LBA 位移和独立 UDF 回读，并要求目标页出现中文标签和同一 421 像素
  texture-dump delta 后才能晋级。
- `ui-battle-command-atlas-map-canary-validation.json`：chunk 4 战场候选的
  最小定位组件；只擦除 `COMMAND MENU`，记录 2,297 个逻辑像素、1,221 个
  archive byte、非目标 chunk 和等长 KVMDATA 门。
- `ui-battle-command-atlas-map-canary-runtime-validation.json`：把战场组件
  绑定到单成员、零 LBA 位移的隔离 DVD；固定 65 个未替换成员、独立 UDF
  回读和 ISO SHA-256，并将战场截图与同一 2,297 像素 texture delta 登记为
  运行晋级双门。
- `ui-bazaar-atlas-map-canary-validation.json`：chunk 5 商店候选的最小定位
  组件；只擦除大号 `バザー`，记录 2,197 个逻辑像素、1,210 个 archive
  byte、非目标 chunk 与等长 KVMDATA 门。
- `ui-bazaar-atlas-map-canary-runtime-validation.json`：把商店组件绑定到
  单成员、零 LBA 位移的隔离 DVD；固定 65 个未替换成员、独立 UDF 回读和
  ISO SHA-256，并将商店截图与同一 2,197 像素 texture delta 登记为运行晋级
  双门。
- `ui-intermission-atlas-map-canary-validation.json`：chunk 6 幕间候选的最小
  定位组件；只擦除顶部 `インターミッション`，保留透明黑／不透明黑背景和
  右侧箭头，记录 803 个逻辑像素、509 个 archive byte、非目标 chunk 与等长
  KVMDATA 门。
- `ui-intermission-atlas-map-canary-runtime-validation.json`：把幕间组件绑定
  到另一个单成员、零 LBA 位移的隔离 DVD；固定 65 个未替换成员、独立 UDF
  回读和 ISO SHA-256，并将幕间截图与同一 803 像素 texture delta 登记为运行
  晋级双门。
- `ui-formation-atlas-map-canary-validation.json`：chunk 7 编成候选的最小
  定位组件；只擦除 `新規編成`，记录 1,325 个逻辑像素、691 个 archive
  byte、非目标 chunk 与等长 KVMDATA 门。
- `ui-formation-atlas-map-canary-runtime-validation.json`：把编成组件绑定到
  单成员、零 LBA 位移的隔离 DVD；固定 65 个未替换成员、独立 UDF 回读和
  ISO SHA-256，并将编成截图与同一 1,325 像素 texture delta 登记为运行晋级
  双门。
- `ui-surface-inventory.json`：从真实语料、当前前五关字库和 COMPDATA
  动态名称结构确定性投影的 UI 场景摘要；固定 P0 的 462 条文本、九个缺字、
  12 个剩余候选槽、三槽余量和开场名称 writer 状态，并明确区分译文决策、
  writer、ISO 与运行状态。
- `ui-runtime-test-matrix.json`：把 14 类 UI 场景完整分成 10 类当前测试目标
  和 4 类显式延期，锁定 7 张精确 ISO、19 个逐屏用例、7 类 fixture、
  42 个截图点、6 个截图序列和 5 个 texture delta；信息页用例绑定中文候选
  及其 421 像素 delta，其余四项仍绑定擦除定位 canary。当前只有 fresh-boot
  fixture 就绪，六份原生 memory card 尚未取得，因此 19 个用例均保持
  `not_tested`；八个核心 UI 用例绑定精确 `ui-p2-core` ISO，清单不保存
  存档、截图或游戏字节。
- `runtime/ui-cases/*.json`：未来每个已通过用例的 hash-only receipt。receipt
  必须由 case-owned session probe、截图／序列、全部断言及可选 atlas
  texture delta 生成；矩阵锁定 receipt SHA-256，receipt 反向锁定排除运行
  状态和自身 receipt 字段的稳定 `matrix_plan_sha256`。当前没有任何此类
  通过清单。
- `ui-p0-font-validation.json`：在不改变 first-five 组件的前提下追加九个
  P0 UI 字符并统一重绘九个原版汉字；记录 1,454 个 assignment、VT1
  size-preserving 重压缩、SLPS offset 回读、462 条文本零缺字／零原版汉字
  混用和三槽余量。状态仅为离线通过，ISO 和运行验证仍待完成。
- `ui-p1-summary-font-validation.json`：继承 P0 字库并为 28 条世界史追加
  41 个字符、统一重绘 53 个既有汉字；记录 650 个合法 Shift-JIS 安全候选、
  86 个仅由原渲染公式证明可寻址的 raw-trail 空隙、38 个实际 raw 分配、
  490 条选择零缺字和 48 槽余量。指令窗口与既有 `987F=试` 运行先例均锁定，
  但 P1 组件本身及 `0xFD` 类仍为 `not_tested`。
- `ui-p1-world-history-validation.json`：在 P1 字库之上写入全部 28 条
  MTV_PROS 世界史记录；记录 12 个重编码文本块、两个 byte-exact 无文本块、
  14/14 解码往返、定长 allocation、SLPS 60 字节 offset 表所有权以及
  独立全文重读。该清单只拥有 component 证据。
- `ui-p1-world-history-runtime-validation.json`：把上述 component 与独立
  `ui-p1-world-history` ISO 绑定；记录 66 个成员、63 个未替换成员逐字节
  一致、三项替换独立 UDF 回读、DVD/NSR02 和固定 ISO SHA-256。滚动
  起点／中段／结尾及 raw-trail 新类别仍为 `not_tested`。
- `ui-p1-core-validation.json`：把标题中文 TIM2、P0 菜单 SLPS、开场
  45 个动态名称字段、P1 字库和 28 条世界史组合为同一 component；锁定
  2,659 个 P0 菜单修改字节、零 SLPS owner 重叠、13 个非标题 VT1 chunk
  byte-exact、世界史全文回读和四项最终输出。
- `ui-p1-core-runtime-validation.json`：把上述组合 component 与
  `ui-p1-core` DVD 镜像静态绑定；记录 66 个成员、62 个未替换成员、四项
  替换独立 UDF 回读、分段 LBA 位移、DVD/NSR02 和固定 ISO SHA-256。
  标题、玩家设置、幕间、信息页、战场、搜索和世界史逐屏运行仍为
  `not_tested`。
- `ui-p2-display-name-font-validation.json`：继承 P1 字库，为 researched
  名称新增 29 个 allocation、重新启用 `娅杰艾贾` 四个退役 assignment，
  并统一重绘 29 个原版汉字；1,262 个字段 renderer 缺字为零，余 19 槽，
  运行仍为 `not_tested`。
- `ui-p2-display-names-validation.json`：在固定 P0 COMPDATA 基线上合并
  开场 45 项和 researched 1,262 项；1,307 项中 1,213 项写入、94 项 no-op，
  人物 ID、机体指针和非目标字节不变，压缩流精确回解。
- `ui-p2-world-history-validation.json`：将 P2 名称字库与 28 条世界史合成
  SLPS／VT1／MTV_PROS 组件；保持世界史 allocation、14 块 codec 和全文
  回读契约。
- `ui-p2-core-validation.json`：把标题、P0 菜单、1,307 项动态名称、P2
  字库和世界史合并为四成员 component，锁定所有输入、所有权和输出 golden。
- `ui-p2-core-runtime-validation.json`：把 P2 component 静态绑定到
  `ui-p2-core` DVD；记录 66 个成员、62 个未替换成员、两段 LBA 位移、
  四项独立 UDF 回读和镜像 SHA-256。逐屏运行仍为 `not_tested`。
- `ui-p0-fixed-slps-validation.json`：在 UI 字库候选 SLPS 上记录 101 条
  byte-exact no-op，并写入 317 条／378 个去重目标；全部 418 条 P0 SLPS
  均覆盖，指针、MIPS HI/LO、非目标字节和解压字库哈希不变。ISO 和运行验证
  仍待完成。
- `ui-p0-fixed-compdata-validation.json`：44 条 P0 COMPDATA 中记录 3 条
  byte-exact no-op 和 41 条 fixed-span 写入；证明 28,100 个指针字节及
  非目标解码字节不变、suffix 重编码完整回解，并记录 2,060 字节成员增长。
  ISO 和运行验证仍待完成。
- `display-name-structure.json`：COMPDATA 的 933 条人物记录、2,799 个固定
  人物字段、808 个机体指针和 348 个唯一名称槽的完整结构清单；保存稳定 ID、
  前像、计数和聚合哈希，不保存日文名称或游戏字节。
- `display-name-researched-coverage.json`：排除开场 45 个已写回字段后，
  以 v1 术语库 `researched` 决定作精确源词传播；选择 1,262 个字段
  （1,221 人物／41 机体、307 个唯一源词），当前 P1 字库可直接覆盖
  1,166 个编码项；统一 renderer 有 33 个缺字（含 21 个编码缺字、
  5 个普通 ASCII 和 7 个原表不可达汉字）。其中 4 个复用已登记退役槽，
  29 个需要新 allocation，另重绘 29 个原版汉字，预计余 19 槽且零
  projected allocation 溢出。日文只在被忽略的审核 JSON／TSV；该清单
  只拥有选择结论，writer 和 runtime 状态由各自 P2 清单拥有。
- `ui-p0-display-names-validation.json`：在固定 P0 COMPDATA 组件上写入开场
  45 个已审校动态名称字段；证明人物 ID、机体指针和非目标字节不变、所有文本
  留在原 allocation、压缩流精确回解。ISO 和运行验证仍待完成。
- `world-history-layout.json`：28 条 MTV_PROS 世界史的 22 格中文断行、
  14 个空行、三个跨记录连续组和零定长溢出清单；相对当前 P0 字库记录
  27 个未映射字符、14 个 resolver 不可达字符、三个安全槽和 38 槽短缺，
  并保留 `not_tested` 运行边界，不包含原文或游戏字节。
