# 当前运行验收状态

本文只记录当前可成立的结论与缺口。截图必须绑定精确 ISO、存档和目标路线；
历史候选的画面不能晋级当前候选。

## 当前证据基线

```text
profile: ui-p10-full-story
size:    3,758,358,528 bytes
sha256:  21b00c2de1d25ca668f21b1c9d95486c223aa7f55d610d684495ca463eead4cc
static:  passed
boot smoke: pending for exact hash
target routes: pending
```

静态已确认：

- 66 个 ISO 成员路径和顺序保持；
- 59 个未替换成员 byte-exact；
- 7 个 replacement 独立 UDF 回读一致；
- 零成员 LBA 位移；
- 205 个 STAGE 压缩块可严格解码；
- 154 个选择剧情块的 82719 条对白、558 条条件文本和 8469 个说话人可以从最终
  ISO 逐条回读；
- 1760 个机师姓名字段、`确定／返回`、24×3 对话布局和 1925 个运行时占位符
  可以从最终 ISO 独立回读；
- 最终字库解码哈希一致；当前本地测试主字体为造字工房典黑细体，34 个缺字显式
  回退 Noto Sans CJK SC 2.004，统一 22px、24×24、y=-1，已纳入语料的剧情、
  P10 继承文本和旧存档主角名缺字为 0。

这些结论不证明 PCSX2 已到达人物确认后转场、数据库页面、各剧情关卡或 atlas
目标场景。

## 已证明的运行能力

当前 `21b00c...` 精确候选尚无匹配哈希的正式 fresh-process 收据。现有
`manifests/runtime/ui-p10-full-story-stage-entry.json` 绑定前一张
`383e51...` ISO，不能晋级为当前候选证据。

历史精确候选还分别证明过以下能力：

- PS2 DVD、ELF 和 PINE 可进入 Running，日志可做到零 TLB miss；
- 游戏 R5900 解压器可以接受 clean-room 重编码的 VT1 字库流；
- 两字菜单 canary、世界史和剧情中文能在目标 surface 显示；
- 标题 `开始／读取／继续／资料库` atlas 的运行纹理与离线 RGBA 结果一致；
- 前驱候选能够进入第一话并显示中文对白。

历史目标画面只是实现能力证明，不是当前 `21b00c...` ISO 的验收。当前候选仍需
重新执行目标路线并绑定新哈希。

## 当前待验收范围

### 启动与转场

- fresh process 加载精确 ISO、DVD、ELF、PINE Running 和零 TLB 待重新验证；
- 选择主人公、确认人物并进入第一话；
- 目标流程中无黑屏、TLB miss 或异常指令。

### UI 与数据库

- 标题、玩家设置、幕间、编成、战场、结算、搜索和系统设置；
- 人物技能、机体特殊能力、精神指令、小队长能力；
- 代表性的 348 个机体显示名和 711 个武器名；
- 长文本、边界宽度、数字／ASCII token 和列表滚动。

### 剧情

- 154 个选择剧情块中关键路线的进入、对白、说话人、条件和退出流程；
- 男女主人公路线、分支和跨关存档连续性；
- 当前字体在真实对话框中的字形、标点、行宽和三行边界。

### 战斗语音字幕

- `BTL/SRVC.BIN` 与配对 SEG 的完整文本、指针和长度边界；
- 样例 `「一気に間合いをっ！」` 已定位到第 71 块的 `0xACE32`、`0xAE527`；
- 中文码表复用原日文字槽后，未汉化 SRVC 出现中文混字属于预期，验收目标是将该
  文本域完整汉化，而不是维持原日文可读；
- 写回后仍需成员扇区预算、零 LBA 位移和实机战斗字幕验证。

### 图片 atlas

- 五张 KVMDATA 中文候选的真实场景归属；
- PCSX2 texture dump 与锁定 reference PNG 的完整 RGBA 比较；
- 变化像素只位于授权 mask；
- 选中／未选中、透明度和相邻 UI 无回归。

### 全量字库

当前 P10 与全文剧情统一字库已经通过静态覆盖。运行晋级前仍必须覆盖：

- 每个 standard resolver 行；
- 实际使用的 `0x7F/0xFD/0xFE/0xFF` raw trail 类；
- direct-index 非文本保留项；
- 完整 decoded-font 哈希和代表性目标 glyph。

## 运行 fixture

运行矩阵和 fixture 事实源分别是：

```text
config/runtime/ui-test-matrix.json
manifests/ui-runtime-test-matrix.json
```

优先补齐幕间、战场、前五关进度、结算前、全改造、商店和路线分支 memory card。
原始存档只读复制到隔离 session；savestate 只用于定位，最终证据仍从 fresh-process
primary route 采集。

## 通过标准

一个 surface 只有同时满足以下条件才可标记为通过：

1. 精确 ISO、组件、存档、日志和截图哈希齐全；
2. 从声明路线实际到达目标画面；
3. PINE 状态、DVD、ELF 和零 TLB 检查通过；
4. 所有文本、布局、交互和纹理断言明确通过；
5. hash-only receipt 已进入 `manifests/runtime/ui-cases/`；
6. runtime matrix 重新审计通过。

boot smoke、静态回读、旧截图或单独的 session probe 均不能替代上述闭环。执行
命令见 `BUILD_AND_RUNTIME.md`。
