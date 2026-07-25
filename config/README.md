# 配置与事实源

`config/` 同时包含不可漂移的外部锁和中文生产输入。新字段必须先确定唯一
所有者，不得为了某个 CLI 方便而复制一份可修改事实。

| 路径 | 所有权 |
| --- | --- |
| `upstream.lock.json` | 固定上游 Python 快照及授权/来源边界 |
| `toolchain/`、`fonts/` | 第三方工具、字体来源、版本和哈希 |
| `surfaces/` | 原版成员、稳定 entry ID、地址、allocation、codec/render/writer |
| `encoding/codebook.json` | 中文字符到游戏 code/glyph 的唯一分配账本 |
| `build-profiles/` | 构建选择集、最低编辑状态和必需 gates |
| `canary/` | E0 golden 的原版输入、构建环境和预期输出，不拥有译文/码位 |
| `iso/` | PS2 DVD 容器工具链、profile workspace、最终输出和布局锁 |
| `patches/` | ASM/二进制前像、允许差异和写入所有者 |

当前所有生产 JSON 使用 `schema_version: 1`，由
`tools/srwz/project.py` 在读取时 fail-closed 校验。最小端到端实例是
`build-profiles/canary-menu.json`；执行：

```bash
python3 tools/validate_build_profile.py
```

详细字段、数据流和新增 surface 步骤见
`docs/PRODUCTION_PIPELINE.md`。
ISO 的 `rom/work/build` 所有权见 `docs/ISO_DIRECTORY_LAYOUT.md`。
