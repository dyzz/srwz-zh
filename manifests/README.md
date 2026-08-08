# Manifest 约定

`manifests/` 只保存哈希、大小、计数、地址范围和验收状态，不保存可还原的游戏
字节。它们是工具生成的验证摘要，不是手工驱动构建的输入替代品。

当前发布的主要摘要：

| 文件 | 内容 |
| --- | --- |
| `original-disc.json` | 固定原盘身份 |
| `zh-release-font-validation.json` | 全局字体覆盖和固定大小组件 |
| `release-base-ui-validation.json` | 最终编码 UI 四成员基线 |
| `ui-*-atlas-zh-validation.json` | 五张中文 KVMDATA 图集 |
| `ui-atlas-suite-zh-validation.json` | 图集字节所有权合成 |
| `full-story-components-validation.json` | 11 个最终成员组合 |
| `zh-release-remaining-ui-iso-content-validation.json` | 最终 ISO 的菜单／名字／部件静态回读 |
| `zh-release-srvc-battle-iso-content-validation.json` | 最终 ISO 的 SRVC 全索引回读 |
| `zh-release-full-story-iso-content-validation.json` | 当前 ISO 全量静态回读 |

历史基础 UI 构建已折叠为 `release-base-ui-validation.json`；历史 ISO、测试组合、
模型审校和旧运行会话 manifest 不再保留，需要追溯时使用 Git 历史。

任何 `runtime_verified` 结论必须绑定当前 ISO SHA-256、匹配存档、fresh-process
路线、PCSX2 版本及零 Trap/illegal-instruction/TLB 错误记录。当前 r8 只有静态
验证，尚未取得正式运行收据。
