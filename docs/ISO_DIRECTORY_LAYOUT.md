# ISO 目录契约

状态：已实施。ISO 相关路径按“不可变输入、可重建中间态、最终产物、运行证据”
分层，并以 ISO profile ID 隔离。`tools/build_iso.py` 会在读取配置时
校验这些边界，错误路径不会开始构建。

本地工作数据统一放在本仓库的 `work/`，父目录同名目录已合并；分类、存档迁移
与历史缓存恢复方式见 [work 目录说明](WORK_DIRECTORY_LAYOUT.md)。

## 日常测试使用 ISO，CHD 仅用于正式发布

2026-09-20 日常游戏库固定为 **2 + 2 + 3，共 7 项**。原盘和 v0.4.2 普通发布版
各保留 Original／Best 两份；current 的目标是 Original／Best／SP 各一份带方块 skip
的 ISO。CHD 只在正式 release 时制作，不再为 current 或 Q&A 工作快照生成 CHD。

| 类别 | 日常 ISO | 方块 skip |
| --- | --- | --- |
| 日文原盘 | `rom/original.iso`、`rom/best.iso` | 原版行为 |
| v0.4.2 发布版 | `build/iso/v0.4.2/srwz-zh-v0.4.2-{original,best}.iso` | 不启用 |
| 本篇 current | `build/iso/daily-test/current-{original,best}-skip.iso` | 启用，逐字节回读核对 |
| SP current | `build/iso/special-disc/sp-current.iso` | 启用，逐字节回读核对 |

机器可读清单见 `config/iso/daily-test-isos.json`，身份和保留规则见
`config/iso/retained-isos.json`。本篇 daily current 由最新统一构建产物通过现有
`tools/srwz/release_variants.py` 派生，只修改声明的 skip 可执行文件区域，核对全盘其他
字节及 LBA 不变。每次 current 重建后须重新派生并更新该清单，不能继续使用旧副本。
SP current 已集成方块 skip，完整构建也默认安装；适配细节与运行验证范围见
[SP 方块 skip](special-disc/SQUARE_SKIP.md)。

ARMSX2 只扫描上述 ISO 目录，并排除 SP 日文原盘及其他未列入清单的镜像。
SP 日文原盘仍是必要构建输入，保留在 `rom/`，但不占日常测试的 7 个游戏库槽位。
存档、截图、回执、差分基线和原版成员缓存按各自生命周期保留。

### 正式发布归档

现有 `build/chd/v0.4.2/` 父子 CHD 保留归档，不进入日常游戏列表。
中文子 CHD 依赖对应日文父盘；不得只删除父盘。历史 v0.4.1／v0.4.0 的配置路径
不保证文件仍存在，恢复前先检查实际归档。CHD 按需还原须验证发布配置锁定的大小和
SHA-256，拒绝覆盖当前新镜像。历史恢复记录见 `work/cleanup/chd-only-20260917/`。

清理和恢复记录见 `work/cleanup/iso-cleanup-20260920/` 与
`work/cleanup/daily-isos-20260920/`。静态 skip 回读不等于新镜像已经完成战斗场景运行验收。

## 1. 目录结构

以下为构建时目录结构；日常测试保留路径以上表和机器可读清单为准。

```text
rom/
  original.iso
  best.iso

work/
  disc/
    SLPS_258.87
    DATA/...
  build/
    zh-release-full-story/
      components/
        SLPS_258.87
        DATA/...
        BTL/...
        KURODATA/...
        component-validation.json
      iso/
        original/
        staging/
        layout/
          original.xml
          build.xml
          lba.txt
  runtime/
    lrps2/
      <scenario-id>/
        <session-id>/
  toolchain/

build/
  iso/
    v0.4.0/
      0.4.0-original.iso
      0.4.0-best.iso
    v0.4.1/
      srwz-zh-v0.4.1-original.iso
      srwz-zh-v0.4.1-best.iso
    zh-release-full-story/
      current-original.iso
      iso-validation-current.json
    zh-release-best/
      current-best.iso
```

## 2. 各层所有权

### `rom/`：用户输入

- 只保存用户合法持有的原版镜像。
- 当前唯一默认输入是 `rom/original.iso`。
- 普通构建工具只读取和校验，不修改、重命名、自动搜索或写回。
- 原盘大小和 SHA-256 由 `manifests/original-disc.json` 与 ISO build config
  固定。

### `work/disc/`：选择性原版成员缓存

- 由 `extract_iso_member.py` 从固定原盘只读提取。
- 保留原盘成员路径，供 parser、writer 和前像审计共用。
- 可重新提取，但不能手工修补后继续冒充原版输入。
- 它不是完整 ISO authoring tree；完整布局缓存属于具体 profile。

### `work/build/<profile>/components/`：候选组件

- domain writer 的输出，例如候选 SLPS、VT1 和 component validation。
- 只从原版成员和已提交的 profile/corpus/codebook 生成。
- 不同 profile 不共享可变候选文件；当前生产只登记
  `zh-release-full-story`。

### `work/build/<profile>/iso/`：ISO authoring 中间态

- `original/`：`dumps2iso` 得到的原版布局缓存；
- `staging/`：本次构建的 hardlink staging tree；
- `layout/`：原始/改写 XML 和 LBA 日志。

这些目录都可重建。构建器必须先逐成员校验 `original/`，再创建 staging；
不能把上一次 staging 当作下一次构建输入。

### `build/iso/<profile>/`：最终产物

- 只保存用户实际拿来运行的候选 ISO 和同次构建报告。
- 日常保留上表中的 7 份测试 ISO；SP 日文原盘另作必要构建输入。历史发布归档与日常列表分开。
- ISO 必须从对应 `work/build/<profile>/components` 和 authoring workspace
  一次生成，不允许 patch-over-patch。
- 输出路径由 config 固定，禁止回退到 `work/iso/` 或仓库根目录。

### `work/runtime/<profile>/`：运行证据

- LRPS2 自动 receipt、隔离记忆卡和截图按 scenario/session 隔离；PCSX2 手工证据
  由测试者另行保存。
- LRPS2 runner 只允许把 session 建在 `work/runtime/lrps2/` 子目录；即使显式传入
  `--output-directory` 也不能越界。
- 它们必须绑定最终 ISO、组件和 runtime address/hash。
- runtime 证据不是构建输入；删除它不会改变 ISO，但会失去相应运行结论。

`work/runtime/pcsx2-home/` 单独保存模拟器的可变 portable 配置和缓存，不属于
任何候选构建，也不能作为某个 profile 已通过运行验证的证据。

可提交的 byte-free 摘要仍位于 `manifests/`。原版成员、候选组件和完整 ISO
都不能进入 Git。

## 3. 生命周期

| 路径 | 是否可直接清理 | 恢复方式 |
| --- | --- | --- |
| `rom/original.iso` | 否 | 用户重新提供合法原盘 |
| `work/disc/` | 是 | 重新选择性提取 |
| `work/build/<profile>/components/` | 是 | 重跑 component build |
| `work/build/<profile>/iso/` | 是 | 重跑 ISO build；必要时 refresh extraction |
| `build/iso/<profile>/` | 仅旧候选和临时副本 | 按固定输入重建；上表中的冻结镜像及 current 槽位须保留 |
| `work/runtime/<profile>/` | 审核后 | 重跑 LRPS2 场景或重新执行 PCSX2 手工验收 |

清理命令不得把 `rom/`、仓库根目录或未解析变量作为递归目标。需要保留运行证明
时，应先确认 manifest 引用的日志、PINE 报告和截图已经有匹配哈希。

## 4. 当前门禁

当前 ISO build config 加载时强制：

- source ISO 位于 `rom/`；
- authoring workspace 位于 `work/build/<profile>/iso/`；
- replacement source 位于 `work/build/<profile>/components/`；
- ISO 与报告位于 `build/iso/<profile>/`；
- ISO 输出扩展名为 `.iso`；
- 所有路径均为项目内相对路径。

目录校验只证明所有权边界。成员 byte-exact、ISO9660/UDF、DVD 识别、LBA、
整镜像哈希和 PCSX2 运行结论仍由各自独立 gate 验证。

当前默认生产 profile 为 `zh-release-full-story`，Original ISO 为
`build/iso/zh-release-full-story/current-original.iso`；其静态报告
已通过；当前精确哈希的 fresh-process 启动和目标路线 runtime 仍待完成。构建与运行命令见
`BUILD_AND_RUNTIME.md`。
