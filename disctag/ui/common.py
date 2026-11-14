"""Shared UI constants and helpers."""
from __future__ import annotations

import sys
from pathlib import Path

from ..i18n import tr
from ..itunes import COVER_SIZES, ITUNES_REGIONS
from ..settings import settings_path

BACKGROUND = "#F3F5FA"
CARD = "#FFFFFF"
INK = "#202236"
MUTED = "#73778C"
ACCENT = "#6857E5"
ACCENT_DARK = "#5140C8"
BORDER = "#E3E6EF"
SUCCESS = "#167A5B"
DANGER = "#B34452"
REPOSITORY_URL = "https://github.com/pretenderlu/DiscTag"
LATEST_RELEASE_URL = f"{REPOSITORY_URL}/releases/latest"
COVER_EMBED_SIZES = (500, 800, 1000)
SOURCE_ITUNES = "iTunes / Apple Music"
SOURCE_DISCOGS = "Discogs"
SOURCE_MUSICBRAINZ = "MusicBrainz"
SOURCE_HINTS = {
    SOURCE_ITUNES: tr("全部地区：美国、日本、中国大陆、中国香港、中国台湾。\n不同地区的专辑版本会分别保留。"),
    SOURCE_DISCOGS: tr("Discogs 收录实体唱片的地区版本、再版与目录号。\n需要个人令牌，请求频率受限。"),
    SOURCE_MUSICBRAINZ: tr("导入 WAV 后可不填专辑名，按音轨时长识别光盘。\n✓ 表示该版本与本地音轨时长吻合。"),
}



def _resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / relative


def _settings_path() -> Path:
    return settings_path()


def _region_labels() -> list[str]:
    return [tr("全部地区（美 / 日 / 中 / 港 / 台）"), *(tr("{0}（{1}）", name, code) for code, name in ITUNES_REGIONS.items())]


def _region_label(code: str) -> str:
    if code == "ALL":
        return _region_labels()[0]
    return tr("{0}（{1}）", ITUNES_REGIONS.get(code, ITUNES_REGIONS["US"]), code if code in ITUNES_REGIONS else "US")


def _region_code(label: str) -> str:
    if label == _region_labels()[0]:
        return "ALL"
    for code, name in ITUNES_REGIONS.items():
        if label == tr("{0}（{1}）", name, code):
            return code
    return "US"


def _cover_size_labels() -> list[str]:
    return [_cover_size_label(size) for size in COVER_SIZES]


def _cover_size_label(size: int) -> str:
    return f"{size} × {size}"


def _cover_embed_labels() -> list[str]:
    return [tr("不嵌入"), *(_cover_size_label(size) for size in COVER_EMBED_SIZES), tr("同 cover.jpg")]


def _cover_embed_label(value) -> str:
    if value == "none":
        return tr("不嵌入")
    if value in COVER_EMBED_SIZES:
        return _cover_size_label(value)
    return tr("同 cover.jpg")


def _cover_embed_value(label: str):
    if label == tr("不嵌入"):
        return "none"
    for size in COVER_EMBED_SIZES:
        if label == _cover_size_label(size):
            return size
    return "original"


def _duration(milliseconds: float | int | None) -> str:
    if not milliseconds:
        return "—"
    seconds = round(milliseconds / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"
