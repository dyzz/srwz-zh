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
- `compress-tool-static-analysis.json`：上游附带 native debug compressor 的
  哈希、函数地址、level 0–9 参数、独立模型压缩率和 `maximum` 工程边界；
  不包含反编译源码或游戏 payload。
- `compdata-maximum-size-validation.json`：P1 开场姓名、P2 researched 名称和
  P10 数据库三种历史超标 decoded payload 的 `maximum` 大小、哈希、71-sector
  余量、native/Python 等价门和 P0 解压 token 工作量；候选运行验证逐层进行。
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
- `ui-battle-command-atlas-zh-validation.json`、
  `ui-bazaar-atlas-zh-validation.json`、
  `ui-intermission-atlas-zh-validation.json` 和
  `ui-formation-atlas-zh-validation.json`：分别在上述擦除前像和 mask 内
  栅格化受审中文标签；相对原图锁定
  2,292／3,634／2,083／1,262 个逻辑像素变化，完整 KVMDATA 等长且非目标
  chunk 不变。四者均保持 `runtime_mapping_pending`。
- 对应四份 `ui-*-atlas-zh-runtime-validation.json`：分别绑定单成员、
  65 个未替换成员、零 LBA 位移的隔离 DVD，并锁定 ISO SHA-256。只有目标页
  出现中文标签且 texture dump 精确匹配各自原图 delta，才允许晋级。
- `ui-surface-inventory.json`：从真实语料、当前 P2 字库、COMPDATA
  动态名称结构和五份 atlas manifest 确定性投影的 UI 场景摘要；记录
  1,307 个已选名称、1,493 个剩余非空名称和各场景的哈希锁定图片候选，并
  明确区分译文决策、writer、ISO 与运行状态。
- `ui-embedded-scene-map.json`：把 `menus/extended-embedded-dialogs` 的
  275 条 SLPS 决定穷尽拆为 22 个静态屏幕候选；18 组／253 条是可见候选，
  两组／17 条混合诊断内容，两组／5 条要求先查代码引用。清单锁定每组的
  ID、target、普通 pointer、embedded HI/LO 所有权聚合哈希和运行路线计数，
  并以当前 P2 字库和真实 allocation 证明 13 组／123 条整组 fixed-span
  ready、5 组只缺六字、4 组共有七条 overflow；不保存日文原文、中文译文
  或游戏字节，22 组均仍为 `not_tested`。
- `ui-atlas-suite-zh-validation.json`：证明五份中文 atlas 对原版
  `KVMDATA.BIN` 的字节所有权互不重叠；组合后只改变 5,568 个归档字节，
  所有权外字节保持原样。该清单只拥有测试用 component，不拥有场景归因。
- `ui-p2-first-five-atlas-test-validation.json`：以完整成员组合 P2 UI、
  前五关 `HB/STAGE` 和五图 atlas suite，锁定 7 个成员、三类 owner 与输出
  golden；不携带游戏字节或译文。
- `ui-p2-first-five-atlas-test-runtime-validation.json`：把上述综合
  component 静态绑定到 66 成员 DVD；记录 59 个未替换成员、7 个 replacement、
  `+7/+42` 两段 LBA 位移、独立 UDF 回读和镜像 SHA-256。运行仍为
  `not_tested`，作为 P3/P4 候选的历史可复建基线。
- `ui-p3-fresh-boot-validation.json`：从 embedded scene map 只选择两个
  `fixed_span_ready` 的 fresh-boot 分区。23 条决定中 11 条 no-op、12 条写入
  32 个 target；SLPS 改变 124 字节／35 段，和 P2 core 修改零重叠，三个
  非 SLPS 成员及解码字库保持精确不变。
- `ui-p3-fresh-boot-first-five-atlas-test-validation.json`：以完整成员组合
  P3 fresh-boot UI、前五关 `HB/STAGE` 和五图 suite；锁定 7 个成员和三类
  owner，运行仍为 `not_tested`。
- `ui-p3-fresh-boot-first-five-atlas-test-runtime-validation.json`：把上述
  P3 component 静态绑定到 66 成员 DVD，固定 59 个未替换成员、7 个
  replacement、`+7/+42` LBA 位移和镜像 SHA-256
  `f16814461b353aae054a5e8634bf6c28d247d8bee2eee31a73e64e24b618d47b`。
  五张隔离 atlas 的场景映射证据仍必需；该镜像现作为 P4 的历史基线。
- `ui-p4-intermission-validation.json`：以 P3 SLPS 为精确前像，选择编成确认
  与战术状态指标两组 24 条决定；6 条 no-op、18 条写入 30 个 target，
  相对 P3 改变 408 字节／38 段，和既有修改零重叠。最终 SLPS SHA-256 为
  `1a822e1f503aeb73684f7fb9f336f50e880791f2c58c1a2c9311b5e1121bfd65`。
- `ui-p4-intermission-first-five-atlas-test-validation.json`：以完整成员组合
  P4 UI、前五关 `HB/STAGE` 和五图 suite，锁定 7 个成员与三类 owner。
- `ui-p4-intermission-first-five-atlas-test-runtime-validation.json`：把 P4
  component 绑定到 66 成员 DVD，锁定 59 个未替换成员、7 个 replacement、
  `+7/+42` LBA 位移及镜像 SHA-256
  `24b793d68b802bb36ae38ec47fcfe7d4b8d3f79177b006db834ad821c62cd8cc`。
- `ui-p5-battle-menus-validation.json`：以 P4 SLPS 为精确前像，选择地图指令
  尾项、行动限制、快捷指令和修理／补给／精神目标四组 38 条决定；5 条
  no-op、33 条写入 37 个 target，相对 P4 改变 1,024 字节／60 段且零重叠。
  最终 SLPS SHA-256 为
  `473b5f5fee31d78aacbe5e6f78db1c9207a52f33ff50ef65a846e880b080d16d`。
- `ui-p5-battle-menus-first-five-atlas-test-validation.json`：以完整成员组合
  P5 UI、前五关 `HB/STAGE` 和五图 suite，锁定 7 个成员与三类 owner。
- `ui-p5-battle-menus-first-five-atlas-test-runtime-validation.json`：把 P5
  component 绑定到 66 成员 DVD，锁定 59 个未替换成员、7 个 replacement、
  `+7/+42` LBA 位移及镜像 SHA-256
  `2abecf4261b0a2a89c206bb64cdbd1c5f4908b43ad276823cba18a795bc2bf73`。
- `ui-p6-deployment-validation.json`：以 P5 SLPS 为精确前像，选择出击小队、
  尺寸筛选与搜索格式组的 16 条决定；13 条 no-op、3 条写入 3 个 target，
  相对 P5 改变 44 字节／5 段且零重叠。最终 SLPS SHA-256 为
  `f03b1b3487afe15772973ae3d5214679fdf7d3ffbd356dfe5a3514ce2745b93d`。
- `ui-p6-deployment-first-five-atlas-test-validation.json`：以完整成员组合
  P6 UI、前五关 `HB/STAGE` 和五图 suite，锁定 7 个成员与三类 owner。
- `ui-p6-deployment-first-five-atlas-test-runtime-validation.json`：把 P6
  component 绑定到 66 成员 DVD，锁定 59 个未替换成员、7 个 replacement、
  `+7/+42` LBA 位移及镜像 SHA-256
  `8d245c6c6dff5a2fd81db4acbed96141f1249c6d3e80fa8700bbb8f1a0eb511d`。
- `ui-p7-embedded-font-validation.json`：继承 P2 字库账本，为五个
  `font_extension_required` 场景追加 `忆显缓网锋页额` 七字，并统一重绘
  `振滑画符`；93 条选择从候选字库重读后零缺字、零原版汉字混用，余 12 槽。
- `ui-p7-embedded-font-groups-validation.json`：在 P6 core 上只重建 VT1
  字体 chunk 2，保持其余 13 个 chunk byte-exact，并写入五组 93 条决定。
  其中 20 条 no-op、73 条写入 86 个 target；字体 offset 与 969 个文本变化
  字节零重叠，COMPDATA／MTV_PROS 精确沿用 P6。
- `ui-p7-embedded-font-groups-first-five-atlas-test-validation.json`：以完整
  成员组合 P7 UI、前五关 `HB/STAGE` 和五图 suite，锁定 7 个成员与三类
  owner。
- `ui-p7-embedded-font-groups-first-five-atlas-test-runtime-validation.json`：
  把 P7 component 绑定到 66 成员 DVD，锁定 59 个未替换成员、7 个
  replacement、`+7/+43` LBA 位移及镜像 SHA-256
  `743b26bf2ad211e65a9a56638f295ceca5f53c965b4435a8a9b5ed6ac4882348`。
- `ui-p8-remaining-user-facing-validation.json`：以 P7 core 为精确前像，
  晋级余下四个纯玩家可见 fixed-span 分区的 59 条决定；19 条 no-op、40 条
  写入 47 个 target，SLPS 变化 418 字节／61 段，字库、COMPDATA 和
  MTV_PROS 均保持 byte-exact。
- `ui-p8-remaining-user-facing-first-five-atlas-test-validation.json` 与
  同名 runtime manifest：组合 P8 UI、前五关和五图 suite，并绑定到 66
  成员 DVD；镜像 SHA-256 为
  `99235186f0a70b6cad40aa7f2b34d564d751bd1c5c93810b2fce75cdea5bbc3f`，
  运行状态仍为 `not_tested`。
- `ui-p9-mixed-user-facing-subset-validation.json`：在 P8 前像上逐条晋级
  两个混合组中 9 条玩家标签，写入 34 个 target、改变 174 字节／36 段；
  13 条诊断、控制、格式或未证实片段不进入选择。
- `ui-p9-mixed-user-facing-subset-first-five-atlas-test-validation.json` 与
  同名 runtime manifest：组合历史 P9 UI、前五关和五图 suite，并绑定到
  66 成员 DVD；镜像 SHA-256 为
  `73563075703fa49eb3fcdc4e3edab38f6cc6dfc1a4617ccccd8588097583558b`，
  运行状态仍为 `not_tested`。
- `ui-database-fixed-core-selection.json`：从 1,250 条大型数据库中选择
  402 条定长可写、术语已审的驾驶员技能／机体特殊能力／精神指令／小队长
  能力条目，延期 848 条，并锁定五项受保护排除及四个运行家族。
- `ui-p10-database-font-validation.json`：继承 P7 组合字库，消耗最后 12 个
  renderer-addressable 候选槽并统一重绘 14 个继承汉字；402 条选择零缺字，
  最终 decoded 字库 SHA-256 为
  `4798a2f62af9d4fb6ad65502ca25a772a5eabbc196633aebacc3ff8728005ad6`。
- `ui-p10-database-fixed-core-validation.json`：在 P9 前像上写入 232 条 SLPS
  和 170 条 COMPDATA 决定；402 条全部定长回读，指针／非目标字节不变，
  COMPDATA 完整回解且压缩前缀保留 113,266 字节，VT1 只替换字体 chunk 2。
- `ui-p10-database-fixed-core-first-five-atlas-test-validation.json` 与同名
  runtime manifest：组合当前 P10 UI、前五关和五图 suite，并绑定到 66 成员
  DVD；59 个成员不变、7 个 replacement 独立 UDF 回读精确，LBA 位移为
  `+8/+45`，镜像 SHA-256 为
  `2bba1c82a0f1fa88eef2d0870c62eddbf36cfe4ceaa8f566767d3c5020c37431`。
  fresh-process boot smoke 已证明其在加入改写 COMPDATA 后触发 TLB，不能
  晋级为当前运行候选。
- `ui-iso-incremental-validation.json`：从 first-five 起依次单独加入 atlas、
  VT1、SLPS、MTV_PROS 和 COMPDATA；实读六张 ISO、静态 build report、
  PCSX2 v2.6.3 PINE receipt 与日志。当前只晋级
  `first-five-noncompdata-ui`，精确 SHA-256 为
  `85ba645d980d84861f233a11c93b1f0cb3742a8a0583cec41d9e70263851ec39`，
  并把 `DATA/COMPDATA.BN` 锁为唯一运行阻塞增量。
- `ui-vt1-slps-atomic-runtime-validation.json`：用 VT1-only 错配作为负面
  对照，固定片头后 12 次 TLB、离线切片解码失败，以及匹配 SLPS/VT1 组合的
  1,290,240 字节完整解码、标题双光标截图和长路径 0 TLB；明确两成员必须
  原子选择和晋级。
- `ui-external-save-candidates.json`：记录四份 GameFAQs/Internet Archive
  CodeBreaker 存档的来源、CBS／转换后 `.ps2` 哈希、MyMC++ 文件系统检查及
  17997 第 38 话实际载入的 0 TLB 日志／截图；仍保持
  `candidate_not_promoted`，不冒充前五关精确谱系 fixture。
- `compdata-incremental-validation.json`：固定同一非 COMPDATA 基线上的三个
  COMPDATA 因果实验。23 条按钮的重编码组件保持 71 sectors 并启动通过；
  原始压缩流逐字节不变、只追加 419-byte 零尾的 72-sector 控制与 44 条
  P0 完整组件均以 `0x1c6ea0/0x02000000` TLB 失败。清单据此锁定
  145,408-byte 原位上限、后续四个语义层的超额字节数和继续拆分顺序。
- `ui-runtime-test-matrix.json`：把 14 类基础 UI 场景完整分成 10 类当前
  测试目标和 4 类显式延期，并通过场景图与 P7 字库 promotion manifest
  选择十八个整组分区，通过 P9 promotion manifest 选择两个逐条子集，再由
  P10 promotion manifest 加入四个数据库家族；共 38 类／34 类当前目标，
  锁定 8 个制品 profile、46 个逐屏用例、8 类 fixture、112 个截图点、6 个截图
  序列和 5 个 texture delta；
  五张 atlas 用例均绑定
  中文候选及其 421／2,292／3,634／2,083／1,262 像素 delta。当前只有
  fresh-boot fixture 就绪，七份原生 memory card 尚未取得；标题主菜单已经
  通过，另 4 个 fresh-boot 用例可直接执行，35 个等待当前缺失的原生
  memory-card fixture，6 个由 COMPDATA 容量／TLB 阻塞。幕间按钮用例已绑定
  71-sector 启动通过候选；人物／机体名、搜索项和两类 COMPDATA 数据库用例
  仍绑定容量阻塞候选。清单不保存存档、截图或游戏字节。
- `runtime/ui-cases/*.json`：每个已通过用例的 hash-only receipt。receipt
  必须由 case-owned session probe、截图／序列、全部断言及可选 atlas
  texture delta 生成；矩阵锁定 receipt SHA-256，receipt 反向锁定排除运行
  状态和自身 receipt 字段的稳定 `matrix_plan_sha256`。当前标题主菜单已有一份
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
  `ui-p1-core` DVD 镜像绑定；记录 66 个成员、62 个未替换成员、四项替换
  独立 UDF 回读、分段 LBA 位移、DVD/NSR02、固定 ISO SHA-256，以及精确
  镜像的 fresh-process PINE Running／零 TLB boot receipt。标题、玩家设置、
  幕间、信息页、战场、搜索和世界史逐屏视觉运行仍为 `not_tested`。
- `ui-p2-display-name-font-validation.json`：继承 P1 字库，为 researched
  名称启用 24 个新 allocation、重新启用 `娅杰艾贾` 四个退役 assignment，
  将误分配给 `a/f/h/r/u` 的五槽退休保留，并统一重绘 29 个原版汉字；
  1,262 个字段 renderer 缺字为零，余 19 槽，
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
  1,166 个编码项；修正可打印 ASCII 审计后，统一 renderer 有 28 个缺字
  （含 21 个编码缺字和 7 个原表不可达汉字）。其中 4 个复用已登记退役槽，
  24 个需要活跃新 allocation；早期误分配给 `a/f/h/r/u` 的五槽退休保留，
  另重绘 29 个原版汉字，预计余 19 槽且零
  projected allocation 溢出。日文只在被忽略的审核 JSON／TSV；该清单
  只拥有选择结论，writer 和 runtime 状态由各自 P2 清单拥有。
- `ui-p0-display-names-validation.json`：在固定 P0 COMPDATA 组件上写入开场
  45 个已审校动态名称字段；证明人物 ID、机体指针和非目标字节不变、所有文本
  留在原 allocation、压缩流精确回解。ISO 和运行验证仍待完成。
- `world-history-layout.json`：28 条 MTV_PROS 世界史的 22 格中文断行、
  14 个空行、三个跨记录连续组和零定长溢出清单；相对当前 P0 字库记录
  27 个未映射字符、14 个 resolver 不可达字符、三个安全槽和 38 槽短缺，
  并保留 `not_tested` 运行边界，不包含原文或游戏字节。
