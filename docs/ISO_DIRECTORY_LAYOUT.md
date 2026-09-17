# ISO 目录契约

状态：已实施。ISO 相关路径按“不可变输入、可重建中间态、最终产物、运行证据”
分层，并以 ISO profile ID 隔离。`tools/build_iso.py` 会在读取配置时
校验这些边界，错误路径不会开始构建。

本地工作数据统一放在本仓库的 `work/`，父目录同名目录已合并；分类、存档迁移
与历史缓存恢复方式见 [work 目录说明](WORK_DIRECTORY_LAYOUT.md)。

## 本地长期保存 CHD，ISO 按需还原

2026-09-17 按用户要求改为只保存 CHD 镜像。本体原盘、汉化发布版、current、
旧候选的 ISO 及上传用 ISO ZIP 不再长期占用磁盘；xdelta 补丁包、构建和运行证据继续保留。
机器可读保留与还原映射见 `config/iso/retained-isos.json`。其中 `path` 是按需生成的
ISO 目标路径，`chd_path` 才是本地长期保留文件，不应据此假定 ISO 已经存在。

| 长期保留文件 | 位置 | 依赖 |
| --- | --- | --- |
| Original / Best 日文父 CHD | `build/chd/v0.4.2/srwz-jp-{original,best}.chd` | 无 |
| v0.4.2 四份中文子 CHD | `build/chd/v0.4.2/srwz-zh-v0.4.2-{original,best}[-skip].chd` | 对应日文父盘 |
| v0.4.1 两份中文子 CHD | `build/chd/v0.4.1/srwz-zh-v0.4.1-{original,best}.chd` | 对应日文父盘 |

v0.4.1 目录中的两个同名日文父盘是指向 v0.4.2 父盘的硬链接，共用一份文件数据；
父盘视为不可变。每个中文子盘直接依赖对应日文父盘，带 skip 子盘不依赖不带 skip 子盘。
父盘和子盘须一起保留。日文父盘仅本地使用，不放入公开补丁发布包。

清理前已从两份父盘和六份子盘重新提取 ISO，逐一核对大小、SHA-1、SHA-256，
确认与现有 ISO 完全一致。v0.4.0 的两份 ISO 在本次清理前已经不在本地，也没有
对应 CHD；配置中的路径只保留历史记录，不代表可以从本地恢复。

本次未处理仍在分析中的 Special Disc 原盘及其 canary ISO，也未处理仓库外的第二次 Z 镜像。

### 构建和复验前还原 ISO

现有构建器仍使用 ISO 输入；CHD 保存方式不改变构建器的格式要求。从仓库根目录运行：

```sh
# 列出本次归档可以还原的槽位
python3 work/cleanup/chd-only-20260917/restore_iso.py
# 还原构建所需的两版日文原盘
python3 work/cleanup/chd-only-20260917/restore_iso.py original
python3 work/cleanup/chd-only-20260917/restore_iso.py best
# 按需还原某个冻结发布版本
python3 work/cleanup/chd-only-20260917/restore_iso.py 0.4.2-best-skip
```

本地辅助脚本依赖 `chdman`，提取后校验 SHA-256，拒绝覆盖已有目标。
也可直接执行 `chdman extractdvd -i <子CHD> -ip <父CHD> -o <ISO>`；
还原日文父盘本身时不传 `-ip`。完成构建或复验后，可移除临时 ISO。
新构建镜像须先另存为子 CHD，并通过还原校验，才能删除其唯一的 ISO 副本。

`current-original` / `current-best` 的归档映射只记录此次清理时的内容，恰与 v0.4.2
不带 skip 发布版一致；后续构建会变化，不能用旧发布版代替新 current。
原发布配置、receipt、ZIP 清单保留历史路径和哈希，不改写成仍有文件的假象。
源码快照、报告、布局、存档、截图和当前组件继续保留；旧游戏二进制缓存按需重建。
完整删除清单、CHD 还原证明和恢复映射见 `work/cleanup/chd-only-20260917/`。
本次清理不构成新的构建或模拟器运行验收。

## 1. 目录结构

以下 ISO 与装配目录为构建时路径，清理后允许不存在；长期存储以以上 CHD 表格为准。

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
- 长期保留八份冻结 `0.4.0`／`0.4.1`／`0.4.2` 镜像、`current-original` 和 `current-best`；精确路径见上表。
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
