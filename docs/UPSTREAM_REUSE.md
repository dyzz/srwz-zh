# 上游可复用资源清单

固定上游版本见 `config/upstream.lock.json`。项目协作方已确认允许直接复用并计划把通用修复贡献回上游，因此可复用 Python 源码已按原目录结构保存在 `vendor/upstream-python/`。所有文件固定到来源 commit，Windows 二进制仍不迁移、不执行。

## 固定参考与活动实现

| 能力 | 中文仓库实现 | 来源与边界 |
| --- | --- | --- |
| 上游 Python 最小快照 | `vendor/upstream-python/` | 23 个源码、配置和小型 fixture；当前不导入其中的 Python 模块 |
| 从 ISO 读取指定文件 | `tools/extract_iso_member.py` | 独立封装系统 `7z`；必须显式指定成员，不会整盘提取 |
| 外部偏移表切分归档 | `tools/srwz/archive.py` | 依据已知行为独立实现，增加严格 offset、尺寸和哈希校验 |
| `STAGE.BIN` 的 205 段布局 | `config/stage-offsets.json` | 将上游 824 字节表转换为 206 个数值，并固定来源 SHA-256 |
| 解码器和错误边界 | `tools/srwz/codec.py`、`codec_contract.py` | 中文仓库的严格实现；返回实际 consumed，不调用上游二进制 |
| 汉化数据解析 | `tools/srwz/text.py`、`menu.py`、`stage.py`、`summary.py` | 独立结构 parser；94,189 条与固定上游 XML 逐条一致 |
| 快照差异检查 | `tools/compare_upstream_snapshot.py` | 与相邻上游逐文件比较，便于识别可回馈的修改 |

活动入口会直接读取快照中的 `project/tbl_all.json` 和
`project/menu_files.json`。`Stages_Offset.bin` 的信息已固化为本项目
`config/stage-offsets.json`；其他上游 Python 只作来源可追溯的研究参考。

## 上游快照文件评估

| 上游路径 | SHA-256 | 结论 |
| --- | --- | --- |
| `tools/python/isotool.py` | `5bba46d40ced799b999bf6b680f5ec26e1e2d1d95cefc0c968df90cdc747c22f` | 保留完整 ISO 提取/重建参考；当前活动链不导入或执行，回包使用固定 `mkps2iso` |
| `tools/python/lib/FileIO.py` | `4bed381834864a3005c59f57abb3906dac38a023e912f4921d1cb9925e0e44fe` | 保留上游模块依赖闭包；当前活动链不导入 |
| `tools/python/lib/archive.py` | `556b59c3e06c41371cb02ff674aeaa5ea491ed30fe4165debbe80a554bc18e96` | 保留归档行为参考；当前实现为 `tools/srwz/archive.py` |
| `tools/python/lib/decompressor.py` | `cca948e01962d4deb74b6a032d9f5944ef0c5c29699c78fb420d21f15b65913e` | 保留格式研究参考；已知错误不进入当前 codec |
| `tools/python/lib/stage.py` | `43ffd60bc05e626ddcd6132a7cd8e4b01f538e1fd4a86caa2746c1ffe56a4b65` | 保留剧情结构和指针知识；当前 parser 独立实现 |
| `tools/python/lib/binary_extracted.py` | `ef75a0b6e2dd0d55143fa1f61fe1e9faf8a9e34cae2c832a2f4b5fbc7b12c0a0` | 保留文本行为参考；活动链只直接读取 `project/tbl_all.json` |
| `tools/python/lib/xml.py` | `938633dfa1fc4fd81d42aaf16d5331a321592bd8893bed5a83a2f686fde45b1e` | 保留上游中间格式参考；当前活动链不导入 |
| `tools/python/lib/LZ77.py` | `3d5ee81586837b56e5eb4acc21b84b254f018a12455ae300d8a9b4cb3145f853` | 教学型通用 LZ77，与 SRWZ 码流不兼容，不使用 |
| `tools/utilities/SRWZ.exe/.dll` | 未迁移 | Windows/.NET 参考工具；不执行、不提交 |
| `tools/utilities/CompressTool.exe` | 未迁移 | Windows 原生工具；不执行、不提交 |

## 精简决定

快照只保留两类内容：

1. 难以重新推导的 SRWZ 专用知识，例如归档/区段偏移、文本编码、控制码、剧情和 MTVPROS 结构。
2. 让 `SRWZ.py`、`stage.py` 和 `mtvpros.py` 保持上游原样时所需的最小导入依赖。

因此没有迁移另一套通用 CD/DVD/IML 构建链、薄 CLI、未使用的空壳模块、环境清单和镜像布局生成物。完整的 23 项保留清单以及 10 项排除理由见 `vendor/upstream-python/selection.json`。

## 回馈上游

`vendor/upstream-python/` 的 23 个入选上游文件应与固定提交逐字节一致：

```bash
python3 tools/compare_upstream_snapshot.py
```

中文工程专用功能放在 `tools/srwz/`。能够改善上游通用提取、解码或健壮性的修改，应保持小而独立，并在相邻上游建立分支后移植、测试和提交 PR。

已知上游兼容性：系统 Python 3.9 无法编译快照中的 `SRWZ.py:337` 和 `mtvpros.py:23`，原因是嵌套单引号 f-string。快照为保持逐字节一致没有修正；这两处适合以后作为独立上游 PR。

## 当前工作流

只提取 `STAGE.BIN`：

```bash
python3 tools/extract_iso_member.py DATA/STAGE.BIN
```

只切出用于 codec 研究的三个压缩块：

```bash
python3 tools/split_stage_archive.py --index 0 --index 1 --index 2
```

输出都位于 `work/`，不会进入 Git。以上命令只做 ISO 成员提取和 byte-range 切分，不会调用任何 SRWZ 解压程序。

本地已用原版基线验证这条路径：`STAGE.BIN` 的大小和 SHA-256 与 `manifests/original-disc.json` 一致，0、1、2 号块已经准备在 `work/stage/compressed/`。可提交的大小、offset 和哈希记录见 `manifests/codec-samples.json`，其中不含游戏字节。

完整菜单、数据库、剧情、摘要和 VT1 字库段解析使用：

```bash
python3 tools/parse_srwz_iso_data.py --force
```

结果和对照边界见 `docs/SRWZ_DATA_PARSING.md` 与
`manifests/iso-data-parse.json`。
