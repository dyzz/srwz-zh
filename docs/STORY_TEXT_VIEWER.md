# 本地剧情文本阅读器

`tools/build_story_viewer.py` 会把现有的剧情文本队列生成一个完全本地的静态网页。网页不执行游戏、不访问网络，也不参与 ISO 写回；它只用于翻译阅读、校对和路线整理。

## 构建

在仓库根目录运行：

```sh
python3 tools/build_story_viewer.py
```

产物位于 `work/review/local-model/story-viewer/`（`work/` 已被忽略，不会进入提交）：

```text
index.html       页面骨架
styles.css       本地样式
app.js           搜索、筛选、路线/资源导航
data.js          内嵌的静态剧情数据
BUILD-MANIFEST.json
```

直接打开 `index.html` 即可，不需要启动服务。若浏览器策略或调试工具更适合 HTTP，可在产物目录启动标准库服务器：

```sh
python3 -m http.server 8765 --directory work/review/local-model/story-viewer
```

然后访问 <http://127.0.0.1:8765/>。

构建完成后，即使误打开源码模板 `tools/story_viewer/index.html`，它也会尝试加载同一份 `work/` 静态数据；推荐仍使用上面的生成产物入口。

## 页面顺序与数据边界

页面左侧的“路线导览”来自 `docs/STAGE_ROUTE_MAP.md`，展示主人公路线、共通路线和分支标题。正文中间的“剧情资源”来自 `story-dialogue-unique.jsonl`，按照 `story/001` … `story/153`、`story/185`、`story/186` 的资源号排序。

仓库路线表已注明：`Stage Name` 的标题 `ordinal` 与 `story/NNN` 资源文件号不是一对一关系，一个章节还可能使用多个资源文件。因此网页不会把章节标题强行绑定到某个资源号；这避免了看起来顺滑但实际错误的章节映射。每条对白保留日文原文、当前译文/机器草稿状态、说话人、分段、出现次数、来源 ID 和源文本哈希，方便回到翻译队列校对。

## 更新数据

如果剧情队列或本地模型样本发生变化，重新运行构建脚本即可覆盖忽略目录中的静态产物。脚本优先显示队列中已有的审校译文，其次显示本地模型验证产物中的机器草稿，最后标记为“待翻译”；机器草稿不会覆盖已有审校译文。

## 验证

```sh
python3 -m unittest tests.test_story_viewer
python3 tools/build_story_viewer.py
```

测试检查路线标题解析、资源顺序、队列哈希以及译文状态计数。静态网页本身不等同于 PCSX2 运行时验证；它只验证导出文本和阅读顺序。
