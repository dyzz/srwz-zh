# SRWZ shared JS layout

浏览器与 Node.js 使用 **同一份无依赖 ES module**。不用 DOM、Canvas `measureText` 或系统字体估算游戏宽度。JSON/JSONL CLI 和 Python 批量适配器调用的也是这份核心。

## 场景契约

| scene | 场景 | step | 总行宽 | 最大行数 | 缩进 |
|---|---|---:|---:|---:|---|
| `story` | 剧情对白 | 21 | 483px / 23格 | 3 | 所有续行1全角格 |
| `battle` | 战斗台词 | 22 | 462px / 21格 | 2 | 续行1全角格 |
| `main_flow` | 本篇梗概 | 16 | 480px / 30格 | 调用方字段预算 | 保留段首 |
| `sp_flow` | SP梗概 | 16 | 480px / 30格 | 调用方字段预算 | 保留段首 |
| `main_scroll` | 本篇普通滚动字幕 | 24 | 528px / 22格 | 调用方字段预算 | 保留段首 |
| `sp_scroll` | SP滚动字幕 | 25 | 575px / 23格 | 调用方字段预算 | 保留段首 |
| `main_scroll_strip` | 本篇两条窄条字幕 | 24 | 504px / 21格 | 调用方字段预算 | 保留段首 |

总宽度包含引号、标点和缩进；闭引号没有免费格。剧情续行22格正文+1格缩进；战斗续行20格正文+1格缩进。剧情/战斗优先填满前行；非对白正文先选最少可行行数，再均衡同段各行的物理像素宽度。不能通过改变step强行两端齐行。

剧情/战斗默认保护词语；梗概/滚动字幕默认 `protectWords:false`，不按中文词、人名、数字单位组合限制断行，采用 `balanced_width`。两种模式都保留标点禁则、完整控制符、完整 `<z>` 标识符及成对省略号。段首缩进/空白行界定段落，续行不擅自合并段落。滚动字幕空白行使用全角空白占位。

`<z>` 是作者语义，核心不会自动修改正文或把所有英数加标签。已有标签会按场景编译，原有native控制原样保留。剧情/战斗紧缩W14、H11、step12；结束分别恢复21/12/21、22/11/22。梗概与滚动字幕使用各自契约的紧缩参数，不套用对白。`advancePx` 与 `occupiedPx` 分开返回，行尾字形外沿（例如紧缩W14 / step12的2px外沿）计入检测。

原生宽度与非对白策略以 `config/text-layout/native-scene-contracts.json` 及其LRPS2证据为准；此前Python作者profile中的400/504/525是旧收窄稿；当前Python生产默认也已同步原生宽度。其余参数来自 `config/text-layout/zh-layout-profiles.json`、`compact_scopes.py`、已留存的原生场景分析与词表，通过 `tools/text_layout/export_js_contracts.py` 生成 `contracts.mjs`。不要手改生成文件；`--check` 检查漂移。不是从一个step值猜场景。

## 浏览器 / Node.js

```js
import { layout, measure, validate, expandCompact } from './engine.mjs';

const result = layout(
  '“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任务后返回基地！”',
  'battle',
  { preserveLineCount: false } // 明确允许改变字幕行数
);
console.log(result.text, result.rows.map(row => row.occupiedPx));
// 两行：446 / 198px，第二行含缩进
```

`layout` 重新分行，`measure` 保留输入分行只计算字形，`validate` 检查物理宽度/行数/缩进/标点，`expandCompact` 输出native控制形式。结果包含原生字形参数；height是游戏字体参数，不是已经翻倍后的画面高度。浏览器几何示意按height*2展示，不等于游戏像素光栅验收。

`preserveLineCount` 默认：战斗true，剧情false。默认不会偷偷新增/删除战斗行；用户批准改行数后才传false，并由调用方更新SRVC源文换行许可。`escapedNewlines:true` 用于语料内字面 `\n`（输入输出保留此表示），其余情况使用实际LF。前端和后端必须传同一scene和options；后端仍需独立执行一次，不能信任客户端发来的“已排版结果”。

`maxLines` 可收紧字段行数，不能放宽剧情/战斗最大行数。梗概/滚动字段必须由资源所有者给出行数预算；未给时只保证几何宽度。动态模板、重复渲染器、方括号参数、未知控制符、对齐卡片和独立选项不自动重排，返回结构化 `LayoutError`，不回退到猜测字符宽度。

STAGE关键词需显式传 `keywordLinks:true`，此时《》不占普通字格、链接内容不拆开；一般书名号不启用这个选项。运行时替换符默认预留6格，可通过 `placeholderCells` 选择明确预算；真实替换内容仍由资源调用方核对。

## JSON CLI / Python backend

```sh
printf '%s\n' '{"action":"layout","scene":"story","text":"“目标<z>MS-013</z>已锁定！”"}' | node shared/text-layout/cli.mjs
```

每行一个JSON请求，或一批请求的JSON数组。成功返回 `{ok:true,result:...}`，失败返回 `{ok:false,error:{code,message,details}}`；单条失败不隐藏其他批量结果。

```python
from srwz.js_layout import request_layout, layout_batch
result = request_layout('“目标<z>MS-013</z>已锁定！”', 'story')
# layout_batch([...]) 一次启动Node处理整批，避免逐条起进程。
```

Python适配器需要系统Node（或环境变量 `SRWZ_NODE` 指定路径）。字节编码、双字节空格、资源容量、源文SHA、压缩预算、字幕换行许可、ISO写回仍由原资源管线负责。本地社区站的战斗重排、普通剧情重排及预览测量已接入此核心；预览组件在浏览器中再次使用同一ES module核对几何。源文引号与特殊owner适配层仍保留；图鉴DSCR/DSC2正文现已接入JS，名称及其他字段保留原有规则。游戏生产图鉴、梗概与滚动布局及剧情/战斗几何门禁已接入；编码、容量与特殊owner仍由资源工具负责。审阅站已部署，详见本轮文档。

## 验证与本地运行

```sh
python3 tools/text_layout/export_js_contracts.py --check
node --test shared/text-layout/engine.test.mjs
python3 tools/text_layout/check_js_layout_parity.py
node shared/text-layout/server.mjs
# http://127.0.0.1:8767
```

页面“浏览器排版”仅本地执行；“与后端逐字段比较”调用本机Node API并比较完整JSON。几何预览不是LRPS2截图。测试包含已捕获LRPS2字形数据、引号/缩进/外沿、跨行状态、10场景参数、段落/硬空行、换行许可边界和Python差分。旧Python特殊owner会原样保留的部分文本，新核心会明确要求owner契约，这种差异单独记录。

## 浏览器原生字形预览

`assets/native-glyphs.json` 和带哈希的PNG来自 `export_preview_glyphs.py`：先核对当前Original发布ISO和读回证明，再解码24×24/4bpp字形，不裁字、不重新栅格化、不按字符改基线。5508个字符复用4060个原始格子（含字形库82格）；全角英数按生产写回归一规则映射至同一ASCII字形。`glyphs` 是各字符的原版字形格，供定宽场景使用；`latinBank.glyphs` 是英文数字和 - . ' / 在HarmonyOS字形库（字形编号576起）里的格子，比例排版场景里凡引擎给出 `advanceBox` 度量的字形都应取这里的格子，按本场景汉字格尺寸绘制。布局核心不依赖这些位图；浏览器绘制层按W/H缩放格子，所以字形形状、格内留白和字距不再由浏览器字体决定。姓名/变量及缺字提示保留网页字体。PNG图像插值仍与PS2绘制管线有差异，不等于新一次LRPS2验收。

社区站本地验证：`http://localhost:8768/layout-lab`，可切换剧情/战斗，载入英数混排；“按输入原样预览”会暴露第三行裁切，“按规则排版”使用共享核心生成两行。该诊断路由未发布；正式审阅站预览组件已经上线。

## 2026-10-28 宽度纠正与非对白均衡

梗概为原生30格/480px；普通滚动正文为本篇22格/528px、SP23格/575px。`summary/03/000`、`summary/04/000` 的504px裁剪区用独立 `main_scroll_strip`，也可以传 `scene:'main_scroll', options:{resourceId:'summary/03/000'}` 自动选择该变体。

默认的非对白正文不保词，以最少可行行数为第一目标，再最小化同段各行像素宽度对该段平均推进量的平方偏差；并列时先填较早行。不保证跨不同长度段落完全等宽，不合并段落，不改变固定step。实际均衡行宽可低于可用上限；例如54格在30格上限下排成27/27格，而不是30/24。`packing:'max_width'` 可显式选择旧式前行优先填满作比较，不是非对白默认。

16项JS测试包含850个纯中文长度/缩进组合，检查最少行数和同段行宽差不超过一个原生step；混排另检查作用域、外沿和原文保留。767个请求检查覆盖Python适配与JS输入输出；初次改用新散文策略时有76条与旧收窄稿不同。当前生产Python适配已调用JS，适配器一致性不再被当作独立旧算法的证明。

## 图鉴与浏览器格式化补充

图鉴正文三场景：`library_character`为21px step / 336px / 中文H12，`library_robot`为21px / 546px / 中文H10，`library_glossary`为21px / 525px / 中文H12。三者默认不保词、最少行数内均衡；紧缩W14/step12，字符／术语英文字高12、数字11，机体英文11、数字10；作用域结束按各自正文恢复，H10编码8A。

社区站的格式化接口返回已绑定原文并规范化后的JS排版输入；浏览器按钮用同一ESM再次执行layout，比较结果后才写入编辑框。图鉴正文提供原字形几何预览；图鉴名称、声优、登场作品、参数等字段未改用正文场景。此补充不代表原生补丁、全部构建工具、所有图鉴字段均已改成JS。

## 游戏构建

`tools/srwz/build_layout.py`提供生产批处理、既存分行校验和十场景预检。Original/Best/SP入口执行预检，四个ESM运行文件计入冻结输入及组件缓存指纹。图鉴正文生产批处理直接调用JS；剧情/战斗构建核对既存几何，保留源绑定与时序许可。梗概/滚动writer及作者工具使用JS，原生固定字格与特殊结构仍由其owner处理。需要Node.js；缺失或失败时停止，不回退另一套生产排版。

网站剧情预览对白使用黑色原生字形（白色alpha图集按剧情范围染色），战斗和图鉴保持白色。仅预览字色变动，不修改原生字库。
