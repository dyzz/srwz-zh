# v0.3.0 Manifest

`manifests/` 保存 v0.3.0 构建的哈希、大小、计数、地址范围和静态回读结果，不保存
可还原的游戏字节。历史候选、内部问题盘点和一次性实验清单需要追溯时使用 Git 历史。

主要发布摘要：

| 文件 | 内容 |
| --- | --- |
| `original-disc.json` | 固定原盘身份 |
| `zh-release-font-validation.json` | 全局字体覆盖与固定大小组件 |
| `ui-*-atlas-zh-validation.json` | 六张中文 KVMDATA 图集 |
| `ui-atlas-suite-zh-validation.json` | 图集字节所有权合成 |
| `full-story-components-validation.json` | 最终成员组合与结构回读 |
| `full-story-library-components-validation.json` | LIBRARY 与最终组合回读 |
| `zh-release-full-story-iso-content-validation.json` | v0.3.0 最终 ISO 内容回读 |
| `zh-release-special-width-assignment-audit.json` | 构建使用的特殊宽度码位约束 |

manifest 是构建产生并核验的摘要，不替代 `corpus/` 与 `config/` 中的生产事实源。
静态回读只证明精确 ISO 中的存储内容、结构和哈希；运行与画面验收仍需人工在同一
ISO 上完成。
