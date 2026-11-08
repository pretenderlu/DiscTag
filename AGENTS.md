# DiscTag 项目说明

## 测试
- `python -m unittest discover -s tests -v`

## 版本号
- 唯一来源：`disctag/__init__.py` 的 `__version__`。`DiscTag.spec`、`installer/DiscTag.iss` 和各处 User-Agent 都从这里读取。
- README 中的版本文字（"当前版本"和安装包文件名）需要手动同步。

## 发布流程
1. 修改 `__version__` 和 README，提交到 main。
2. Windows 本地构建：`python -m pip install -r requirements-dev.txt`，然后 `python build_app.py`（优先使用 `vendor/ffmpeg.exe`），输出到 `dist/DiscTag`。
3. 用 `shutil.make_archive` 打包 `dist/DiscTag-Windows-x64.zip`（ZIP 内顶层为 `DiscTag/` 目录）。
4. 编译安装包：`"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\DiscTag.iss`，输出 `dist/installer/DiscTagSetup-v<版本>.exe`。
5. 归档：把 `dist/DiscTag` 复制到 `dist/v<版本>/DiscTag`。
6. 推送 main 和附注 tag `v<版本>`（tag 信息为 `DiscTag v<版本>`）。推送 tag 后会触发 `Build macOS` 工作流，用 `gh run download` 下载两个 DMG。
7. `gh release create`：上传安装包、ZIP 和两个 DMG，发布说明沿用以往格式。
8. 自动更新要求 Release 资产带有 GitHub 的 `sha256` digest，发布后用 `check_for_updates("<旧版本>")` 验证。
