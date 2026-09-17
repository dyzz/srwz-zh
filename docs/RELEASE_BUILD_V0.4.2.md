# v0.4.2 紧急修复构建与发布记录

2026-09-17。修复 Best 的 STAGE 111 与 150 地图事件分发表损坏，默认发行镜像关闭方块 skip，并为两版另提供可选 skip 补丁。四份 xdelta 均直接以对应日文原盘为输入。

第 47 话黑屏由用户“贴吧用户_a6bM8ty”反馈；后续排查发现另一处同类事件表问题。

## 源码与修复边界

- `d5646c1`：为两关文本尾部和地图事件表建立独立边界；恢复原生 Best 全部十个事件目标，同步修改读表指令。编译及最终 ISO 解压回读均执行检查。
- `65de477`：仅同步两条过期测试断言，分别对应已经提交的 9 月 15、16 日译文；没有为通过测试修改语料。
- `25f302e`：默认关闭方块 skip，新增四种发布变体的冻结、独立变换校验、xdelta 和父子 CHD 打包支持。

最终双版本输入摘要：`531f76bfcc7d981c00c443037822fef5751a692f44cf7a743a5074be2a293858`。
构建快照在上述提交前已经包含实际工作树修改，因此快照的 `source_head` 仍为 `cfa8669`，不能只凭该字段推断构建内容。

逐文件核对确认：编译所用生产工具、语料、字库及版本布局配置与提交后源码一致。随后更新的 `retained-isos.json` 仅增加发布镜像保留槽位。快照还包含一份预先存在、未参与生产构建的只读分析模块 `tools/srwz/stage_events.py`，本次没有将他人的未提交工作纳入提交。详见 [源码绑定](../manifests/releases/v0.4.2/source-binding.json)。

## 冻结镜像

路径均位于 `build/iso/v0.4.2/`；大小遵循对应日文原盘，Original 为 3,758,358,528 字节，Best 为 3,755,081,728 字节。

| 文件 | SHA-256 |
| --- | --- |
| `srwz-zh-v0.4.2-original.iso` | `6a72307c36ec6b2f7f0af9e6f31d1a88cdb092af7d1b64377341c2e4b7e0e50c` |
| `srwz-zh-v0.4.2-original-skip.iso` | `83cbf6bd8863c8a8ce22113431b7c40f2c3d61aa383ff7da8fa22047930b8e47` |
| `srwz-zh-v0.4.2-best.iso` | `081b4ce998b9c71ba17f84f5e410e6bfa0b99b9d4582711f2d72d60defa6cc1a` |
| `srwz-zh-v0.4.2-best-skip.iso` | `c87442d9d8f2cb8c4399292ed135e9682f45e0f0e7c6461988fbb6e3557a15cb` |

两个默认版本由同一输入批次分别构建并完成静态语义回读。可选 skip 版本从对应默认版本应用现有精确指令契约生成，再独立核对整盘：目录、大小、LBA、全部非可执行文件字节不变，可执行文件只能是声明的 skip 变换结果。打包前还会重新读取实际 ISO 验证这一关系。

Best skip 镜像与此前运行通过的诊断镜像**整盘完全一致**。Original skip 镜像与本次修复前正常使用的 current-original 完全一致。两份默认镜像则仅关闭各自的 skip 补丁。

## 检查与运行证据

- `python3 -m unittest discover -s tests`：首次发现 334 项，333 项通过；缺少 Unicorn 时，整个 `test_battle_square_skip_native.py` 模块被记成一个 skipped 项。随后在隔离环境安装 Unicorn 2.1.4，补跑该模块，Original／Best 共 34 个 MIPS64 汇编执行测试全部通过、零跳过。本次合计通过 367 个实际测试用例；见 [测试凭据](../manifests/releases/v0.4.2/tests.json)。
- 双版本正式构建、组件语义回读、实际 ISO 身份及输入批次绑定检查通过。
- Best 最终 ISO 解压全部 205 块；核对 182 个含分发器块的 **184 张事件表**。块 10、130 各有两张，不能将块数当成表数。
- 两个受影响块与诊断修复版逐字节一致；最终 Best 的全部 205 个解压块均与诊断镜像一致。见 [最终事件表回读](../manifests/releases/v0.4.2/stage-event-readback.json)。
- 不带 skip 的最终 Original、Best 镜像分别冷启动 LRPS2，从隔离记忆卡第二槽读入第 46 话后进度，经第 47 话标题进入地图，继续到玩家回合并打开单位“移动／地面／精神／能力”菜单。
- 不带 skip 的最终 Best 镜像恢复本次会话自己的中场状态，仅将内存下一关字段改为 150，进入目标地图，确认机体登场并继续至盖纳“那团岩石是什么？”对白。该路径与诊断阶段的日文 Best 对照一致。
- Best skip 复用整盘哈希相同的诊断运行证据，包含两个目标入口；Original skip 本次没有另行运行，其补丁状态与变体身份已静态核对。

运行使用锁定的 x86_64 LRPS2、Software renderer，关闭金手指。输入卡 `user-Mcd001.ps2` 的 SHA-256 前后均为 `0ff0c38896eca6d9c738f01a5aa895d78253d079fed7750699ccd862a96c9caa`。源卡未改动。

上述证明入口和指定后续行为恢复，不是两关完整通关、全部事件分支或全路线运行验收。本轮没有重新执行 PCSX2。构建原始回读中的 `runtime=not_tested` 保留，运行结果由 [独立运行凭据](../manifests/releases/v0.4.2/runtime.json) 绑定最终镜像。

## xdelta 与 CHD

使用 xdelta3 3.2.0，固定 `-e -9 -S djw -A -a`，对四份补丁分别从日文原盘实际还原 ISO，比较大小及整盘 SHA-256。发布目录为 `build/release/v0.4.2/`；[补丁清单](../manifests/releases/v0.4.2/patches.json) 记录实际还原结果。

本地 `build/chd/v0.4.2/` 保留六份 CHD：两个 `srwz-jp-*.chd` 日文父盘，以及与四份冻结 ISO 同名的中文子盘。使用 chdman 0.289、zlib、16,384 字节 hunk。每个子盘直接依赖对应日文父盘；检查父盘逻辑数据哈希、父子链接，并提取每个子盘核对 ISO 大小与 SHA-256。[CHD 清单](../manifests/releases/v0.4.2/chd.json) 记录实际制品及验证结果。完整 ISO 和日文父盘不上传 GitHub Release。

## 重建命令

```sh
python3 tools/build_editions.py --editions original,best
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best.json
python3 tools/prepare_release_variants.py --manifest work/editions/<input_digest>/original-best.json --version 0.4.2
python3 tools/build_release.py --config config/release/v0.4.2.json
python3 tools/build_release_chd.py --config config/release/v0.4.2.json --quiet
```

`prepare_release_variants.py` 用于首次冻结，若已有该版本目录或配置会拒绝覆盖。复验既有发布镜像直接使用其锁定配置打包。发布元数据变化可能改变输入摘要，但生成的游戏字节必须满足四份冻结镜像哈希。

本地构建、测试及打包日志位于 `work/release/v0.4.2/`；本轮运行截图和完整按键记录位于 `work/runtime/lrps2/v042-original/`、`work/runtime/lrps2/v042-best/`；先前诊断对照位于 `work/runtime/lrps2/stage47-cause-20260917/`。
