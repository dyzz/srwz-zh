# v0.4.0 配置入口

Special Disc 开发目录登记与研究输入见 [products/special-disc/README.md](products/special-disc/README.md)，其预览图片输入位于 `assets/special-disc/`。

配置树保存当前双版本构建输入、审核契约与版本化发布配置。历史配置按其版本解释，
不能用旧发布目标哈希替代当前产物身份。

| 文件 | 作用 |
| --- | --- |
| `iso/zh-release-chain.json` | 当前 ISO、哈希和状态 |
| `iso/zh-release-current-build.json` | Original 固定原盘、replacement、LBA 和输出哈希 |
| `release/v0.4.0.json` | 双版本原盘、冻结目标 ISO、独立 xdelta 和验证契约 |
| `release/dual-current.json` | 同批双版本构建入口 |
| `editions/{original,best}/edition.json` | 两版原盘和可执行文件身份 |
| `runtime/lrps2-common-sequences.json` | LRPS2 常见路线别名、场景入口和按键表 |
| `runtime/lrps2-{title,new-game-menu,load-menu,continue-menu,library-menu}.json` | 常见路线的完整逐帧输入与画面断言 |
| `runtime/examples/lrps2-custom-open-load.json` | 相对帧自定义按键与截图检查点示例 |
| `full-story-components.json` | 从锁定原版成员直接写回的最终组件与依赖顺序 |
| `encoding/release-menu-codebook.json` | v0.3.0 菜单文本的固定字符编码 |
| `assets/title-menu-zh.json` | 标题菜单四个中文标签的审核后像素掩码 |
| `assets/tricmn-battle-overlays-zh.json` | `TRICMN` 六张逻辑纹理的完整盘点，以及 51 项战斗提示、状态与能力文字的索引贴图、透明度及边界锁 |
| `assets/tricmn-battle-overlays-zh-render-snapshot.json` | 已经 ISO／LRPS2／ARMSX2 验收的三张 TRICMN PSMT4 索引图冻结快照；正式构建只消费该快照，不重新绘字 |
| `story-component.json` | 含对白 STAGE 块的布局与写回契约 |
| `fonts/zh-font-build-chain.json` | 全局字体及其组件消费者 |
| `fonts/zh-release-font.json` | 当前 VT1 字体 profile |
| `encoding/zh-release-font-assignments.json` | 追加式字符、码位和 glyph 快照 |
| `assets/ui-atlas-suite-zh.json` | KVMDATA 中文图集组合 |
| `stage-default-formation-inventory.json` | 已审核 STAGE 编队位置 |
| `terrain-name-inventory.json` | 已审核 MAPMODEL 地形名位置 |
| `world-map-title-render-snapshot.json` | 已审核世界地图标题像素快照 |

`assets/`、`display-names/`、`encoding/`、`fonts/`、`library/` 和文本布局配置均由
上述主链传递引用。构建中的哈希、计数、容量和前像是 fail-closed 门；确认生产输入
发生变化后才允许通过对应构建入口刷新，不能为了通过构建而手工改写结果字段。
