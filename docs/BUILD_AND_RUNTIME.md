# 构建与运行验收

本文只记录当前采用的 ISO 工具链、单候选规则和 PCSX2 证据门。历史候选比较、
失败实验和本机会话流水不在当前文档中保存。

## 当前工具链结论

- 原版输入固定为 `rom/srwz.iso`，大小和 SHA-256 由 build config 与
  `manifests/original-disc.json` 锁定。
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
rom/srwz.iso                         不可变原版
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
- 修改 `rom/srwz.iso`；
- 为满足体积而截断文本、吞掉 decoded tail 或移动未授权成员 LBA；
- 用旧 ISO 的截图或存档状态晋级新 ISO。

## 构建

首次准备固定工具链：

```bash
python3 tools/bootstrap_mkps2iso.py
```

先构建 Rust codec，再由全局主链一次生成字体、154 个 STAGE 块、六张图集和最终
12 成员组件：

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
build/iso/zh-release-full-story/
  srwz-zh-release-full-story-r13.iso
```

其 SHA-256 为
`7b2b9b0f628846cf3ef9685107685af3879df612c26d414cef1cca5d030e7d80`，大小为
`3758358528` 字节，与原版镜像大小完全一致。`DATA/VT1.BIN` 保持原始
`127500736` 字节，`DATA/STAGE.BIN` 及其后所有成员的 LBA 均不移动。
`build/iso/zh-release-full-story/iso-validation-r13.json` 已锁定两次
字节级一致构建、66 个成员的 ISO9660/UDF 读取、54 个未替换成员 byte-exact 和
12 个 replacement byte-exact。构建配置还要求 12 个 replacement 与
`manifests/full-story-components-validation.json` 的输出路径、大小和 SHA-256
逐项一致，不能复制旧锁后直接出盘。单候选重建命令为：

```bash
python3 tools/build_iso.py \
  --config config/iso/zh-release-full-story-build.json
```

三份详细内容回读摘要分别覆盖整合剧情、剩余 UI 和 SRVC 战斗字幕：154 个剧情
块的 91746 条文本、2452 个机师长名／短名字段、307 条 COMPDATA 固定偏移 UI、
357 条 COMPDATA 帮助文本、6 条 COMPDATA 定长内联 UI、59 条队长效果、
379 条 SLPS 上下文 UI、156 条 SLPS UI、9 条 STAGE 固定小队名、132 条实际写回的
强化部件文本，以及 25708 条唯一 SRVC 译文／58740 个索引记录／353 个块。所有
这三份摘要仍保留其原 r11 哈希作为历史快照；r13 由当前组件 manifest 的 12 项
输出锁和 ISO builder 的 12 项独立 UDF 成员回读绑定。由于并行润色仍在改动
NISVDATA、COMPDATA 与 SRVC 语料，内容回读器会按预期拒绝用新语料覆盖旧快照；
待语料稳定并重建组件后再统一刷新三份摘要。

字体组件链使用 HarmonyOS Sans SC
Regular 1.0，只有 `〜∀♪` 三个字符显式回退 Noto Sans CJK SC 2.004；动态 CJK
统一使用 22px、`24x24` 字槽和全局 `y=+1`，不做逐字裁切、缩放、重心修正或
例外。当前唯一活动的 `zh-release-font` 扫描 `corpus/zh` 全部非空翻译字段，
共有 121384 条选择输入、3265 个主映射和 701 个 surface-safe 别名，当前没有剩余
候选槽；`%s/%2$s`、`$c/$f/$l/$n/$F`、`{XX}` 和文本 tag
均走既有控制编码路径并从字形覆盖中排除，新增字符不得进入
`0x8140..0x889E` 单字符模式区；VT1 仍为 `127500736` 字节。
KVMDATA chunk 6 的两处“中场休息”和七个菜单按九个原日文切片整块替换，使用
HarmonyOS Sans SC Light；chunk 7 的“移至后备区／移至小队区”在原切片内先把
背景调色板索引强制重建为 0，再居中绘制中文，避免透明别名索引留下日文残影。
动态 CJK 继续使用 Regular。chunk 11 仅在 `x=60..153, y=0..23` 的固定贴图范围
把 `までクリア！` 重画为“已通关！”，`第／話`、闭引号、数字精灵和
`NEXT:出撃 小隊` 保持原样。构建器从 204 条关卡节点记录还原全部 122 条 Stage
Name 的显示归属：107 个可玩标题由 VT1 group 8 中独立的 512×64、4bpp TIM2
提供并逐槽生成中文；另外 15 条路线选择／内部记录由 COMPDATA 动态文字覆盖。
每个压缩 slot、内部偏移表、VT1 总大小和成员 LBA 均保持不变。当前
`7b2b9b0f...` ISO 尚未取得绑定精确哈希的
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
python3 tools/prepare_pcsx2_session.py \
  --case-id release/stage-entry \
  --session-id release-stage-entry

python3 tools/verify_pcsx2_session.py \
  --lock work/runtime/pcsx2-sessions/release-stage-entry/session-lock.json

python3 tools/launch_pcsx2_session.py \
  --lock work/runtime/pcsx2-sessions/release-stage-entry/session-lock.json \
  --execute
```

若使用外部 memory card 或 savestate，必须显式传入 `--exploratory`；原始卡不原位
修改，savestate 只用于加速定位，不能替代同一 ISO 的 fresh-process primary
run。停止后用 `collect_pcsx2_session.py` 回收日志和卡快照。

最终 runtime 结论必须同时绑定当前 ISO 哈希、`SLPS-25887`、PCSX2 2.6.3、PINE
Running、fresh process、目标画面截图以及零 TLB miss／illegal instruction。
boot smoke、静态回读和 savestate 截图都不能单独晋级当前候选。
