# LRPS2 自动运行验证

仓库内自动运行验证统一使用 LRPS2 + `libretro.py`。PCSX2 只用于测试者手工验收，
不再通过 CGEvent、键盘事件或窗口焦点执行自动流程。自动验证和 PCSX2 手工验收仍是
两个独立证据通道，都不能替代组件、ISO 和静态回读门。

## 固定环境

当前 macOS 自动基线是：

- Rosetta 下的 x86_64 Python 3.12 或更高版本；
- `libretro.py==0.8.3`；
- `config/runtime/lrps2-load-menu.json` 锁定的 x86_64 LRPS2 dylib；
- LRPS2 `Software (SW)` renderer；
- 独立的 system、save 和输出目录；
- `config/iso/zh-release-current-build.json` 声明的精确 ISO；
- 默认读取 ARMSX2 当前 `Mcd001.ps2`，每次运行复制到独立 session 后再挂载。

官方 arm64 LRPS2 核心目前会在 Apple Silicon macOS 的重编译器初始化阶段执行未成功
切换为 executable 的动态代码，并在 `retro_load_game` 前后触发 SIGBUS／Instruction
Abort。自动入口因此 fail closed 要求 `platform.machine() == x86_64`；不能因为 nightly
存在 arm64 dylib 就把它当作可用基线。

LRPS2 核心放在本地忽略目录：

```text
work/runtime/lrps2/core-x86_64/pcsx2_libretro.dylib
```

BIOS 由测试者合法提供，放在：

```text
work/runtime/lrps2/system/pcsx2/bios/
```

核心、BIOS、记忆卡副本、截图和 receipt 都不得进入 Git 或发布包。runner 对输出路径
fail closed：包括 `--output-directory` 覆盖在内，只允许写入
`work/runtime/lrps2/` 的子目录；仓库 `.gitignore` 用 `/work/` 覆盖整棵运行树。核心可以从
Libretro x86_64 macOS nightly 获取；下载后的文件必须匹配场景配置中的 SHA-256，
nightly 更新不能静默替换验证基线。

## 运行

在 x86_64 Python 环境安装前端：

```bash
arch -x86_64 /path/to/python3.12 -m pip install 'libretro.py==0.8.3'
```

执行默认“读取界面”场景：

```bash
arch -x86_64 /path/to/python3.12 \
  tools/run_lrps2_validation.py
```

核心、system、ISO、记忆卡和各自期望哈希都可以通过 CLI 显式覆盖。核心和 ISO 必须
有精确期望哈希；默认 ARMSX2 卡有意不锁哈希，以便每次使用当前存档。如需复现某张
固定卡，和 `--memory-card` 一起传入 `--expected-memory-card-sha256`。例如验证一个尚未
写入 ISO config 的候选时：

```bash
arch -x86_64 /path/to/python3.12 \
  tools/run_lrps2_validation.py \
  --iso /absolute/path/to/candidate.iso \
  --expected-iso-sha256 <sha256>
```

默认输出：

```text
work/runtime/lrps2/<scenario-id>/<timestamp-pid>/
  receipt.json
  save/<iso-stem>.ps2
  frames/<frame>-<capture-id>.png
```

runner 先把源记忆卡复制到会话目录，LRPS2 只读取或修改隔离副本；receipt 会记录源卡
运行前后哈希、复制完成后的副本哈希、隔离卡运行后哈希、ISO／核心身份、
Python／libretro.py 版本、核心选项、逐帧动作、截图 RGBA／PNG 哈希、亮度、dHash 和
每项断言。副本与源卡不一致，或 ARMSX2 源卡在运行期间发生变化，整个 session 都失败。

## 已固化的标题路线

所有路线都先在第 1801–1803 帧按 Start 跳过启动 CG；标题菜单的移动和确认使用互不
重叠的三帧脉冲：

| 场景配置 | 标题后的动作 | 目标 |
| --- | --- | --- |
| `lrps2-title.json` | 无 | 标题主菜单 |
| `lrps2-new-game-menu.json` | 圈 | 剧本选择 |
| `lrps2-load-menu.json` | 下、圈 | 存档读取列表 |
| `lrps2-continue-menu.json` | 下、下、圈 | 当前卡的快速继续结果 |
| `lrps2-library-menu.json` | 下、下、下、圈 | 资料库主菜单 |

执行指定路线：

```bash
arch -x86_64 /path/to/python3.12 \
  tools/run_lrps2_validation.py \
  --sequence library
```

`--sequence` 读取 `config/runtime/lrps2-common-sequences.json`，不会在 Python 入口中
暗藏另一份按键表。可用路线随时可以列出：

```bash
python3 tools/run_lrps2_validation.py --list-sequences
```

需要完全独立的基础场景时仍可传 `--scenario path/to/scenario.json`；它与
`--sequence` 互斥。不传时默认使用 `load`。

## 追加自定义按键序列

issue 路线不需要复制核心、ISO、记忆卡和启动帧配置。先选一条已经验证的常见路线，
再用 `--append-input-sequence` 追加一个或多个 JSON：

```bash
arch -x86_64 /path/to/python3.12 \
  tools/run_lrps2_validation.py \
  --sequence title \
  --append-input-sequence \
    config/runtime/examples/lrps2-custom-open-load.json
```

自定义序列从基础场景的 `terminal_frame` 开始。每个 step 的 `after_frames` 都相对于
上一个 step 的完成帧，而不是相对于模拟器启动帧：

```json
{
  "schema_version": 1,
  "sequence_id": "issue-047-route",
  "description": "Open the affected screen and capture its stable UI region.",
  "steps": [
    {
      "after_frames": 60,
      "button": "down",
      "duration_frames": 3,
      "label": "select-affected-entry"
    },
    {
      "after_frames": 60,
      "button": "circle",
      "duration_frames": 3,
      "label": "open-affected-entry"
    },
    {
      "after_frames": 120,
      "capture": {
        "id": "issue-047-result",
        "expected_width": 640,
        "expected_height": 448,
        "dhash_region": {
          "x": 0,
          "y": 0,
          "width": 640,
          "height": 70
        },
        "expected_dhash": "0123456789abcdef",
        "max_dhash_distance": 2
      }
    }
  ]
}
```

每个自定义序列至少要有一个按键 step 和一个截图 step；只发送按键但没有结果证据会
fail closed。`duration_frames` 默认是 3。支持的 PS2 名称包括 `circle`、`cross`、
`triangle`、`square`、方向键、`start`、`select`、L/R 系列；映射仍由 runner 统一转换。

首次探索可以暂时只设置截图尺寸和亮度，运行后从 receipt 读取 dHash；用于 issue
关闭的固定路线应再锁定稳定全屏或 ROI dHash 并 fresh rerun。receipt 会记录基础场景
JSON 和每个追加序列的路径、大小、SHA-256、起止帧、动作数与截图数。组合后的 session
ID 类似 `title--issue-047-route/<timestamp-pid>/`，仍只能位于忽略的
`work/runtime/lrps2/`。

## 已验证的读取界面路线

`config/runtime/lrps2-load-menu.json` 固定以下一基帧序列：

| 帧 | 动作 | 作用 |
| ---: | --- | --- |
| 1801–1803 | Start | 跳过启动 CG |
| 1981–1983 | 下 | 标题菜单从“开始”移动到“读取” |
| 2041–2043 | 圈 | 打开读取界面 |

第 2040、2160、2220 帧分别断言“读取已选中”、“存储卡检查完毕”和“存在存档的读取
列表”。三张图必须是 640×448，并通过亮度范围和 64-bit dHash 距离门。存档行会随
ARMSX2 当前卡变化，所以最后一张只对读取界面的固定顶部区域计算断言 dHash；完整画面
dHash 和像素哈希仍写入 receipt。需要验证具体存档内容时，应显式锁定记忆卡哈希并为
该问题另设画面断言。固定帧序列只适用于配置锁定的核心、软件 renderer 和 ISO；任一
身份变化都要重新取得证据，不能沿用旧截图。

LRPS2 使用 RetroPad 面键命名：PS2 圈=`JoypadState(a=True)`，叉=`b=True`，
三角=`x=True`，方块=`y=True`。场景 JSON 统一写 PS2 名称，runner 在内部转换，避免
路线脚本直接混用 RetroPad 字母。

## libretro.py 兼容边界

`libretro.py` 0.8.3 在当前 x86_64 Python 的 video callback 中可能把 framebuffer
地址包装为嵌套 `c_void_ptr`。runner 在注册回调前解开该包装，再把确定的整数地址交给
`memoryview_at`。LRPS2 初始化还要求日志接口存在；runner 提供日志接口但把冗长核心
消息丢弃，不能传 `log=None`。

这些兼容处理属于锁定版本的 frontend bridge。升级 `libretro.py` 或 LRPS2 时必须先
跑单独探针和默认读取场景，再决定是否删除兼容层。

## PCSX2 手工验收

测试者仍可在 PCSX2 中使用同一精确 ISO 和匹配存档人工检查字体、布局、动画和交互。
仓库不负责启动、聚焦或发送 PCSX2 按键。人工结论应记录 PCSX2 版本、ISO SHA-256、
存档 SHA-256、路线和截图；LRPS2 自动通过不能自动关闭需要 PCSX2 视觉判断的问题。
