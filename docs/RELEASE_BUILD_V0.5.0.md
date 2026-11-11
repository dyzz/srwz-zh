# v0.5.0 构建与发布记录

Original、The Best 和 SP 同批构建并冻结，输入摘要为 `e007abb22f3355e4d9ee08585c73572b53bf641e26fc511d407a29b93bbfd0c5`。本篇两版标题显示 `v0.5.0`。三版的构建回读与方块 skip 钩子检查见[冻结验证清单](../manifests/releases/v0.5.0/validation.json)。

与定稿 RC 作整盘哈希对照，Original 和 The Best 的变化限定在标题版本号所在的 `VT1.BIN` 压缩块，SP 整盘字节一致。快照中 879 项受 Git 跟踪的输入与 `42e193ad` 的文件内容逐一匹配。 [源码与 RC 对照记录](../manifests/releases/v0.5.0/source-binding.json)

| 冻结 ISO | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `srwz-zh-v0.5.0-original.iso` | 3,799,459,840 | `2a76a11f84bb9d0b75363fce528e4f5e319d102597d11f807b1a07644bfc7749` |
| `srwz-zh-v0.5.0-best.iso` | 3,796,187,136 | `6f0df648c20e495e776c769ebe862af7918a2ae9f00a50775049bca8756318fc` |
| `srwz-zh-v0.5.0-sp.iso` | 3,918,860,288 | `e09afe50f0131691456489e300ba089aef8e768f0c2ffb9dd018b91b725e1c37` |

## 验证

- 全套 1,043 项单元测试通过，使用 Unicorn 2.1.4，零跳过。 [测试凭据](../manifests/releases/v0.5.0/tests.json)
- 三份 xdelta 使用 xdelta3 3.2.0、`-e -9 -S djw -A -a` 生成，各自从锁定的日文原盘实际还原，并核对还原镜像大小和整盘 SHA-256。 [补丁清单](../manifests/releases/v0.5.0/patches.json)
- ARMSX2 runner（Metal 4×）冷启动三份冻结 ISO。Original 与 The Best 使用空白卡和已有进度卡分别进入资料库，核对四处原生进度指令，检查机体、人物、关键词、剧情流程及第 21 话梗概。SP 进入战斗鉴赏并播放一场战斗。 [运行凭据](../manifests/releases/v0.5.0/runtime.json)
- 本轮运行抽查覆盖上述入口与页面。全路线、真机和 PCSX2 手动验证不在本轮范围内。

## 重建

```sh
python3 tools/build_editions.py --release-version 0.5.0
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best-sp.json
python3 tools/freeze_release.py --manifest work/editions/<input_digest>/original-best-sp.json --version 0.5.0
python3 tools/build_release.py --config config/release/v0.5.0.json
```

SP 构建依赖由 `config/editions/sp/inputs.json` 锁定。重新打包既有发布镜像时，使用发布配置及首次冻结保留的本地 ELF 和钢狮子动画校验数据。完整镜像位于本地 `build/iso/v0.5.0/`，发行附件位于 `build/release/v0.5.0/`。 [三版构建说明](BUILD_EDITIONS.md)
