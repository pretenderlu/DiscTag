"""Moves source files to the Recycle Bin / Trash. Never deletes permanently on its own."""
from __future__ import annotations

import sys
from pathlib import Path

from .i18n import tr


class TrashError(OSError):
    pass


def trash_name() -> str:
    return tr("回收站") if sys.platform == "win32" else tr("废纸篓")


def move_to_trash(paths: list[Path]) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Returns (moved, failures). Files that could not be moved to the trash are left in place."""
    moved: list[Path] = []
    failures: list[tuple[Path, str]] = []
    for path in paths:
        try:
            _trash_one(path)
        except Exception as exc:  # 任何失败都只是保留原文件。
            failures.append((path, str(exc) or exc.__class__.__name__))
            continue
        if path.exists():
            failures.append((path, tr("文件仍在原位置")))
        else:
            moved.append(path)
    return moved, failures


def _trash_one(path: Path) -> None:
    if not path.is_file():
        raise TrashError(tr("文件不存在"))
    if sys.platform == "win32":
        _windows_recycle(path)
    else:
        from send2trash import send2trash

        send2trash(str(path))


# SHFileOperationW 常量
_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
# 若文件无法进入回收站（过大、所在磁盘没有回收站），Windows 会先弹出永久删除警告，用户可以取消。
_FOF_WANTNUKEWARNING = 0x4000
_DRIVE_REMOTE = 4


def _windows_recycle(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    resolved = str(path.resolve())
    if resolved.startswith("\\\\"):
        raise TrashError(tr("网络路径没有回收站，已保留原文件"))
    root = resolved[:3]
    if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == _DRIVE_REMOTE:
        raise TrashError(tr("网络驱动器没有回收站，已保留原文件"))

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    operation = SHFILEOPSTRUCTW(
        hwnd=None,
        wFunc=_FO_DELETE,
        pFrom=resolved + "\0",  # 以双空字符结尾的路径列表
        pTo=None,
        fFlags=_FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI | _FOF_WANTNUKEWARNING,
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if operation.fAnyOperationsAborted:
        raise TrashError(tr("已取消移到回收站"))
    if result != 0:
        raise TrashError(tr("移到回收站失败（错误代码 {0}）", result))
