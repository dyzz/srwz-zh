# 测试范围

测试按被测模块命名，覆盖解析、控制码、字体、布局、归档、Rust 压缩、TIM2、
组件组合、ISO/LBA 和运行证据 schema。

剧情语料使用覆盖全部 170 个含对白资源的领域级门禁；具体译句只保存在 `corpus/`，
不再为早期关卡复制一套逐句期望值。

```bash
python3 -m compileall -q tools tests
python3 -m unittest discover -s tests -p 'test_*.py'
```

默认测试只覆盖生产语料、组件和 ISO 链路，不导入或重建 `work/review/` 下的人工
审核网页。审核网页的候选统计会随尚未定稿的人工决策变化，也不属于确定性 ISO 的
输入。审核页面只通过 `python3 tools/build_editorial_review.py` 手动重建，不属于默认
测试套件。

生产压缩测试构建 `tools/native/srwz-codec-rs/`，再由 Rust decoder 回解；Python
严格 decoder 只允许出现在隔离的格式对照单元测试中，生产与静态验收不得调用。
仓库不再包含 Python/C 生产压缩加速路径。需要原盘、ImageMagick、mkps2iso 或
PCSX2 的测试在输入缺失时必须明确 skip 或 fail closed，不得伪造通过。普通最终组件
构建读取冻结的世界地图标题渲染快照，因此不再因地图标题启动 ImageMagick。

单元测试和 ISO 静态回读不能替代目标运行流程。运行结论必须使用当前精确 ISO、
匹配存档和对应 receipt。
