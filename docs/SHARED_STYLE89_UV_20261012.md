# 共享样式 89 的拼接黑线资源修复

用户确认统一修改该样式的所有引用。修改接入 `build_ui_headings()` 的 KVPDATA
资源输出阶段，契约在 `config/assets/ui-headings-zh.json` 的 `shared_frame_uv` 中。
构建器 `tools/srwz/ui_frame_uv.py` 先校验完整样式块及每条记录的前像，随后只允许
九处左侧拼块的 U1 从 24 改为 23。重复写入、遗漏图层、重复 owner 或额外字段
修改均拒绝。

Original 与 Best 的原始 KVPDATA 逐字节一致，Best 后端消费同批 Original
编译结果并校验原生资源相同。SP 使用自己的
`config/assets/special-disc/shared-frame-uv.json`，在 `write_image_labels.py`
完成标题及菜单修复后应用；`verify_full_text.py` 从最终 ISO 独立回读整个修复块。
SP 旧菜单回执锁定的是 UV pass 前的完整资源。因此先校验最终 UV 块，再在内存
副本中仅还原九个端点，交给原菜单整成员校验；实际 ISO 不作还原。两个阶段都
保留完整身份约束，不放宽旧菜单的哈希检查。

| 版本 | KVPDATA 大小 | 边框块 | 块索引 |
| --- | ---: | --- | ---: |
| Original / Best | 239664 | `[0x2F4C0, 0x2F730)` | 1401 |
| SP | 287456 | `[0x398B0, 0x39B20)` | 1569 |

两种布局的 624 字节块前像完全相同。每版均只修改九个 U1 字节，校验修改前后
完整块哈希；不会把本篇文件偏移直接套用到 SP。单元测试使用合成的周围数据，
完整原盘资源只在本地构建中验证，不提交资源副本。

## 原因与范围

KVMDATA 存贴图像素，KVPDATA 存独立的 sprite/UV 记录。样式 89 对应 chunk
1401，范围 `[0x2F4C0, 0x2F730)`。左侧拼块屏幕宽度为 24，原始 U1=24
使最后一个屏幕像素采到透明列 U=23；改成 U1=23 后，该像素落在有填色的 U=22。
修改覆盖上、中、下三块的 palette 7、10、15 三层。V、XY、材质、颜色、右侧
镜像、贴图像素和 executable 全部保留。

静态清点至少发现 17 个引用：12 条布局记录和 5 个直接调用。这不是 17 个独立
页面，也不是穷尽动态调用。共享资源只改一次，所有调用该样式的页面会使用它；
SP 的相同边框现在也接入本次修复；其调用数量未作同样的静态清点。
其他样式、其他游戏及模拟器的通用 UV 规则均不在本次范围。

## 已完成的验证

- 普通 ARMSX2 2.6.6.8.4、普通 PCSX2 2.8.2：既有抓帧状态中，仅改变九处
  资源字节；Metal 1×、Metal 6×（各向异性 16x）、软件原生输出均消除目标线。
- 软件基线修正：这两款普通安装版在原始 UV 下的软件渲染也有黑线，改后消失。
  早先 CPU 软件模型和另一源码构建的无黑线参考不能替代安装版基线。此次修改
  改变了左侧纹理映射，不声称与那个参考逐像素一致。
- PCSX2 候选 ISO 冷启动，未使用即时存档或运行时写入。只读回读整份驻留
  KVPDATA，与候选文件逐字节一致。用已有调查记忆卡的副本读取第 24 话中场存档，
  进入胜平的驾驶员培养页，Metal 6× / 软件输出均无目标线。
- 原生产 ISO 与候选 ISO 全流比较：恰好九个字节不同；所有文件系统成员记录、
  LBA、大小一致。没有移动后续成员或扩大分配。
- 完整组件构建成功；其 KVPDATA 与已测候选完全一致。执行 735 项 unittest，
  6 项跳过，其余通过，使用 bundled Python 3.12.14。系统 Python 3.9.6 的首次全套运行
  以 132 退出，换 bundled runtime 后完整通过。

三版本接入后的完整测试为 787 项全部通过、无跳过，包含固定版本 Unicorn 2.1.4
的原生 MIPS 指令测试。新增测试覆盖两种成员布局、九处修改范围、前像漂移、
遗漏／重复图层、越界、额外字段修改、完整修复块回读，以及菜单前一阶段的
精确重建。Unicorn 测试在本地非沙箱进程运行；沙箱内的首次运行停在原生用例。

三版已通过 `build_editions.py --force-rebuild` 完整构建、各版最终 ISO 回读及
`verify_editions.py` 同批绑定核验。另从三版 current ISO 读取 KVPDATA，分别
核对完整修复块：每版相对原盘同一块恰好九处 U1 不同，块内非目标字节、成员
LBA 和大小均保持一致。Original / Best 的最终 KVPDATA 相同；SP 使用自己的
287456 字节资源。结构化记录见
[三版 UV 回读摘要](../manifests/editions/shared-style89-uv-20261012.json)，
具体制品身份同时保存在 `manifests/editions/{original,best,sp}/current.json`。
本次正常构建将日期徽标更新为 `v0.4.2+20261012`；新三版 ISO 的运行验证尚未重做。

尚未逐页实机验证其余样式 89 引用；ARMSX2 的上述页面证据来自资源差异受控的
诊断状态，冷启动中文页面证据来自 PCSX2。以上画面证据来自 Original 候选；
Best 和 SP 的新构建运行验证独立记账，不继承 Original 的画面验收。

Best 的 `v0.4.2+20261009 / 24b140b` CHD 已另行生成 UV23 候选。CHD 完整性
检查和完整解压回读通过，ISO 恰好九字节不同；原 CHD 保留。该候选未启动验证。

## 复现及证据

项目根目录是本文所在仓库的父目录。调查目录为：

`../work/blackline-iso-uv-20261012/`

- `shared_style89.py`：从保留的生产 ISO 创建独立候选、完整 ISO 差异比较，生成
  仅九处资源变化的诊断状态。源镜像有意保持不变。
- `shared-style89/srwz-original-style89-uv23.iso`：已测候选。
- `shared-style89/index.html`：真实截图与证据索引。
- `shared-style89/manifest.json`：九处文件/ISO 偏移及源、候选哈希。
- `shared-style89/validation.json`：测试结果、渲染范围、截图哈希。
- `shared-style89/diagnostic-state-proof.json`：诊断状态恰好九处 EE 资源字节差异，
  其他 zip entries 不变。
- `shared-style89/pcsx2-cold-resource.json`：冷启动整份资源只读核对。
- `shared-style89/production-build.log`、`full-build-receipts/`：完整组件构建记录。
  该构建同时刷新了当前语料相对于旧锁的其他依赖；无关的 tracked 刷新已还原，
  当前改动只保留 UV 配置、UI manifest 及对应依赖锁。后续整版发布需照常刷新
  完整构建链，不能直接把旧整版 manifest 当作当前构建证明。

候选 ISO SHA-256：

`73bc7f0a9f663633886fae4b15b95a522f7e582db50c21505be7e2b844ecb22c`

KVPDATA SHA-256：

`de01691be46f2e70d97d03b4ea17bd42b3149594b18bc2d74ba94e417bbb983d`

组件验证命令：

```sh
python3 tools/build_ui_headings.py
python3 -m unittest discover -s tests -p 'test_ui_frame_uv.py'
/Users/nate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -v
```
