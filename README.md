# DiscTag

DiscTag 是一款 Windows 与 macOS 桌面工具，用于整理 CD 抓轨后的 WAV 文件。它可以保留 WAV，也可以转换为 FLAC 或 MP3，并写入专辑资料与封面。

项目地址：[github.com/pretenderlu/DiscTag](https://github.com/pretenderlu/DiscTag)

当前版本：**v1.6.2**

## 功能

- WAV 保留原音频并写入 RIFF ID3 标签，或转换为 FLAC、MP3。
- 查询 iTunes 美区、日区、中国香港以及中国台湾曲库，并通过 Apple Music 公开网页检索中国大陆内容，支持全部地区合并检索。
- 支持 Discogs 实体唱片检索，补充独立发行、再版、地区版本、目录号和高清封面。
- 自动下载专辑资料与封面，也可使用本地封面。
- 一键清除专辑资料并保留已导入 WAV，过期搜索不会覆盖清除后的状态。
- 启动时后台检查 GitHub 最新 Release，发现更新时显示圆点，点击版本号即可打开发布页。
- 封面可设置 600、1200、2400、3000 像素上限，自动降级下载并显示实际尺寸，不放大低清图片。
- 本地与在线曲目数量不一致时，可按 CD 曲序手动插入缺曲。
- 根据整张专辑的曲目时长智能对齐，自动标记缺失位置，等待用户按实体 CD 曲目表确认。
- 支持多首缺曲、曲目编辑、顺序调整、时长差异提醒和修改保护。
- 高 DPI 界面，内置 Windows FFmpeg，无需单独安装。

## 下载与运行

发布页提供 Windows 压缩包，以及 Apple Silicon、Intel Mac 的 macOS 构建：

[下载 Releases](https://github.com/pretenderlu/DiscTag/releases)

Windows 用户请完整解压 `DiscTag-Windows-x64.zip`，然后运行 `DiscTag.exe`，保留旁边的 `_internal` 目录。

macOS 构建目前使用 ad-hoc 签名，未经过 Apple Developer ID 签名和公证。首次打开时，macOS 可能显示安全提示。

## Discogs 设置

Discogs 的数据库搜索需要每位用户自己的 Personal Access Token，免费且不需要 OAuth 应用审核：

1. 注册并登录 Discogs。
2. 打开 [Discogs 开发者设置](https://www.discogs.com/settings/developers)。
3. 创建 Personal Access Token。
4. 在 DiscTag 的曲库来源中选择 Discogs，点击“申请令牌”并将令牌粘贴到输入框。

令牌通过系统凭据管理器保存：Windows 凭据管理器或 macOS 钥匙串。令牌不会写入源码、普通设置文件或 GitHub 仓库。

Discogs 已认证请求通常限制为每分钟 60 次，未认证请求为每分钟 25 次，具体以 [Discogs 官方文档](https://www.discogs.com/developers)为准。DiscTag 会限制请求间隔，遇到 429 时请稍后再试，不要批量猛刷接口。

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

美区、日区、中国香港和中国台湾使用公开的 iTunes Search API；中国大陆使用 Apple Music 公开网页中的结构化数据，不需要 Apple 账号。网页检索不是官方免密 API，页面结构变化时可能需要更新解析逻辑。官方 Apple Music API 需要 Apple Developer Program 开发者令牌，本项目未使用该凭证。

Discogs 使用官方 REST API，实体版本、曲目、厂牌、国家和封面由用户个人令牌鉴权获取。请求频率受限，请遵循 Discogs 的 API 条款和署名要求。

不同地区的数字发行曲目可能不同，最终标签请以实体 CD 曲目表为准。

音频处理使用 FFmpeg，标签写入使用 Mutagen，图像处理使用 Pillow。
