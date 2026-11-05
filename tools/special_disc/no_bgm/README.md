# SP 战斗鉴赏：关闭 BGM

外层「BGM 设置」新增第四项「关闭 BGM（保留音效）」，无需进入选曲分页。选择后主界面显示「无 BGM」，关闭左右队长机自动选曲；重新选择默认曲或手动选曲即可恢复。原选曲列表和随机曲目池保持原样。

`writeback/build_full_text.py` 在事件鉴赏补丁之后调用 `apply_no_bgm`，正常 `python3 tools/build_editions.py --editions sp` 构建包含此功能。`build.py` 是针对尚未安装本补丁的 ELF/ISO 的隔离实验入口，不能重复应用于已安装版本。

内部使用未参与原选曲池的曲目 ID 101。同步和异步 BGM 请求遇到该 ID 时调用游戏原生 BGM 停止函数 `0x18b1f0`，不修改总音量、语音或音效音量。外层菜单扩展为四行并增加中文说明。代码位于 `0x81e000..0x820000` 的空隙，复用零长度 ELF 程序头 70，不移动事件鉴赏区或堆边界。安装时校验所有指令原值和区域边界。

2026-11-06 验证：正常构建成功；4 项 ISO relocation 单元测试通过。ARMSX2 runner 从当前 SP ISO 冷启动，验证第四项显示、关闭、恢复默认曲、再次关闭、30 秒战斗及返回。战斗中曲目 ID 为 101，原生 BGM 状态为 0，语音与音效仍有 key-on。返回鉴赏菜单恢复其原生菜单曲，所选战斗曲仍为无 BGM。证据见 `docs/issue-assets/sp-no-bgm-20261106/`，复现脚本在 `work/analysis/sp-no-bgm-20261105/test_outer.py`。

这是 ARMSX2 runner 的运行证据，不等同于真机验证；本轮未验证与实验中的 VOCAL.BIN 播放器组合。

另以 ARMSX2 Metal 4× 录制 39.12 秒菜单及战斗视频，分辨率 2560×1792、显示比例 4:3；战斗 BGM 状态再次确认是 0。录像元数据见上述证据目录的 `metal4x-recording.json`。视频及 ISO 留在本地构建目录，不纳入 Git。
