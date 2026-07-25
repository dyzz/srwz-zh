# 上游 Python 工具快照

来源：

- 仓库：`https://github.com/fortiersteven/Super-Robot-Wars-Z`
- 分支：`main`
- 固定提交：`a6cefe8b51dfd949e16000442084d24594841e8f`
- 本地参考路径：`../`

本目录只保留经筛选的上游文件，并保持入选上游文件的原始目录结构和内容
不变，用于中文工程研究、结果对照、按需复用，以及后续把通用修复贡献回上游。
项目协作方已确认允许复用；同步时仍应保留来源提交和贡献记录。当前中文活动
链不导入这里的 Python 模块，只直接读取两份固定项目 JSON 数据表。

## 包含内容

- `tools/python/lib/SRWZ.py` 及其完整的本地导入依赖。
- `stage.py`、`mtvpros.py`、`binary_extracted.py` 和 `decompressor.py` 等游戏专用格式参考。
- 上游完整流程曾使用的 `isotool.py`、`files.txt` 和
  `Stages_Offset.bin`；当前中文活动链不导入或执行这些 Python 模块。
- `tools/python/tests/` 的控制码 fixture。
- 保存归档位置、区段、菜单和字符编码知识的四个 `project/*.json`。

共 23 个上游文件。逐项用途和排除理由记录在 `selection.json`，比较工具会同时检查快照没有缺项或未声明的额外文件。

## 未包含

- `SRWZ.exe`、`SRWZ.dll`、PDB、`CompressTool.exe`、`armips.exe` 等二进制。
- `Compdata.xml`、译文、图片、字库和从游戏生成的大型数据。
- `__pycache__`、备份和临时文件。
- `LZ77.py`：它是教学型通用 LZ77，与 SRWZ 自定义码流不兼容。
- `cd.py`、`dvd.py`、`iml.py`、`main_iml.py`：未被核心编排调用的旧 IML 构建链。
- `main.py`：容易按中文工程接口重写的薄 CLI。
- `mtv_bgc.py`：包含硬编码本机路径，偏移知识已收录在 `archives.json`。
- `library.py`：未被引用的空壳模块。
- `requirements.txt`、`files_list.txt`、`srwz.ims`：环境或镜像相关清单/生成物，不作为逆向知识迁移。

## 使用方式

快照中的脚本保留上游路径假设和依赖，不承诺能在中文仓库根目录直接运行。中文工程应优先在 `tools/srwz/` 中增加适配层或可回馈上游的修复，并用测试固定行为。

系统 Python 3.9 对整份快照执行 `compileall` 时，当前上游的 `SRWZ.py:337` 和 `mtvpros.py:23` 会因嵌套引号 f-string 语法失败；这是原样保留的上游状态，不是迁移损坏。新工具保持 Python 3.9 兼容，若修复这两处应作为独立的上游兼容性贡献。

检查 23 个入选文件是否齐全、没有夹带未声明文件，并与相邻上游逐字节一致：

```bash
python3 tools/compare_upstream_snapshot.py
```

当快照内出现有意修改时，这个命令会列出差异文件；可以据此在相邻上游建立分支并移植改动。
