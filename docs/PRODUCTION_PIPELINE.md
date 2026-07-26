# 正式生产流水线

状态：E1 最小纵向切片已实现。当前 `canary-menu` 已从正式
`SurfaceSpec + corpus/zh + codebook + BuildProfile` 进入原有、已验证的
canary writer；专用 canary 配置不再保存字形分配或 replacement text。

本文规定当前可运行入口，也规定后续菜单、摘要和剧情 writer 必须接入的输入
契约。字段设计的完整方向见 `ENGINEERING_PLAN.md`；本文只描述已经实现、可以
执行和测试的部分。

## 1. 数据流

```text
固定原版 SLPS/VT1 + 固定上游码表
                  |
                  v
          BuildProfile 选择集
             /      |       \
            v       v        v
     SurfaceSpec  corpus/zh  codebook
            \       |        /
             v      v       v
       profile reconciliation
                  |
                  v
       原版 surface 解码/哈希前像
                  |
                  v
      编码、字形、定长和布局门禁
                  |
                  v
       work/build/<profile>/components
                  |
                  v
       build/iso/<profile> -> PCSX2/PINE/截图
```

`config/canary/minimal-slps-font.json` 只保留 E0 构建环境、原版输入、
rasterizer、字库段和 golden 输出。生产语义来自下面四类文件。

## 2. 四类生产输入

### 2.1 SurfaceSpec

当前实例：`config/surfaces/menu-slps-opening.json`

必需事实：

- `surface_id`：渲染/写回 surface 的稳定 ID；
- `source_member`：原版容器成员；
- `record.entry_id`：和中文语料连接的稳定记录 ID；
- `record.source_text_sha256`：日文原文的 UTF-8 SHA-256，不保存第二份原文；
- `layout.offsets`：原版内写回位置；
- `layout.encoded_size_with_terminator`：包含终止符的分配大小；
- `codec_profile`、`render.profile`：编码和渲染语义；
- `writer.kind` 及其定长要求；
- `runtime_fixture`：运行证据应覆盖的场景。

地址只允许由 SurfaceSpec 持有。writer、中文语料和 PINE 验证器不得再各自复制
同一 offset。

### 2.2 中文语料

当前实例：`corpus/zh/menu.json`

每条记录只保存：

- `id`；
- `source_text_sha256`；
- `translation`；
- `editorial_status`；
- 可选 `notes`。

`corpus/zh` 不重复提交日文正文。修改当前菜单译文的唯一生产入口是
`translation`；修改专用 canary 配置不会改变译文。

当前 profile 支持：

```text
todo < draft < reviewed < final
```

profile 的 `minimum_editorial_status` 是构建门。运行验证是证据属性，不在修改
字体、writer 或 ISO 后自动沿用为新的编辑状态。

### 2.3 Codebook

当前实例：`config/encoding/codebook.json`

每个可编码中文字符必须有显式 assignment：

- 唯一 assignment ID、字符、两字节 code 和 glyph index；
- `mapping=standard`，并满足原版 `standard_glyph_index(code)`；
- `status=assigned`；
- 字体 raster 三层 SHA-256；
- allocation owner、依据和空白前像。

未登记 code、空白 glyph 和“码表没有引用”的位置都不是自动可用空间。
BuildProfile 只能选择 `assigned` 项；选了但译文未使用的 assignment 也会失败。

### 2.4 BuildProfile

当前实例：`config/build-profiles/canary-menu.json`

profile 只做显式选择：

- SurfaceSpec 集合；
- 中文语料源；
- codebook 及 assignment ID；
- 最低编辑状态；
- 必须满足的 gate 名称。

构建报告把这份选择投影为 `production_inputs`，静态与运行证据因此可以回指相同
输入，而不把某个本地 `work/` 文件当作事实源。

## 3. Fail-closed reconciliation

`tools/srwz/project.py` 和 `tools/validate_build_profile.py` 当前拒绝：

- profile 或其引用路径逃出项目根目录、缺失或 schema 不受支持；
- 重复 surface、translation、assignment、字符、code 或 glyph；
- SurfaceSpec 与中文记录的 source hash 不一致；
- 中文记录包含第二份 `source_text`；
- 编辑状态低于 profile 门；
- 未登记或非 `assigned` 的 codebook 项；
- code 与 glyph 公式不一致、code 低字节为 `00`；
- 与固定日文码表冲突的 code 或重复已有字符；
- 无法编码、定长不符或选中却未使用的字形。

canary writer 另从固定原版 SLPS 解码 source，验证：

- 实际解码长度等于 SurfaceSpec allocation；
- 实际日文文本 SHA-256 等于 SurfaceSpec；
- 多 offset surface 的原文一致；
- 原始编码字节与写回前像一致；
- 替换前后 width class 一致；
- 只有登记 glyph、SLPS 文本和 VT1 offset 表发生允许的变化。

## 4. 当前命令

先验证所有生产输入，不读取 ISO：

```bash
python3 tools/validate_build_profile.py
```

再从固定原版成员重建同一个 E0 golden：

```bash
python3 tools/fetch_canary_font.py
python3 tools/build_static_canary.py --force
```

继续构建和验证 ISO：

```bash
python3 tools/bootstrap_mkps2iso.py
python3 tools/build_canary_iso.py
```

PCSX2 已启动当前候选后，PINE 验证器也从同一个 BuildProfile 取得 codebook、
译文和 surface offset：

```bash
python3 tools/verify_pcsx2_font_runtime.py --force
```

单元与结构门：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## 5. 新增一个 surface 的顺序

1. 从固定原版解析结果确认实际读取源、稳定 ID、位置、allocation、codec 和
   render path。
2. 新建 SurfaceSpec；只登记已证实的事实，未知语义保持未知。
3. 在 `corpus/zh/<domain>.json` 增加同 ID 和 source hash 的中文决策。
4. 对所有新字符先完成 codebook allocation、字形锁和冲突/活性证据。
5. 将 surface、语料源和所需 assignment 加入一个小 profile。
6. 先运行 profile validation，再运行对应 component writer。
7. 检查 component diff、归档重读和 ISO 布局。
8. 为该 surface 建立独立 PCSX2 fixture；运行时内存一致和实际可见截图分别
   验收。

不得通过复制 canary 配置、在脚本中硬编码 offset，或直接修改 `work/` 输出来
新增汉化内容。

## 6. 当前边界

E2 已把 SLPS 菜单、MTV_PROS 摘要和 STAGE 剧情接入正式
SurfaceSpec/corpus/codebook/profile，并生成隔离 component manifest 和
PCSX2 fixture。`canary-complete` 只组合这三个已登记 surface，不代表数据库、
剧情或全游戏已经可批量写回。

`relocate_menu_texts_to_pool()` 已提供通用 SLPS/COMPDATA 普通 pointer 与
MIPS HI/LO 写回门禁，但尚未为真实文件登记可批量使用的池区。E3 还需完成：

- 全量 extraction freshness 与双向 reconciliation 的规模化运行；
- 真实 SLPS/COMPDATA 池区及批量 profile；
- 全量 STAGE arena policy 和通用 VT1 writer；
- offline render oracle、coverage ratchet 和 clean-copy deterministic build。
