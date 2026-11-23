# v0.5.1 构建与发布记录

Original、The Best 和 SP 同批构建并冻结，输入摘要为 `2cef62d3e8408e61cae73c8453b2d376baf7908c246c174524b802b2c58b0100`。三版标题显示 `v0.5.1`。三版的构建回读与方块 skip 钩子检查见[冻结验证清单](../manifests/releases/v0.5.1/validation.json)，源码对应关系见[源码对照记录](../manifests/releases/v0.5.1/source-binding.json)。

| 冻结 ISO | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `srwz-zh-v0.5.1-original.iso` | 3,799,459,840 | `c6754f75eb12be7c4b4af5c23993cfafa0d5be2bb4ecb78311029390becb3862` |
| `srwz-zh-v0.5.1-best.iso` | 3,796,187,136 | `90c9d05c2f9ef75a8abdfececa577fd7b0a09046045df9d1fdecc5f0ce3b0f9f` |
| `srwz-zh-v0.5.1-sp.iso` | 3,918,860,288 | `0175bffd0a3312db930f45d5058e56fc60058362c6941a26fb87ad8a91496ae9` |

## 验证

- 全套 1,070 项单元测试通过，使用 Unicorn 2.1.4，零跳过。 [测试凭据](../manifests/releases/v0.5.1/tests.json)
- 三份 xdelta 使用 xdelta3 3.2.0、`-e -9 -S djw -A -a` 生成，各自从锁定的日文原盘实际还原，并核对还原镜像大小和整盘 SHA-256。 [补丁清单](../manifests/releases/v0.5.1/patches.json)
- ARMSX2 runner（Metal 4×）冷启动三份冻结 ISO。Original 与 The Best 使用空白卡和已有进度卡分别进入资料库，核对标题版本号、四处原生进度指令，检查机体、人物、关键词、剧情流程及第 21 话梗概。SP 进入战斗鉴赏并播放一场战斗。 [运行凭据](../manifests/releases/v0.5.1/runtime.json)
- 22px 无 hinting 字库在三版图鉴、SP 战斗台词／梗概／滚动剧情中冷启动抽查，SP 镜像即本发布镜像。 `字库抽查记录`（已删除，原文见提交 eb9c1f90）
- 窗口细线（V050-001）的修复验证见 `v0.5.0 发布后问题`（已删除，原文见提交 eb9c1f90）。
- 本轮运行抽查覆盖上述入口与页面。全路线、真机和 PCSX2 手动验证不在本轮范围内。

## 重建

```sh
python3 tools/build_editions.py --release-version 0.5.1
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best-sp.json
python3 tools/freeze_release.py --manifest work/editions/<input_digest>/original-best-sp.json --version 0.5.1
python3 tools/build_release.py --config config/release/v0.5.1.json
```

SP 构建依赖由 `config/editions/sp/inputs.json` 锁定。重新打包既有发布镜像时，使用发布配置及首次冻结保留的本地 ELF 和钢狮子动画校验数据。完整镜像位于本地 `build/iso/v0.5.1/`，发行附件位于 `build/release/v0.5.1/`。 [三版构建说明](BUILD_EDITIONS.md)
