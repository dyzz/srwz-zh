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
- `ui-surface-inventory.json`：从真实语料、当前前五关字库和 COMPDATA
  动态名称结构确定性投影的 UI 场景摘要；固定 P0 的 462 条文本、九个缺字、
  12 个剩余候选槽、三槽余量和开场名称 writer 状态，并明确区分译文决策、
  writer、ISO 与运行状态。
- `ui-p0-font-validation.json`：在不改变 first-five 组件的前提下追加九个
  P0 UI 字符并统一重绘九个原版汉字；记录 1,454 个 assignment、VT1
  size-preserving 重压缩、SLPS offset 回读、462 条文本零缺字／零原版汉字
  混用和三槽余量。状态仅为离线通过，ISO 和运行验证仍待完成。
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
- `ui-p0-display-names-validation.json`：在固定 P0 COMPDATA 组件上写入开场
  45 个已审校动态名称字段；证明人物 ID、机体指针和非目标字节不变、所有文本
  留在原 allocation、压缩流精确回解。ISO 和运行验证仍待完成。
- `world-history-layout.json`：28 条 MTV_PROS 世界史的 22 格中文断行、
  14 个空行、三个跨记录连续组和零定长溢出清单；同时记录 27 个缺字、24 槽
  短缺及 `not_tested` 运行边界，不包含原文或游戏字节。
