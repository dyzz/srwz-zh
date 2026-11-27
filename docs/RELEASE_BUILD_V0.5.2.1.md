# v0.5.2.1 热修构建记录

通过 `tools/build_editions.py --release-version 0.5.2.1 --out-dir build/iso/test/v0521-final` 构建三版三语合盘，使用 `tools/freeze_release.py` 冻结。各版标题版本号为 v0.5.2.1。[冻结镜像 SHA-256](../config/release/v0.5.2.1.json) · [静态回读](../manifests/releases/v0.5.2.1/validation.json)

headless ARMSX2 从冻结镜像启动，覆盖初版、The Best、SP 的简体、台湾繁体和香港繁体。在全部 18 个「版本 × 语言 × 界面」组合中，战场自由光标和场间整备主菜单均未显示常驻提示。每组都实测了 SELECT 打开、调整选项、× 取消、再次打开和 ○ 应用，并读取内存核对菜单状态和选项值。[战场截图](../manifests/releases/v0.5.2.1/map.jpg) · [整备截图](../manifests/releases/v0.5.2.1/home.jpg) · [运行记录](../manifests/releases/v0.5.2.1/runtime.json)

全量单元测试通过 1144 项。三份 xdelta 均从各自的日文原盘回解并核对冻结镜像的大小与整盘 SHA-256。[补丁清单](../manifests/releases/v0.5.2.1/patches.json)
