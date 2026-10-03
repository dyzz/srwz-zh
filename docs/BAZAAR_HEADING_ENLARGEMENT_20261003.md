# 集市标题放大与三版生产入口

2026-10-03。按用户要求，将“集市”的字号从 42 增至 62。原版字形墨迹为
137×61，原中文为 82×41，放大后为 120×58。保留既有译文、字块范围及 `-Bazaar-`
装饰。对照见 [原版／修改前／放大后](issue-assets/bazaar-heading-20261003/comparison.png)。

## 写入范围

`config/assets/ui-bazaar-atlas-zh.json` 及其已冻结渲染快照、图集组件和依赖锁同步更新。
本次仅改变 KVMDATA 第 5 页 `(3,1,137,61)` 标题矩形内的 3,737 个索引像素，
相对修改前成品为 2,035 个归档字节。其他 13 个冻结标签记录逐字节相同；TIM2 头、
CLUT、非目标像素及归档尾部保持原样。KVPDATA 绘制记录不变。三版实际 ISO 中，KVMDATA 成员之外的全部字节也与修改前逐段比较一致。

首次隔离构建揭示 SP 沿用不可变 text-canary 基线中的旧图集，不会自动消费本篇
集市的冻结更新。新增 `config/assets/special-disc/bazaar-heading.json` 和
`tools/special_disc/writeback/bazaar_heading.py`，由 SP 正式 image-labels 写入流程消费。
该配置保存同一放大字块的冻结索引，并绑定共享渲染快照；构建不重新栅格化文字。

SP 写入检查标题旧像素／已写入像素、格式和头／CLUT／尾部哈希，且只修改矩形内
索引。缓存已有依赖契约将所有 config 和 SP 工具纳入指纹，新增入口会使旧组件失效。
装配检查配置哈希，独立最终 ISO 验证器逐像素回读放大字块，再核对组件收据。

## 验证边界

26 项针对字体图集、共享引用、SP 标题和新增集市入口的测试通过。新增测试覆盖
非目标索引保留、重复写入、错误旧像素／CLUT／冻结像素拒绝、共享快照漂移拒绝和
SP 其他标题字块无重叠；另在已验证的旧 SP image-labels 组件上检查实际覆盖结果。

三版生产 ISO 的当前身份、逐像素回读、KVPDATA／非目标字节保留和 SPECIFICATIONS
共享 I 保留证明见 [生产与回读收据](../manifests/editions/bazaar-20261003.json)。
CHD 完整解压还原的 ISO 哈希证明见
[CHD 验证](issue-assets/bazaar-heading-20261003/chd-verification.json)。

本次没有把菜单／指令重做或英文还原混入集市修改。新 ISO／CHD 的 PCSX2 和人工
集市场景验收待复核；旧 SPECIFICATIONS 的 LRPS2 截图不能作为本次新成品的运行验收。
