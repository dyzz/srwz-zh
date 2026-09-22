# ISO 目录契约

2026-09-22 更新：带明确版本号的 ISO 保持原位；其他 ISO 的实体文件统一存放在本仓库 `build/` 下。原盘、当前产物、构建缓存、验证候选分别存放，避免把历史候选误当成当前镜像。

## 当前目录

```text
build/
  iso/
    sources/                         # 三份日文原盘，只读输入
      original.iso
      best.iso
      Super Robot Taisen Z - Special Disc [J].iso
    zh-release-original/
      current-original.iso           # 本篇当前构建
    zh-release-best/
      current-best.iso               # BEST 当前构建
    special-disc/
      sp-current.iso                 # SP 当前构建
      sp-current.json
    daily-test/                      # 自动更新的三版当前 ISO 精确副本，均内置 skip
      current-original-skip.iso
      current-best-skip.iso
      current-sp-skip.iso
    v0.4.2/                          # 带版本的冻结发布镜像，原位保留
    .tmp/baselines/                   # SP 基线还原临时盘，随进程退出清理
  editions/
    zh-release-original/<run-key>/project/
    zh-release-best/<run-key>/project/
    zh-release-sp/<run-key>/project/  # 各版独立工作区；内部原盘副本及 ISO 均位于 build 下
  verification/
    sp-flow-layout-20260922/          # 验证候选及同次报告
    instructions-final-20260922/
  chd/                               # 已有正式发布 CHD
  release/                           # 已有发布包
```

构建输入快照仍在 `work/build/shared/`，提取成员、组件、日志和运行证据仍按各自用途放在 `work/`。共享快照不包含完整 ISO；三版会在 `build/editions/` 下使用独立可写副本。

## 兼容入口与构建引用

原有配置、历史报告和本地运行记录继续通过相对目录链接访问原位置：

| 兼容入口 | 实体目录 |
| --- | --- |
| `rom/` | `build/iso/sources/` |
| `work/build/zh-release-original/` | `build/editions/zh-release-original/` |
| `work/build/zh-release-best/` | `build/editions/zh-release-best/` |
| `work/build/zh-release-sp/` | `build/editions/zh-release-sp/` |
| `work/verification/sp-flow-layout-20260922/` | `build/verification/sp-flow-layout-20260922/` |
| `work/verification/instructions-final-20260922/` | `build/verification/instructions-final-20260922/` |

链接只提供旧路径入口，不保存另一份 ISO。配置中的 `rom/original.iso` 等路径仍有效，原盘身份锁不变。新工作区可先创建 `build/iso/sources/`、将三份原盘放入，再创建指向该目录的 `rom` 相对链接；不要覆盖已有的真实 `rom` 目录。

统一构建器直接在 `build/editions/<profile>/<run-key>/project` 中运行，不依赖旧工作区链接来决定新输出位置。SP 差分与锁仍在 `work/build/special-disc/baselines/`，还原出的临时 ISO 使用 `build/iso/.tmp/baselines/`。

## 保留与清理

- 原盘只读，必须匹配各版 `config/editions/<edition>/edition.json` 的大小、SHA-256 与可执行文件身份。
- 带版本的冻结发布镜像保持路径和内容不变。父目录 `SRWZ2/SRWZ2CHS2.5.iso` 同样属于带版本文件，未移动。
- 三份当前 ISO 由 `manifests/editions/{original,best,sp}/current.json` 绑定；整理目录不触发重建、不改变镜像字节。
- `daily-test/` 的三版镜像由统一构建器在该版回读通过后自动更新，内容与对应当前 ISO 一致且均含 skip。路径策略见 `config/iso/daily-test-isos.json`，实际身份见各版 `manifests/editions/<edition>/current.json` 的 `daily_test` 字段。
- 私有工作区和验证候选可能仍被历史回读报告引用；本轮保留其内容及引用关系，不仅凭文件名相同判断重复。
- 不使用硬链接共享可写的私有构建文件，保留版本之间的写入隔离。
- 新的完整 ISO 候选使用 `build/iso/`、`build/verification/` 或 `build/editions/`；普通二进制成员缓存继续使用 `work/`。
- 正式发布 CHD 的父子依赖保持原样。ISO、原盘成员、CHD、存档和私有构建文件均不进入 Git。

## 本轮检查

工作区及父目录共盘点 54 个 ISO：51 个非版本 ISO 全部位于本仓库 `build/` 内；3 个带版本 ISO 保持原位。其中 46 个 ISO 原先位于 `build/` 外，通过同卷目录移动完成整理。

移动前后逐个核对全部 54 个文件的设备号、inode、大小和修改时间，并检查旧路径仍能访问同一文件。三版当前 ISO 的实际哈希、冻结输入和最终回读凭据重新核验；三份原盘重新校验身份。相关 40 项测试通过，包括新版工作区路径、SP 临时盘位置、版本隔离与发布保护。

本地清单与证据：`work/reviews/iso-cleanup-20260922/`。已有三版内容回读凭据保持有效：

```sh
python3 tools/verify_editions.py --manifest manifests/editions/misc-text-20260922.json
```

目录和哈希检查不代替 PCSX2 游戏运行验收。
