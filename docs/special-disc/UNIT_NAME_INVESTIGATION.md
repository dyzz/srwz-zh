# SP BGM 设置中的「イズモ艦」漏译排查

## 2026-09-20 写回更新

用户随后授权“加入并写入，commit”。已将下述五条审校名称接入独立写回模块、全量构建与最终 ISO 验证器，覆盖 5 个名称槽、9 个机体记录指针。新增原生语料保留既有译文，并登记写回契约；不将尚未绑定的其他原生文本算作已完成。

- [写回模块](../../tools/special_disc/writeback/unit_names.py)、[名称／指针契约](../../config/products/special-disc/unit-names.json)、[回归测试](../../tests/test_special_disc_unit_names.py)
- [写回与验证记录](../issue-assets/special-disc-unit-names-20260920/writeback.json)
- 新镜像：[sp-zh-unit-names.iso](../../build/iso/special-disc/unit-names/sp-zh-unit-names.iso)
- 新镜像 SHA-256：`af2a11e11bda56ead72d871ed7e096dc732b6b7466738a685a3bbb55582785ae`
- 写入时基于当时最新全量候选 `7cf59a242d583692d2550264f186a902b21cd8f71af5a6570207ce01994f5ef1`，输出到独立路径；不覆盖并行任务使用的全量候选。该基线晚于下文最初排查的 `57bbe844…`。

五条名称均在原槽内写入，不移动指针；重压后 174,997 字节，成员预算 177,467 字节。最终 ISO 的 9 个名称指针均回读为预期中文，成员 LBA／大小不变，COMPDATA 以外整盘字节一致，解压数据中名称槽以外字节一致。

罗马数字 `Ⅰ` 保留原字，使用 `0x8754`；其当前字形与原版字形相同，已锁定像素哈希并在写回时检查，无需改写成数字或修改全局字库。

验证：7 项新增测试、合计 43 项 SP 专项测试通过。额外运行全量验证器时，最终 ISO 和成员哈希检查通过，随后因继承清单中的 `work/build/special-disc/full-text/system/report.json` 与当前磁盘报告哈希不一致而停止；没有绕过该锁，也没有声称全量文本遍历通过。本次新增落点、字体例外、固定容量和其他 ISO 区域均已独立验证。未执行新的模拟器验证，`runtime=pending`。

复跑名称写回（输出路径须不存在；源镜像及其清单须保持上述身份）：

```sh
PYTHONPATH=tools python3 -m special_disc.writeback.unit_names \
  --source-iso build/iso/special-disc/full-text/sp-zh-full-text.iso \
  --source-sha256 7cf59a242d583692d2550264f186a902b21cd8f71af5a6570207ce01994f5ef1 \
  --output-iso build/iso/special-disc/unit-names/sp-zh-unit-names.iso \
  --proposal work/build/special-disc/text-candidate/font/proposal.json
```

## 最初排查记录

2026-09-20，以下是首次只读排查时的结果；写回更新见上文。

用户照片显示 BGM 设置的机体对象列表仍为「イズモ艦」。既有定名为 **出云舰**；本地当前全量候选 ISO 可静态复现名称数据缺口。问题是普通机体名称未接入补译写回，并非缺少译稿。

- [用户原图](../issue-assets/special-disc-unit-names-20260920/bgm-izumo-user.jpg)
- [本次 ISO 回读证据](../issue-assets/special-disc-unit-names-20260920/readback.json)
- [本地复跑脚本](../../work/review/special-disc/unit-name-audit-20260920/audit.py)：仓库根目录运行 `python3 work/review/special-disc/unit-name-audit-20260920/audit.py`。

## 原生落点与当前结果

核对镜像为 `build/iso/special-disc/full-text/sp-zh-full-text.iso`，SHA-256 为 `57bbe8444972c0c567dfb50c34e843401a9ad6b9082a2a891e9cbeae242a84eb`。本次重新计算整盘哈希，并核对以下两个成员与镜像清单一致。

| 存储位置 | 偏移 | 当前 ISO 回读 |
| --- | --- | --- |
| `DATA/COMPDATA.BN` 解压后的普通机体名称 | `0x85198` | `イズモ艦` |
| 同一解压文件的战斗鉴赏列表名称 | `0x9AEA8` | `出云舰` |
| `SLPS_259.20` 舰船名称 | `0x375DB4` | `出云舰` |

普通机体记录索引 **775**，名称指针在解压 COMPDATA 的 `0x61970`，值为 `0x7EA118`；减去 SP 加载基址 `0x764F80` 后指向 `0x85198`。名称原始字节为 `8343835983828acd00`，当前镜像仍保留原文。其「出云舰」编码为 `8f6f895d964200`，含 NUL 共 7 字节，小于原文 9 字节，故该条不是容量不足。

照片和机体表回读相互吻合；本次没有取得照片所用镜像的哈希，也没有动态跟踪 BGM 页的读取函数，因此不把静态落点当作新的模拟器验收。

## 根因与统计遗漏

1. [migrate_compdata.py](../../tools/special_disc/writeback/migrate_compdata.py) 从本篇原始／汉化 COMPDATA 构造名称复用答案。SP 原文没有对应本篇答案时，走 `no answer in the main game` 分支并保留原文。本次检查本篇原始解压 COMPDATA，没有精确的 NUL 结尾「イズモ艦」。
2. [native-text.json](../../corpus/zh/special-disc/native-text.json) 已收录 `sd/compdata/85198`，译文「出云舰」、审校状态 `reviewed`，但写回状态仍为 `binding_and_layout_pending`。
3. [write_system_text.py](../../tools/special_disc/writeback/write_system_text.py) 读取 `system-text.json` 和 `frame-text.json`，没有消费 `native-text.json`。战斗鉴赏和主程序中的两个同名字段属于已覆盖输入，不能代替普通机体名称落点。
4. [build_full_text.py](../../tools/special_disc/writeback/build_full_text.py) 的 8,629 条覆盖统计仅针对既有五份语料，没有包含新增原生文本语料。旧范围内 `pending=0` 不能证明这些新增名称已写入；[Pro 校订导入记录](PRO_REVIEW_IMPORT.md) 也明确登记了这一边界。

因此，仅重建现有构建链仍不会补上这处普通机体名。

## 顺查结果

新增原生语料中的五条机体名称都与当前 ISO 显示不同：

| 原生 ID | 当前 ISO 回读 | 已审校译文 |
| --- | --- | --- |
| `sd/compdata/84AC8` | `XAN−跷−` | `XAN-斩-` |
| `sd/compdata/85198` | `イズモ艦` | `出云舰` |
| `sd/compdata/85230` | `バルゴラ（Ⅰ号機）` | `巴尔戈拉（Ⅰ号机）` |
| `sd/compdata/85270` | `バルゴラ（Ⅱ号機）` | `巴尔戈拉（Ⅱ号机）` |
| `sd/compdata/85380` | `レムレース辑作型` | `雷姆雷斯试作型` |

另扫描全部 854 个机体槽，在 14 条机体记录、10 个唯一名称地址发现假名残留，具体索引／指针／原文／当前显示见 JSON。这个数量是静态候选数，不代表全部会在普通流程出现，也不是全部名称问题的总数：例如 `XAN−跷−` 没有假名，单靠假名检查就会漏掉。

## 修复入口

将新增机体名称以原文身份、机体记录指针、独立槽容量和共享字库验证为约束接入 COMPDATA 写回；将新增语料纳入构建覆盖与最终 ISO 按指针回读检查。出云舰可在原槽内写入，其他名称分别验证容量和字形，不能凭该条容量结果批量推定。

完成组件与 ISO 回读后，在同一镜像的 BGM 设置列表及机体详情页复验。首次调查阶段未修复或重建；后续已按上文完成写回，运行验证仍待进行。
