"""Customizable keyboard shortcuts: key normalization, validation and the action catalog (no Tk dependency).

A shortcut is stored as a canonical string such as ``"Ctrl+Shift+F"``, ``"Space"`` or ``"Cmd+Enter"``.
Defaults use ``"Primary"``, which means Cmd on macOS and Ctrl elsewhere.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from .i18n import tr

TABLE = "table"    # 曲目表获得焦点时生效
GLOBAL = "global"  # 主窗口中任意位置生效

MODIFIER_ORDER = ("Ctrl", "Cmd", "Alt", "Shift")
# Tk 在不同平台上用不同的状态位表示修饰键（Windows 的 0x8 是 NumLock，不能当作 Alt）。
MODIFIER_MASKS = {
    "win32": {"Shift": 0x1, "Ctrl": 0x4, "Alt": 0x20000},
    "darwin": {"Shift": 0x1, "Ctrl": 0x4, "Cmd": 0x8, "Alt": 0x10},
    "other": {"Shift": 0x1, "Ctrl": 0x4, "Alt": 0x8},
}
MODIFIER_KEYSYMS = {
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
    "Super_L", "Super_R", "Caps_Lock", "Num_Lock", "Option_L", "Option_R", "Command", "ISO_Level3_Shift",
}
KEY_NAMES = {
    "space": "Space", "Return": "Enter", "KP_Enter": "Enter", "Escape": "Esc", "BackSpace": "Backspace",
    "Prior": "PageUp", "Next": "PageDown", "Tab": "Tab", "ISO_Left_Tab": "Tab",
}
FUNCTION_KEYS = {f"F{number}" for number in range(1, 13)}
NAVIGATION_KEYS = {"Up", "Down", "Left", "Right", "Tab", "Esc", "Home", "End", "PageUp", "PageDown"}
# 文本编辑常用组合键，留给输入框使用。
EDITING_KEYS = {"C", "V", "X", "A", "Z", "Y"}


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    scope: str
    default: str


def actions() -> list[Action]:
    return [
        Action("edit_track", tr("编辑选中曲目"), TABLE, "Enter"),
        Action("toggle_preview", tr("试听 / 停止选中曲目"), TABLE, "Space"),
        Action("move_up", tr("上移曲目"), TABLE, "Primary+Up"),
        Action("move_down", tr("下移曲目"), TABLE, "Primary+Down"),
        Action("import_wav", tr("导入 WAV 文件夹"), GLOBAL, "Primary+O"),
        Action("search", tr("搜索曲库"), GLOBAL, "Primary+F"),
        Action("start", tr("开始处理"), GLOBAL, "Primary+Enter"),
        Action("add_to_queue", tr("加入队列"), GLOBAL, ""),
        Action("show_queue", tr("打开队列窗口"), GLOBAL, ""),
    ]


def platform_key(platform: str | None = None) -> str:
    platform = platform or sys.platform
    return platform if platform in MODIFIER_MASKS else "other"


def primary_modifier(platform: str | None = None) -> str:
    return "Cmd" if platform_key(platform) == "darwin" else "Ctrl"


def resolve_default(spec: str, platform: str | None = None) -> str:
    return spec.replace("Primary", primary_modifier(platform))


def from_event(keysym: str, state: int, platform: str | None = None) -> str | None:
    """Canonical shortcut for a Tk key event, or None for a bare modifier key."""
    if keysym in MODIFIER_KEYSYMS:
        return None
    masks = MODIFIER_MASKS[platform_key(platform)]
    modifiers = [name for name in MODIFIER_ORDER if name in masks and state & masks[name]]
    key = KEY_NAMES.get(keysym, keysym)
    if len(key) == 1:
        key = key.upper()
    return "+".join([*modifiers, key])


def split(spec: str) -> tuple[list[str], str]:
    parts = spec.split("+")
    return parts[:-1], parts[-1]


def validate(spec: str, scope: str) -> str | None:
    """Returns an error message, or None if the shortcut may be used for an action in this scope."""
    modifiers, key = split(spec)
    if not modifiers and key in NAVIGATION_KEYS:
        return tr("方向键、Tab、Esc 等用于界面导航，不能单独使用")
    if any(name in modifiers for name in ("Ctrl", "Cmd")) and key in EDITING_KEYS and modifiers in (["Ctrl"], ["Cmd"]):
        return tr("这是复制、粘贴等文本编辑快捷键，请换一个")
    if modifiers == ["Alt"] and key == "F4":
        return tr("Alt+F4 用于关闭窗口，请换一个")
    if scope == GLOBAL and key not in FUNCTION_KEYS and not any(name in modifiers for name in ("Ctrl", "Cmd", "Alt")):
        return tr("全局快捷键需要包含 Ctrl、Alt 或 ⌘，或使用 F1–F12，以免输入文字时误触发")
    return None


def load(saved: dict | None, platform: str | None = None) -> dict[str, str]:
    """Merges saved overrides into the defaults, dropping invalid or duplicate shortcuts."""
    saved = saved if isinstance(saved, dict) else {}
    result: dict[str, str] = {}
    used: set[str] = set()
    for action in actions():
        spec = saved.get(action.id, resolve_default(action.default, platform))
        if not isinstance(spec, str) or (spec and validate(spec, action.scope)) or spec in used:
            spec = resolve_default(action.default, platform)
            if spec in used:
                spec = ""
        if spec:
            used.add(spec)
        result[action.id] = spec
    return result


def overrides(mapping: dict[str, str], platform: str | None = None) -> dict[str, str]:
    """Only the shortcuts that differ from the defaults, for settings.json."""
    return {
        action.id: mapping.get(action.id, "")
        for action in actions()
        if mapping.get(action.id, "") != resolve_default(action.default, platform)
    }


def conflict(mapping: dict[str, str], spec: str, action_id: str) -> str | None:
    return next((other for other, value in mapping.items() if value == spec and other != action_id), None)


def display(spec: str, platform: str | None = None) -> str:
    if not spec:
        return tr("未设置")
    modifiers, key = split(spec)
    names = {
        "Space": tr("空格"), "Enter": tr("回车"), "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
        "Backspace": "Backspace", "Delete": "Delete",
    }
    key = names.get(key, key)
    if platform_key(platform) == "darwin":
        symbols = {"Ctrl": "⌃", "Cmd": "⌘", "Alt": "⌥", "Shift": "⇧"}
        return "".join(symbols[name] for name in modifiers) + key
    return "+".join([*modifiers, key])
