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

Python 生产入口通过 `worker-stdio` 为每个构建线程复用一个 Rust 进程，编码输入与
结果均在管道中传输，不再为每块创建进程和临时文件。线程退出时关闭其 worker，
构建结束时清理剩余 worker；工具二进制身份变化后，下次请求启动新进程。
原来的 `decode-stdio`、`payload`、`encode` 单次命令仍可用于独立比对。

请求使用小端 `8s7Q`：`SRWZQ001`、操作（0 解码／1 编码 payload）、输入长度、
window size、prefix size、minimum match length、search chain、lazy bias（全 1 表示
完整候选集）。随后是输入字节。响应使用小端 `8s2Q`：`SRWZR001`、状态（0 成功／1
编解码错误）、结果长度，随后是结果字节。解码成功的结果沿用 `SRWZD001` 元数据
及解压字节；错误结果为 UTF-8 消息，消费后可以继续下一条请求。帧上限 512 MiB，
解码仍使用原来的 256 MiB 输出、10 字节 coded integer 和 1,000 万 token 限制。
