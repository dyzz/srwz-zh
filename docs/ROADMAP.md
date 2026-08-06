# 路线图

路线图只记录当前状态和未完成门。历史阶段、失败候选和逐轮试验不在本文保留。

## 当前里程碑

| 里程碑 | 状态 | 已完成 | 剩余门禁 |
| --- | --- | --- | --- |
| M0 可重复基线 | 完成 | 原版锁、clean-room parser、固定上游快照、测试与 manifest | 持续防止来源漂移 |
| M1 中文 canary | 完成 | 菜单、世界史、剧情、字库、TIM2、ISO 与 PCSX2 纵向切片 | 仅保留为回归 fixture |
| M2 中文字库与文本引擎 | 全文静态候选完成 | 4,480 glyph 格式、严格码表、全文 registry、写回和完整 renderer 静态覆盖 | 目标画面 renderer/runtime 覆盖 |
| M3 系统 UI 与数据库 | 静态候选完成 | P0–P10 fixed-span、动态名称、武器／机体数据库、五张 atlas | 精确当前 ISO 的目标页面和纹理验收 |
| M4 剧情生产 | STAGE 全文静态候选完成 | 154 个剧情块、91746 条对白／条件／说话人、术语、写回、最终 ISO 回读 | SRVC 战斗语音字幕、译文润色、人审、关键路线运行与完整回归 |
| M5 发布 | 未开始 | 发布边界和目录契约已定义 | 当前候选证据闭包、补丁格式、安装验证和发行清单 |

## 当前候选

```text
profile: ui-p10-full-story
size:    3,758,358,528 bytes
sha256:  21b00c2de1d25ca668f21b1c9d95486c223aa7f55d610d684495ca463eead4cc
status:  static ISO passed; exact-hash runtime receipt pending
```

该候选替换 7 个成员、保持 59 个成员原字节且零 LBA 位移。静态成功不能替代
人物确认后转场、数据库代表页面、剧情关卡和 atlas 场景的实际运行验收。

## 下一步顺序

1. **提取并汉化 SRVC 战斗语音字幕**
   - 从 `BTL/SRVC.SEG`／`BTL/SRVC.BIN` 建立完整块、文本和指针清单；
   - 以截图 `「一気に間合いをっ！」` 的第 71 块双重出现作为首个回归样本；
   - 中文码表继续允许复用原日文字槽，未汉化日文混字不单独修字模；
   - 写回必须保持 SRVC 原成员扇区预算和其后成员 LBA。

2. **关闭当前 ISO 运行门**
   - 从 fresh process 启动精确候选；
   - 现有两条 fresh-process 收据属于前一张 `383e51...` ISO，当前哈希需重做；
   - 覆盖人物确认后转场、代表性 UI／数据库页面及 154 个剧情块的关键路线；
   - atlas 页面同时采集截图和纹理 delta。

3. **补齐运行 fixture**
   - `first-intermission-card`；
   - `first-battle-card`；
   - `first-five-progress-card`；
   - `pre-results-card`、`full-upgrade-card`、商店和路线分支存档。

4. **晋级全量中文字库**
   - 冻结 append-only registry；
   - 重绘固定 ASCII 与当前中文字符；
   - 覆盖每个 standard resolver 行、使用到的 raw trail 类和 direct-index 保留项；
   - 分开验收完整字库加载与具体 glyph 画面。

5. **继续剧情审校**
   - 按 `STAGE_ROUTE_MAP.md`、术语决定和优先队列润色当前全文草稿；
   - 继续以日文为源，英文只作参考；
   - 每批完成术语、token、行宽、写回、压缩和独立回读；
   - 不把机器首译直接提升为 `reviewed` 或 `final`。

6. **发布准备**
   - 冻结 release manifest 和输入哈希；
   - 选择不包含原版数据的补丁格式；
   - 在干净环境验证安装、重建和卸载／恢复路径；
   - 发布许可证、来源、已知限制和精确复验命令。

## 完成定义

项目“完成”至少意味着：

- release 范围内所有译文、术语和字体 assignment 均可追溯；
- 所有 writer、压缩流、归档和 ISO 均可确定性重建；
- 每类玩家可见 surface 均有匹配当前 ISO 的 runtime／visual 证据；
- 关键剧情路线和边界用例已实际运行；
- 发布包不含原版 ISO、解包成员、存档或其他不可分发数据。
