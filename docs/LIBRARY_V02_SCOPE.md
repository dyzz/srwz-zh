# v0.2 LIBRARY 汉化范围

v0.2.0 已确定纳入完整 LIBRARY，而不是只处理入口标签。生产范围包括：

- LIBRARY 主菜单；
- 机体图鉴（321 条）；
- 角色事典（411 条）；
- 术语事典及关键词弹窗（52 条）；
- 音乐选择；
- 剧情流程；
- 攻略 Q&A。

范围与原版成员前像统一登记在 `config/library/v0.2.0.json`，语料批次状态登记在
`corpus/releases/v2.json`。当前状态是 `in_progress`；这些文件表达 0.2 的发布门，
不表示上述内容已经完成写回或运行验收。

## 当前汉化进度

三个 ZKN 图鉴成员已完成原版前像校验、逐块解压、ZKAN 解析和稳定字段 ID 提取：

- 784 个图鉴条目（机体 321、角色 411、术语 52）；
- 4,921 个文本字段引用；
- 去重后 2,709 条待译文本；
- 阿里云 DashScope 固定快照 `deepseek-v4-flash-0731` 已生成 2,709/2,709
  条机器初稿；滚动别名不允许作为 0.2 生产语料来源；
- 初稿 ID、源文本哈希、源队列顺序、禁假名规则和强制术语规则均已通过严格校验；
- 曲名从提取和模型队列源头排除。

机器初稿只保存在忽略提交的 `work/review/` 审校区，尚未晋升 `corpus/zh/`。
自动风险审计当前标出 1,326 条优先审校项；其中包含术语提示未命中、英文残留、
原文等同和疑似译文碰撞。风险项包含可接受的数值或作品名误报，也已检出明显音译
错误，因此不能把 2,709/2,709 的结构通过解释为翻译审校完成。

```bash
python3 tools/extract_library_v02_corpus.py
python3 tools/run_aliyun_library_v02_all.py --workers 3
python3 tools/audit_library_v02_machine_draft.py
```

批量脚本默认使用项目 `.env` 中的阿里云 DashScope 兼容接口配置。失败响应和计费
回执会保留，严格验收通过的批次可断点复用；重跑聚合不会再次请求模型。

## 曲名保留规则

音乐选择的界面标题、分页和操作提示进入中文化范围；85 首曲名保持游戏原始日语，
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
| 音乐选择曲名 | `DATA/COMPDATA.BN` | 解压区间内 85 条原始标题 |

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
的 ZKAN 文档，文本编码为 CP932。读取侧已经实现严格解析、稳定条目 ID 和前像哈希；
生产写回侧仍需补齐字段编码、块重压缩、容量检查和独立回读。不得按截图散改，也不
得把当前字体投影后的混合文字当作原文。

## 0.2 发布门

1. 七个登记 surface 的条目清单、译文和术语审校闭包；
2. 曲名解压区间与原版逐字节一致；
3. 所有改变成员确定性重建，压缩和固定 allocation 失败即停；
4. 最终 ISO 成员大小、目录、LBA 和内容回读通过；
5. 匹配精确候选 ISO 的六个入口、列表、代表正文、关键词弹窗、剧情流程与 Q&A
   实机验收通过；
6. 运行收据中无 TLB、illegal instruction 或 trap 错误。

在这些门全部闭合前，只能称为 0.2 开发范围，不能称为 0.2 发布候选完成。
