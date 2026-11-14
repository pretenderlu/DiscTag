# 第三方组件声明 / Third-Party Notices

DiscTag 发布包内含以下第三方组件。完整许可文本位于随附的 `licenses/` 目录。

## FFmpeg 9.0.2 与 LAME 3.100（内置 `ffmpeg` 可执行文件）

- 许可：GNU Lesser General Public License v2.1 或更高版本（`licenses/LGPL-2.1.txt`）。
- 构建配置：仅启用 WAV 解码与 FLAC/MP3 编码，未启用任何 GPL 或 nonfree 组件；静态链接 LAME 3.100（LGPL）。
- 对应源码：
  - FFmpeg：https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz
  - LAME：https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz
  - 完整构建脚本：https://github.com/pretenderlu/DiscTag/blob/main/scripts/build_ffmpeg.sh
- `ffmpeg` 作为独立进程调用，可用任何兼容版本替换：设置环境变量 `DISCTAG_FFMPEG` 指向替换后的可执行文件即可。

FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project.

## Python 依赖

| 组件 | 许可 |
| --- | --- |
| Mutagen | GPL-2.0-or-later（`licenses/GPL-2.0.txt`） |
| Pillow | MIT-CMU |
| Requests | Apache-2.0 |
| urllib3 | MIT |
| certifi | MPL-2.0 |
| idna | BSD-3-Clause |
| charset-normalizer | MIT |
| keyring 及 jaraco.*、more-itertools | MIT |
| pywin32-ctypes（仅 Windows） | BSD-3-Clause |
| Send2Trash（macOS 废纸篓） | BSD-3-Clause |
| Python 运行时 | PSF License |

各组件源码可在 PyPI（https://pypi.org/）获取。
