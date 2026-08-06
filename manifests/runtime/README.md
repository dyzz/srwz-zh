# 运行用例收据

本目录只保存经过审阅的 hash-only 运行收据，不保存截图、纹理、日志、存档、
ISO 或游戏字节。逐用例收据放在 `ui-cases/*.json`，release 级启动／关卡入口
收据可放在本目录根部。UI 用例必须由
`config/runtime/ui-test-matrix.json` 的对应 case 以路径和 SHA-256 锁定。

生产流程：

1. `prepare_ui_runtime_case.py` 在被忽略的 `work/runtime/ui-cases/` 生成
   case plan 和空白草稿；
2. 从新 PCSX2 进程启动精确 ISO，再由 `probe_ui_runtime_session.py` 记录
   PINE、DVD／ELF、日志和零 TLB 结果；
3. 填入截图／序列、逐条断言和已知限制，用
   `verify_ui_runtime_evidence.py` 生成本地 hash-only receipt；
4. 人工审阅后才把 receipt 提交到 `ui-cases/`，更新矩阵并重新审计。

receipt 绑定 `matrix_plan_sha256`。该哈希覆盖矩阵中的路线、采集点、断言、
制品、fixture 与模拟器约束，只排除每个 case 的 `runtime_status` 和
`runtime_evidence`；这样矩阵可以反向锁定 receipt，而不会形成循环哈希。

当前矩阵中的 UI surface 用例仍须独立验收；release 级关卡入口收据不能替代
这些视觉／交互用例。
