# SP DATA HELP 独立字块接入

2026-09-20 最终范围：用户看过标题布局后决定“只要项目说明”。因此，本组件只保留
DATA HELP →「项目说明」。此前扩展的其他 17 个标题块均恢复到本组件接入前的状态，
取消其中文替换和分散排版。已经存在的其他汉化组件不属于这次标题实验的回退范围。
数字、共享拉丁字母和其他多层效果不改。

## 当前实现

- SP 块 1198 的前景／阴影两组共 16 条原记录，分别重定向到独立“项目”与既有“说明”。
- “项目”使用 4 个冻结条带，放在第 6／8 页；“说明”复用第 4 页只读词块。
- 两词块的起点相差 38px，整组宽 84px，保持「项目说明」连写。
- 前景起点 x=32、阴影 x=34，分别居中于原来的 148px 标题占位；原颜色、层次与偏移保留。
- 不使用整块覆盖共享英文图集，不重新栅格化已冻结文字；原页头、CLUT、透明度索引角色、
  数字区域和其他取样区均受校验保护。

## 撤回其他标题

恢复 CHALLENGE BATTLE、STORY MODE、SPECIAL DISC、OTHERS COMMAND、分段 Command、
人物选择、人物图鉴、机体图鉴、PILOT DATA、MAP WEAPON、DATA UNKNOWN 的本轮改动。
这不撤回此前已经存在的指令／菜单／阵型及按键说明组件。

配置保留 196 条撤回记录的确切前像与已安装版本前像，用于把现有候选 ISO 安全恢复到
本组件之前。正常从基线构建时，这些恢复记录不产生变化。此前为上述标题分配的 44 个
字块还原为空白；只有确切匹配旧字块或原空白才允许清除，不能擦除未知或其他任务的像素。
因此这次撤回同时清理绘制引用与本组件新增像素，不留下活动标题替换。

`title-atlas.json` 中只有块 1198 属于活动标题。`restored_title_chunks` 和
`restored_drawing_records` 单独记录撤回动作；不要再将历史 18 块覆盖数当作当前中文范围。

## 构建和验证

- `title_atlas.py` 成对处理 KVM 与 KVP，支持原基线、此前中文版本、分散版本的确切前像，
  未知前像拒绝写入。组件幂等，成员长度不变。
- `migrate_textures.py`／`write_image_labels.py` 在既有 command-headings 后应用此组件。
- `build_full_text.py` 检查当前配置锁；`build_title_atlas_candidate.py` 对当前 ISO 增量更新，
  回读两个成员、验证所有 LBA 与其他字节，并在替换前复核并行任务未改当前 ISO 或说明文件。
- 单元测试覆盖连写距离、整组居中、共享源保护、数字保护、旧版本升级、撤回引用及像素清理。
- LRPS2 绘制探针和自然入口、PCSX2 人工检查分别记账；历史中文图鉴探针属于已撤回方案，
  不再代表当前镜像。

此前全量 assemble 遇到历史 system 组件的 `system codebook drift`，未覆盖该校验。
本次使用成对资源增量写入，保留当前 ISO 其他组件，不宣称完成新的全量剧情构建。

## 证据位置

当前保留／回退验证保存在 `work/analysis/sp-data-help-only-20260920/`，运行验证位于
`work/runtime/lrps2/sp-data-help-only-20260920/`。当前 ISO 身份以
`build/iso/special-disc/sp-current.json` 为准。

此前完整替换和分散排版记录保存在 `work/analysis/sp-title-localization-20260920/`、
`work/analysis/sp-title-justify-20260920/`；撤回前说明保存在
`work/analysis/sp-data-help-only-20260920/withdrawn-implementation.md`，仅作历史追溯。

最终验证：标题测试 8 项、既有指令测试 4 项通过。`static.json` 确认除 DATA HELP
图元与四个“项目”条带外，KVP／KVM 与组件接入前逐字节相同。完整 image-labels 写回器
输出的两成员及配置锁与候选一致。LRPS2 自然流程通过，挑战标题已恢复英文，帮助窗口
打开、关闭、切至支援后重开仍显示连写「项目说明」。用户照片中的武器详情入口及
PCSX2 人工验收仍待验证。

后续统一构建接入已完成新的全量构建和独立文本回读，当前标题资源随该流程重建。
具体 ISO 身份与运行验证边界见 [三版当前 ISO 重建](../BUILD_REFRESH_20260920.md)。
