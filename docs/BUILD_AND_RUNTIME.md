# 构建与运行验收

本文只记录当前采用的 ISO 工具链、单候选规则和 PCSX2 证据门。历史候选比较、
失败实验和本机会话流水不在当前文档中保存。

## 当前工具链结论

- 原版输入固定为 Redump Disc 4932 的
  `rom/Super Robot Taisen Z (Japan, Korea).iso`，规范文件名、大小和校验值由
  release/build config 与 `manifests/original-disc.json` 锁定。
- ISO 构建固定使用 `mkps2iso` v1.1.1，仓库、tag、commit、许可证和本地可执行
  文件路径均由 config 声明。
- PCSX2 当前验收基线为 v2.6.3；PINE 用于确认游戏 ID、运行状态和 EE 内存。
- 不执行上游 EXE/DLL、Wine 或 Mono。上游二进制只提供历史静态证据，不是生产
  依赖。
- ISO builder 只做构建和静态回读，不会自动运行模拟器，也不会授予 runtime
  结论。
- 最终候选采用 fixed-LBA 门：每个 replacement 的扇区数不得超过原成员，所有
  shift segment 必须为 0，输出镜像大小必须与原版一致。任一条件不满足时在
  重建整镜像前直接失败。
- build XML 给每个逻辑成员写入原盘 LBA。replacement 即使压缩后少占扇区，也只
  在成员之间留下不可见空白，不得给压缩流追加填充字节或让后续成员前移。

## 目录与单候选规则

```text
rom/Super Robot Taisen Z (Japan, Korea).iso                         不可变原版
work/build/<profile>/components/    可重建组件
work/build/<profile>/iso/layout/    构建 XML 与 LBA 日志
build/iso/<profile>/                当前 ISO 与静态报告
work/runtime/pcsx2-sessions/        本地运行会话与 hash-only 证据
```

`build/iso/` 同一时间只保留一张 `.iso`。历史候选只在 Git 和恢复快照中追溯；
当前 config、component manifest、`iso-validation.json` 和 runtime receipt 才是
发布边界。
`work/build/<profile>/iso/original` 与 `staging` 在构建完成后可清理，不能作为下次
构建输入。完整所有权见 `ISO_DIRECTORY_LAYOUT.md`。

不得：

- patch-over-patch；
- 从仓库根目录或未解析变量递归清理；
- 修改 `rom/Super Robot Taisen Z (Japan, Korea).iso`；
- 为满足体积而截断文本、吞掉 decoded tail 或移动未授权成员 LBA；
- 用旧 ISO 的截图或存档状态晋级新 ISO。

## 构建

首次准备固定工具链：

```bash
python3 tools/bootstrap_mkps2iso.py
```

先构建 Rust codec，再由全局主链一次生成字体、154 个 STAGE 块、六张图集、
MAPMODEL 世界地图地名和最终 13 成员组件：

```bash
python3 tools/build_rust_compressor.py
python3 tools/rebuild_zh_font.py --skip-fetch
```

确认输入 ratchet 发生预期变化时附加 `--refresh-manifests`；只有字体视觉规则变化
才再附加 `--refresh-asset-ratchets`。随后构建精确 ISO：

```bash
python3 tools/build_iso.py \
  --config config/iso/<profile>-build.json
```

只有原版布局缓存缺失或需要重新校验提取时才使用：

```bash
python3 tools/build_iso.py \
  --config config/iso/<profile>-build.json \
  --refresh-extraction
```

builder 必须同时验证：

1. 原版大小、SHA-256、成员数、ISO9660 system ID 和 UDF 标识；
2. replacement 的路径、大小和 SHA-256；
3. 成员路径、顺序和未替换成员 byte-exact；
4. replacement 独立 UDF 回读；
5. 成员 LBA 和允许的 shift segment；
6. fixed-LBA profile 的 replacement 原成员扇区预算；
7. 输出大小、整镜像 SHA-256 和确定性重建属性。

当前单一候选为：

```text
build/iso/v0.1.0/
  srwz-zh-v0.1.0.iso
```

其 SHA-256 为
`d65bfca8469582105357b2f71d8627490513c9e4aef346672bbcb4dcfd518146`，大小为
`3758358528` 字节，与原版镜像大小完全一致。`DATA/VT1.BIN` 保持原始
`127500736` 字节，`DATA/STAGE.BIN` 及其后所有成员的 LBA 均不移动。
`build/iso/v0.1.0/iso-validation-v0.1.0.json` 已锁定两次
字节级一致构建、66 个成员的 ISO9660/UDF 读取、53 个未替换成员 byte-exact 和
16 个 replacement byte-exact。构建配置还要求 16 个 replacement 与
`manifests/full-story-components-validation.json` 的输出路径、大小和 SHA-256
逐项一致，不能复制旧锁后直接出盘。单候选重建命令为：

```bash
python3 tools/build_iso.py \
  --config config/iso/zh-release-full-story-build.json
```

完整 ISO 是本地开发和运行验收制品，不对外分发。生成 v0.1.0 可分发补丁包时运行：

```bash
python3 tools/build_release.py --config config/release/v0.1.0.json
```

发布工具固定核对 Redump 规范文件名以及原版与目标 ISO 的大小和 SHA-256，使用
xdelta3 3.2.0 生成补丁；附带说明中的 `-s` 输入也固定写为
`Super Robot Taisen Z (Japan, Korea).iso`，
再从原版实际还原目标镜像并复核哈希。输出目录
`build/release/v0.1.0/` 只允许包含 `.xdelta`、说明、清单、校验文件和 ZIP；ISO
不得进入发布目录或 ZIP。

`manifests/zh-release-full-story-iso-content-validation.json` 是唯一的整盘内容回读
摘要，并绑定当前 v0.1.0 的大小与 SHA-256。它覆盖 154 个剧情块的 91746 条文本、
2452 个机师长名／短名字段、308 条 COMPDATA 固定偏移 UI、357 条 COMPDATA
帮助文本、6 条 COMPDATA 定长内联 UI、59 条队长效果、407 条 SLPS 上下文 UI、
177 条 SLPS UI、9 条 STAGE 固定小队名和 132 条实际写回的强化部件文本。
`manifests/full-story-components-validation.json` 另锁定 25708 条唯一 SRVC 译文、
58740 个索引记录和 353 个块，并证明控制 token、记录预算、索引结构、SEG 和未索引
尾部保持不变。历史 R11 的分领域快照不再作为当前仓库结论。

字体组件链使用 HarmonyOS Sans SC
Regular 1.0，只有 `〜∀♪` 三个字符显式回退 Noto Sans CJK SC 2.004；动态 CJK
统一使用 22px、`24x24` 字槽和全局 `y=+1`，不做逐字裁切、缩放、重心修正或
例外。当前唯一活动的 `zh-release-font` 扫描 `corpus/zh` 全部非空翻译字段，
共有 125728 条选择输入、3419 个主映射和 693 个 surface-safe 别名，另有 264 个
未占用的 renderer 双字节位置可按需替换原日文字形；`%s/%2$s`、
`$c/$f/$l/$n/$F`、`{XX}` 和文本 tag 均走既有控制编码路径并从字形覆盖中排除；
ASCII、控制码和已占用映射保持不变，VT1 仍为 `127500736` 字节。
KVMDATA chunk 6 的两处“中场休息”和七个菜单按九个原日文切片整块替换，使用
HarmonyOS Sans SC Light；chunk 7 的“移至后备区／移至小队区”在原切片内先把
背景调色板索引强制重建为 0，再居中绘制中文，避免透明别名索引留下日文残影。
动态 CJK 继续使用 Regular。chunk 11 仅在 `x=60..153, y=0..23` 的固定贴图范围
把 `までクリア！` 重画为“已通关！”，`第／話`、闭引号、数字精灵和
`NEXT:出撃 小隊` 保持原样。构建器从 204 条关卡节点记录还原全部 122 条 Stage
Name 的显示归属：107 个可玩标题由 VT1 group 8 中独立的 512×64、4bpp TIM2
提供并逐槽生成中文；另外 15 条路线选择／内部记录由 COMPDATA 动态文字覆盖。
每个压缩 slot、内部偏移表、VT1 总大小和成员 LBA 均保持不变。当前
`d65bfca8...` ISO 尚未取得绑定精确哈希的
fresh-process 启动收据；上一候选的启动结果不能外推。新游戏、读档 STAGE 入口和
战斗字幕画面均由用户继续测试；静态回读不能晋级为 runtime passed。

## 当前文本覆盖边界

STAGE 全文、`COMPDATA.BN` 的 297 条战斗退场台词，以及战斗动画中随语音出现的
`BTL/SRVC.BIN` 短句都已纳入中文语料。截图样例
`「一気に間合いをっ！」` 位于其第 71 个 SEG 块，BIN 偏移分别为 `0xACE32`
和 `0xAE527`。

生产写回按原索引顺序压紧每个块的文本池，只重写索引中的文本偏移字；每条译文仍须
小于等于自己的原始终止字符串预算。字面 `\\n` 保持为原始 `5C 6E` 控制字节，
`%s` 等其他占位符也按原签名核对。`SRVC.BIN` 仍为 3313040 字节，成员扇区预算和
原 LBA 均未改变；当前剩余门禁是精确 ISO 的实际战斗字幕显示验证。

## 当前运行验收流程

运行会话直接绑定 `config/iso/zh-release-full-story-build.json`，不再维护历史候选
矩阵。准备命令只复制 PCSX2、设置、BIOS 引用和可选存档，不启动模拟器：

```bash
python3 tools/pcsx2.py prepare \
  --case-id release/stage-entry \
  --session-id release-stage-entry

python3 tools/pcsx2.py verify \
  --lock work/runtime/pcsx2-sessions/release-stage-entry/session-lock.json

python3 tools/pcsx2.py launch \
  --lock work/runtime/pcsx2-sessions/release-stage-entry/session-lock.json \
  --execute
```

若使用外部 memory card 或 savestate，必须显式传入 `--exploratory`；原始卡不原位
修改，savestate 只用于加速定位，不能替代同一 ISO 的 fresh-process primary
run。停止后用 `python3 tools/pcsx2.py collect --lock <session-lock>` 回收日志和
卡快照；需要按会话记录安全发送 SIGINT 时使用 `pcsx2.py stop --session-id <id>`。

最终 runtime 结论必须同时绑定当前 ISO 哈希、`SLPS-25887`、PCSX2 2.6.3、PINE
Running、fresh process、目标画面截图以及零 TLB miss／illegal instruction。
boot smoke、静态回读和 savestate 截图都不能单独晋级当前候选。
