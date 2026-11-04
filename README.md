# DiscTag

DiscTag 是一款 Windows 与 macOS 桌面工具，用于整理 CD 抓轨后的 WAV 文件。它可以保留 WAV，也可以转换为 FLAC 或 MP3，并写入专辑资料与封面。

项目地址：[github.com/pretenderlu/DiscTag](https://github.com/pretenderlu/DiscTag)

当前版本：**v1.1.0**

## 功能

- WAV 保留原音频并写入 RIFF ID3 标签，或转换为 FLAC、MP3。
- 查询 iTunes 美区、日区、中国大陆、中国香港以及中国台湾曲库，支持全部地区合并检索。
- 自动下载专辑资料与封面，也可使用本地封面。
- 本地与在线曲目数量不一致时，可按 CD 曲序手动插入缺曲。
- 根据整张专辑的曲目时长智能对齐，自动标记缺失位置，等待用户按实体 CD 曲目表确认。
- 支持多首缺曲、曲目编辑、顺序调整、时长差异提醒和修改保护。
- 高 DPI 界面，内置 Windows FFmpeg，无需单独安装。

## 下载与运行

发布页提供 Windows 压缩包，以及 Apple Silicon、Intel Mac 的 macOS 构建：

[下载 Releases](https://github.com/pretenderlu/DiscTag/releases)

Windows 用户请完整解压 `DiscTag-Windows-x64.zip`，然后运行 `DiscTag.exe`，保留旁边的 `_internal` 目录。

macOS 构建目前使用 ad-hoc 签名，未经过 Apple Developer ID 签名和公证。首次打开时，macOS 可能显示安全提示。

## 从源码运行

需要 Python 3.12 或更高版本。音频转换需要 FFmpeg；仅整理 WAV 标签时不需要 FFmpeg。

```bash
python -m pip install -r requirements.txt
python main.py
```

Windows 和 macOS 均可使用以下命令构建桌面应用：

```bash
python build_app.py
```

macOS 构建前先安装 FFmpeg：

```bash
brew install ffmpeg
```

Windows 构建会优先使用 `vendor/ffmpeg.exe`，否则使用系统 PATH 中的 FFmpeg。`vendor` 和 `dist` 不会提交到仓库。

## macOS GitHub Actions

工作流位于 `.github/workflows/build-macos.yml`，支持手动触发，也会在推送 `v*` 标签时运行：

- `macos-15`：Apple Silicon。
- `macos-15-intel`：Intel。

每个任务生成一个经过 ad-hoc 签名的 `DiscTag.app`，并上传对应的 DMG 构建产物。

## 数据来源

专辑检索使用公开的 iTunes Search API，不需要 Apple 账号。不同地区的数字发行曲目可能不同，最终标签请以实体 CD 曲目表为准。

音频处理使用 FFmpeg，标签写入使用 Mutagen，图像处理使用 Pillow。
