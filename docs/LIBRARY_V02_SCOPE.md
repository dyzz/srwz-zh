# v0.2 LIBRARY 汉化范围

> 历史技术基线：本文保留 v0.2 建立的 LIBRARY 资源范围和结构定位。翻译进度与
> 发布状态已经由 v0.3.0 发布说明取代，文中的旧批处理和审校命令不属于当前构建。

v0.2.0 已确定纳入完整 LIBRARY，而不是只处理入口标签。生产范围包括：

- LIBRARY 主菜单；
- 机体图鉴（321 条）；
- 角色事典（411 条）；
- 术语事典及关键词弹窗（52 条）；
- 音乐选择；
- 剧情流程；
- 攻略 Q&A。

范围与原版成员前像统一登记在 `config/library/v0.2.0.json`，语料批次状态登记在
`corpus/releases/v2.json`。当前仍保留 `in_progress`：图鉴正文已经完成，但剧情流程
和攻略 Q&A 的深层内容清单及当前精确 ISO 的运行覆盖尚未闭合。它们作为测试版的
已知限制曾登记在 v0.2.0 TODO；该内部记录已从当前文档树移除，可从 Git 历史追溯。

## 当前汉化进度

三个 ZKN 图鉴成员已完成原版前像校验、逐块解压、ZKAN 解析、人工审校、生产写回和
最终 ISO 独立回读：

- 784 个图鉴条目（机体 321、角色 411、术语 52）；
- 4,921 个文本字段引用；
- 去重后 2,709 条文本已全部审校并晋升正式语料；
- 阿里云 DashScope 固定快照 `deepseek-v4-flash-0731` 已生成 2,709/2,709
  条机器初稿；滚动别名不允许作为 0.2 生产语料来源；
- 初稿 ID、源文本哈希、源队列顺序、禁假名规则和强制术语规则均已通过严格校验；
- 2,709 条正式译文已写入 4,921 个文本字段，784 个条目和三个成员的大小、块跨度、
  二进制字段及运行时文本回读全部保持合同；
- 曲名从提取和模型队列源头排除。

正式语料位于 `corpus/zh/library/v0.2-reviewed.json`。机器初稿和风险审计仍保留在
忽略提交的 `work/review/` 中作为审校溯源，不再是生产构建输入。

```bash
python3 tools/extract_library_v02_corpus.py
python3 tools/run_aliyun_library_v02_all.py --workers 3
python3 tools/audit_library_v02_machine_draft.py
```

批量脚本默认使用项目 `.env` 中的阿里云 DashScope 兼容接口配置。失败响应和计费
回执会保留，严格验收通过的批次可断点复用；重跑聚合不会再次请求模型。

## 曲名保留规则

音乐选择的界面标题、分页和操作提示进入中文化范围；101 首曲名保持游戏原始日语，
不得进入翻译语料，也不得因批量替换、字体投影或重新压缩而改变。

曲名位于 `DATA/COMPDATA.BN` 解压后的
`[0x6EDC0, 0x6F630)`，共 2,160 字节。校验以解压后区间逐字节相等为准，不能用
“候选中仍能搜到部分曲名”代替。这样允许 COMPDATA 因其他中文内容重新压缩，同时
仍对曲名本体保持失败即停的保护。

```bash
python3 tools/verify_library_v02.py

python3 tools/verify_library_v02.py \
  --candidate-compdata \
  work/build/zh-release-full-story/components/DATA/COMPDATA.BN
```

第二条命令只证明候选 COMPDATA 的曲名区间未变；它不证明 0.2 图鉴正文、ISO 或
运行流程已经完成。

## 已锁定资源

| 范围 | 原版成员 | 已知结构 |
| --- | --- | --- |
| LIBRARY 主菜单（运行时） | `DATA/NISVDATA.BIN` | chunk 0 解压后 TIM2 记录 2，256×256，PSMT8 |
| 相似但未被该页面采用的菜单图 | `DATA/JTIM.BIN` | TIM2 记录 5；生产组件恢复并保持原版 byte-exact |
| LIBRARY 动态标题／按键提示 | `SLPS_258.87` | 固定槽文字；Q&A 提示从 `0x340BD8..0x340C18` 读取 |
| 机体图鉴正文 | `DATA/MTVZKNRT.BIN` | 321 个压缩块 |
| 角色事典正文 | `DATA/MTVZKNPT.BIN` | 411 个压缩块 |
| 术语正文／关键词 | `DATA/MTVZKNKW.BIN` | 52 个压缩块 |
| 音乐选择曲名 | `DATA/COMPDATA.BN` | 解压区间内 101 条原始标题 |

实际运行的 LIBRARY 主菜单六个中文标签以 4 倍分辨率栅格化、一次面积平均缩回目标
尺寸，冻结在 `config/library/library-menu-runtime-render-snapshot.json`。普通组件构建
只核对并消费快照，不重新调用 ImageMagick；仅在译文、字体或渲染规则经过明确审改
后执行：

```bash
python3 tools/freeze_nisv_library_menu_renders.py --force
```

JTIM 中存在一张外观相似的菜单图，但运行截图与归档定位证明它不是当前主菜单的
实际来源；生产组件不再向它写入中文，并要求输出与原版逐字节一致。右上角
“确定／返回”、Q&A 页提示和进入子页后的动态标题由 SLPS 固定槽提供；最终回读还
要求原始 `決定` 的字节序列为零，否则被中文字库复用的 `決` 字形会显示成“糕”。
修改或验收 Library 时必须分别检查 NISVDATA、JTIM 还原状态和 SLPS。

三个 `MTVZKN` 成员由压缩块组成；解压后是带 0x20 字节包装、转义变换和 TLV 字段
的 ZKAN 文档，文本编码为 CP932。生产链已经实现严格解析、稳定条目 ID、前像哈希、
字段编码、Rust 块重压缩、容量检查和独立回读。不得按截图散改，也不得把当前字体
投影后的混合文字当作原文。

## v0.2.0 测试版边界

测试版发布时已经闭合：

1. 机体图鉴、角色事典和术语事典的译文、术语、写回及独立回读；
2. 曲名解压区间与原版逐字节一致；
3. 所有已改变成员确定性重建，压缩和固定 allocation 失败即停；
4. 最终 ISO 成员大小、目录、LBA 和内容静态回读。

剧情流程深层界面、攻略 Q&A 正文和匹配精确候选 ISO 的完整 PCSX2 运行覆盖尚未
闭合，因此 v0.2.0 维持测试版标识，并把这些项目明确列入 TODO。
