# SRWZ Rust codec

仓库自有的 clean-room SRWZ 生产压缩与解压工具。v0.3.0 的组件构建、压缩后回读和
ISO 验证均使用此实现；编码结果必须完整回解并满足原成员字节／扇区预算。

```bash
python3 tools/build_rust_compressor.py --force
```

release 可执行文件由 Cargo 构建到忽略目录：

```text
work/toolchain/srwz-compressor-rs/target/release/srwz-compress
```

命令参数、match 策略和工具链提交由 v0.3.0 配置及构建入口锁定，普通发布构建无需
单独调参。
