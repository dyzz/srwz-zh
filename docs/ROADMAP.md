# 路线图

本文件按汉化内容记录 M0–M5 里程碑；事实源、模块边界、统一构建、验证门禁和
E0–E5 工程实施顺序见 [`ENGINEERING_PLAN.md`](ENGINEERING_PLAN.md)。

macOS 工具链、上游 ASM 行为、R5900 关键地址和实施验证门的当前探索结果见
[`TOOLCHAIN_ROADMAP.md`](TOOLCHAIN_ROADMAP.md)。字体只读分析、稳定语料与
写回契约、clean-room 压缩编码器、`24×24/4-bpp` glyph 读写、
双字节 code→glyph 普通/扩展映射、STAGE/MTV_PROS 归档重建和
MTV_PROS production writer、STAGE allocation/pointer writer 和三类 surface
canary 已经完成。现阶段进入 E3，优先建立 offline render oracle、全量行宽/
文本池门禁和 776 个未引用 glyph 的安全分类。图片第一轮清单已确认
706 个 TIM2 记录/1,146 个
picture、上游只修改 KVMDATA chunk 5/6，并新增解析 195 条 MAPNAME 固定文本；
TIM2 外部工具初筛已完成并确定 `minimal_local_writer` 路线；严格原位 4-bpp
注入器和真实 chunk 5 byte-identical no-op 已完成；运行时纹理转储已把标题
atlas 归属到 `VT1 chunk 6 / record 1 / picture 0`，固定 8-bpp index canary
已通过重压缩、ISO、PCSX2/PINE 画面和纹理直方图验证；坐标级 PSMT8 写回也已
把四项标题菜单改为 `开始/读取/继续/资料库`，两种光标状态与运行时纹理逐像素
验证通过。无 hook 的两字静态中文
canary、原生 armips 固定
与补丁审计已经完成，
首个 canary ISO 已完成；PCSX2/PINE 已确认游戏内完整字库解压哈希和开场
文本内存一致，`SELECT SCENARIO` 的 `ゲーム测试をプレイします。` 已完成实际
渲染截图。该两字切片已经迁入正式 SurfaceSpec、`corpus/zh`、codebook 和
`canary-menu` profile。MTV_PROS 世界史和 STAGE 开场增长文本现也分别从
`canary-summary`、`canary-story` profile 构建并完成运行截图；完整组合镜像
已进入剧情通路。完整战斗回归和存档流程仍待执行。

## M0：可重复基线

- 记录原版 ISO、`SLPS_258.87` 和关键归档的 SHA-256。
- 完成无修改提取；已用 UDF/ISO9660 重建首个两字 canary ISO，并逐项确认
  64 个未替换成员 byte-exact、两项替换精确、成员顺序一致。
- 已完成关键数据解析、94,189 条稳定语料导出、232 条真实压缩流重编码往返，
  以及 STAGE 205 块和 MTV_PROS 14 块的真实对齐归档重建。
- 已固定两个官方 armips 源码提交，并验证各两次干净构建一致、官方 CTest
  通过、双版本项目 ASM 一致及真实差异所有者/覆盖契约。
- 已在 PCSX2 中启动、验证字库解压并进入开场场景选择；剧情隔离 fixture
  已进入战斗地图，完整战斗操作与结算回归尚未执行。
- 已完成首个图片运行 canary：标题 `START` 的 351 个亮黄 index 精确替换，
  运行时只有预期 RGBA 变化，0 TLB miss。
- 已完成首个正式图片中文切片：标题四项的 8 个选中/未选中文字槽均已写回，
  PCSX2 实机画面无截断重叠，运行时纹理与离线输出逐像素一致。
- 保存构建命令、日志和结果清单。

## M1：中文 canary

- 已完成 Start 后菜单 `本編` → `测试`、MTV_PROS 世界史 `测试。` 和
  STAGE Denzel 两行增长文本三个独立 canary。
- 已为 `测/试` 分配静态候选 code `987E/987F` 和 glyph 4478/4479；
  字库加载、开场文本内存和实际菜单显示均已运行验证。
- 已移除 canary 配置中的私有译文和字形分配；profile reconciliation 会检查
  source hash、编辑状态、codebook、可编码性和定长要求。
- 已从固定 OFL 字体确定性生成并回插两个字形，重建 VT1 第 2 段和 SLPS
  offset 表，并完成 ISO 插入和游戏内解压验证。
- 已验证菜单、数据库/摘要和剧情三种渲染路径，并固定独立 ISO、截图、日志
  与完整组合 smoke。

## M2：中文字库与文本引擎

- 从中文语料自动生成字符集。
- 确定性生成字形、编码表和压缩字体。
- 实现中文逐字断行、标点禁则和真实字宽计算。
- 增加缺字、行数、文本池和指针校验。

## M3：系统菜单与数据库

- 命令、按钮和战斗条件。
- 精神、技能和特殊能力。
- 零件、武器、机体、驾驶员和关卡名。
- 图鉴和所有图像内嵌文字。
- `MAP/MAPNAME.BIN` 的 195 条地图名。

## M4：剧情生产

- 序章和教程。
- 主人公路线。
- 共通路线和分支。
- 每关经过初译、审校、术语检查和运行验证。

## M5：发布

- 全路线回归测试。
- 两次干净构建产物一致。
- 生成不含原版游戏数据的补丁。
- 整理许可证、致谢、使用说明和已知问题。
