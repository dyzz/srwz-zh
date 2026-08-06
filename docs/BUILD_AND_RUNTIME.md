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

## 目录与单候选规则

```text
rom/srwz.iso                         不可变原版
work/build/<profile>/components/    可重建组件
work/build/<profile>/iso/layout/    构建 XML 与 LBA 日志
build/iso/<profile>/                当前 ISO 与静态报告
work/runtime/ui-cases/<case-id>/    本地运行证据
manifests/runtime/ui-cases/         可提交 hash-only 收据
```

`build/iso/` 同一时间只保留一张 `.iso`。历史 ISO 可以删除；其 config、component
manifest、`iso-validation.json` 和 runtime receipt 才是可追溯边界。
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

组件必须先由对应 profile 的生产命令生成。随后构建精确 ISO：

```bash
python3 tools/build_canary_iso.py \
  --config config/iso/<profile>-build.json
```

只有原版布局缓存缺失或需要重新校验提取时才使用：

```bash
python3 tools/build_canary_iso.py \
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
  srwz-zh-release-full-story.iso
```

其 SHA-256 为
`edcadb0ff4bd1c0bbdd24514ae1aada7ba43e091935c5c09a8314c855e0ea091`，大小为
`3758358528` 字节，与原版镜像大小完全一致。`DATA/VT1.BIN` 保持原始
`127500736` 字节，`DATA/STAGE.BIN` 及其后所有成员的 LBA 均不移动。
`build/iso/zh-release-full-story/iso-validation.json` 已锁定两次
字节级一致构建、66 个成员的 ISO9660/UDF 读取、59 个未替换成员 byte-exact 和
7 个替换成员 byte-exact。构建配置还要求 7 个 replacement 与
`manifests/full-story-components-validation.json` 的输出路径、大小和 SHA-256
逐项一致，不能复制旧锁后直接出盘。单候选重建命令为：

```bash
python3 tools/build_ui_iso_step.py \
  --chain config/iso/zh-release-chain.json \
  --step-id zh-release-full-story \
  --replace-existing
```

`manifests/zh-release-full-story-iso-content-validation.json` 进一步从最终 ISO
独立解码并逐条
核对 154 个剧情块：82719 条对白、558 条条件文本和 8469 个说话人，共 91746
条；同时核对 1760 个机师姓名字段、`确定／返回`、全部对白的 24×3 上限和
1925 个原始 ASCII 运行时占位符。字体块也按最终 SLPS/VT1 重新解码并与全文
字体清单一致。当前 ISO 明确不含尚未完成的 `BTL/SRVC.BIN`／`BTL/SRVC.SEG`
写回；战斗台词必须在形成独立验证组件后再加入同一 chain。历史
`21b00c...` ISO 是切换前的典黑测试快照，只保留配置和静态收据，不再作为当前
候选或 HarmonyOS 字体的运行时证据。当前字体组件链已切换为 HarmonyOS Sans SC
Regular 1.0，只有 `〜∀♪` 三个字符显式回退 Noto Sans CJK SC 2.004；动态 CJK
统一使用 22px、`24x24` 字槽和全局 `y=+1`，不做逐字裁切、缩放、重心修正或
例外。当前唯一活动的 `zh-release-font` 扫描 `corpus/zh` 全部非空翻译字段，
共有 3178 个主映射和 701 个 surface-safe 别名，保留 85 个已避开别名占用的
默认宽度追加候选槽；`%s/%2$s`、`$c/$f/$l/$n/$F`、`{XX}` 和文本 tag
均走既有控制编码路径并从字形覆盖中排除，新增字符不得进入
`0x8140..0x889E` 单字符模式区；VT1 仍为 `127500736` 字节。
first-five/P0…P10/full-story 字体
profile 只保留为历史迁移证据，不再逐层重建。在重建精确 ISO 并完成新游戏、
读档两条 STAGE 入口前，不能把该静态结果晋级为运行时通过。

`manifests/runtime/ui-p10-full-story-stage-entry.json` 绑定的是前一张 SHA-256 为
`383e51ecc337904d894663db5926659f86686bf1b2ad2ebd3c666239b01269e7` 的精确
ISO，而不是当前 `21b00c...` 镜像。该收据记录过两条 fresh-process 路线：

1. 加载当前 memcard 第一页最后一个存档（第 8 格，Rand，第 37 话），从场间
   菜单选择下一地图，正常出现“仕組まれた決戦”并进入地图剧情；
2. 从标题页开始新游戏，使用默认男主角设定，正常进入首关地图剧情。

两条日志的 Trap exception、Unknown R5900、Unrecognized op 和 TLB miss 均为
0；两个隔离存档在退出后仍与原始 memcard SHA-256 完全一致。该证据证明这两条
关卡入口，不代表当前 ISO 已完成运行验收，也不代表 154 关完整路线已经逐关
实机验收。

## 当前文本覆盖边界

STAGE 全文与 `COMPDATA.BN` 的 297 条战斗退场台词已纳入中文语料，但战斗动画中
随语音出现的短句来自另一成员 `BTL/SRVC.BIN`，尚未完整提取。截图样例
`「一気に間合いをっ！」` 位于其第 71 个 SEG 块，BIN 偏移分别为 `0xACE32`
和 `0xAE527`。

中文码表允许复用原日文字槽；因此未汉化 SRVC 文本在当前字库下出现中文混字是
预期过渡状态。后续门禁不是恢复这些日文字形，而是完整提取、翻译、重编码和回读
SRVC 的玩家可见战斗文本，并继续保持成员扇区预算和原 LBA。

## 运行前检查

```bash
python3 tools/audit_ui_runtime_matrix.py --force
python3 tools/audit_ui_runtime_fixtures.py --force
python3 tools/check_ui_runtime_host.py --force
```

host preflight 只检查 PCSX2 架构、Rosetta、精确 ISO 和 route-ready case；它
不启动模拟器。只有报告给出 `launch.safe_to_launch: true` 才进入正式运行。

存档必须先复制到隔离 session。原始 memory card 不原位修改；savestate 只能
用于加速定位，不能替代同一 ISO 的 fresh-process primary run。

## 单个运行用例

```bash
# 生成路线说明、目录和证据草稿，不启动 PCSX2
python3 tools/prepare_ui_runtime_case.py \
  --case-id <case-id> --force

# 从新进程启动精确 ISO，并在 PCSX2 运行时验证会话
python3 tools/probe_ui_runtime_session.py \
  --case-id <case-id> \
  --log work/runtime/ui-cases/<case-id>/sessions/<session-id>/logs/emulog.txt \
  --fresh-process --force

# 停止后回收稳定日志和截图
python3 tools/collect_pcsx2_session.py \
  --lock work/runtime/pcsx2-sessions/<session-id>/session-lock.json

# 对截图、断言和目标画面生成 hash-only 收据
python3 tools/verify_ui_runtime_evidence.py \
  --case-id <case-id> --force
```

session probe 必须同时确认：

- 精确 ISO 路径、大小和 SHA-256；
- `SLPS-25887` 与 PINE `Running`；
- fresh process、DVD 识别和 ELF executing；
- 日志中零 TLB miss；
- 当前用例要求的截图、导航结果和断言。

atlas 用例还必须将 PCSX2 纹理转储与锁定 reference PNG 做完整 RGBA 比较，并
证明变化只在授权 mask 内。

## 证据晋级

运行文件先保存在 `work/runtime/`。只有满足以下条件才可将 hash-only receipt
复制到 `manifests/runtime/ui-cases/` 并把矩阵状态改为 `passed`：

1. ISO、组件、存档和截图哈希完整；
2. 实际到达目标 surface；
3. 所有视觉／交互断言明确通过；
4. 日志和 PINE 绑定同一 fresh-process 会话；
5. runtime matrix 重新审计通过。

boot smoke 只证明启动路径；静态回读只证明字节与结构；savestate 截图只可作为
辅助证据。三者都不能单独称为目标场景运行通过。
