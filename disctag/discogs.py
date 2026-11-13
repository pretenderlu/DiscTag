from __future__ import annotations

import re
import threading
import time

import requests

from . import __version__
from .catalog_common import fetch_cover, match_score as _match_score
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
                "format": "CD",
                "per_page": 20,
            },
            token,
        )
        albums = []
        for item in data.get("results", []):
            if item.get("type") != "release" or not item.get("id"):
                continue
            artist_name, title = _split_release_title(item.get("title", ""))
            artist_name = _clean_artist(artist_name)
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
        previous_position = None
        for index, item in enumerate(_audio_entries(data.get("tracklist", [])), 1):
            position = _position(item.get("position", ""))
            disc_number, track_number = position or (1, index)
            performer = _artist_names(item.get("artists", [])) or artist
            duration = _duration_ms(item.get("duration", ""))
            if tracks and position is not None and position == previous_position:
                # 3.1 / 3.2 等子曲目属于同一条 CD 音轨。
                previous = tracks[-1]
                previous.title += " / " + item.get("title", f"Track {index}")
                if performer != previous.artist:
                    previous.artist += "、" + performer
                previous.duration_ms = previous.duration_ms + duration if previous.duration_ms and duration else 0
                continue
            tracks.append(
                TrackMetadata(
                    title=item.get("title", f"Track {index}"),
                    artist=performer,
                    track_number=track_number,
                    disc_number=disc_number,
                    disc_count=1,
                    duration_ms=duration,
                )
            )
            previous_position = position
        if not tracks:
            raise DiscogsError("这张唱片没有可匹配的曲目。")
        disc_count = max(track.disc_number for track in tracks)
        for track in tracks:
            track.disc_count = disc_count
            track.track_count = len(tracks)
        images = data.get("images", [])
        primary = next((image for image in images if image.get("type") == "primary"), images[0] if images else {})
        return AlbumMetadata(
            title=data.get("title", ""),
            artist=artist,
            album_artist=artist,
            release_date=re.sub(r"(?:-00)+$", "", data.get("released") or "") or str(data.get("year", "") or ""),
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
            return fetch_cover(artwork_url, size, self._headers(""), self.timeout)
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
        headers = {"User-Agent": f"DiscTag/{__version__} +https://github.com/pretenderlu/DiscTag"}
        if token.strip():
            headers["Authorization"] = f"Discogs token={token.strip()}"
        return headers


def _split_release_title(value: str) -> tuple[str, str]:
    if " - " in value:
        artist, title = value.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", value.strip() or "未知专辑"


def _clean_artist(value: str) -> str:
    value = re.sub(r"\s\(\d+\)(?=\*?(?:\s|,|$))", "", value)
    return re.sub(r"(?<=\S)\*(?=\s|,|$)", "", value).strip()


def _artist_names(artists: list[dict]) -> str:
    entries = [(_clean_artist(artist.get("anv") or artist.get("name", "")), (artist.get("join") or "").strip()) for artist in artists]
    entries = [entry for entry in entries if entry[0]]
    parts = []
    for index, (name, join) in enumerate(entries):
        parts.append(name)
        if index < len(entries) - 1:
            parts.append("、" if not join else ", " if join == "," else f" {join} ")
    return "".join(parts)


def _audio_entries(items: list[dict], title: str = "", artists: list[dict] | None = None):
    for item in items:
        if item.get("type_") == "heading":
            continue
        name = item.get("title", "")
        name = f"{title} ({name})" if title else name
        performers = item.get("artists") or artists or []
        if item.get("type_") == "index":
            children = item.get("sub_tracks") or []
            if not children:
                raise DiscogsError("唱片包含没有子曲目的分组，无法确定音轨，请改用手动模式。")
            if any(not child.get("position") and child.get("type_") not in {"heading", "index"} for child in children):
                raise DiscogsError("分组内的子曲目缺少曲序，无法确定音轨，请改用手动模式。")
            yield from _audio_entries(children, name, performers)
        else:
            yield {**item, "title": name, "artists": performers}


def _position(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(?:CD)?(?:(\d+)[-–])?(\d+)(?:\.\d+|[a-z])*", value.strip(), re.I)
    if match:
        return int(match.group(1) or 1), int(match.group(2))
    return None


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
