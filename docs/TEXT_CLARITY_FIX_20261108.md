# 文字清晰度修复与原版标题恢复（2026-11-08）

按用户最终选择，SELECT-、FORMATION、SORT 使用各版本日文原盘的英文贴图和原始多层绘制记录；不再使用中文“选择／阵型／排序”标题。阵型列表正文和操作提示仍保留中文。

- 原版 SELECT 和 FORMATION 图集区域已与原盘逐索引核对，保持原始像素。原 SORT 区域曾被中文“选择”占用，现恢复原盘 page 2 的 (0,56,56,16) 完整单词。
- original/Best 与 SP 各恢复 27 条标题绘制记录，包含原始位置、宽度和 UV。配置保存原盘成员 SHA256 与冻结像素。
- 按键／说明／项目贴图减轻描边，移除填充加粗和倾斜，保留调色板索引的填充与轮廓分层。
- SP 剧情流程中文标题调整为浅色填充、深色边缘；保留英文后缀与目标矩形外的像素。
- COMMAND / OTHERS COMMAND 原版恢复继续保留。

## 验证

28 项相关单元测试通过。original、Best、SP 均做完整 ISO 字节比较：目标成员外完全一致，所有文件大小和 LBA 不变。生产更新前再次校验当前 ISO 和候选 ISO 的 SHA256，避免覆盖并发更新；旧镜像以 APFS clone 保留在 build/iso/text-clarity-20261108/。

ARMSX2 runner，Metal 4×：original 冷启动进入阵型界面，确认 SELECT-FORMATION / SELECT-SORT；同轮先前捕获 SELECT-ROBO、按键说明与项目说明。SP 同轮先前捕获剧情流程标题，后续恢复菜单标题不改变 HSFC 资源。Best 未运行，只通过静态与 ISO 比对。未声称覆盖全部游戏界面。

最终截图见 [截图说明](issue-assets/text-clarity-fix-20261108/README.md)，更新记录见 [promotion.json](issue-assets/text-clarity-fix-20261108/promotion.json)。
