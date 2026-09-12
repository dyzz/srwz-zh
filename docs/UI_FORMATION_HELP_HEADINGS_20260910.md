# 阵型与说明标题汉化

2026-09-10。承接阵型术语提交 `dd81244`，用户确认继续处理反馈图 3–6 中的六个英文标题。

| 原标题 | 中文 | 使用位置 |
| --- | --- | --- |
| FORMATION | 阵型 | 敌我小队预览、单队／批量阵型预览 |
| SELECT-FORMATION | 选择阵型 | 单队／批量阵型选择 |
| SELECT-SORT | 选择排列 | 单队队员排列 |
| Key Help | 按键说明 | SELECT 说明窗口右上角 |
| OTHERS COMMAND | 其他指令 | 说明窗口的指令分类标题 |
| DATA HELP | 数据说明 | 说明窗口下方标题 |

本次语料为 `corpus/zh/ui-atlas/formation-help-headings.json`。
三种阵型仍使用已确定的 TRI阵型／集中阵型／分散阵型。

## 资源来源与修改边界

标题的像素来自 `KURODATA/KVMDATA.BIN`，绘制记录来自 `KURODATA/KVPDATA.BIN`。
两份成员在已核对的 Original 和 The Best 原盘中分别逐字节相同。
本次没有修改 ELF 的纹理／绘制偏移表。

- KVMDATA 第 4 块为 256×256、低半字节优先的线性 4bpp TIM2；不能按 TRICMN 的
  swizzle 格式处理。保留所有 CLUT、头、尾部、成员大小和非目标逻辑像素。
- 回收原 FORMATION 区域，并使用现有中文“指令菜单”两侧的透明空白，放入七个双字字块。
  原“指令菜单”的像素保持；其绘制引用收窄到相应中文区域，避免空白区的新字块被带入。
- 多个英文词被其他标题按字母重复采样，尤其 DATA HELP 原为两层各八个字母。
  本次只改目标绘制记录，保留其他共用英文源字。DATA HELP 每层改为两个中文字块，
  余下六个字母图元缩为零面积，保留原绘制顺序及终止标记。
- 共调整 79 个固定 34 字节绘制记录。每条记录均锁定修改前字节；只允许纹理页低半字节、
  顶点位置和 UV 变化，图元类型、终止位、材质高半字节、颜色保持。
- 中文索引冻结在 `config/assets/ui-headings-render-snapshot.json`：0 为透明，1–7 为描边，
  8–15 为填充，使用原有层角色。正常构建不重绘、不依赖 ImageMagick 或字体文件。
  快照同时绑定中文语料和字块契约哈希。

## 构建

```sh
python3 tools/build_ui_headings.py
```

输入为现有 UI atlas suite 产物，加上原盘 KVPDATA；输出是一对必须同时安装的成员：

| 成员 | 字节数 | SHA-256 |
| --- | ---: | --- |
| KVMDATA.BIN | 3,335,408 | `343068888b22cca5dab5cf9a2c55204a9dd57f987ffe8539e2318deced83e09c` |
| KVPDATA.BIN | 239,664 | `d9250f51eaff4eb5a36a39ea66eb90d3bde2f2a17a69e7b1d21fe01c7661c256` |

产物目录为 `work/build/ui-headings-zh/components/KURODATA/`。
`rebuild_zh_font.py` 在 atlas suite 后运行该构建器；组件组合、增量缓存、依赖失效和
当前 ISO 替换清单均加入 KVPDATA。The Best 组合器接受新增的第 25 个成员，继续要求
跨版本共享成员的原盘字节相同。本次未构建或运行 The Best 整盘。

任何语料、基础贴图、源绘制记录或快照漂移都会拒绝构建；`--refresh-manifest` 仅更新
已锁定输出对应的静态清单，不会重新绘制或自动接受新源。后续改字或改变基础 atlas 时，
须重新审核字块与配对输出，再更新相应锁。

## 验证

- 274 项单元测试通过，包括绘制记录前像、非目标字节、材质／颜色／终止位、重复写入拒绝、
  共用英文标题隔离及 DATA HELP 图元收缩检查。
  此后补充奇数 x 边界的 4bpp 写入测试，确认两行字块只修改对应半字节，邻像素、调色板和
  头尾不变；更新后的 5 项标题专用测试通过。
- 配对组件重复构建与逐字节回读通过；原盘基线验证、`compileall`、构建 CLI 导入和
  `git diff --check` 通过。
- 临时诊断 ISO 从 Original 原盘制作，只替换本次两个新成员，其余成员采用上次已验证
  组件。所有替换成员回读、大小及 LBA 均核对；它不是本次全部中文源的发行构建。
  因此诊断截图正文仍可能显示“中央／广域／队形”，不代表已提交的最新阵型语料。
- 诊断 ISO SHA-256：`adca5c614632525581993513c1a314ef83922b9f078ee0153e74832031e7d224`。
  配方、源组件哈希及读取记录在 `work/review/ui-heading-localization-20260910/`。
- LRPS2 已目视核对批量阵型的“选择阵型”“阵型”，以及部队表和整备编成界面 SELECT
  说明的“按键说明”“数据说明”；文字颜色、边框、阴影及位置正常。
  “选择排列”“其他指令”已完成静态修改与回读，尚未在该诊断镜像中进入对应界面，
  保留运行待验；不能把未触发入口的脚本退出成功当成截图验收。

| 已查看的运行证据 | 本地路径 |
| --- | --- |
| 批量阵型 | `work/runtime/lrps2/ui-headings-roster-help-20260910/frames/02784-bulk-formation-final.png` |
| 部队表数据说明 | `work/runtime/lrps2/ui-headings-held-help-20260910/frames/03200-roster-select-held.png` |
| 部队表按键一览 | `work/runtime/lrps2/ui-headings-squad-help-20260910/frames/03350-key-list.png` |
| 整备编成数据说明 | `work/runtime/lrps2/ui-headings-intermission-20260910/frames/03600-organization-help.png` |

各运行目录的 `receipt.json` 锁定输入 ISO、核心、原始与隔离存档、动作及截图哈希。
本次只操作隔离存档副本。诊断 ISO 在验收后删除，保留构建配方、组件与运行记录；
后续可按配方复建。

静态构建清单始终保留 `runtime=not_tested`；独立运行证据另行记录，不能把临时诊断镜像的
结果继承为后续发行镜像验收。本次没有更新生产 `srwz-zh-current.iso`，也未完成 PCSX2 人工验收。

## “队形→阵型”画面复验

用户再次指出旧截图中的“队形”后，重新核查中文语料、构建代码及测试。
中文语料原已完成替换；补正 `tools/build_best_candidate.py` 中实验迁移分支残留的
“采用中央队形时”为“采用集中阵型时”。术语表的废弃译名和历史审校记录保持，
用于识别旧译，不能当成现行显示文字。

另建临时诊断镜像，将现行语料的 24 个阵型相关固定文本槽和“批量设置阵型”菜单项
装入已锁定的旧组件，并加入本次标题贴图／绘制记录对。固定容量、控制标记、非目标
字节和成员 LBA 保持，压缩与回读使用 Rust 编解码器。它仍不是全部源码的正式发行构建。

- 镜像 SHA-256：`1b56f1fbf98c73290918e9c772ecb635421ea3e01abd92dee531d553a652d8d0`。
- 语料审计、配方和 25 个文本槽回读：`work/review/formation-wording-runtime-20260910/`。
- 实际运行截图：`work/runtime/lrps2/formation-wording-final-20260910/frames/02790-formation-wording-final.png`。
- 已目视确认顶部“统一阵型”、TRI阵型／集中阵型／分散阵型三个选项，以及底部“阵型”。
- 实验 Best 迁移脚本的 7 项测试、编译检查和差异格式检查通过；本次没有运行 Best 镜像。

后续展示批量阵型结果使用这张新截图。运行 receipt 保留镜像、核心、隔离存档和截图哈希；
检查结束后删除本次临时 ISO，保留配方及证据，不更新两版 current 工作镜像。
