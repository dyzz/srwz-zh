# ISO 目录契约

状态：已实施。ISO 相关路径按“不可变输入、可重建中间态、最终产物、运行证据”
分层，并以 ISO profile ID 隔离。`tools/build_iso.py` 会在读取配置时
校验这些边界，错误路径不会开始构建。

本地工作数据统一放在本仓库的 `work/`，父目录同名目录已合并；分类、存档迁移
与历史缓存恢复方式见 [work 目录说明](WORK_DIRECTORY_LAYOUT.md)。

## 长期保留的 ISO

自 v0.4.1 发布后，本地长期保留以下八份 ISO：v0.4.0 与 v0.4.1 各两版冻结发布镜像、
两版日文原盘、两版 current 工作镜像。原盘使用 `original.iso` 与 `best.iso`。
机器可读路径见 `config/iso/retained-isos.json`。

| 槽位 | 实际路径 | 用途 |
| --- | --- | --- |
| `0.4.0-original` | `build/iso/v0.4.0/0.4.0-original.iso` | v0.4.0 初版冻结镜像 |
| `0.4.0-best` | `build/iso/v0.4.0/0.4.0-best.iso` | v0.4.0 The Best 冻结镜像 |
| `0.4.1-original` | `build/iso/v0.4.1/srwz-zh-v0.4.1-original.iso` | v0.4.1 初版冻结镜像 |
| `0.4.1-best` | `build/iso/v0.4.1/srwz-zh-v0.4.1-best.iso` | v0.4.1 The Best 冻结镜像 |
| `current-original` | `build/iso/zh-release-full-story/current-original.iso` | 当前 Original 中文工作镜像 |
| `current-best` | `build/iso/zh-release-best/current-best.iso` | 当前 BEST 中文工作镜像；身份及回读记录见 `manifests/editions/best/current.json` |
| `original` | `rom/original.iso` | Original 原盘，只读输入 |
| `best` | `rom/best.iso` | BEST 原盘，只读输入 |

v0.3.0、旧 `srwz-zh-current.iso` 与各工作区中的重复 ISO 不再长期保留。两版 current
可以随后续开发更新；四份版本化镜像保持各自发布时字节不变。两份 0.4.0 未压缩 ISO
同时作为后续玩家反馈的固定复现与调试基准，打包 ZIP 后也继续保留；不另增调试副本。
上传用 ZIP 独立保存，不计入八个 ISO 槽位。

目录仍按构建 profile 隔离；统一文件名不更换底盘、不修改镜像字节。Redump 的规范
文件名继续保留在来源元数据中，本地原盘路径使用上表名称。

构建期间允许在 `work/` 或版本隔离目录生成临时副本。验收、核对哈希并选定当前
产物后，移除重复 ISO 和旧候选，保留上述槽位；日志、组件、布局、输入快照、
存档和截图单独保留。阶段 1 的 Original 隔离输出
`build/iso/zh-release-original/current-original.iso` 属于此类临时副本，
它与当前生产输出逐字节相同时不重复长期保留。后续 BEST 构建仍写入
`current-best` 槽位；当前源码构建能力见 [BEST 构建](BEST_CURRENT_BUILD.md)，历史候选身份由新的本版构建记录替换。

清理先登记旧路径及文件身份，并确认文件未被构建或模拟器使用，再处理上述槽位
之外的旧 ISO 和重复副本。v0.4.0 本次清理先采用带恢复清单的归档；用户随后要求
积极清理不必要文件，已核对保留镜像和证据后永久删除清单中的旧 ISO 与缓存。
原路径的报告与预览继续保留，最终清单见 [work 目录说明](WORK_DIRECTORY_LAYOUT.md)。
被清理副本的历史 receipt 保留原始路径与哈希；复验历史批次时，从固定输入重建，
或从哈希一致的保留镜像重新制作所需临时副本。清理不构成新的构建或运行验收。

发布配置与发布校验清单保留打包时的 `srwz-zh-v0.4.0-<edition>.iso` 路径，作为
历史构建记录；本地长期保留路径以上表为准，两者的大小与 SHA-256 相同。需要复验
原发布打包命令时，临时将对应冻结镜像复制回发布配置要求的路径，核验结束后移除
临时副本。不得覆盖后续已经更新的 current 来复验旧发布。

## 1. 目录结构

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
- 长期保留四份冻结 `0.4.0`／`0.4.1` 镜像、`current-original` 和 `current-best`；精确路径见上表。
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
