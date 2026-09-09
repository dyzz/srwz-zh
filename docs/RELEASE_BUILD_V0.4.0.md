# v0.4.0 构建与发布记录

2026-09-09。发布包含 Original 和 The Best 两个独立 xdelta，均从对应日文原盘
直接生成中文镜像。游戏内容来自 `71cbb2b74bfd22b3367f931fd4ca9f6c4147d074`，
随后提交的发布工具、文档和结果锁不改动中文语料或游戏写回逻辑。

> 发布后的本地保留约定：两份冻结镜像现名为
> `build/iso/v0.4.0/0.4.0-original.iso` 与 `build/iso/v0.4.0/0.4.0-best.iso`。
> 本页下方的发布路径、发布配置和校验清单保留打包时的名称；ISO 字节与哈希不变。
> 本地只保留两份冻结镜像、两份日文原盘和两份 current，详见
> [ISO 目录契约](ISO_DIRECTORY_LAYOUT.md)。复验打包时可从这两份冻结镜像临时恢复
> 下表路径，完成后移除临时副本。

## 冻结与验证

同批双版本输入摘要为
`4b6c661d17edf5eb1a822ced92e29034ed3f985ee4a942f2d9fa27dd04391706`。

| 版本 | 冻结镜像 | SHA-256 |
| --- | --- | --- |
| Original | `build/iso/v0.4.0/srwz-zh-v0.4.0-original.iso` | `d4fce948600e347ea92d38920eabe1539f6e4b1541d90767c045d3f7f89817b6` |
| The Best | `build/iso/v0.4.0/srwz-zh-v0.4.0-best.iso` | `4ccb2355ab6d18e08db4183f06333f1d9d58b7cb7e3e4e98e6d972ae9784a18a` |

两版完成实际构建、固定布局与非目标字节检查、最终语义回读，并由
`verify_editions.py` 核对同批输入、各版回读和真实 ISO 的绑定。Original 回读覆盖
170 个 STAGE、93,071 条翻译记录；BEST 检查 205 个 STAGE 块、84,338 条剧情文本
所有者和 58,740 条字幕物理记录。Original 的 23 个最终组件已同步到日常生产槽位。

`python3 -m unittest discover -s tests`：253 项通过，包含 7 项双版本发布绑定测试。
原盘验证、Python 编译检查和 CLI 入口检查通过。补丁使用 xdelta3 3.2.0，参数为
`-e -9 -S djw -A -a`；关闭 application header 和 armor 扩展，生成独立 VCDIFF。
每个补丁均实际还原到临时目录，核对文件大小和 SHA-256，临时 ISO 不进入发布目录。

两个补丁重复构建的 SHA-256 相同；Original 在生产槽位按固定锁重新构建也与冻结镜像一致。
补丁还原结果及输入证据摘要见 [补丁清单](../manifests/releases/v0.4.0/patches.json)。

版本证据保存在 [发布验证清单](../manifests/releases/v0.4.0/validation.json)、
[Original 回读](../manifests/releases/v0.4.0/original-readback.json)、
[BEST 回读](../manifests/releases/v0.4.0/best-readback.json) 与
[BEST 组件回读](../manifests/releases/v0.4.0/best-components-readback.json)。
回读副本保留历史构建路径；冻结镜像路径和相同字节身份以发布验证清单为准。
本地完整日志位于 `work/release/v0.4.0/`，同批输入和构建工作区继续保留。

本次没有重新运行 PCSX2 或 LRPS2。此前人工验收记录
`manifests/editions/runtime-user-acceptance-20260907.json` 仅适用于其绑定的旧批次，
不能替代本次发布哈希的运行验收；全路线、全部分支和即时存档兼容仍不作保证。

## 从源码重建补丁

在 v0.4.0 标签的工作区准备 `rom/original.iso` 与 `rom/best.iso`，原盘身份由
`config/editions/{original,best}/edition.json` 锁定。

```bash
python3 tools/build_editions.py --editions original,best
# 使用上一命令输出的 batch_manifest 路径：
python3 tools/verify_editions.py --manifest work/editions/<input_digest>/original-best.json
mkdir -p build/iso/v0.4.0
cp -n build/iso/zh-release-original/current-original.iso build/iso/v0.4.0/srwz-zh-v0.4.0-original.iso
cp -n build/iso/zh-release-best/current-best.iso build/iso/v0.4.0/srwz-zh-v0.4.0-best.iso
python3 tools/build_release.py --config config/release/v0.4.0.json
```

发布工具只接受配置中固定的两版来源、版本化目标及回读锁。若重建结果与冻结目标
不同，会在编码前停止，不允许改哈希绕过验证。`build/release/v0.4.0/` 中只有两个
xdelta、说明、发布清单及 SHA-256 校验表；GitHub Release 仅上传两个 `.xdelta`。
历史 schema 1 单版本 ZIP 发布仍可显式使用对应历史配置。

## 发布说明整理

发布说明保留双版本差异、可见修复、技术处理、社区站和文本润色五类内容，并补齐
两个补丁的安装命令、原盘与成品校验值、验证边界。移除草稿标记和过期编辑备注。

统计更新为相较 v0.3.0 的 4,901 个条目：剧情 2,935、战斗 1,867、人物名 10、
机体名 30、武器名 59。数据来自与内容提交一致的审阅站导出，方法与来源摘要见
[文本统计](../manifests/releases/v0.4.0/text-statistics.json)。图鉴 784 项是通读范围，
不是全部改写数量；图鉴正文、关键词及攻略 Q&A 未计入 4,901 条。

## 本地清理

四个历史审阅工作区的 15 处生成目录已移入带恢复清单的本地归档，清理前 `du` 合计
约 147.2 GiB。范围仅为其重复原盘、ISO、构建输出和工具链；保留源码修改，并将
报告、日志和预览复制回原路径。APFS 共享块可能影响实际磁盘占用，此数值不代表
释放了同等空间。没有永久删除这些文件。

本地归档位置与逐项映射见 `work/release/v0.4.0/cleanup.json` 和归档内的
`RESTORE_PATHS.json`。原盘主副本、当前组件链、当前工作镜像、历史发布镜像、
运行证据、用户存档及相邻项目保留。v0.4.0 两版冻结镜像登记到
`config/iso/retained-isos.json`，供后续开发区分发布与 current 输出。

2026-09-05 的扩容安全审计另行归档，按当时的提交和哈希解释；其中的内部引用检查
缺口不作为当前已发现运行故障，也没有借本次发布修改生产 writer。
