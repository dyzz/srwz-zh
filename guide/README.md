# 流程与隐藏要素攻略

`srwz-z-flow-guide.html` 是可直接离线打开的单文件攻略。页面的 CSS、JavaScript、
流程数据与隐藏要素均内嵌，不依赖网络资源。面向玩家的页面只分为“流程图”和
“隐藏要素”两个视图；关卡条件、加入机体、强化内容与本话隐藏步骤全部直接展开。

生成：

```bash
python3 tools/build_stage_guide.py
```

检查已提交页面是否与当前输入一致：

```bash
python3 tools/build_stage_guide.py --check
```

数据边界：

- `docs/STAGE_ROUTE_MAP.md` 提供路线表；中文标题必须与
  `corpus/zh/menu/stage-names.json` 完全一致。
- 原版 `work/disc/DATA/STAGE.BIN` 的每个覆盖块经生产 Rust 解码器解压；块头的
  `stg_###a/b/c.bin` 名称把资源号绑定到标题 ordinal。
- 胜利、失败和 SR 条件由 STAGE 指针表重新解析，再按稳定 corpus ID 读取中文。
- `data/hidden-elements.json` 只写触发关系；其中所有 `{{term-id}}` 在构建时必须从
  全局 glossary 或全量机体显示名表解析，未知术语会让构建失败。
- `data/progression.json` 整理每话加入、换装、新武器与数值强化；Akurasu Timeline
  只用于核对取得时点和覆盖范围，页面正文统一使用项目全局术语。已确认的 Akurasu
  名称、重复条目或条件解释问题，会在对应关卡显示简短“Akurasu 校正”。

`stage-guide-manifest.json` 保存输入锁、完整资源哈希、入口地址、覆盖数与术语来源，
供维护和自动测试使用，不在玩家页面展示。
