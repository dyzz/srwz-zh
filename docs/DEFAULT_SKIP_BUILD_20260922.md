# 默认 skip 与三版日常测试镜像：2026-09-22

三版当前 ISO 均已默认内置方块键跳过战斗动画；统一构建后自动更新 `build/iso/daily-test/` 的精确副本，SP 已纳入。带版本的冻结发布镜像和配置保持不变。

## 实测时间

本机时区 Asia/Singapore（UTC+8），本轮 19:53:18 开始，19:59:32 完成。正常完整构建，使用本地已有原盘、工具链与资源缓存；非空缓存冷启动基准。

| 阶段 | 墙钟耗时 |
| --- | ---: |
| 原盘预检与冻结输入 | 4.582 秒 |
| ORIGINAL（含准备、校验、当前盘及日常副本发布） | 104.597 秒 |
| BEST（含准备、校验、当前盘及日常副本发布） | 27.468 秒 |
| SP（含准备、校验、当前盘及日常副本发布） | 237.533 秒 |
| 整批合计 | **374.181 秒（6 分 14 秒）** |

构建完成后另外运行一次三版批次绑定校验，耗时 9.537 秒；此时间不计入上表。

## 子阶段

| 版本 | 子命令 | 耗时 |
| --- | --- | ---: |
| original | `codec` | 0.219 秒 |
| original | `components` | 62.435 秒 |
| original | `fonts` | 0.096 秒 |
| original | `iso` | 11.129 秒 |
| original | `iso-toolchain` | 6.275 秒 |
| original | `readback` | 16.754 秒 |
| original | 日常副本复制、完整哈希与 skip 回读 | 1.539 秒 |
| best | `native-components-and-iso` | 20.888 秒 |
| best | 日常副本复制、完整哈希与 skip 回读 | 1.484 秒 |
| sp | `rust-compressor` | 2.572 秒 |
| sp | `sp-full-text` | 216.040 秒 |
| sp | `sp-independent-readback` | 12.228 秒 |
| sp | 日常副本复制、完整哈希与 skip 回读 | 1.483 秒 |

子阶段之外还包含私有输入物化、缓存准备、原盘与产物哈希、当前盘发布及回执绑定检查，均已计入各版总耗时。BEST 使用同批 Original 前端结果，因此其耗时不是完全独立重建本篇的耗时。SP 完整写入阶段占整批约 58%，是本轮主要耗时项。

## 当前镜像身份

以下时间是 ISO 文件最后写入时间（UTC+8），早于该版最终回读与发布结束时间。日常副本保留源文件时间，且 inode 与主输出不同。

| 版本 | 日常路径 | 文件时间 | SHA-256 |
| --- | --- | --- | --- |
| original | `build/iso/daily-test/current-original-skip.iso` | 2026-09-22T19:54:40.306900+08:00 | `f3a36c90bad5a4e303ecd4e44b84563ad460909716100fb8fbbe7bf8a4021ced` |
| best | `build/iso/daily-test/current-best-skip.iso` | 2026-09-22T19:55:26.080160+08:00 | `b82ca630e04aaa8abff08046d030918c36705ac59005e5f55610fb262a45cf25` |
| sp | `build/iso/daily-test/current-sp-skip.iso` | 2026-09-22T19:58:59.880390+08:00 | `cd4e8ae3ba23d6974cfe896caf250af54a55014645990e8fe6556acdc6ede3e5` |

此前日常 Original / BEST 均为 2026-09-20 22:06 的旧盘，目录中没有 SP。现在三版均与对应当前盘大小、SHA-256 完全一致。

## 验证与输入

- 43 项相关测试通过：版别隔离、批次失败行为、输入快照、skip 开关与原生跳转字节、日常副本哈希/独立写入/坏输入保护。
- 三版最终内容回读通过；从三个日常副本读取各自可执行文件，验证 skip hook 与跳转。
- 独立 `verify_editions.py` 校验三版实际 ISO、日常副本、冻结输入、组件与最终内容回读回执的绑定。
- 本次未重新运行 LRPS2 或 PCSX2。可选 Unicorn 测试依赖未安装，不计入 43 项通过测试；不继承旧 ISO 的运行验收状态。
- 源码提交：`182640c`；冻结输入：`086fbca37c31fffde79a21db0df7c8c340ae8c5a83b5c23a393ad534590cec85`。
- 构建包含当时工作区已有的 4 份剧情语料修改：SP story-dialogue，以及本篇 stage-013、stage-016、stage-186；这些编辑保持原有未提交状态。构建后核对实际输入，未发现冻结后漂移。

批次凭据：`manifests/editions/default-skip-20260922.json`；当前回执：`manifests/editions/{original,best,sp}/current.json`。
本地日志与时间清单：`work/reviews/default-skip-20260922/`。

```sh
python3 tools/build_editions.py
python3 tools/verify_editions.py --manifest manifests/editions/default-skip-20260922.json
```
