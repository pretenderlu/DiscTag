from __future__ import annotations

import io
import re
import threading
import time
from difflib import SequenceMatcher

import requests
from PIL import Image, ImageOps

from .models import AlbumMetadata, AlbumSummary, TrackMetadata


class DiscogsError(RuntimeError):
    pass


class DiscogsClient:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout
        self._last_request_time = 0.0
        self._request_lock = threading.Lock()

    def search_albums(self, album: str, artist: str, token: str) -> list[AlbumSummary]:
        if not token.strip():
            raise DiscogsError("请先填写 Discogs Personal Access Token。")
        data = self._get(
            "https://api.discogs.com/database/search",
            {
                "q": " ".join(part.strip() for part in (artist, album) if part.strip()),
                "type": "release",
                "per_page": 20,
            },
            token,
        )
        albums = []
        for item in data.get("results", []):
            if item.get("type") != "release" or not item.get("id"):
                continue
            artist_name, title = _split_release_title(item.get("title", ""))
            albums.append(
                AlbumSummary(
                    collection_id=int(item["id"]),
                    title=title,
                    artist=artist_name,
                    release_date=str(item.get("year", "") or ""),
                    genre=(item.get("genre") or [""])[0],
                    artwork_url=item.get("cover_image") or item.get("thumb", ""),
                    country=item.get("country", "DG"),
                    source="discogs",
                )
            )
        return sorted(albums, key=lambda entry: _match_score(entry, album, artist), reverse=True)[:15]

    def get_album(self, collection_id: int, token: str) -> AlbumMetadata:
        data = self._get(f"https://api.discogs.com/releases/{collection_id}", {}, token)
        artist = _artist_names(data.get("artists", [])) or "未知歌手"
        tracks = []
        for index, item in enumerate(data.get("tracklist", []), 1):
            disc_number, track_number = _position(item.get("position", ""), index)
            tracks.append(
                TrackMetadata(
                    title=item.get("title", f"Track {index}"),
                    artist=_artist_names(item.get("artists", [])) or artist,
                    track_number=track_number,
                    track_count=len(data.get("tracklist", [])),
                    disc_number=disc_number,
                    disc_count=1,
                    duration_ms=_duration_ms(item.get("duration", "")),
                )
            )
        if not tracks:
            raise DiscogsError("这张唱片没有可匹配的曲目。")
        disc_count = max(track.disc_number for track in tracks)
        for track in tracks:
            track.disc_count = disc_count
        images = data.get("images", [])
        primary = next((image for image in images if image.get("type") == "primary"), images[0] if images else {})
        return AlbumMetadata(
            title=data.get("title", ""),
            artist=artist,
            album_artist=artist,
            release_date=data.get("released") or str(data.get("year", "") or ""),
            genre=(data.get("genres") or [""])[0],
            artwork_url=primary.get("uri") or primary.get("resource_url", ""),
            collection_id=collection_id,
            tracks=tracks,
            source="discogs",
        )

    def download_cover(self, artwork_url: str, size: int, token: str) -> bytes:
        if not artwork_url:
            raise DiscogsError("这张唱片没有可用封面。")
        try:
            self._throttle()
            response = requests.get(artwork_url, headers=self._headers(token), timeout=self.timeout)
            response.raise_for_status()
            if len(response.content) > 25 * 1024 * 1024:
                raise DiscogsError("封面文件过大。")
            image = Image.open(io.BytesIO(response.content))
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=94, optimize=True)
            return output.getvalue()
        except (requests.RequestException, OSError) as exc:
            raise DiscogsError(f"Discogs 封面下载失败：{exc}") from exc

    def _get(self, url: str, params: dict, token: str) -> dict:
        try:
            self._throttle()
            response = requests.get(url, params=params, headers=self._headers(token), timeout=self.timeout)
            if response.status_code == 401:
                raise DiscogsError("Discogs 令牌无效或已失效，请重新创建。")
            if response.status_code == 429:
                raise DiscogsError("Discogs 请求过于频繁，请稍后再试。")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise DiscogsError(f"无法连接 Discogs：{exc}") from exc
        except ValueError as exc:
            raise DiscogsError("Discogs 返回了无法识别的数据。") from exc

    def _throttle(self) -> None:
        with self._request_lock:
            remaining = 1.05 - (time.monotonic() - self._last_request_time)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_time = time.monotonic()

    @staticmethod
    def _headers(token: str) -> dict:
        headers = {"User-Agent": "DiscTag/1.5 +https://github.com/pretenderlu/DiscTag"}
        if token.strip():
            headers["Authorization"] = f"Discogs token={token.strip()}"
        return headers


def _split_release_title(value: str) -> tuple[str, str]:
    if " - " in value:
        artist, title = value.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", value.strip() or "未知专辑"


def _artist_names(artists: list[dict]) -> str:
    return "、".join(artist.get("name", "") for artist in artists if artist.get("name"))


def _position(value: str, fallback: int) -> tuple[int, int]:
    match = re.match(r"(\d+)[-–](\d+)", value)
    if match:
        return int(match.group(1)), int(match.group(2))
    if value.isdigit():
        return 1, int(value)
    return 1, fallback


def _duration_ms(value: str) -> int:
    if not value:
        return 0
    parts = value.split(":")
    try:
        if len(parts) == 2:
            return (int(parts[0]) * 60 + int(parts[1])) * 1000
        if len(parts) == 3:
            return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000
    except ValueError:
        return 0
    return 0


def _match_score(entry: AlbumSummary, album: str, artist: str) -> float:
    album_score = SequenceMatcher(None, entry.title.casefold(), album.casefold()).ratio()
    artist_score = SequenceMatcher(None, entry.artist.casefold(), artist.casefold()).ratio() if artist and entry.artist else 0.5
    exact_bonus = 0.25 if entry.title.casefold() == album.casefold() else 0
    return album_score * 0.72 + artist_score * 0.28 + exact_bonus
