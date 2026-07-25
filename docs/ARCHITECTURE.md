# 工程架构

## 数据边界

工程将数据分为三层：

1. `rom/`：用户本地、不可变的原版 ISO，永不提交。
2. `corpus/`、`config/`、`patches/`：中文工程的可审查源数据；
   SurfaceSpec、中文决策、codebook 和 BuildProfile 是生产事实源。
3. `work/`：提取缓存、按 profile 隔离的组件/ISO 中间态和运行证据。
4. `font/generated/` 和 `build/`：从源数据生成的最终产物，永不作为唯一来源。

ISO 相关目录不得混用：`rom/` 只读，`work/build/<profile>/` 可重建，
`build/iso/<profile>/` 才是模拟器加载的最终镜像。完整契约见
`ISO_DIRECTORY_LAYOUT.md`。

## 构建流水线

```text
原版校验
  -> 提取与 round-trip 校验
  -> SurfaceSpec 与日文语料哈希基准
  -> BuildProfile reconciliation
  -> 中文译文、编辑状态与术语检查
  -> 字符集和字形生成
  -> 中文断行与空间检查
  -> 文本、字库和 ASM 回插
  -> ISO 重建
  -> PCSX2 运行验证
  -> 补丁打包
```

每个阶段都应产生清单或测试结果。任何缺字、无法编码字符、文本池溢出、超过最大行数或来源哈希变化都必须令构建失败。

当前已实现的最小生产路径是
`config/build-profiles/canary-menu.json`。它连接
`config/surfaces/menu-slps-opening.json`、`corpus/zh/menu.json` 和
`config/encoding/codebook.json`，并由 `tools/srwz/project.py` fail-closed
校验。静态 canary 与 PINE 验证器从同一个 profile 读取译文、字形和地址；
旧 canary 配置只保留构建环境与 E0 golden。字段和新增 surface 流程见
`PRODUCTION_PIPELINE.md`。

ASM 阶段额外由 `config/toolchain/armips.lock.json` 固定官方 MIT armips 源码、
构建环境和产物哈希；`config/patches/upstream-asm-audit.json` 固定原版前像、
最终差异集合、写入所有者、允许区间和显式覆盖。未知输入、文件扩容、越界写入
或未登记覆盖不会生成可接受产物。

## 上游集成

上游仓库固定到明确提交，并以源码快照保留逆向参考和可复用 Python 工具。
当前活动实现位于中文仓库，只读取少量固定数据定义并按需做结果对照，避免依赖
上游工作树中的未提交状态；若以后直接复用或修复上游代码，通用差异应整理为可
贡献回上游的改动。

如果以后改用 submodule 或 subtree，应同步更新 `config/upstream.lock.json`，并保持中文语料、ROM 和构建产物不进入上游。

当前同时保留两层：`vendor/upstream-python/` 是未修改的上游参考快照；
`tools/srwz/` 是中文工程的 clean-room 实现。当前核心库不导入快照中的
Python 模块，只由少数入口读取固定数据表并进行行为对照。Windows 二进制仍不
迁移。详细复用边界见 `UPSTREAM_REUSE.md`，模块和外部依赖归属见
`../tools/README.md`。
