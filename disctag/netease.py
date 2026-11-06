from __future__ import annotations

import io
import threading
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher

import requests
from PIL import Image, ImageOps

from .models import AlbumMetadata, AlbumSummary, TrackMetadata


class NetEaseError(RuntimeError):
    pass


class NetEaseClient:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout
        self._last_request_time = 0.0
        self._request_lock = threading.Lock()

    def search_albums(self, album: str, artist: str) -> list[AlbumSummary]:
        query = " ".join(part.strip() for part in (artist, album) if part.strip())
        raw = self._post("https://music.163.com/api/search/get/web", {"s": query, "type": 10, "limit": 20, "offset": 0})
        albums = raw.get("result", {}).get("albums", [])
        if not albums:
            songs = self._post("https://music.163.com/api/search/get/web", {"s": query, "type": 1, "limit": 20, "offset": 0}).get("result", {}).get("songs", [])
            albums = [song["album"] for song in songs if song.get("album")]
        results = []
        seen = set()
        for item in albums:
            collection_id = int(item["id"])
            if collection_id in seen:
                continue
            seen.add(collection_id)
            results.append(
                AlbumSummary(
                    collection_id=collection_id,
                    title=item.get("name", "未知专辑"),
                    artist=_artist_names(item.get("artists", [])),
                    release_date=str(item.get("publishTime", "") or ""),
                    genre=item.get("subType", ""),
                    track_count=int(item.get("size", 0) or 0),
                    artwork_url=item.get("picUrl", ""),
                    country="NE",
                    source="netease",
                )
            )
        return sorted(results, key=lambda entry: _match_score(entry, album, artist), reverse=True)[:15]

    def get_album(self, collection_id: int) -> AlbumMetadata:
        data = self._get(f"https://music.163.com/api/v1/album/{collection_id}")
        raw = data.get("album") or {}
        songs = data.get("songs") or []
        if not raw or not songs:
            raise NetEaseError("网易云音乐没有返回这张专辑的完整曲目。")
        artist = _artist_names(raw.get("artists", [])) or "未知歌手"
        tracks = [
            TrackMetadata(
                title=song.get("name", f"Track {index}"),
                artist=_artist_names(song.get("ar", [])) or artist,
                track_number=int(song.get("no", index) or index),
                track_count=len(songs),
                disc_number=_disc_number(song.get("cd")),
                disc_count=1,
                duration_ms=int(song.get("dt", 0) or 0),
            )
            for index, song in enumerate(songs, 1)
        ]
        disc_count = max(track.disc_number for track in tracks)
        for track in tracks:
            track.disc_count = disc_count
        return AlbumMetadata(
            title=raw.get("name", ""),
            artist=artist,
            album_artist=artist,
            release_date=_release_date(raw.get("publishTime")),
            genre=raw.get("subType", ""),
            artwork_url=raw.get("picUrl", ""),
            collection_id=collection_id,
            tracks=tracks,
            source="netease",
        )

    def download_cover(self, artwork_url: str, size: int) -> bytes:
        if not artwork_url:
            raise NetEaseError("这张专辑没有可用封面。")
        try:
            self._throttle()
            response = requests.get(artwork_url, headers=_headers(), timeout=self.timeout)
            response.raise_for_status()
            if len(response.content) > 25 * 1024 * 1024:
                raise NetEaseError("封面文件过大。")
            image = Image.open(io.BytesIO(response.content))
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=94, optimize=True)
            return output.getvalue()
        except (requests.RequestException, OSError) as exc:
            raise NetEaseError(f"网易云封面下载失败：{exc}") from exc

    def _get(self, url: str) -> dict:
        self._throttle()
        try:
            response = requests.get(url, headers=_headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise NetEaseError(f"无法连接网易云音乐：{exc}") from exc
        except ValueError as exc:
            raise NetEaseError("网易云音乐返回了无法识别的数据。") from exc

    def _post(self, url: str, data: dict) -> dict:
        self._throttle()
        try:
            response = requests.post(url, data=data, headers=_headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise NetEaseError(f"无法连接网易云音乐：{exc}") from exc
        except ValueError as exc:
            raise NetEaseError("网易云音乐返回了无法识别的数据。") from exc

    def _throttle(self) -> None:
        with self._request_lock:
            remaining = 0.4 - (time.monotonic() - self._last_request_time)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_time = time.monotonic()


def _headers() -> dict:
    return {
        "Referer": "https://music.163.com/",
        "User-Agent": "Mozilla/5.0 (compatible; DiscTag/1.0; +https://github.com/pretenderlu/DiscTag)",
        "Cookie": "appver=2.0.2;",
    }


def _artist_names(artists: list[dict]) -> str:
    return "/".join(artist.get("name", "") for artist in artists if artist.get("name"))


def _disc_number(value) -> int:
    try:
        return max(1, int(value or 1))
    except (ValueError, TypeError):
        return 1


def _release_date(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    except (ValueError, TypeError, OSError):
        return str(value)


def _match_score(entry: AlbumSummary, album: str, artist: str) -> float:
    album_score = SequenceMatcher(None, entry.title.casefold(), album.casefold()).ratio()
    artist_score = SequenceMatcher(None, entry.artist.casefold(), artist.casefold()).ratio() if artist and entry.artist else 0.5
    exact_bonus = 0.25 if entry.title.casefold() == album.casefold() else 0
    return album_score * 0.72 + artist_score * 0.28 + exact_bonus
