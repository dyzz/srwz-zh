# 测试范围

测试按被测模块命名，覆盖解析、控制码、字体、布局、归档、Rust 压缩、TIM2、
组件组合、ISO/LBA 和运行证据 schema。

剧情语料使用覆盖全部 154 个资源的领域级门禁；具体译句只保存在 `corpus/`，
不再为早期关卡复制一套逐句期望值。

```bash
python3 -m compileall -q tools tests
python3 -m unittest discover -s tests -p 'test_*.py'
```

生产压缩测试构建 `tools/native/srwz-codec-rs/`，再由 Python 严格 decoder 回解；
仓库不再包含 Python/C 生产压缩加速路径。需要原盘、ImageMagick、mkps2iso 或
PCSX2 的测试在输入缺失时必须明确 skip 或 fail closed，不得伪造通过。

单元测试和 ISO 静态回读不能替代目标运行流程。运行结论必须使用当前精确 ISO、
匹配存档和对应 receipt。
