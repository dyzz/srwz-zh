# 配置入口

配置树只保存可复现构建输入。当前发布从以下文件进入：

| 文件 | 作用 |
| --- | --- |
| `iso/zh-release-chain.json` | 当前唯一 ISO、哈希和运行状态 |
| `iso/zh-release-full-story-build.json` | 固定原盘、成员、LBA 和 ISO 工具链 |
| `release/v0.1.0.json` | v0.1.0 原版／目标 ISO 哈希、xdelta3 参数和发布包布局 |
| `full-story-components.json` | 16 个最终成员的组合契约 |
| `story-component.json` | 154 个 STAGE 剧情块的固定布局与 Rust 写回契约 |
| `fonts/zh-font-build-chain.json` | 全局字体及静态图集消费者 |
| `fonts/zh-release-font.json` | 唯一活动 VT1 字体 profile |
| `encoding/zh-release-font-assignments.json` | 追加式字符、码位和 glyph 快照 |
| `assets/ui-atlas-suite-zh.json` | 六张 KVMDATA 中文图集组合 |

目录职责：

- `story-component.json` 与各领域配置：成员、记录、地址、容量和 renderer。
- `fonts/`、`encoding/`：字体来源锁、raster 规则和 codebook。
- `assets/`：当前 TIM2/PSMT4 图集、组合配置及 `maps/` 像素擦除边界。
- `display-names/`：人物长名／短名与机体名的原版结构。
- `iso/`：只保存当前发布构建与单候选状态。
- `release/`：只保存补丁发布契约；完整 ISO 仍留在本地 `build/iso/`。

历史 UI 分期已折叠为 `manifests/release-base-ui-validation.json`。新文本进入
`corpus/zh` 和全局字体快照；新图片进入独立 atlas profile；最终只由
`full-story-components.json` 组合。

配置中的哈希、计数和容量都是 fail-closed ratchet。确认输入发生变化后才允许
通过对应工具刷新，禁止为了让测试通过而手工改写结果字段。
