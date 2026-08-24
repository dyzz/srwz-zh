# v0.3.0 构建与验收

本文只记录 v0.3.0 当前可执行的 ISO、静态回读和发布包流程。模拟器操作由测试者
人工完成，不属于仓库内 Python 构建闭包。

## 前提

- Python 3、Git、CMake、Rust／Cargo 和 ImageMagick 7；
- 生成可分发补丁时另外需要 xdelta3 与 7-Zip；
- 用户合法持有的 Redump Disc 4932 原版镜像；
- 原版文件放在 `rom/Super Robot Taisen Z (Japan, Korea).iso`；
- 原版大小为 `3758358528` 字节，SHA-256 为
  `ddbedefc0061213c50928fb213a7fb277c0345f01dab7386adc0383638a78cd2`；
- 构建工具按 `config/upstream.lock.json` 与 ISO 配置锁定版本。

`rom/` 只读；`work/` 是可重建的提取与组件目录；`build/` 保存本地 ISO 和发布包。
不得在旧汉化 ISO 上重复打补丁，也不得让 `rom/`、完整 ISO、存档或本地运行记录进入
Git 或发布 ZIP。

## 按物理文件构建

P0–P10 只属于开发历史，不是 v0.3.0 的生产输入。当前链从锁定原版成员直接写回，
不先生成一套“基础汉化”二进制，也不在内部叠加 xdelta。组件阶段只有三个互斥的
构建组：

1. **可执行文件、字体与核心 UI**：`SLPS_258.87`、`DATA/VT1.BIN`；
2. **文本与资料归档**：`COMPDATA`、`NISVDATA`、`STAGE`、`MTV_PROS/PROP`、
   `HSFC/HB` 和三个 ZKAN 资料库；
3. **战斗、地图、特效与演示归档**：`SRVC`、`OP0/1/2`、`MAPMODEL`、
   `KVMDATA` 与 `VEFF2DX`。

同一物理文件只属于一个构建组。每个压缩流先解压一次，在同一 decoded workspace
内完成该流的字体、文本、布局和 UI 写入，通过结构检查后再统一压缩一次。组件完成后，
ISO 组合、整盘静态回读和发布包生成是三个顺序明确的交付步骤，不再称为额外 pass。

例如 `NISVDATA.BIN` 第 6 流中的武器特殊效果名和攻略 Q&A 共享一个工作区：
先解压，连续完成两类写入，最后统一压缩。构建 manifest 会记录每个共享工作区的
解压、写入阶段与压缩次数；重复压缩会直接失败。

## 完整构建

```bash
python3 tools/verify_original_disc.py
python3 tools/extract_iso_member.py --force \
  SLPS_258.87 \
  MAP/MAPMODEL.BIN EFF/VEFF2DX.BIN \
  BTL/OP0.BIN BTL/OP0.SEG BTL/OP1.BIN BTL/OP1.SEG \
  BTL/OP2.BIN BTL/OP2.SEG BTL/SRVC.BIN BTL/SRVC.SEG \
  DATA/COMPDATA.BN DATA/HSFC.BIN DATA/JTIM.BIN \
  DATA/MTV_PROP.BIN DATA/MTV_PROS.BIN \
  DATA/MTVZKNKW.BIN DATA/MTVZKNPT.BIN DATA/MTVZKNRT.BIN \
  DATA/NISVDATA.BIN DATA/STAGE.BIN DATA/VT1.BIN
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_rust_compressor.py

python3 tools/fetch_zh_font.py
python3 tools/fetch_zh_font.py \
  --flavor config/fonts/zh-localization-font-light.json
python3 tools/rebuild_zh_font.py --skip-fetch

python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json
python3 tools/verify_full_story_iso_content.py --force
python3 tools/build_release.py \
  --config config/release/v0.3.0.json
```

`extract_iso_member.py` 只建立 `work/disc/` 原版成员缓存。`rebuild_zh_font.py` 从这些
原版成员开始，生成全局字体，构建 reviewed LIBRARY、剧情和 UI 图集，再合并全部
21 个最终成员。菜单文本和标题菜单分别由
`corpus/zh/menu/release-v0.3.json` 与 `config/assets/title-menu-zh.json` 直接写入；
旧发布 ISO、旧汉化成员和发布用 xdelta 都不是构建依赖。普通构建不修改配置中的哈希
与快照；只有确认生产输入发生变化后，才使用各入口提供的 `--refresh-*` 选项。

## 固定输出

最终 ISO：

```text
build/iso/zh-release-full-story/srwz-zh-current.iso
```

- 大小：`3758358528` 字节
- SHA-256：`64b42bf2134b368037fcfdd20abc068a417f95817ff10fb801d06fd6f28961f9`

可分发包：

```text
build/release/v0.3.0/srwz-zh-v0.3.0.zip
```

发布工具会核对原版与目标 ISO 的文件名、大小和 SHA-256，使用锁定的 xdelta3 生成
补丁，再从原版实际还原目标 ISO 并复核哈希。发布目录和 ZIP 只允许包含 xdelta、
说明、清单与校验文件，不得包含完整 ISO。

## 构建硬门

ISO builder 和静态 verifier 必须 fail closed：

1. 原版身份、ISO9660/UDF 布局和成员顺序一致；
2. 每个 replacement 的来源、大小和 SHA-256 与组件 manifest 一致；
3. replacement 不超过原成员扇区预算，后续 LBA 不移动；
4. 未替换成员 byte-exact；
5. 字体、文本、控制 token、指针、图集和压缩流可以独立回读；
6. 最终镜像大小和 SHA-256 与 v0.3.0 配置一致；
7. 发布补丁可以从固定原版还原出同一目标镜像。

## 运行与画面验收

静态回读不等于运行通过。人工验收应使用上述精确 ISO，并记录 PCSX2 版本、关卡、
路线、触发步骤和截图。新游戏、读档、目标 STAGE、战斗字幕及低频界面的运行结果
只属于被测试的 ISO 哈希，不能从旧候选外推。
