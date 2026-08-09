# ISO 目录契约

状态：已实施。ISO 相关路径按“不可变输入、可重建中间态、最终产物、运行证据”
分层，并以 ISO profile ID 隔离。`tools/build_iso.py` 会在读取配置时
校验这些边界，错误路径不会开始构建。

## 1. 目录结构

```text
rom/
  srwz.iso

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
    pcsx2-sessions/
      <session-id>/
  toolchain/

build/
  iso/
    v0.1.0/
      srwz-zh-v0.1.0.iso
      iso-validation-v0.1.0.json
```

## 2. 各层所有权

### `rom/`：用户输入

- 只保存用户合法持有的原版镜像。
- 当前唯一默认输入是 `rom/srwz.iso`。
- 工具可以读取和校验，绝不修改、重命名、自动搜索或写回。
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
- 当前只保留一个实际运行候选；精确路径由选中的 ISO build config 声明。
- ISO 必须从对应 `work/build/<profile>/components` 和 authoring workspace
  一次生成，不允许 patch-over-patch。
- 输出路径由 config 固定，禁止回退到 `work/iso/` 或仓库根目录。

### `work/runtime/<profile>/`：运行证据

- PCSX2 日志、PINE 结果和截图按 profile 隔离。
- 它们必须绑定最终 ISO、组件和 runtime address/hash。
- runtime 证据不是构建输入；删除它不会改变 ISO，但会失去相应运行结论。

`work/runtime/pcsx2-home/` 单独保存模拟器的可变 portable 配置和缓存，不属于
任何候选构建，也不能作为某个 profile 已通过运行验证的证据。

可提交的 byte-free 摘要仍位于 `manifests/`。原版成员、候选组件和完整 ISO
都不能进入 Git。

## 3. 生命周期

| 路径 | 是否可直接清理 | 恢复方式 |
| --- | --- | --- |
| `rom/srwz.iso` | 否 | 用户重新提供合法原盘 |
| `work/disc/` | 是 | 重新选择性提取 |
| `work/build/<profile>/components/` | 是 | 重跑 component build |
| `work/build/<profile>/iso/` | 是 | 重跑 ISO build；必要时 refresh extraction |
| `build/iso/<profile>/` | 是 | 从固定输入重新构建 |
| `work/runtime/<profile>/` | 审核后 | 重新运行 PCSX2 fixture |

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

当前单一候选 profile 为 `zh-release-full-story`，ISO 为
`build/iso/v0.1.0/srwz-zh-v0.1.0.iso`；其静态报告
已通过；当前精确哈希的 fresh-process 启动和目标路线 runtime 仍待完成。构建与运行命令见
`BUILD_AND_RUNTIME.md`。
