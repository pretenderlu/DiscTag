# DiscTag 项目说明

## 测试
- `python -m unittest discover -s tests -v`
- 设置 `DISCTAG_FFMPEG=vendor/ffmpeg.exe`（macOS 为 `vendor/ffmpeg`）可同时运行真实 FFmpeg 转换测试；CI 会自动这样做。
- `ruff check .`（规则见 `ruff.toml`，只检查真实错误）。

## 代码结构
- 无界面逻辑：`audio`（转换与标签）、`matching` / `ranking`（时长对齐与结果排序）、`editing`（曲目编辑）、`jobs`（处理队列）、`models`。
- 曲库客户端：`itunes`、`apple_music_web`、`discogs`、`musicbrainz`，公共的评分与封面下载在 `catalog_common`。
- 界面：`app.py` 的 `DiscTagApp` 只负责启动、线程调度（`_run_async` / `_post`，后台线程不得直接调用 Tk）、设置与退出；具体功能按职责拆成 `disctag/ui/` 下的 mixin：`layout`、`theme`、`catalog`、`cover`、`tracks`、`processing`、`updates`、`easter_egg`，共享常量与辅助函数在 `ui/common.py`。
- 测试中 mock 界面模块时，patch 目标要指向实际使用该名称的模块，例如 `disctag.ui.processing.convert_album`。

## 版本号
- 唯一来源：`disctag/__init__.py` 的 `__version__`。`DiscTag.spec`、`installer/DiscTag.iss` 和各处 User-Agent 都从这里读取。
- README 中的版本文字（"当前版本"和安装包文件名）需要手动同步；`tests/test_release.py` 会在不一致时失败。

## 发布流程
1. 修改 `__version__` 和 README，提交到 main，等待 `Tests` 工作流通过。
2. 推送附注 tag `v<版本>`（tag 信息为 `DiscTag v<版本>`）。`Release` 工作流会：
   - 校验 tag 与 `__version__` 一致；
   - 在 Windows 上拉取精简 FFmpeg、运行测试、构建，生成 `DiscTag-Windows-x64.zip`（顶层为 `DiscTag/`）和 `DiscTagSetup-v<版本>.exe`；
   - 在 macOS（Apple Silicon / Intel）上构建并 ad-hoc 签名，生成两个 DMG；
   - 创建包含以上 4 个资产的**草稿** Release。
3. 在 GitHub 上核对草稿资产，按以往格式填写发布说明，然后发布。草稿和预发布不会触发应用内更新。
4. 自动更新要求 Release 资产带有 GitHub 的 `sha256` digest（上传后自动生成），发布后用 `check_for_updates("<旧版本>")` 验证。

本地构建（仅用于调试）：`python scripts/fetch_ffmpeg.py`，`python -m pip install -r requirements-dev.txt`，`python build_app.py` 输出到 `dist/DiscTag`；安装包用 `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\DiscTag.iss`。

## 许可
- 项目本身为 GPL-3.0-or-later（`LICENSE`）。
- Mutagen 为 GPL-2.0-or-later，打包后的应用整体须以 GPL 兼容方式分发。
- 内置 FFmpeg/LAME 为 LGPL-2.1+。第三方声明见 `THIRD_PARTY_NOTICES.md`，许可文本在 `licenses/`，由 `DiscTag.spec` 打包进应用。升级 FFmpeg 时同步更新声明中的版本与源码地址（`tests/test_release.py` 会检查）。

## 升级 FFmpeg
1. 修改 `scripts/build_ffmpeg.sh` 中的版本号与 SHA-256，推送到 main（触发 `Build FFmpeg` 工作流）。
2. 用 `gh run download` 下载 3 个构件（windows-x64 / macos-AppleSilicon / macos-Intel）。
3. 以 `gh release create ffmpeg-<版本> --prerelease --latest=false` 创建新 prerelease，上传 3 个二进制（命名为 `ffmpeg-windows-x64.exe`、`ffmpeg-macos-AppleSilicon`、`ffmpeg-macos-Intel`）。
4. 更新 `scripts/ffmpeg.json` 中的 tag 和各资产 SHA-256，提交。
