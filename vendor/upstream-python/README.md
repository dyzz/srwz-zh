# 上游静态数据快照

来源仓库 `fortiersteven/Super-Robot-Wars-Z`，固定提交
`a6cefe8b51dfd949e16000442084d24594841e8f`。

当前目录只保留生产链直接读取的 `menu_files.json` 与 `tbl_all.json`。归档地址
已经固化在 `config/assets/archive-inventory.json`，不再重复保留上游地址文件。
上游 Python 实现、测试 fixture、ISO 清单和研究脚本已经移除，活动实现全部
位于 `tools/srwz/`，且不会执行上游 EXE、DLL、Wine 或 Mono。

逐项用途见 `selection.json`。来源提交和复用边界见
`../../config/upstream.lock.json`。
