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
