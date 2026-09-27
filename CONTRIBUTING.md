# 贡献与发布约定

本仓库只提交可审查源码、中文语料、配置和不含游戏字节的验证摘要。
`rom/`、`work/`、`build/`、`outputs/`、存档和完整镜像均为本地数据，不得提交。

## 修改边界

- 日文原版是唯一翻译源；英文和社区资料只能作为术语参考。
- 中文决定写入 `corpus/zh/`，术语写入 `corpus/glossary/`，不得把 `work/`
  中的派生结果当作事实源。
- 所有写回必须锁定输入哈希、目标前像、容量和非目标字节；禁止静默截断。
- 生产压缩和解压只使用 `tools/native/srwz-codec-rs/`。
- 不执行上游 EXE/DLL、Wine 或 Mono，不修改相邻上游仓库。

## 提交前检查

先将测试依赖安装到运行测试的同一个 Python 环境：

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests
```

`requirements-dev.txt` 固定 Unicorn 版本，用于执行 MIPS 原生指令测试，包括 SP
默认双路线奖励。安装后这些测试不应再因缺少 Unicorn 而跳过；依赖本地原版文件
或其他运行条件的测试仍可能跳过。需要隔离环境时，可先用 `python3 -m venv .venv`
创建环境并执行 `source .venv/bin/activate`，再运行上述命令。

```bash
python3 tools/build_editions.py --plan
git diff --check
```

单元测试已导入全部生产链模块，不必再单独执行 `compileall` 或各入口的 `--help`；
原盘校验由每次构建自行完成。涉及最终组件或 ISO 时，运行
`python3 tools/build_editions.py`（必要时加 `--editions`），并用
`python3 tools/verify_editions.py --manifest <批次 JSON>` 把结论绑定到精确制品哈希。
静态回读、模拟器启动、目标流程和画面验收是不同证据层，不能互相替代。

准备补丁包时先冻结同一批次已验证的 Original、The Best 和 SP，再生成补丁
（后续 release 必须包含三版，全部内置 skip，每版一份）：

```bash
python3 tools/freeze_release.py --manifest work/editions/<摘要>/original-best-sp.json --version <x.y.z>
python3 tools/build_release.py --config config/release/v<x.y.z>.json
```

完整 ISO 只保留在本地 `build/iso/`。`build/release/` 只能包含 xdelta 补丁、说明、
清单、校验文件和它们的归档，不能包含 ISO；发布工具必须实际还原并核对目标哈希。

提交前用 `git status --short` 和 `git diff --stat` 确认范围；只有用户明确授权后
才提交、推送或发布补丁。
