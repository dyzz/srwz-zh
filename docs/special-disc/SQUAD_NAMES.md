# SP 小队名扫描与翻译

2026-09-20：按本篇的结构扫描、原文绑定和冻结位置清单方式，完成 SP 玩家关卡的小队／部队显示名与 NISVDATA 小队名建议表。已生成独立中文组件并回读，**未替换 ISO，运行验收待完成**。

## 覆盖

| 范围 | 数量 |
| --- | ---: |
| 不同日文源名称 | 266 |
| 玩家 STAGE 块 | 42 |
| STAGE 名称字段 | 1,338 |
| NISVDATA chunk 4 建议名称 | 113 |
| 合计字段 | 1,451 |

STAGE 覆盖固定编队、单位／阵营／人物显示名、自动编队及带所有者指针的短表。原有 39 个直接绑定、280 个字段全部保留，现有中文 STAGE 写回器覆盖 390 个按关卡／源名称合并的绑定、1,338 个字段。NISVDATA 不再只迁移本篇的 104 条，也覆盖 SP 新增或变更项。

266 条均来自已有项目译名：124 条本篇默认编队、53 条本篇建议名、46 条说话人、26 条 SP 已校订框架名、13 条机体显示名、3 条 SP 原生校订、1 条全局术语。没有调用外部翻译服务，也没有修改 Pro 已校订名称。`Orange`、`XAN`、`BIG-FAU`、`MS`、数字等按既有译名保留；不以缩写英文解决容量。

- [翻译语料](../../corpus/zh/special-disc/squad-names.json)：每个源名称的译文、原文哈希、术语来源及全部位置。
- [冻结位置清单](../../config/products/special-disc/squad-name-inventory.json)：原盘成员身份、偏移、容量、名称槽哈希、记录前后元数据和已确认的指针记录。
- [扫描与写回验证](../../work/review/special-disc/squad-names/verification.json)：字库、容量、编码回读、非名称字节保护及最终组件回读。

## 扫描补漏与边界

复用本篇 `record6+23`、`formation18+33+1`、固定数组和指针短表规则，另外补齐两种已由 SP 原生记录确认的情况：

1. 单字名称：challenge chunk 047 的“桂”，位于 `0x3808`。仍要求完整的 32 字节指针所有者，不能仅凭单个字符串入库。
2. 已填成员编号的连续记录：challenge chunk 040 的魔神Z、大魔神、古连泰沙、盖塔机器人。名称指针位于记录 `+16`，保留既有 selector／尾哨兵约束，并要求相邻的 32 字节记录、有效编号和可解码名称。原版只接受特定前置哨兵的规则会漏掉这组；完整所有者记录已锁定。大魔神的字段按真实 24 字节对齐槽处理，不把前方零填充误当作 6 字节记录头。

关卡对白／条件的原生解析范围优先于名称启发式；字段之间不得重叠。STAGE chunk 0 的流程图与 stg_500／501 开发关卡不参与玩家覆盖数，排除信息保留在清单中。扫描不是全盘任意字符串替换，也不涵盖玩家自定义队名或旧存档内部的名称改写。

正常写回读取冻结清单，核对源槽、记录元数据与指针所有者；不会在每次构建时重新用启发式扩大范围。`stage_auxiliary.py` 消费全部关卡名称，并核对已有 SP 直接绑定译文一致；`migrate_nisv.py` 消费完整 113 条建议名，支持 `--output` 写入独立组件目录。

## 验证与组件

- 266 条译文的共享字库覆盖、编码回读和 1,451 个槽位容量均通过，无新增字形分配。
- 名称写入只改变已拥有的名称字段；原生记录的成员数据、匹配条件和指针保持不变。
- 与当前中文对白合成后的 42 个 STAGE 块全部回写原压缩槽，最小余量 **147 字节**（chunk 051）；NISVDATA 名称块余量 **261 字节**。HB 边界、成员大小和解压大小不变。
- 从两个生成组件重新解码，1,451 个字段全部与语料一致；已有 39 个 SP 直接绑定无遗漏。
- 36 项 SP 专项测试通过，其中新增 6 项覆盖短名所有者、连续成员记录、非名称保护、源槽漂移、溢出和冻结覆盖。Python 3.13 工作区自检通过。

组件保存在 `work/build/special-disc/squad-names/{stage,nisv}/`，未覆盖现有组件或 ISO。STAGE 成员 SHA-256 为 `58671b1722b2dec8c5270f3d8b7286d53601b98c98df960b5e9f58e90804d468`；NISVDATA 为 `0eb72c289ad9af6a2c0496bb174ecabb3c926033846f6650afcd6c9dc1fc4a68`。

验证器还记录“只替换日文原块的名称、保留日文对白”的独立压缩实验，其中 40 个 STAGE 块超出原槽；这不是中文组件的构建结果。实际组合组件已如上通过容量检查，不能将两种压缩分母混用。其他 Pro 校订页面的排版／字库问题、ISO 装配和 LRPS2／PCSX2 验收仍按各自记录跟进。本轮不提供新增运行证据。

现有 `build_full_text.py` 会通过 STAGE 写回器消费新的名称清单；其保留的 canary ISO 仍含旧 NISV 内容，下一次全量镜像装配还需明确合入新 NISVDATA 的 chunk 4，不能仅运行旧 `--assemble-only` 就宣称全部名称进入镜像。

## 复现

建议使用 Python 3.12 以上。重新扫描会核对冻结清单，只有显式 `--freeze` 才更新位置文件：

```sh
python3.13 tools/special_disc/verification/scan_squad_names.py
python3.13 tools/special_disc/verification/verify_squad_names.py --components work/build/special-disc/squad-names
python3.13 -m unittest discover -s tests -p 'test_special_disc_*.py'
python3.13 tools/special_disc/check_workspace.py
```

独立组件构建：

```sh
python3.13 tools/special_disc/writeback/migrate_stage_dialogue.py \
  --allow-draft --include-formations \
  --chunks 1 2 3 4 5 7 8 9 11 13 14 15 16 18 19 20 21 23 24 25 26 27 28 29 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 \
  --proposal work/build/special-disc/text-candidate/font/proposal.json \
  --base work/build/special-disc/full-text/system \
  --output work/build/special-disc/squad-names/stage
python3.13 tools/special_disc/writeback/migrate_nisv.py \
  --output work/build/special-disc/squad-names/nisv
```
