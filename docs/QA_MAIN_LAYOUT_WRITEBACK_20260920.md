# Original / The Best Q&A 排版写回（2026-09-20）

Original 和 The Best 采用同一份中文 Q&A 排版结果。全部 102 页、264 条菜单文字经过静态回读，最终有 70 页调整，源语料 2609 条记录重排成 2303 条显示记录。文字、每个字符的颜色和 z 值保持一致；稳定语料 ID 仍指向原始记录，不能拿显示记录序号直接当作语料 ID。

## 修复内容

- issue #24 的 30 页、44 处行首标点全部修复。`manifests/qa-main-layout-audit-20260920.json` 逐一给出原始 ID、标点的最终坐标和所在行。
- 第 12 页 `0.5%`、`1.2倍` 同行显示；其他已发现的数字、单位、MAP、SR 点数拆行也已处理。
- 末字起点不超过 x=513，解决旧 x=532 限制下的实际窗口裁切。
- 保留表格列起点；第 30 页这类黄色项目名加说明栏的续行，继续对齐说明栏。短说明能放入前行时合并，避免“防御”等词拆开或留下孤立短行。
- 保留标题、彩色强调、段落间隔、表格、项目符号和双字节空格。没有用改写英文、数字或术语的方式规避布局问题。

共记录 152 次排版修复，其中 68 次针对右侧窗口边界，其余处理行间断点。未发现行首闭合标点、行末开括号、水平重叠、越界或假名残留；项目符号 `・` 保留，未误判为日文。

## 镜像和范围

| 版本 | 当前 ISO | SHA-256 |
| --- | --- | --- |
| Original | `build/iso/zh-release-original/current-original.iso` | `a2b02c6820d7f1369ad255ad265dbd8d3eea387b2e116dca6b2c7a695227e79b` |
| The Best | `build/iso/zh-release-best/current-best.iso` | `993f18a02574dafc87474c29adbac4324a364d72a3d5d1ae427cd502f3a50230` |

两版解压后的 Q&A 完全一致，SHA-256：`60bd421801bd77d879a5b5e039b45bf09aa4800a51f2abcfd3fd6a05733410be`。

只替换当前 ISO 中已有的 NISVDATA 第 6 块压缩槽。分别读取 Original / Best 可执行文件的原生索引表，没有套用另一版的文件偏移。页分配表、每页容量、sprite 数据和 264 条元数据保持原样。两版最小页内余量都是 75 字节；ISO 文件大小、所有成员 LBA、Q&A 槽以外的完整字节均不变。

Original 工作 ISO 从已冻结 v0.4.2 子 CHD 恢复后更新；已发布 v0.4.2 的 CHD 没有覆盖。两次排版修正的回执形成可追溯链，首次结果保存在 `work/authoring/qa-main-20260920/{edition}/baselines/`。当前回执明确记录为 Q&A 增量验证，不冒充整盘重新构建和全游戏运行测试。

## 构建与验证

- 生产构建：`tools/srwz/nisv_strategy_qa.py`，按字符重排由 `tools/srwz/qa_typography.py` 实现；The Best 后端继续消费同一次 Original 前端产物。
- 完整构建和最终 ISO 内容验证器均已适配显示记录数变化；源清单仍锁定 2609 条，成品改为验证文字与样式序列、坐标、页面容量和实际显示记录数。
- 当前 ISO 的窄范围更新工具：`python3 tools/update_qa_editions.py --edition original --apply`，Best 对应 `--edition best`。再次运行会验证输入和当前回执，并在内容已一致时报告 `already_current`。
- SP 使用其已验收排版配置；共享代码调整后，SP 既有组件的逐字节幂等测试仍通过，本轮没有再次改写 SP ISO。
- Q&A 18 项测试通过；Best 相关 23 项通过。
- 扩大到发布工作流的 40 项检查中，有 2 项既有失败：`story/014/dialogue/02.02/0073` 人物称谓样本缺失，以及 `battle:00113`“快脱出 / 逃生”断言差异。未改动这些无关内容。

运行证据：最终两版均通过 LRPS2 Software 逐页打开 102 页，并逐页执行向下滚动检查；各保留 204 张截图，共 408 张。所有页号通过问题标题 OCR 和少量识别差异的人工复核交叉确认。人工画面复核覆盖第 6、12、29、30、54、60、64、78、87、93、100、102 页的数字、表格、标点和右侧窗口边界；不把自动打开全部页面等同于逐行人工校对。全部操作使用按键输入和隔离存储卡，没有内存修改。

最终回执见 `manifests/qa-main-runtime-20260920.json`。中间候选截图位于 `*-before-table`，未混用作最终镜像证据。issue #24 明确接受 LRPS2 作为运行验收依据。

对应 CHD 已保存到 `build/chd/qa-20260920/current-original.chd` 和 `current-best.chd`，同目录提供所需父 CHD 的硬链接。两个子 CHD 均经过验证、完整解压及 ISO SHA-256 比对，结果完全一致。工作 ISO 暂留供复核，保留登记已更新。

## 证据文件

- `manifests/qa-original-writeback-20260920.json`
- `manifests/qa-best-writeback-20260920.json`
- `manifests/qa-main-layout-audit-20260920.json`
- `manifests/qa-main-runtime-20260920.json`
- `manifests/qa-main-chd-20260920.json`

实现已分别提交为 `851017a`（主版本排版）和 `67a2403`（SP 校订与写回）。用户确认后，GitHub issue #24 于 2026-09-20T09:40:28Z 以 completed 原因关闭；未发送额外评论。本次没有推送提交。
