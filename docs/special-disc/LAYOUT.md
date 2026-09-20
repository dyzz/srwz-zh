# Special Disc 目录契约

实施日期：2026-09-19。仅整理既有成果、调整工具路径和保存当前预览图片输入，不改变译文或游戏逻辑，不重建镜像。Special Disc 与 Original／BEST 的现行生产入口分开维护。

## 1. 当前目录

以下目录已实际建立。`tools/` 使用 Python 标识符 `special_disc`，数据与文档使用产品名 `special-disc`。

```text
docs/special-disc/
  README.md                     总入口
  LAYOUT.md                     本文
  STATUS.md                     进度与后续任务
  PLAN.md                       详细规划及历史研究记录

tools/special_disc/
  README.md
  check_workspace.py            只读路径与图片哈希检查
  writeback/                    11 个组件生成器、预览装配、剧情试排
  export/                       文本导出与 SD 解析适配
  translation/                  初稿、校验、术语与审阅表作者工具
  images/                       图片作者工具，不由预览构建自动调用
  verification/                 镜像回读与当前状态核对

config/products/special-disc/
  workspace.json                本次目录登记与兼容映射
  disc-inventory.json           原盘成员身份、位置、大小与哈希
  ui/                           exe_strings、menu_map、patch_sites 研究输入
config/editorial/special-disc/
  roster.json                   当前角色卡与暂定译名
  sd-terms.json                 当前 SD 术语草案
config/assets/special-disc/
  preview.json                  开发预览图片输入锁
  preview/<job>/                实际消费的 PNG／索引 NPY／调色板 NPY

corpus/zh/special-disc/          5 份现有译稿，位置与内容不变

work/authoring/special-disc/
  images/                       去字底板、作者输入、jobs、试图与工作包
  translation/                  batches、results、review、日志与历史批处理
work/review/special-disc/
  text-export/                  导出的 JSON／CSV／Markdown、旧 ZIP
  status/                       本次整理前 snapshot 与迁移后 verification
work/analysis/special-disc/      历史研究目录的集中链接索引
work/disc/special-disc/          从 SP 原盘恢复的只读成员缓存
work/build/special-disc/
  components/
    font/ text/ srvc/ compdata/ library/ nisv/ names/ flow/
    textures/ exe-patches/ system-text/
    stage-dialogue/             保留历史试排报告；实际首批组件在 text-candidate/stage/
  preview/                      预览成员与镜像装配工作区
build/iso/special-disc/preview/
  sp-image-preview.iso
  manifest.json
```

`rom/Super Robot Taisen Z - Special Disc [J].iso` 保留原位。本次不更名，也不改为 CHD。后续若改名或归档，应更新独立输入身份与恢复说明。

运行记录继续使用仓库约定的 `work/runtime/lrps2/<scenario-id>/`。已有 `sd-*`／`sp-*` 场景不搬动；后续场景建议命名为 `special-disc-<场景>-<日期>`，并绑定精确镜像哈希。PCSX2 验收证据单独登记。

## 2. 可版本管理的内容与本地内容

| 类型 | 保存位置 | 规则 |
| --- | --- | --- |
| 源码与文档 | `tools/special_disc/`、`docs/special-disc/` | 可提交；源码与可变运行输出分离 |
| 原盘／地址／菜单研究输入 | `config/products/special-disc/` | 保存解析与写回所需的既有清单；当前还不是完整产品地址契约 |
| 译稿及编辑参考 | `corpus/zh/special-disc/`、`config/editorial/special-disc/` | 当前草案状态不变，移动目录不代表术语获批 |
| 预览图片输入快照 | `config/assets/special-disc/preview/` | 保存此次预览真正读取的 21 份输入；哈希一致。状态为 development-preview-snapshot，不代表最终美术验收 |
| 作者工作包 | `work/authoring/special-disc/` | 本地保留；有不可自动恢复的用户底图和编辑中间稿，不能视为普通缓存删除 |
| 研究／审阅／运行证据 | `work/analysis/`、`work/review/`、`work/runtime/` | 本地保留，旧报告正文和原有哈希不回写 |
| 原盘成员缓存 | `work/disc/special-disc/` | 可按原盘哈希恢复，不允许手工修改后冒充原始成员 |
| 候选组件与镜像 | `work/build/special-disc/`、`build/iso/special-disc/` | 本地保留，不进 Git；正式可复建前不按“可重建”随意清理 |

源码迁入版本管理范围，不等于本次已经 commit。原有本篇发行说明、复盘和 STAGE 事件分析改动未并入此次整理。

## 3. 作者输入与构建输入分离

图片作者脚本的输出集中到 `work/authoring/special-disc/images/`。预览装配器只读 `config/assets/special-disc/preview/`，运行前核对 `preview.json` 的哈希，避免作者工作包中的重新绘制结果自动进入预览。

这次保存的 18 份图片输入与 3 份调色板均和既有预览 manifest 的输入哈希一致，没有重新绘字、量化或改变索引。后续改图时，应先审图，再显式更新快照和相应哈希；不要直接调用作者脚本覆盖锁定目录。

`apply_heading_plate.py` 已改读作者工作包内的 `inputs/heading-plate.png`，使用现有存档底板；其原先失效的 Claude 临时成员路径改为 `work/disc/special-disc/`。所需 `SLPS_259.20` 和 `DATA/VT1.BIN` 已从原盘恢复，并按原盘清单核对 SHA-256，恢复记录为 `work/disc/special-disc/extraction.json`。

翻译工具继续把批次、模型结果和审阅表写入本地作者目录。`.env` 留在仓库根部且被 Git 忽略；本次没有读取或复制凭据，也没有调用翻译 API。当前角色卡和术语草案移到 `config/editorial/special-disc/`，本地原位置有兼容链接。

## 4. 兼容与历史记录

活跃工具和工作包迁移后，原位置保留相对符号链接。旧文档的可点击链接和已有调用路径仍可找到同一份文件，没有保留两份可独立修改的源码。

典型映射如下，完整映射见 `config/products/special-disc/workspace.json`：

| 旧路径 | 当前路径 |
| --- | --- |
| `work/analysis/sp-localization-plan-20260917/writeback/*.py` | `tools/special_disc/writeback/*.py` |
| `work/analysis/sp-localization-plan-20260917/ai-image-kit/` | `work/authoring/special-disc/images/`；其中 Python 文件链接到 `tools/special_disc/images/` |
| `work/analysis/sp-mt-20260918/` | `work/authoring/special-disc/translation/`；其中 Python 文件链接到 `tools/special_disc/translation/` |
| `work/analysis/sp-text-export-20260918/` | `work/review/special-disc/text-export/`；导出脚本链接到正式工具目录 |
| `work/build/sd-<name>-component/` | `work/build/special-disc/components/<name>/` |
| `work/build/sp-image-preview-20260917/` | `work/build/special-disc/preview/` |
| `build/iso/sp-image-preview/` | `build/iso/special-disc/preview/` |
| `docs/SPECIAL_DISC_STATUS.md`、`docs/SPECIAL_DISC_PLAN.md` | 原位置保留入口页，正文为 `docs/special-disc/STATUS.md`、`PLAN.md` |

9/12、9/17 等历史研究包仍保留原位，由 `work/analysis/special-disc/` 集中索引。其中一次性脚本依赖原目录深度，尚未提升为正式工具；不通过移动它们改写历史证据。预览与组件报告保留生成时的路径，不伪造一次新的构建记录。

兼容链接是本地过渡层，新工具使用当前目录。未来移除链接前，先检查剩余引用、确认历史证据有恢复映射，再逐项清理；不要批量删除整个旧 `sp-*`／`sd-*` 集合。

## 5. 本次验证与后续目录预留

迁移日志和原脚本备份位于 `work/cleanup/special-disc-consolidation-20260919/`。每次移动先记大小和 SHA-256，再核对迁入文件；源码随后只调整路径、图片输入锁与校验输出位置。可变语料、图片成品和已有镜像未重写。

路径自检：`python3 tools/special_disc/check_workspace.py`。镜像与语料复核：使用带 NumPy、Pillow 的 Python 运行 `tools/special_disc/verification/audit.py`，输出到 `work/review/special-disc/status/verification.json`。图片作者工具依赖 OpenCV／SciPy，本次只检查语法和已保存输入，不重新绘制。

后续按实际实现再新增，不创建空目录冒充已接入：

- `tools/srwz/`：待解析器／写回器稳定后，将可复用库逻辑抽入这里；先保留现有 SP 入口。
- `config/products/special-disc/`：补正式地址契约、组件顺序与输入依赖；当前 `workspace.json` 只负责目录登记。
- `manifests/special-disc/`：正式组件／覆盖率／构建回读摘要，绑定精确输入输出哈希。
- `build/iso/special-disc/current/` 与 `build/release/special-disc/<version>/`：正式开发镜像和版本化补丁；当前仍使用独立的 `preview/`。

现有工具仍引用部分本篇构建答案键、历史解析输出和社区站参考数据。本次保持这些依赖及其原路径；把它们转为可独立复建的输入闭包属于下一阶段的构建规范化，不因目录整理而声称已完成。

## 两关文本候选

`work/build/special-disc/text-candidate/` 保存共享字库的隔离构建输出、SP 字库安装组件和 `stage/` 两关写回组件；`build/iso/special-disc/text-candidate/` 保存独立候选镜像及回读清单。构建入口为 `tools/special_disc/writeback/build_text_candidate.py`，范围与复现见 [TEXT_CANDIDATE.md](TEXT_CANDIDATE.md)。

## 当前译稿全量候选

`work/build/special-disc/full-text/` 保存 `system/`、`stage/`、`srvc/`、`frame/`、`image-labels/`、覆盖和检查日志；`build/iso/special-disc/full-text/` 保存完整文本候选及镜像报告。`build_full_text.py` 是统一入口。新图片文字单独冻结在 `config/assets/special-disc/full-text-image-labels.json`；原 `preview/` 图片快照不变。绑定补充和类型契约分别位于 `config/editorial/special-disc/`、`config/products/special-disc/`。详情见 [全量候选](FULL_TEXT_CANDIDATE.md)。
