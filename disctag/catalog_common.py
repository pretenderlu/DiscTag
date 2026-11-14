from __future__ import annotations

import io
from difflib import SequenceMatcher

import requests
from PIL import Image, ImageOps

from .i18n import tr
from .models import AlbumSummary

MAX_COVER_BYTES = 25 * 1024 * 1024


class CoverTooLarge(OSError):
    pass


def match_score(entry: AlbumSummary, album: str, artist: str) -> float:
    album_score = SequenceMatcher(None, entry.title.casefold(), album.casefold()).ratio()
    artist_score = SequenceMatcher(None, entry.artist.casefold(), artist.casefold()).ratio() if artist and entry.artist else 0.5
    exact_bonus = 0.25 if entry.title.casefold() == album.casefold() else 0
    return album_score * 0.72 + artist_score * 0.28 + exact_bonus


def fetch_cover(url: str, size: int, headers: dict, timeout: float) -> bytes:
    """Downloads an image (capped at MAX_COVER_BYTES) and returns it as a JPEG no larger than size."""
    response = requests.get(url, headers=headers, timeout=timeout, stream=True)
    try:
        response.raise_for_status()
        if int(response.headers.get("Content-Length", 0) or 0) > MAX_COVER_BYTES:
            raise CoverTooLarge(tr("封面文件过大。"))
        data = bytearray()
        for chunk in response.iter_content(256 * 1024):
            data.extend(chunk)
            if len(data) > MAX_COVER_BYTES:
                raise CoverTooLarge(tr("封面文件过大。"))
    finally:
        response.close()
    return to_jpeg(bytes(data), size)


def to_jpeg(data: bytes, size: int) -> bytes:
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=94, optimize=True)
    return output.getvalue()
