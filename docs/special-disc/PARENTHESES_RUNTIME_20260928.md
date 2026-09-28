# SP 原版括号与武器详情验证（2026-09-28）

本记录对应先前的字形恢复阶段。后续本体／BEST／SP 的武器详情局部编码修复、
更新镜像及验证见 [三版武器详情括号记录](../WEAPON_DETAIL_PARENTHESES_20260928.md)。

SP 最终组装在写入锁定的共享中文字库后，将 `（`、`）` 的已有主槽和中文别名槽
复制为 SP 原盘 `8169`、`816A` 的原始 4-bpp 像素。中文编码 `8FE8`、`8FEB`
及渲染器字距保持不变。独立最终盘回读再次逐字节核对四个槽位。

实现入口是 `tools/special_disc/writeback/parenthesis_glyphs.py`，接入
`build_full_text.py` 和 `verification/verify_full_text.py`。SP 原盘解码字体身份为
`e68a24df2daaf16f472e55e0ba9b2282752bb70225aedc0bbb8aeef7713662bd`。
压缩使用当前锁定字体 profile 的 codec 参数，并保留已有字体槽、相邻音频和所有归档偏移。

## 字形恢复阶段的镜像和静态证明

- 该阶段 SP ISO：`f6935e848d632d6221cbf1bff29366e3d252173eac003b1da1a30bcec1ef1c5d`。
- 该阶段本篇 Original ISO：`3fe887bbc31f9fdf51514fbe9f2aa929c46fabdc4c885721703ed9c5ac6ae129`。
- 两版日常测试盘均已由统一构建入口同步，保留方块 skip。
- SP 修改前后解码字体共 4,480 个字形，仅 `2856`、`2859` 两个中文括号槽改变；
  其余 4,478 个字形逐字节一致。
- 两版内容回读通过；SP 批次完整性校验通过。11 项相关测试通过。

## 本轮运行画面

使用 LRPS2 Software、隔离记忆卡，从冷启动自然进入 Z 高达的武器性能页。
SP 前后运行都在 7,705 帧捕获光束步枪详情，未修改 RAM，也未恢复旧状态。
本篇另以标准运行器冷启动读档，捕获同一 PLA/PB 模板。

左侧为改动前，右侧为 SP 原版括号。右括号向外恢复，PLA/PB 图标与右括号之间
有更清楚的间隔，图标保持完整。分类行仍使用原版括号；另外自然切换检查了 TRI/B、ALL/B。

![SP 武器详情前后对比](../../work/runtime/lrps2/parentheses-20260928/sp-detail-before-after.png)

[SP 完整画面](../../work/runtime/lrps2/parentheses-20260928/sp-after/natural-ranged.png)
和[本篇完整画面](../../work/runtime/lrps2/parentheses-20260928/main/frames/07217-native-parentheses-pla-pb.png)。

完整身份、命令日志、截图哈希和测试计数记录在
[`native-parentheses-runtime-20260928.json`](../../config/editorial/special-disc/native-parentheses-runtime-20260928.json)。

这是本轮新盘的静态回读和 LRPS2 Software 画面证据。没有新增 PCSX2 人工验收；
字体替换不调整动态图标位置或文字步进，也不证明全部括号场景已检查。
