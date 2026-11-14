"""Minimal UI translation: Chinese source strings, looked up in an English catalog when English is active.

Strings are wrapped as ``tr("中文 {0}", value)``. The language must be chosen before the UI modules are
imported (see main.py), because some labels are built at import time; changing it takes a restart.
"""
from __future__ import annotations

import locale
import os
import subprocess
import sys

SUPPORTED = ("zh", "en")
LANGUAGE_NAMES = {"zh": "中文", "en": "English"}

_language = "zh"


def tr(text: str, *args) -> str:
    if _language == "en":
        from .locales.en import EN

        text = EN.get(text, text)
    return text.format(*args) if args else text


def language() -> str:
    return _language


def set_language(code: str) -> None:
    global _language
    _language = code if code in SUPPORTED else "zh"


def resolve(setting: str | None) -> str:
    """Maps the saved setting ("zh", "en" or "auto") to a concrete language."""
    if setting in SUPPORTED:
        return setting
    return system_language()


def system_language() -> str:
    override = os.environ.get("DISCTAG_LANG", "")
    if override in SUPPORTED:
        return override
    try:
        if sys.platform == "win32":
            import ctypes

            # LANGID 的低 10 位是主语言，0x04 为中文。
            return "zh" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04 else "en"
        if sys.platform == "darwin":
            output = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=3
            ).stdout
            first = next((line.strip(' \t",()') for line in output.splitlines() if line.strip(' \t",()')), "")
            return "zh" if first.lower().startswith("zh") else "en"
    except (OSError, AttributeError, subprocess.SubprocessError):
        pass
    code = (locale.getlocale()[0] or os.environ.get("LANG", "")).lower()
    return "zh" if code.startswith(("zh", "chinese")) else "en"
