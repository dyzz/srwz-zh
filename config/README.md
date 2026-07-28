# 配置与事实源

`config/` 同时包含不可漂移的外部锁和中文生产输入。新字段必须先确定唯一
所有者，不得为了某个 CLI 方便而复制一份可修改事实。

| 路径 | 所有权 |
| --- | --- |
| `upstream.lock.json` | 固定上游 Python 快照及授权/来源边界 |
| `toolchain/`、`fonts/` | 第三方工具、字体来源、版本和哈希 |
| `surfaces/` | 原版成员、稳定 entry ID、地址、allocation、codec/render/writer |
| `display-names/` | COMPDATA 人物／机体名称表几何、固定前像和结构 ratchet |
| `encoding/codebook.json` | 中文字符到游戏 code/glyph 的唯一分配账本 |
| `build-profiles/` | 构建选择集、最低编辑状态和必需 gates |
| `ui-scenes.json` | UI 场景 selector、优先级、运行路线、容量 ratchet 和动态名称 hash-only 探针 |
| `ui-writeback/` | UI 文本写回选择策略、锁定输入、容量 ratchet 和输出位置；不包含游戏字节 |
| `summary/` | MTV_PROS 世界史中文断行、原 allocation、字库容量和运行边界 |
| `canary/` | 验证切片的原版输入、构建参数和 golden；文本 canary 不拥有译文/码位，TIM2 探索 profile 暂存固定视觉标签 |
| `iso/` | PS2 DVD 容器工具链、profile workspace、最终输出和布局锁 |
| `patches/` | ASM/二进制前像、允许差异和写入所有者 |
| `assets/` | 图片归档成员、压缩标志和 SLPS offset 表范围；不包含游戏字节 |

每类生产 JSON 都必须显式声明自己的 `schema_version`，由对应 loader
fail-closed 校验；不同领域的 schema 独立演进，不能假设全仓库共用同一版本。
SurfaceSpec、BuildProfile 和语料当前使用 v1，前五关 ISO 构建配置使用 v2。
最小端到端实例是
`build-profiles/canary-menu.json`；E2 还包括 `canary-summary.json`、
`canary-story.json` 和组合选择 `canary-complete.json`。执行：

```bash
python3 tools/validate_build_profile.py
python3 tools/build_complete_canary.py --force
```

详细字段、数据流和新增 surface 步骤见
`docs/PRODUCTION_PIPELINE.md`。
ISO 的 `rom/work/build` 所有权见 `docs/ISO_DIRECTORY_LAYOUT.md`。

节子路线前五关的追加式码位账本、字体参数和 ISO 配置分别位于
`encoding/first-five-allocations.json`、`fonts/first-five-font.json` 和
`iso/first-five-build.json`。码位只允许追加，退役槽不复用；字体与工具来源
由相邻 lock 固定，当前候选的精确组件和镜像哈希只记录在
`manifests/first-five-validation.json`。

P0 UI 字库通过 `encoding/ui-p0-allocations.json` 和
`fonts/ui-p0-font.json` 增量引用并锁定上述基线，不修改 first-five 账本。
九个新增汉字只追加到组合 registry，栅格器继续由 first-five 字体配置单点拥有；
离线候选和 coverage 结果见 `manifests/ui-p0-font-validation.json`。
第一层 P0 SLPS 写回由 `ui-writeback/ui-p0-slps-fixed.json` 锁定；它只允许
原 span 内写回，禁止修改指针；当前 P0 无增长文本。
`ui-writeback/ui-p0-compdata-fixed.json` 对压缩 COMPDATA 采用相同 span
契约，并锁定 preserve-prefix suffix 重编码参数和成员增长 ratchet；当前
P0 同样无 overflow。
`ui-writeback/ui-p0-display-names.json` 在该静态组件之上选择
`corpus/zh/display-names/p0-opening.json` 的 45 个已审校字段；只允许原
allocation 内写回，人物 ID、机体指针和非目标字节均不可修改。完整结构和
组件结果分别锁定在 `manifests/display-name-structure.json` 与
`manifests/ui-p0-display-names-validation.json`。

`summary/world-history-layout.json` 锁定 28 条世界史的真实 MTV_PROS 输入、
22 格显示宽度、14 个原版空行和跨记录定长分配策略。它只允许生成布局报告和
byte-free 清单，不拥有字形分配，也不把布局通过升级为组件、ISO 或运行验收。

`assets/archive-inventory.json` 由 `tools/srwz/assets.py` 独立执行严格 schema
检查：未知字段、重复 member、路径穿越、archive/direct 重叠、未知 storage
模式和非法上游提交都会失败。TIM2 外部工具选择尚未形成 lock；准入条件见
`docs/TIM2_TOOLCHAIN_ACCEPTANCE.md`。`canary/tim2-vt1-title-index.json`
固定已通过运行验证的 VT1 标题 index canary，`iso/image-canary-build.json`
固定其独立组件、ISO 路径和 golden hash；两者都不拥有正式图片译文。
`canary/tim2-vt1-title-zh.json` 登记标题四项中文、OFL 字体、ImageMagick
参数和 mask/output golden，`iso/title-menu-zh-build.json` 固定对应独立
ISO；这是当前首个坐标级 8-bpp 图片汉化 profile。
