# 贡献与发布约定

本仓库只提交可审查源码、中文语料、配置、测试和不含游戏字节的验证摘要。
`rom/`、`work/`、`build/`、`outputs/`、存档和完整镜像均为本地数据，不得提交。

## 修改边界

- 日文原版是唯一翻译源；英文和社区资料只能作为术语参考。
- 中文决定写入 `corpus/zh/`，术语写入 `corpus/glossary/`，不得把 `work/`
  中的派生结果当作事实源。
- 所有写回必须锁定输入哈希、目标前像、容量和非目标字节；禁止静默截断。
- 生产压缩只使用 `tools/native/srwz-codec-rs/`。Python codec 只承担严格解码、
  小样本 round-trip 和回归 oracle。
- 不执行上游 EXE/DLL、Wine 或 Mono，不修改相邻上游仓库。

## 提交前检查

```bash
python3 tools/verify_original_disc.py
python3 -m compileall -q tools tests
python3 -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

涉及最终组件或 ISO 时，还要运行对应 verifier，并把结论绑定到精确制品哈希。
静态回读、模拟器启动、目标流程和画面验收是不同证据层，不能互相替代。

准备补丁包时运行：

```bash
python3 tools/build_release.py --config config/release/v0.1.0.json
```

完整 ISO 只保留在本地 `build/iso/`。`build/release/` 只能包含 xdelta 补丁、说明、
清单、校验文件和它们的归档，不能包含 ISO；发布工具必须实际还原并核对目标哈希。

提交前用 `git status --short` 和 `git diff --stat` 确认范围；只有用户明确授权后
才提交、推送或发布补丁。
