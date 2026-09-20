# 特别盘武器详情分类与特殊效果2补漏

2026-09-20 用户提供两张实机画面照片，反馈“原版遇到过的同样问题，射击格斗武器字，武器特殊效果2没汉化”。照片中的射击分类仍显示日文字形“射撃”，特殊效果2残留“バリア貫通”对应文本。照片没有可核对的镜像身份；本次通过本地镜像回读，独立确认特别盘当前候选具有相同遗漏。

- [分类反馈照片](../issue-assets/special-disc-weapon-detail-20260920/reported-category.jpg)
- [特殊效果反馈照片](../issue-assets/special-disc-weapon-detail-20260920/reported-effect.jpg)

## 原因与修复范围

这些文字由 `SLPS_259.20` 的 MIPS LUI/ORI 指令在运行时组装，不是静态文本池中的普通字符串。本篇已分别有武器分类及特殊效果2修复，但 `migrate_exe_patches.py` 明确跳过这两组补丁，因此特别盘只迁移菜单译文时不会自动覆盖它们。

新增 `config/products/special-disc/weapon-detail-labels.json`，使用特别盘原生完整指令块及各字符串实际构造位置；分析文件 `ui/patch_sites.json` 中的模糊定位只作为调查线索，不作为写入依据。原生 ELF SHA-256 为 `9c345c4a19e7abd791b00af707fe1f44086da6b1b21b8a4344a5872b307c5101`。

| 内容 | 特别盘文件位置 | 修复 |
| --- | --- | --- |
| 格斗分类 | `0x2BB158` | 格斗武器 |
| 射击分类 | `0x2BB1B0` | 射击武器 |
| 特殊效果2：サイズ補正無視 | `0x2BBC14` 起的7条构造指令 | 无视体型修正 |
| 特殊效果2：バリア貫通 | `0x2BBC78` 起的5条构造指令 | 屏障贯通 |

类别共改变3字节，特殊效果共改变23字节，合计26字节。特别盘射击图标编号 `0x01D8`、效果旗标判定、寄存器、存储位置、跳转和 NUL 填充均保留。替换前像漂移即失败；重复应用不再改动字节。文字使用现有共享字库与已审校特殊效果语料。

`build_full_text.py` 已在最终 ELF 装配时调用该修复；`verify_full_text.py` 增加从最终镜像指令立即数重新组装、解码四条文字，以及保护周边原生指令的检查。

## 独立复测镜像

为避免把同时进行的图片工作和未重建的其他译稿混入本次，先从既有全量候选生成仅此修复的独立镜像：

- 源：`build/iso/special-disc/full-text/sp-zh-full-text.iso`
- 源 SHA-256：`57bbe8444972c0c567dfb50c34e843401a9ad6b9082a2a891e9cbeae242a84eb`
- 输出：`build/iso/special-disc/weapon-detail-20260920/sp-zh-weapon-detail.iso`
- 输出 SHA-256：`d13fe73023f2cf383b901b9899c67666e2e8cc74f8a0f710aa88016e77690e04`
- 体积：3,791,781,888 字节；成员大小、目录和 LBA 不变。
- 与源相比只有 `SLPS_259.20` 的26字节变化。主程序之外的3,787,799,688字节逐字节一致。
- 回读与保护报告：输出同目录 `sp-zh-weapon-detail.json`。

复现（输出位置必须尚不存在）：

```sh
PYTHONPATH=tools python3 -m special_disc.writeback.weapon_detail_labels \
  --source-iso build/iso/special-disc/full-text/sp-zh-full-text.iso \
  --source-sha256 57bbe8444972c0c567dfb50c34e843401a9ad6b9082a2a891e9cbeae242a84eb \
  --output-iso build/iso/special-disc/weapon-detail-20260920/sp-zh-weapon-detail.iso \
  --proposal work/build/special-disc/text-candidate/font/proposal.json
```

本次没有覆盖既有全量候选。其缓存组件的 `frame-text.json` 输入锁已过期，完整装配会拒绝复用旧组件；后续整合版本需要先按当前输入重建组件。本次独立候选的26字节差异与ISO回读已经完成，不等同于当前整套译稿重新构建完成。

## 验证

- 武器专项5项通过：新增SP测试3项、本篇分类回归2项。覆盖四条中文、重复应用、14条立即数以外字节保护、SP图标编号，以及构造指令／存储／分支漂移拒绝。
- 从候选 ISO 的主程序独立组装解码，得到“格斗武器（　　）”“射击武器（　　）”“无视体型修正”“屏障贯通”。
- LRPS2 Software (SW) 已从独立候选进入普通挑战第1关的机体菜单。Z高达／光束军刀在第7640帧显示“格斗武器”，Z高达／光束步枪在第7705帧显示“射击武器”，图标均正常。截图已实际审看：[格斗分类](../issue-assets/special-disc-weapon-detail-20260920/melee-after.png)、[射击分类](../issue-assets/special-disc-weapon-detail-20260920/ranged-after.png)。
- 使用隔离存储卡副本；源卡运行前后SHA一致。核心、镜像、卡身份、按键过程和视觉判断记录于 `work/runtime/lrps2/sp-weapon-detail-20260920/provenance.json`。
- 特殊效果2尚未找到本次抽查路线中的对应武器，因此两条效果仅完成静态和ISO回读，画面验收仍待执行。PCSX2人工验收未执行；不将本次LRPS2分类样本视为全武器、全流程验收。
