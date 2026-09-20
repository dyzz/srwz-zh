# Special Disc 开发配置

- `workspace.json`：当前目录和旧路径映射，仅为工作区登记，不是生产产品构建配置。
- `disc-inventory.json`：迁入的原盘身份与逐成员清单，内容保持原样。
- `ui/`：迁入的主程序字符串、菜单映射与补丁位置研究输入，内容保持原样。

作者参考为 `config/editorial/special-disc/`，预览图片输入为 `config/assets/special-disc/`。地址契约、完整组件依赖和发布配置待后续按实际实现补齐。

SP 原盘路径统一由 `disc-inventory.json` 的 `sp.path` 指定，当前为 `rom/Super Robot Taisen Z - Special Disc [J].iso`。各工具通过 `tools/special_disc/source.py` 读取此项，不再各自硬编码文件名；成员身份仍按清单中的 SHA-256 验证。

清单的 `original.path`（以及编辑复用记录中的 `rom/original.iso`）记录本篇来源，不是 SP 原盘入口。SP 成品 ISO 和中间候选也各有用途；不得将本篇来源或中文候选改指向 SP 原盘来消除路径报错。
