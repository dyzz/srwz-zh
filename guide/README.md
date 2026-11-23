# 流程与隐藏要素攻略

`srwz-z-flow-guide.html` 是面向玩家的离线单文件攻略，内嵌样式、脚本与全部正文，
不依赖网络资源；直接用浏览器打开即可。审阅站入口为
[单页攻略](https://srwz.dreamquest.club/guide/)，支持下载同一份 HTML 离线阅读。

攻略分三版，各自一个文件：`srwz-z-flow-guide.html`（简体）、`srwz-z-flow-guide-tw.html`（台湾繁体）、
`srwz-z-flow-guide-hk.html`（香港繁体），页头可以互相切换。三版是各自维护的静态文本，不做简繁转换：

- 人物、机体、关卡标题、胜败条件和游戏界面用语取各版自己的语料和术语表（`corpus/zh*`、`corpus/glossary*`；
  香港缺的文件按 `config/zh-hant/hk-uses-taiwan.json` 用台湾的）。
- 攻略正文在 `data/`（简体）、`data/zh-hant/`、`data/zh-hant-hk/`，三份结构必须一致，只有正文不同，`{{术语}}`
  占位和数字保持不变。页面框架用语在 `data/ui-strings.json`，以简体原文为键。
- `data/regional-sources.json` 记录繁体正文对应的简体文件哈希。简体正文改了，构建会报错，提示去改两份繁体；
  手工改完后运行 `python3 guide/build.py --accept-regional` 记录新哈希。

`data/` 保存隐藏要素、流程补充和资料表源数据。`build.py` 在构建时从当前关卡标题、
游戏 UI 语料、术语表和原盘 STAGE 脚本解析结果生成页面。人物、机体、武器和技能名
使用稳定术语 ID；稀有小队长能力用原界面偏移绑定当前译文。不要直接修改生成的 HTML。

在 `srwz-zh` 根目录运行：

```sh
python3 guide/build.py
python3 guide/build.py --check
python3 guide/test_build.py
```

生成器需要本地原盘提取资源 `work/disc/`，并输出 `stage-guide-manifest.json`，用于
记录输入哈希、107 个可玩标题的资源映射、36 项隐藏要素、术语来源和三版页面的哈希。Manifest 留在
开发侧；玩家只需 HTML。攻略生成与验证独立于游戏补丁和 ISO 构建。

审阅站的 `npm run guide:build` 重新生成三版攻略并复制到 `public/guide/`，`/guide/?lang=zh-hant` 打开对应版本，正式网站构建
会自动执行这一步。攻略 HTML 纳入 CDN 缓存差异清单，后续更新随网站部署一起发布。
章节和路线的技术映射保留在 `../docs/STAGE_ROUTE_MAP.md`。
