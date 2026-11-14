# DiscTag

DiscTag 是一款 Windows 与 macOS 桌面工具，用于整理 CD 抓轨后的 WAV 文件。它可以保留 WAV，也可以转换为 FLAC 或 MP3，并写入专辑资料与封面。

项目地址：[github.com/pretenderlu/DiscTag](https://github.com/pretenderlu/DiscTag)

当前版本：**v2.1.0**

## 功能

- WAV 保留原音频并写入 RIFF ID3 标签，或转换为 FLAC、MP3。
- 每首曲目左侧均有独立试听控件，播放时显示停止图标并高亮当前行，支持切换曲目、自然停止，并在转换或退出时自动停止。
- 查询 iTunes 美区、日区、中国香港以及中国台湾曲库，并通过 Apple Music 公开网页检索中国大陆内容，支持全部地区合并检索。
- 支持 Discogs 实体唱片检索，补充独立发行、再版、地区版本、目录号和高清封面。
- 支持 MusicBrainz：导入 WAV 后可不填专辑名，直接按音轨时长（CD TOC）识别光盘，多碟套装会定位到对应的那一张；也可按专辑名检索实体 CD 版本，封面来自 Cover Art Archive。免费、无需账号。
- 导入 WAV 后搜索 iTunes / Apple Music，会自动用本地音轨时长核对排名靠前的候选版本：时长吻合的版本排在最前并标记 ✓，可按时长补出缺曲的版本标记 ≈。
- 自动下载专辑资料与封面，也可使用本地封面。
- 一键清除专辑资料并保留已导入 WAV，过期搜索不会覆盖清除后的状态。
- 启动时后台检查 GitHub 最新 Release，发现更新时显示圆点；Windows 可自动下载并安装更新，macOS 可跳转到发布页。
- 封面分辨率可设置 600、1200、2400、3000 像素上限，决定 cover.jpg 的尺寸，自动降级下载并显示实际尺寸，不放大低清图片；嵌入选项支持不嵌入（仅保存 cover.jpg）、500 × 500、800 × 800、1000 × 1000 或同 cover.jpg。
- 本地与在线曲目数量不一致时，可按 CD 曲序手动插入缺曲。
- 根据整张专辑的曲目时长智能对齐，自动标记缺失位置，等待用户按实体 CD 曲目表确认。
- 支持多首缺曲、曲目编辑、顺序调整、时长差异提醒和修改保护。
- 批量队列：校对好一张 CD 后点“加入队列”，即可导入下一张；“开始处理”会按顺序逐张处理。处理期间界面保持可用，可以继续准备后面的专辑。在“队列”窗口中可查看每张专辑的状态、移除待处理项，或把失败的专辑重新排队。
- 处理过程中可随时取消：当前专辑已完成的曲目保留，未完成的临时文件自动清理，队列中其余专辑保留待处理。
- 高 DPI 界面，内置 Windows FFmpeg，无需单独安装。
- 支持中文和英文界面：默认跟随系统语言，可点击右下角的 “English / 中文” 切换，切换后自动重启。

## 下载与运行

发布页提供 Windows 压缩包，以及 Apple Silicon、Intel Mac 的 macOS 构建：

[下载 Releases](https://github.com/pretenderlu/DiscTag/releases)

Windows 用户可运行 `DiscTagSetup-v2.1.0.exe` 完成安装，默认安装到 `%LOCALAPPDATA%\Programs\DiscTag`，不需要管理员权限。安装器会创建开始菜单快捷方式，也可选择桌面快捷方式。也提供免安装 ZIP，解压后运行 `DiscTag.exe` 并保留 `_internal` 目录。

Windows 版启动时会检查 GitHub 最新 Release。发现新版本后，右下角显示圆点，点击圆点或版本号可自动下载、校验并安装更新，安装完成后自动重启应用。macOS 点击后跳转到最新发布页。

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

Windows 和 macOS 均可使用以下命令构建桌面应用。构建前安装构建依赖：

```bash
python -m pip install -r requirements-dev.txt
python build_app.py
```

Windows 构建会优先使用 `vendor/ffmpeg.exe`，否则使用系统 PATH 中的 FFmpeg；macOS 构建同理使用 `vendor/ffmpeg` 或系统 FFmpeg。`vendor` 和 `dist` 不会提交到仓库。

发布包内置的是精简 FFmpeg（LGPL，仅支持 WAV 输入与 FLAC/MP3 输出），由 `scripts/build_ffmpeg.sh` 编译并以固定 prerelease 资产的形式托管。获取方式：

```bash
python scripts/fetch_ffmpeg.py
```

脚本会按当前平台下载对应二进制并校验 SHA-256，写入 `vendor/ffmpeg.exe`（macOS 为 `vendor/ffmpeg`），然后再运行 `python build_app.py`。

Windows 安装器从标准构建目录 `dist/DiscTag` 读取文件。完成上述构建后，使用 Inno Setup 编译 `installer/DiscTag.iss`，安装包会生成到 `dist/installer`。

为保护原始音轨，输出文件不能与任何输入 WAV 使用同一路径；需要重新整理已输出的 WAV 时，请选择另一个输出根目录。

## 测试

安装依赖后运行 `python -m unittest discover -s tests -v`。测试使用临时音频和模拟请求，不访问个人凭据或在线曲库；未设置 `DISCTAG_FFMPEG` 时会跳过真实 FFmpeg 转换测试。Windows 与 macOS 的 GitHub Actions 会在推送和 PR 时拉取精简 FFmpeg，运行 `ruff check .` 和全部回归测试。

## 发布构建

推送 `v*` 标签后，`.github/workflows/release.yml` 会在 GitHub Actions 中构建全部平台，并创建草稿 Release：

- Windows：安装包 `DiscTagSetup-v<版本>.exe` 与免安装 ZIP。
- macOS：`macos-15`（Apple Silicon）与 `macos-15-intel`（Intel），各生成一个经过 ad-hoc 签名的 DMG。

核对资产并填写发布说明后，在 GitHub 上手动发布。`.github/workflows/build-macos.yml` 仅保留手动触发，用于单独试构建 macOS 版本。

## 数据来源

美区、日区、中国香港和中国台湾使用公开的 iTunes Search API；中国大陆使用 Apple Music 公开网页中的结构化数据，不需要 Apple 账号。网页检索不是官方免密 API，页面结构变化时可能需要更新解析逻辑。官方 Apple Music API 需要 Apple Developer Program 开发者令牌，本项目未使用该凭证。

Discogs 使用官方 REST API，实体版本、曲目、厂牌、国家和封面由用户个人令牌鉴权获取。请求频率受限，请遵循 Discogs 的 API 条款和署名要求。

MusicBrainz 使用官方 Web Service（数据以 CC0 发布），按其规定每秒最多请求一次；封面来自 Cover Art Archive，图片版权归原权利人所有。TOC 识别根据 WAV 时长推算，抓轨时若删除或改动了音轨间隙，识别可能不准确。

不同地区的数字发行曲目可能不同，最终标签请以实体 CD 曲目表为准。

音频处理使用 FFmpeg，标签写入使用 Mutagen，图像处理使用 Pillow。

## 许可证

Copyright (C) 2026 pretenderlu

DiscTag 以 [GNU General Public License v3.0 或更高版本](LICENSE)（GPL-3.0-or-later）发布。你可以在该许可条款下自由使用、修改和再分发本软件；本软件不提供任何担保。

## 第三方许可

发布包内置的 FFmpeg 与 LAME 采用 LGPL-2.1+，标签库 Mutagen 采用 GPL-2.0-or-later。完整声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，许可文本位于 `licenses/` 目录，并随应用一同分发。
