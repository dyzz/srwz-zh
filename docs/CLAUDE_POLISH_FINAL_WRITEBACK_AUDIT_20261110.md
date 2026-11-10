# Claude 润色写回与地图对话排版终检（2026-11-10）

用户授权：剩余可接受文本直接写入；同时考虑 Claude 新排版算法、地图对话宽度和 SP 名场面集合。

## 文本写回

按写回先后合并六份 editorial 收据，逐条核对当前本地语料，共 1,588 个最终条目：1,504 条完全一致，84 条仅空白／换行不同，措辞差异或漏写为 0。四条用户明确保留的决定继续保留。历史收据和确认记录未覆盖；本轮没有重复写入已经落地的译文，也没有将旧 pending 清单当成新的待写入任务。

核对来源：story-polish、battle-polish、claude-polish-audit、claude-polish-full-recheck、claude-polish-user-confirmed、claude-polish-technical-resolution 的 20261110 收据。逐条结果及收据 SHA-256 在 `work/review/map-dialogue-final-audit-20261110/writeback.json`，同目录 `audit_writeback.py` 可复核。

## 地图宽度与 SP

保留 Claude 的 story_map 420px／最多三行规则和均衡换行策略，普通剧情对话仍为 483px。战斗仍使用原全角空格；本轮不改正文或缩进字符。

- 本篇 169 个剧情文件通过现存正文排版检查（包括地图宽度与词内断行规则）；按用户要求排除不用的 STAGE185 教学。
- SP 剧情 5,894 条和挑战模式 829 条通过当前构建排版桥接器，其中地图对话分别 2,899 和 579 条。此项验证排版输出，未写回 SP 语料。
- SP 名场面集合 22 个场景、681 句与当前语料快照完全一致，包含主角名替换后的正文，全部通过 420px 检查。现有快照已经同步，无需再次生成。
- 为名场面集合 `encode_talk` 新增编码前地图宽度检查，防止以后出现语料一致但超出地图框的文本。
- SP 剧情构建的最终验宽按 story/story_map 分组，避免最后一道检查误用普通对话宽度。
- 批量排版新增文本与场景数量一致检查，防止 zip 静默丢条。

## 验证边界

Python 3.13：排版适配测试 15 项通过；名场面集合测试 45 项中 44 项通过、1 项按原条件跳过。默认 Python 3.9 在已有 prose_widths 的 zip(strict=True) 处出现兼容性错误；切换 3.13 后通过，未改动该无关代码。

本轮证据为本地语料比对、共享排版引擎检查及单元测试。未重建 ISO，未新增 ARMSX2 实机画面核验，不能将上述通过视为实机显示验收；未处理线上、commit 或 push。静态结果保存在 `work/review/map-dialogue-final-audit-20261110/`。
