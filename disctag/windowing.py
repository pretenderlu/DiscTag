from __future__ import annotations

import ctypes
import sys


def apply_native_window_style(root, color: str) -> dict[int, int]:
    if sys.platform != "win32":
        return {}
    color = color.lstrip("#")
    red, green, blue = (int(color[index:index + 2], 16) for index in (0, 2, 4))
    colorref = red | (green << 8) | (blue << 16)
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    user32.GetAncestor.restype = ctypes.c_void_p
    hwnd = user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()
    dwm = ctypes.windll.dwmapi
    dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long
    results = {}
    for attribute, value in ((33, 2), (34, colorref), (35, colorref), (36, 0x00FFFFFF)):
        setting = ctypes.c_uint32(value)
        results[attribute] = dwm.DwmSetWindowAttribute(
            hwnd,
            attribute,
            ctypes.byref(setting),
            ctypes.sizeof(setting),
        )
    return results


def configure_native_window(root, color: str) -> None:
    root.bind("<Map>", lambda event: apply_native_window_style(root, color) if event.widget is root else None)
