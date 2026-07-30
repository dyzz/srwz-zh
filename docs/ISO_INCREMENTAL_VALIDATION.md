# 从 first-five 逐层重建 UI ISO

本轮采用单候选策略：`build/iso/` 只保留一张镜像，每次只加入一个可归因的
资源层，先做静态回读，再用 fresh-process PCSX2/PINE 走到真正使用该资源的
画面。六秒 boot smoke 只证明 DVD、ELF、PINE 和当时没有 TLB，不能替代标题
入口、菜单导航或逐屏视觉验收。

## 2026-07-30 当前 P2 显示名定长候选

当前 `build/` 和 `work/` 中只保留一张 ISO：

```text
build/iso/ui-p2-core/srwz-ui-p2-core.iso
```

- 大小：`3,758,358,528` 字节；
- SHA-256：
  `be95af17bcfe62ff6b0dfc5f7d9665118440c9adaa8061c071881471f76ef811`；
- 四个替换成员是 `SLPS_258.87`、`DATA/COMPDATA.BN`、
  `DATA/MTV_PROS.BIN` 和 `DATA/VT1.BIN`；
- 所有 66 个成员保持原 LBA，`shifted_member_count=0`；
- COMPDATA 使用 clean-room Rust `rust-maximum` 压缩为 `144,485`
  字节／71 扇区，距 `145,408` 硬上限余 `923` 字节；
- fresh-process boot smoke 为 PINE Running、0 TLB，收据位于
  `work/runtime/iso-incremental/13-ui-p2-researched-names-rust-fixed-span/`。

该候选在已人工进入游戏的 P1 定长候选上，只晋级 P2 研究确认显示名及其匹配
字库：选择总数从 45 增至 1,307，其中新增 1,262 个研究精确匹配。P1 已观察到
过程滚动文字、机体能力等 UI 中文；P2 目前只通过 boot smoke，仍需在人物／
机体信息页核对名称、缺字、字形和裁切，不能继承 P1 的视觉结论。

剧情仍是日文属于当前组合的预期边界：`DATA/STAGE.BIN` 没有列入替换成员，
ISO 独立回读仍是原版 SHA-256
`9c56d42f96df7b409ccf468b24412322ed627b9cbbd656864818a404d89240dc`。
完成 P2 显示名视觉验收后，才继续加入下一组固定范围 UI；first-five STAGE
剧情层仍单独保留，不与本轮 UI 归因混合。

## 较早的 first-five 分层结论（历史）

| 层 | 相对上一层的增量 | 六秒 boot smoke | 延长路径 | 当前结论 |
| --- | --- | --- | --- | --- |
| 0 `first-five` | 前五关基线 | 历史通过，0 TLB | 已有前五关剧情实机证据 | 基线 |
| 1 `first-five-atlas` | `KURODATA/KVMDATA.BIN` | 通过，0 TLB | 目标页需要幕间、战斗和商店存档 | 视觉待测 |
| 2 `first-five-atlas-vt1` | `DATA/VT1.BIN` | 通过，0 TLB | 片头后加载标题资源时出现 12 次 TLB | **负面对照，不得晋级** |
| 3 `first-five-atlas-vt1-slps` | 匹配的 `SLPS_258.87` | 通过，0 TLB | 完整标题入口、两个光标状态、0 TLB | **当前可用候选** |
| 4 `first-five-noncompdata-ui` | `DATA/MTV_PROS.BIN` | 仅有旧历史收据 | 本轮尚未重建 | 下一层 |
| 5 full UI | `DATA/COMPDATA.BN` | 历史 TLB 失败 | 独立工程问题 | 不得加入 |

该轮当时唯一物化 ISO：

```text
build/iso/ui-step-03-first-five-atlas-vt1-slps/
  srwz-ui-step-03-first-five-atlas-vt1-slps.iso
```

- 大小：`3,758,424,064` 字节；
- SHA-256：
  `8ce59de31543389df4a07b1e137df2b190309daa1af693c6265881743de97c9b`；
- fresh-process 收据：
  `work/runtime/iso-incremental/03-first-five-atlas-vt1-slps/boot-smoke.json`；
- 标题长路径日志：
  `work/runtime/iso-incremental/03-first-five-atlas-vt1-slps/title-visual/emulog.txt`；
- 标题截图：
  `title-start-selected.png` 和 `title-library-selected.png`。

标题画面中的“开始／读取／继续／资料库”均已实际显示；选中和未选中调色板
正常，没有发现裁切或重叠。atlas 五张图对应的真正页面尚未到达，因此不能把
标题截图当作 atlas 的视觉证据。

## 为什么 VT1 不能单独加入

`DATA/VT1.BIN` 是 14 段归档；各段 offset 不是只存在归档内部，游戏还从
`SLPS_258.87` 的 `0x2FA100..0x2FA13B` 读取一份表。重压 VT1 后，段边界会
改变，所以 VT1 和这 60 字节 offset 表是一个原子兼容单元。

负面对照把当前 VT1 与旧 first-five SLPS 混用：

- 旧表中的 font 段范围为 `0x009AC590..0x00A6BF60`；
- 匹配新 VT1 的范围为 `0x009A8D20..0x00A6CC20`；
- 用旧表切新归档，离线解码立即在输入 `0x8` 失败：
  `back-reference distance 4446 exceeds produced output size 1`；
- 同一错误组合在 PCSX2 运行到 112.8233 秒后出现 12 次 TLB，首条为
  `pc=0x154d60 addr=0x2b4d8789 [load]`；
- 匹配组合可完整解出 `1,290,240` 字节字体段，标题长路径日志为 0 TLB。

`tools/build_ui_iso_step.py` 现在会在删除已有 ISO **之前**，用所选 SLPS
offset 表实际解码所选 VT1 字体段。错误配对会直接拒绝构建；这也意味着第 2
层今后只能作为历史负面对照，不能再被单独物化。

完整机器可读证据见
`manifests/ui-vt1-slps-atomic-runtime-validation.json`。

## 外部存档候选

GameFAQs 保存页列出四份日版 SRWZ CodeBreaker 存档；直接页面受 Cloudflare
保护，本轮从 Internet Archive 保存的 GameFAQs 存档集合取得原文件，再用
隔离安装的 MyMC++ 3.2.0 分别导入独立 8 MiB `.ps2` 卡。四张卡的文件系统
检查均无错误。

| ID | 内容 | 卡内目录 | 用途判断 |
| --- | --- | --- | --- |
| 17997 | 兰德路线第 38 话 | `BISLPS-25887S7` | 已实际载入；战斗场景候选 |
| 17998 | 兰德路线第 58 话 | `BISLPS-25887S12` | 后期战斗候选 |
| 17999 | 通关存档 | `BISLPS-25887S29` | 幕间／资料库候选 |
| 18042 | 双路线通关、Special Mode | `BISLPS-25887S29` | 高覆盖菜单候选 |

候选文件位于：

```text
work/runtime/ui-fixtures/candidates/gamefaqs-srwz/
```

17997 已被当前 ISO 识别并载入第 38 话事件／战斗对话；运行日志 0 TLB，截图
在 `external-save-17997/`。它证明外部卡可用，但不是前五关精确谱系，也尚未
按运行矩阵正式晋级为 fixture。第 38 话仍显示日文是预期结果，因为当前剧情
翻译范围只到前五关。

来源：

- `https://gamefaqs.gamespot.com/ps2/945859-super-robot-taisen-z/saves`
- `https://archive.org/details/gamefaqs_savegames`
- `https://pcsx2.net/docs/configuration/memcards/`

### 存档安全边界

`work/runtime/first-five/memcards` 是指向系统 PCSX2 记忆卡目录的符号链接，
不能再当作隔离测试目录。本轮挂载 17997 时曾因此触及 `Mcd001.ps2`；发现后
已立即用原本字节相同的空白 `Mcd002.ps2` 恢复。恢复后两者大小均为
`8,650,752`，SHA-256 均为
`47ebe237a3987f843fc19b0f801ce1edc1690768ef6b18e4b03a12ca6b298358`，
且 `cmp` 逐字节一致。后续存档运行必须复制完整 portable root 到独立目录，
不得通过该链接换卡。

## 该轮原定顺序（历史）

1. 保留当前第 3 层 ISO，不再重复生成；
2. 用 17999／18042 的复制卡寻找 first-intermission、资料库和 atlas 页面；
3. 用 17997 或更合适的精确卡完成 first-battle／战术地图 fixture；
4. atlas 五个目标页面逐屏验收后，才加入 `DATA/MTV_PROS.BIN` 生成下一张
   唯一 ISO；
5. `COMPDATA.BN` 继续留在独立压缩／原位容量验证链，不能混回当前候选。

日常构建命令：

```bash
python3 tools/build_ui_iso_step.py \
  --step-id first-five-atlas-vt1-slps \
  --replace-existing
```

构建结束会删除该 profile 的 `original/staging` 整盘工作目录。缺少已清理的
历史 ISO 时保留其配置、manifest 和运行收据即可，不得为了让旧六层审计全绿
而批量重建。
