# SP 构建记录修复与发布保护

2026-09-20。当前 `build/iso/special-disc/sp-current.iso` 的全量文本校验已恢复。

## 原因与复现结果

原清单锁定的五份组件报告仍指向可复用的 `work/build/special-disc/full-text/`
目录。后续组件重跑覆盖了这些报告；其中 `frame/report.json` 是一次失败尝试，
记录概要超行、旁白超行和“讥”字缺少映射。旧脚本在失败退出之前就覆盖报告，
对应二进制只在成功后写出，导致报告与组件文件可能属于不同构建。

使用当前代码、语料和字库隔离重跑时，三项旧错误均未复现，系统组件也没有
剩余未写入项。本次没有改动译文或字库。完整重建得到的镜像与修复前当前镜像
SHA-256 完全一致：

`015240db92db0c0a72604257adecc52662d92b0393e79e90e7f9fe60a1067c6e`

恢复出的 frame 报告哈希也与原清单期待值一致：
`1b1303f6dbbe4a47c55b51dd5517d045de02e5836a1c78a64e0ef7b14b2aab18`。
因此本次修复的是报告归属与构建流程；正式 ISO 字节没有变化，既有 Z 双路线
默认奖励补丁及相同镜像的 LRPS2 验证仍有效。

## 流程修正

- `write_frame_text.py`：失败报告写到输出目录旁的 `frame.failed.json`；成功时
  先准备完整组件目录，再发布报告和二进制，避免失败覆盖上次成功产物。
- `build_full_text.py`：普通完整构建默认使用 `full-text/runs/build-*` 独立目录，
  清单锁定本次的五份报告。显式 `--work-directory` 在完整构建时必须是新目录。
- 临时 ISO 完成成员读回、范围检查和 `verify_full_text.py` 全量文本验证后才
  替换目标镜像及清单；校验失败或发现目标已被另一写入者更新时保留原目标。
- `verify_full_text.py` 与非关卡文本导出器从当前清单定位组件报告，不再固定
  读取会被旧重跑覆盖的目录；校验器同时拒绝混合构建目录。

默认构建命令不变：

```sh
python3 tools/special_disc/writeback/build_full_text.py
python3 tools/special_disc/verification/verify_full_text.py
```

复用某次已完成组件构建时，必须明确指定目录：

```sh
python3 tools/special_disc/writeback/build_full_text.py --assemble-only \
  --work-directory work/build/special-disc/full-text/runs/repair-20260920
```

## 验证与证据

完整重建先在候选镜像通过全量验证；确认镜像及全部成员哈希与当前版本相同后，
才将当前清单绑定到新报告。随后针对当前 `sp-current.iso` 再次执行默认全量
校验命令，退出码为 0。临时重复 ISO 已删除，正式输出目录仍仅保留当前镜像。

本次读回计数包括：8,754 条关卡文本、1,338 个编队字段、147 个外围文本目标、
1,679 处系统文本、128 处流程图话数标签、110 个 Z 标题、35 个字幕槽、
621 处地形名称，以及双路线奖励代码与说明文字。SRVC、图片组件通过最终
ISO 成员哈希与组件回执绑定验证。

- 新组件及读回：`work/build/special-disc/full-text/runs/repair-20260920/`。
- 修复前清单、候选验证、当前验证及测试日志：
  `work/verification/sp-full-text-repair-20260920/`。
- SP 专项：86 项中 81 项通过，5 项因系统 Python 未安装 Unicorn 跳过；这 5 项
  已在奖励补丁的独立 Unicorn 环境中通过。
- 新增 3 项发布保护测试，覆盖失败保留旧报告与文件、成功发布完整组件、校验
  失败／并发更新时保护正式镜像；已包含在上述 86 项中。

此次为构建与静态读回修复，没有扩大 LRPS2 或 PCSX2 的既有运行验收范围。
