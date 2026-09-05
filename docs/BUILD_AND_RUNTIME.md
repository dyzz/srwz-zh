# v0.3.0 构建与验收

本文记录 v0.3.0 当前可执行的 ISO、静态回读、发布包和运行验收边界。LRPS2 自动
验证与 PCSX2 手工验收都不属于生产构建闭包；前者由仓库内独立 runner 执行，后者
只由测试者人工完成。

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
python3 tools/rebuild_zh_font.py --skip-fetch --force-rebuild

python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json
python3 tools/verify_full_story_iso_content.py --force
python3 tools/build_release.py \
  --config config/release/v0.3.0.json
```

`extract_iso_member.py` 只建立 `work/disc/` 原版成员缓存。`rebuild_zh_font.py` 从这些
原版成员开始，生成全局字体，构建 reviewed LIBRARY、剧情和 UI 图集，再合并全部
23 个最终成员。菜单文本和标题菜单分别由
`corpus/zh/menu/release-v0.3.json` 与 `config/assets/title-menu-zh.json` 直接写入；
旧发布 ISO、旧汉化成员和发布用 xdelta 都不是构建依赖。普通构建不修改配置中的哈希
与快照；只有确认生产输入发生变化后，才使用各入口提供的 `--refresh-*` 选项。

强制全量路径会重新生成全部资源，但同一次构建的字体灰度图只生成一遍：proposal
准备步骤通过 `.rasters.json` 传给字体组件，组件核对 proposal 摘要、逐字灰度摘要、
量化像素及 packed glyph 摘要后写入。独立运行字体组件且没有 `--raster-input` 时仍
重新光栅化。MAPMODEL 标题／地形链与其他集成资源并行，VEFF 菜单／教学标题链在
所需 SLPS 数据完成后与 STAGE 后处理并行；各归档内部写入顺序保持不变，全部任务
成功才落盘最终组件。Rust 编解码为每个线程复用进程，通过管道传输，保持原有算法、
解码限制和压缩预算。更新 codec 源码后先执行 `python3 tools/build_rust_compressor.py --force`；
文本构建入口会自动重建该工具。

## 文本审阅后的 ISO 构建

只修改剧情、战斗、菜单或资料库文本后，统一使用：

```bash
python3 tools/build_text_update_iso.py --refresh-manifests
```

该入口首次对完整原版 ISO 与关键成员做哈希验证，并在 `work/cache/` 保存绑定仓库
原版 manifest、ISO 锁以及文件 size/inode/mtime/ctime 的本机 receipt。后续文件身份与
仓库锁完全不变时复用该证明；任一项变化、receipt 缺失或执行 `--release-proof` 时都会
重新读取整盘。之后从所有 Git 跟踪的配置收集 `work/disc/` 原版成员锁；缓存缺失或
漂移时会从原版镜像重新提取，不能把旧组件当作事实源。Rust codec 从仓库
源码以 `Cargo.lock` 重建，`mkps2iso` 与字体分别按固定 commit／哈希准备。已经审核的
UI 图集按配置、各组件 manifest、直接输入和最终 `KVMDATA` 的 SHA-256 复用，日常检查
不再重新组合归档和重算逐字节所有权。`--release-proof` 保留确定性重组复验。
clean checkout 缺少图集输出时会自动 bootstrap；已有输出与锁发生漂移时快速
失败，要求先完成资源审核，或显式使用 `--force-full`，避免文本构建悄悄变成全资源构建。

文本路径使用 `build_full_story_components.py --incremental`，根据已审核的完整组件
manifest 和输入锁只重建受影响的物理成员。`SLPS_258.87` 与 `MTV_PROS.BIN` 是强制
闭合的依赖组：任一侧需要重建时会同时重建，并要求 SLPS 内偏移表末值与实际归档
大小完全相等。字体准备仍会重新扫描当前文本覆盖范围；字体来源、fallback、raster
参数和分配表锁未变化时复用 proposal 中逐字形的 raster 哈希。如果字体的二进制
proposal 也未变化，则继续复用字体组件，只更新文本选择验证元数据。日常 ISO 使用
`build_iso.py --incremental`：已有工作镜像、原盘文件身份及配置均匹配上次证明，且
替换成员大小不变时，克隆原镜像并只写入变更成员。macOS 使用 APFS clone；其他平台
退回文件复制。变更成员重新回读，并执行固定 LBA、成员扇区预算、结构校验和最终
整盘 SHA-256；未改区域沿用克隆前的证明。文件身份、布局、成员大小、构建实现或
receipt 不匹配时自动使用完整 mkps2iso 路径；冻结 release profile 不使用此复用。
各阶段
耗时和最终哈希记录在
`work/build/zh-release-full-story/text-update-build.json`；运行时状态仍保持 pending，
不会由该入口自动执行 PCSX2。

剧情和 reviewed LIBRARY 也分别按输入与输出 SHA-256 判断是否需要重建。字体 proposal
的 `ui_selection` 只记录语料选择；它变化而其余字体字段不变时，继续复用未受影响的
STAGE、LIBRARY、NISV、VEFF 和 MAPMODEL，并更新报告绑定。真正的映射、字形、字体源、
alias 等变化仍使相关消费者失效。整合阶段没有受影响成员时，只验证上游验收状态并
重绑报告，不再进入全量 writer。旧增量状态没有字体语义指纹时会保守重建；一次成功
构建后自动写入新版状态。所有这类复用都要求已有输出与受跟踪锁完全一致；clean
checkout 缺少缓存时仍会自动走完整 bootstrap。

对白文件变化现在按关卡处理。`build_story_component.py --incremental` 把共享输入和
逐关卡对白摘要分开，未变关卡复用上一份已验证的压缩块及报告；条件、说话人、编码、
共享配置或实现变化会使相关缓存失效。集成层只重新执行变更关卡的编队名和关键词
写入，其他关卡沿用最终产物。第 0 块、后处理输入或实现变化，以及旧版缓存没有逐块
证明时，回退完整 STAGE 集成。压缩预算、文本控制标记、写入前像、指针和回读检查继续
在实际修改的关卡上执行。

准备发布候选、刷新完整 ISO 内容回读 manifest，或需要当前构建的确定性证明时使用：

```bash
python3 tools/build_text_update_iso.py --refresh-manifests --release-proof
```

`--release-proof` 使用完整 ISO 构建，之后强制执行完整语义回读，再生成一次 ISO 验证
确定性，并检查生产 JSON 是否被 Git 跟踪。日常候选允许尚未 `git add` 的生产 JSON；
源文件、编码、容量和输出校验照常执行。

只准备或核对可重建前提而不写组件／ISO，可使用：

```bash
python3 tools/build_text_update_iso.py --prepare-only
```

需要显式重建全部 UI 图集时再加 `--force-full`。构建后应提交文本事实源、随其变化的
配置和 manifest；不得提交 `work/`、`build/` 或完整 ISO。

## 日常构建缓存

完整冷构建成功后，`rebuild_zh_font.py` 会在 `work/cache/` 写入内容寻址
receipt。后续相同命令先按 SHA-256 核对生产构建代码、配置、受管语料、锁定输入和最终
组件输出；完整 inventory 一致就直接复用。构建实现和图集未变、只有局部输入变化时，
全量入口直接使用与文本入口相同的组件依赖流程，生成完整组件集合，复用字体、资料库
及未变关卡；不会先重跑全部字体、图集和剧情。最终组件整合按成员依赖重建，继续复用
输入未变且已经审核的 NISV、VEFF、MAPMODEL 等冻结成员；不会重演
这些资源的 rasterize、PSMT4/8 swizzle 和逐像素验收。缺失或过期的可重建缓存回退
相应构建；无法解释的输入锁漂移或未知依赖变化仍报错。`--force-rebuild` 才显式要求
全量重算。正常缓存命中也不再要求 `--skip-fetch`，已有完整内容证明时不重复获取字体。

`--refresh-manifests` 也可以命中完整缓存：若所有输入、manifest 和输出原本就一致，
没有需要刷新或重建的内容。全量重建中的 UI atlas 和 suite 各生成一次，随后直接核对
落盘字节与本次内存产物并核对／刷新 manifest，不再自动调用 verify 重建第二次。
独立的 `ui_atlas.py verify` 和 `verify-suite` 仍可用于显式重现性检查。

只需完整组件集合、暂不生成 ISO，也可以直接运行
`python3 tools/build_text_update_iso.py --refresh-manifests --components-only`。

`verify_full_story_iso_content.py` 的完整回读通过后也会保存独立 receipt。日常生成候选
可以在 `build_iso.py` 后停止；完整 ISO 语义回读用于发布候选、固定 LBA/成员映射改动和
专项排错。需要快速复核同一候选时，不带 `--force` 的调用只有在精确 ISO、构建定义、
组件输入/输出、报告和 manifest 全部一致时才复用旧结果。

日常生成候选可使用：

```bash
python3 tools/rebuild_zh_font.py --skip-fetch
python3 tools/build_iso.py \
  --config config/iso/zh-release-current-build.json
```

若要复用之前已通过的同一 ISO 回读结果，再单独运行
`python3 tools/verify_full_story_iso_content.py`；缓存不匹配时该命令会要求显式复验。

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

## LRPS2 自动运行验证

仓库内自动验证统一使用 `tools/run_lrps2_validation.py`，不启动或控制 PCSX2。默认
场景固定 LRPS2 核心、libretro.py、ISO、Software renderer、逐帧输入、截图和视觉断言；
默认从 ARMSX2 复制当前记忆卡，具体问题也可显式锁定另一张卡。输出路径 fail closed，
仅允许写入 Git 忽略的 `work/runtime/lrps2/`。环境准备、标题五条路线、当前架构限制、
常见路线别名、自定义 issue 按键序列、运行命令和 receipt 字段见
`AUTOMATED_RUNTIME.md`。

自动 runtime 可以证明该精确组合按规定路线到达目标并取得匹配画面，但不能外推到
其他核心、renderer、存档或 ISO，也不能替代需要人眼判断的字体与布局验收。

## PCSX2 手工画面验收

静态回读和 LRPS2 自动通过都不等于 PCSX2 手工画面通过。人工验收应使用上述精确
ISO，并记录 PCSX2 版本、关卡、
路线、触发步骤和截图。新游戏、读档、目标 STAGE、战斗字幕及低频界面的运行结果
只属于被测试的 ISO 哈希，不能从旧候选外推。
