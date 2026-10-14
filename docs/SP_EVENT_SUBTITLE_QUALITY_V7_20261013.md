# 事件字幕第七版：原生像素采样与字号调整

用户要求鉴赏完整性先记录、后续再做，本轮只改善字幕。单位、形态与音乐差异已整理到[完整性待办](SP_EVENT_COMPLETENESS_BACKLOG_20261013.md)；本版原生场景运行代码和菜单数据与第六版逐字节相同，没有扩展场景或BGM。

## 字幕显示

字号由26增加到32。保留x64～576、y388～428的底部居中区域，白字、黑描边、轻阴影、透明底，没有黑色底板。37句台词与第六版润色稿逐ID核对一致，12个标题不变。

第六版先制作512×40的每行纹理，再由GS将40行点采样到原生帧缓冲的20行。点采样会跳过部分行，4倍渲染的收益也会在这一步丢失。第七版仍按显示空间4倍渲染，但在生成阶段把每4×8个高分辨率样本平均成一个原生像素，直接输出512×20的字幕行；原生图元和纹理按1:1采样，显示时随地图纵向放大两倍。描边按原生像素比例重新生成，阴影强度减轻，文字增加少量笔画覆盖。

“字号32”是最终640×448显示空间中的设计字号，不是32个原生垂直像素。40像素是字幕行画布高度，包含留白、描边与阴影；不能将它当作实际字高。原生地图帧缓冲仍为640×224，本版改善纹理与采样，不改变游戏帧缓冲分辨率。

![第七版脉冲字幕](issue-assets/sp-event-subtitles-20261013/v7-quality/impulse-350.png)

最长一句仍完整落在区域内：

![最长一句字幕](issue-assets/sp-event-subtitles-20261013/v7-quality/impulse-longest-800.png)

## 检查方法

- 逐句生成37个原生文字遮罩，检查字面边界均未裁切；最长一句15字，宽度检查通过，见[尺寸检查](issue-assets/sp-event-subtitles-20261013/v7-quality/text-fit.json)。
- 新增交替水平细笔画的回归测试，确认被点采样漏掉的行能参与平均。连同记录打包与原图保留，共4个针对性测试通过。
- 12套字幕均为字号32、原生行高20，原effect图片、动画、语音、模型记录保留；ISO9660、UDF、VMAP及成员回读通过，见[构建记录](issue-assets/sp-event-subtitles-20261013/v7-quality/build-receipt.json)。
- 原生运行脚本和菜单数据与第六版逐字节相同；37句中文文本不变，见[静态画质记录](issue-assets/sp-event-subtitles-20261013/v7-quality/static-quality.json)。
- LRPS2从候选ISO冷启动，使用隔离记忆卡和原生按键；14轮完整播放返回覆盖全部12项，含格兰维昂两段各一次字幕时间窗补拍，无宿主内存写入或即时存档加载。覆盖两种字幕纹理格式，重点采样最长句、阿克艾里昂人物图、鸫的屏幕反馈以及其他字幕。鸫的反馈段连续三帧中字形稳定，消失后的采样画面未见可辨认字影；阿克艾里昂4位纹理字幕及原人物图正常，格兰维昂两段均拍到清晰台词。完整流程结果见[流程报告](issue-assets/sp-event-subtitles-20261013/v7-quality/flow-report.json)与[来源记录](issue-assets/sp-event-subtitles-20261013/v7-quality/provenance.json)。不将LRPS2结果称为ARMSX2或PCSX2人工验收。

同句新旧截图可在[画质对照页](issue-assets/sp-event-subtitles-20261013/v7-quality/comparison.html)查看。两图来自不同冷启动会话，同一句台词与相近播放时刻，不主张地图背景逐像素相同。

## 听校与候选

[听校页面](issue-assets/sp-event-subtitles-20261013/review.html)保留37段原音和此前编辑/勾选状态的兼容迁移。仅更新样式元数据；用户仍需逐句听校，页面内容不会自动写回项目。

当前扫描候选为`build/iso/special-disc/event-gallery/sp-event-gallery-subtitles-v7.iso`，精确ISO与ELF哈希见来源记录。第六版留在`work/iso/archive/sp-event-gallery-subtitles-v6.iso`作回退，兼容链接随文件整理更新；见[安装记录](issue-assets/sp-event-subtitles-20261013/v7-quality/install-receipt.json)。生产SP `sp-current.iso`保持不变。本轮没有commit或push。
