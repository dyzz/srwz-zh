# 武器详情括号：本体、BEST、SP（2026-09-28）

保留先前恢复的原版括号字形。仅武器详情的 MAP、TRI、ALL、PLA 文字模板及
一、二、三图标占位框，使用原版编码 `8169 / 816A`，恢复其原生字宽处理。
其他中文文本继续使用现有括号别名 `8FE8 / 8FEB`；中文前缀、`8140` 占位空格、
图标素材和图标定位逻辑均不调整。

## 构建与回读

`tools/srwz/weapon_detail_parentheses.py` 限定每版 7 个原生字符串槽，只接受完整的
中文别名或原版括号占位后缀；拒绝混合编码、错误空格、缺失终止符或越界槽位。
替换最多 28 个字节，不改变可执行文件长度、文字前缀或相邻数据；重复应用不再改字节。

- 本体：接入完整组件构建和固定 SLPS 增量构建；最终 ISO 回读逐条绑定组件证明。
- BEST：继承同一输入快照下本体编译结果，按已审计的分段 ELF 映射投射；
  组件和最终 ISO 都检查 BEST 自身的模板位置。
- SP：接入最终全文组装，独立回读实际 ISO 中的 7 条模板。

`config/full-story-components.json` 将本项列为明确构建依赖，旧缓存会触发可执行文件
重建；本轮补充了缓存失效回归测试，避免只更新源码而沿用旧括号编码。

三版来自输入快照
`60b77e1c36113ecbfe2f641d08ebb0d4ef00a1dfb8f30112f4a410a22541ab03`。
统一构建和批次完整性验证通过，三版日常测试盘均为对应正式盘的精确副本。

这些镜像和构建记录绑定的是本地冻结输入快照，而非仅由某个 Git 提交构成的输入。
快照还包含当时进行中的正文排版改动（`zh-layout-profiles.json`、
`write_frame_text.py`、`chinese_layout.py`、`chinese_prose.py`）；
这些改动不属于本次括号提交。本记录保留实际验证过的镜像身份，
不将本次提交单独宣称为该快照的完整复现输入。

| 版本 | 正式 ISO | SHA-256 |
|---|---|---|
| 本体 | `build/iso/zh-release-original/current-original.iso` | `c5ad79319c158de072f2615a11b6271d055d40fefeb9098512f0d26ac473558c` |
| BEST | `build/iso/zh-release-best/current-best.iso` | `47ba9f9a3145748090a26a0f6ebdd0c00ebf8951f90e53be786885546e0da86e` |
| SP | `build/iso/special-disc/sp-current.iso` | `f77ad4df09d541629050a45fbfc82a749b1899f2b678e78a1c4e0c90b2d0e462` |

独立最终盘检查确认每版 `8169`、`816A`、`8FE8`、`8FEB` 四个字形槽仍为原版
左／右括号像素。证明保存在
`work/review/parentheses-production-20260928/final-font-and-template-readback.json`。

65 项相关单元测试通过，涵盖模板范围、非目标字节、重复应用、非法占位、
BEST 分段映射、增量缓存依赖、字体恢复和三版构建／发布绑定。

## 画面验证

本轮运行记录与截图位于 `work/runtime/lrps2/parentheses-production-20260928/`。
采用 LRPS2 Software 冷启动和隔离记忆卡，自然进入武器详情页；不改 RAM，
不恢复旧状态。运行结果及截图身份见
`config/editorial/weapon-detail-parentheses-runtime-20260928.json`。

三版新正式盘均检查 PLA/PB、普通武器/PB、TRI/B、ALL/B、普通武器/S-P。
本体和 BEST 的标准运行器证明均通过；SP 保留完整自然操作日志。
三版 PB 与未修改日文 SP 原盘平移对齐后，黑／白／背景三类轮廓掩码差异
均为 0/1144，确认其相对居中关系恢复。此比较排除背景亮度差异。

![三版正式盘 PLA/PB](../work/runtime/lrps2/parentheses-production-20260928/three-editions-pla-pb.png)

此处的模板修复不改变全局标点策略。MAP 和单独 P 未进行画面验证；
没有新增 PCSX2 人工验收。
