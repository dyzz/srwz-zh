# v0.3.0 生产流水线

本页定义当前构建事实源、入口顺序和失败边界。分析脚本、实验脚本、机器翻译、审校
网页、内部问题记录和模拟器控制都不属于 v0.3.0 发布闭包。

## 事实源

| 输入 | 位置 | 责任 |
| --- | --- | --- |
| 日文基准与中文语料 | `corpus/ja/`、`corpus/zh/` | 稳定 ID、来源哈希、译文和结构 token |
| 术语 | `corpus/glossary/` | 统一名称与术语决定 |
| 领域配置 | `config/` | 成员、地址、容量、字体、图集和 writer 契约 |
| 组合配置 | `config/full-story-components.json` | 最终组件依赖和输出 |
| ISO 配置 | `config/iso/zh-release-current-build.json` | 原盘、replacement、固定 LBA 和目标哈希 |
| 发布配置 | `config/release/v0.3.0.json` | xdelta 输入、目标和包布局 |

`manifests/` 是构建和回读摘要，不是手工修改后反向驱动构建的事实源。`work/` 与
`build/` 都可重建，不能保存唯一译文或唯一配置。

## 数据流

```text
固定原版 ISO
  -> 原版身份与成员提取
  -> Rust codec 与字体来源准备
  -> 字符分配、布局预算与受控写回
  -> STAGE、UI 图集和领域组件
  -> 最终组件组合与独立回读
  -> fixed-LBA ISO 与整盘静态回读
  -> xdelta 生成、实际还原与 SHA-256 复核
```

对应入口：

```bash
python3 tools/verify_original_disc.py
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_rust_compressor.py
python3 tools/rebuild_zh_font.py --skip-fetch
python3 tools/build_iso.py
python3 tools/verify_full_story_iso_content.py --force
python3 tools/build_release.py
```

## 字体、文本与图集

- VT1 的字符到码位／glyph 分配由
  `config/encoding/zh-release-font-assignments.json` 追加式锁定，已有映射不得因语料
  排序变化而重排。
- printf、游戏控制码、换行和结构 tag 按控制语义保存，不作为普通字形处理。
- 双字节可见文本中的逻辑空格在写回时使用 `0x8140`，不得写入会破坏字节配对的
  裸 `0x20`。
- 固定 UI 图集消费 config 中已审核的渲染快照；v0.3.0 普通构建不运行实验性重冻结
  或发现式扫描。
- 所有 writer 锁定源文件大小、SHA-256、目标前像、容量和唯一 owner；拒绝静默
  截断、未知控制码、未登记指针和非目标字节变化。

## 压缩与 ISO

生产压缩、解压和压缩后回读统一使用 `tools/native/srwz-codec-rs/`。同一物理压缩流
在 decoded workspace 内完成有序写入后只进行一次最终重压，并验证完整回解与成员
预算。

ISO 采用 fixed-LBA 构建：replacement 可以比原成员小，但不能超过原扇区预算，
不能移动后续成员，也不能通过向压缩流追加无意义填充来改变格式。最终镜像大小、
成员、UDF/ISO9660 读取和整盘哈希必须与当前配置一致。

## 失败门

以下任一情况必须停止构建：

- 原版、配置、语料来源哈希或目标前像漂移；
- 未知 ID、缺字、无法编码字符或控制 token 变化；
- 文本、图集、归档或压缩成员超出预算；
- 指针、offset、成员顺序或 LBA 未经授权变化；
- 组件、ISO 或 xdelta 的独立回读不一致；
- 发布目录或 ZIP 包含完整 ISO、原版数据、存档或本地测试记录。

运行和画面验收是发布后的独立证据层，必须绑定精确 ISO 哈希；它们不由 Python 构建
脚本自动执行。
