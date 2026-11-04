import shutil
import sys
from pathlib import Path


project = Path(SPECPATH)
executable = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
bundled_ffmpeg = project / "vendor" / executable
ffmpeg = str(bundled_ffmpeg) if bundled_ffmpeg.is_file() else shutil.which("ffmpeg")
if not ffmpeg:
    raise SystemExit("FFmpeg is required to build DiscTag.")

icon = project / "assets" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[(ffmpeg, "vendor")],
    datas=[(str(project / "assets"), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy",
        "cryptography",
        "bcrypt",
        "setuptools",
        "pkg_resources",
        "jaraco",
        "wheel",
        "pip",
        "psutil",
        "yaml",
        "win32com",
        "pythonwin",
        "brotli",
        "brotlicffi",
        "zstandard",
        "PIL.AvifImagePlugin",
        "PIL._avif",
        "PIL.ImageCms",
        "PIL._imagingcms",
        "PIL.ImageFont",
        "PIL._imagingft",
        "PIL.ImageQt",
        "unittest",
        "doctest",
        "pydoc",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DiscTag",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DiscTag",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="DiscTag.app",
        icon=str(icon),
        bundle_identifier="app.disctag.desktop",
        info_plist={
            "CFBundleDisplayName": "DiscTag",
            "CFBundleShortVersionString": "1.2.0",
            "NSHighResolutionCapable": True,
        },
    )
