# Manifest 约定

`manifests/` 只保存哈希、大小、计数、地址范围和验收状态，不保存可还原的游戏
字节。它们是工具生成的验证摘要，不是手工驱动构建的输入替代品。

当前发布的主要摘要：

`releases/<version>/` 保存已打标签版本的不可变组件证据；当前开发构建继续更新
顶层清单。发布后的 ISO 配置必须指向对应版本快照，不能再绑定会前移的顶层清单。

| 文件 | 内容 |
| --- | --- |
| `original-disc.json` | 固定原盘身份 |
| `zh-release-font-validation.json` | 全局字体覆盖和固定大小组件 |
| `release-base-ui-validation.json` | 最终编码 UI 四成员基线 |
| `ui-*-atlas-zh-validation.json` | 六张中文 KVMDATA 图集 |
| `ui-atlas-suite-zh-validation.json` | 图集字节所有权合成 |
| `full-story-components-validation.json` | 13 个最终成员组合及 SRVC 全索引回读 |
| `zh-release-full-story-iso-content-validation.json` | 当前 v0.1.0 ISO 的剧情、UI、名字、图集与文本存储统一静态回读 |

历史基础 UI 构建已折叠为 `release-base-ui-validation.json`；历史 ISO、测试组合、
模型审校和旧运行会话 manifest 不再保留，需要追溯时使用 Git 历史。

任何 `runtime_verified` 结论必须绑定当前 ISO SHA-256、匹配存档、fresh-process
路线、PCSX2 版本及零 Trap/illegal-instruction/TLB 错误记录。当前 v0.1.0 只有静态
验证，尚未取得绑定精确哈希的正式运行收据。
