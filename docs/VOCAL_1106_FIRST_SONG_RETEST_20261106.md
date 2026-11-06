# 当前 1106 汉化版：第一首音乐鉴赏真唱复测

2026-11-06，使用 ARMSX2 headless runner（SW），分别从当前 editions/current.json 指向的 SP、Original、The Best 汉化镜像生成 APFS 测试副本。只替换音乐鉴赏第一首《マジンガーZ》（BGM ID 0），音频为 test.mp3 经当前网页流程归一化后的完整 Vorbis，220.9698 秒。三份生产源镜像未修改。

| 版本 | 完整播放与循环 | 退出停止 | 重新播放 | 解码/RPC/欠载 |
|---|---|---|---|---|
| SP | 通过，连续推进 14400 帧，循环 1 次 | 通过 | 通过 | 0 / 0 / 0 |
| Z 本体 Original | 通过，连续推进 14400 帧，循环 1 次 | 通过 | 通过 | 0 / 0 / 0 |
| Z 本体 The Best | 通过，连续推进 14400 帧，循环 1 次 | 通过 | 通过 | 0 / 0 / 0 |

## 运行证据

三版均通过正常菜单进入音乐鉴赏并选择第一首，没有临时 RAM 解锁或改歌号。每版录制约 240.324 秒原生 SPU2 输出，音量包络与替换音频匹配；播放期间没有原曲回退。退出后返回菜单并停止，再次进入可重播第一首。

- SP：[播放截图](issue-assets/vocal-1106-first-song-20261106/sp-first-song-playing.png)、[20 秒实录试听](issue-assets/vocal-1106-first-song-20261106/sp-music-select-20s.mp3)、[遥测](issue-assets/vocal-1106-first-song-20261106/sp-runtime.json)。
- Z 本体 Original：[播放截图](issue-assets/vocal-1106-first-song-20261106/original-first-song-playing.png)、[20 秒实录试听](issue-assets/vocal-1106-first-song-20261106/original-music-select-20s.mp3)、[遥测](issue-assets/vocal-1106-first-song-20261106/original-runtime.json)。
- Z 本体 The Best：[播放截图](issue-assets/vocal-1106-first-song-20261106/best-first-song-playing.png)、[20 秒实录试听](issue-assets/vocal-1106-first-song-20261106/best-music-select-20s.mp3)、[遥测](issue-assets/vocal-1106-first-song-20261106/best-runtime.json)。

## 静态与 ISO 读回

安装器检查了三种 ELF 钩子预映像、播放器保留区、ISO9660/VMAP/UDF 记录及未修改区域。BGM.BIN 原始内容保留。输入工作区、源镜像 SHA-256、测试镜像 SHA-256、播放器哈希与详细结果见 [receipt.json](issue-assets/vocal-1106-first-song-20261106/receipt.json)。

本记录是 ARMSX2 第一首音乐鉴赏的实测，不代替所有曲目、实机或其他模拟器测试。
