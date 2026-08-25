# 工程架构

## 数据边界

工程分为四层：

1. `rom/`：用户本地、不可变的原版 ISO，永不提交。
2. `corpus/`、`config/`：可审查的生产源数据。
3. `work/`：提取缓存、profile 组件、ISO 中间态和本地运行证据。
4. `work/build/`、`build/`：可由源数据重建的组件与最终产物。

生产事实源是领域配置、中文语料、codebook／字体账本、最终组件配置和 ISO profile；
manifest 用于锁定输入与结果。`work/`、`build/` 和 dashboard 都不能成为唯一
译文或唯一配置来源。

## 构建流水线

```text
原版哈希与布局
  -> 严格解析和稳定 ID
  -> 来源哈希 reconciliation
  -> 译文、术语和结构 token
  -> 字体、编码和布局预算
  -> 前像受控写回
  -> Rust 原生格式压缩
  -> 组件与归档回读
  -> 单候选 ISO/UDF/LBA
  -> LRPS2 automated runtime / PCSX2 manual runtime
  -> visual/interaction acceptance
```

每层均产生机器可检查结果。来源变化、缺字、无法编码字符、溢出、未登记指针、
压缩超预算、非目标字节变化或证据哈希不匹配必须令构建失败。

模块归属：

- `tools/srwz/`：clean-room parser、codec、writer、ISO 和证据核心；
- `tools/native/srwz-codec-rs/`：生产压缩器；
- `tools/*.py`：薄 CLI 与 orchestration；
- `config/`：地址、成员、surface、字体、写回和 profile；
- `manifests/`：可提交的 hash-only 构建与回读结果。

字段和新增 surface 顺序见 `PRODUCTION_PIPELINE.md`。

## 不可替代的证据层

| 层 | 证明内容 | 不能证明 |
| --- | --- | --- |
| source／translation | 原文、译文、术语与状态 | 可编码、可写回 |
| component | 字体、文本、归档和前像正确 | ISO 可启动 |
| ISO | UDF、成员、大小、哈希和 LBA | 目标游戏路径正确 |
| runtime | 精确 ISO 在匹配存档上到达目标 | 所有画面均已验收 |
| visual | 指定截图、纹理和交互断言 | 未覆盖路线和边界用例 |

旧候选的 runtime 或 screenshot 只属于其原 ISO 哈希。

仓库内自动 runtime 只使用 LRPS2/libretro.py；PCSX2 保留为测试者手工画面验收，
不再由仓库脚本发送键盘事件。两条 runtime 证据必须分别记录，不能相互冒充。

## 上游与工具链

- 上游固定到 `config/upstream.lock.json` 指定的提交；`vendor/upstream-python/`
  只保留当前链直接读取的两份静态 JSON，并由
  `selection.json` 声明用途。
- 活动实现全部位于中文仓库；核心库不导入上游 Python 模块，只读取少量固定
  数据定义。
- 不执行上游 EXE/DLL、Wine 或 Mono。Windows 二进制、预制汉化成员和未提交
  上游工作树都不是生产输入。
- ISO 固定使用 config 锁定的 `mkps2iso` v1.1.1；当前生产闭包不包含 ASM
  patch 或外部 Windows 工具链。
- 通用修复应保持差异可追溯，便于贡献回上游；中文语料、ROM 和构建产物不得
  进入上游仓库。

## 写入与发布原则

- 原版只读；候选始终写入 profile 隔离路径。
- 每处二进制写入必须有前像、边界和唯一 owner。
- 不静默截断、不复用未证明安全的 glyph、不做 patch-over-patch。
- `runtime_verified` 必须绑定精确 ISO、存档、路线、日志、截图和断言。
- 发布包不得包含原版数据、完整 ISO、存档或私有本地证据。
