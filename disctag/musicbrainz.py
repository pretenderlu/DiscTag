"""MusicBrainz release search, fuzzy CD TOC lookup and Cover Art Archive artwork."""
from __future__ import annotations

import re
import string
import threading
import time

import requests

from . import __version__
from .catalog_common import fetch_cover, match_score
from .models import AlbumMetadata, AlbumSummary, TrackMetadata

API = "https://musicbrainz.org/ws/2"
COVER_ART = "https://coverartarchive.org"
# MusicBrainz 要求每个客户端平均每秒不超过 1 次请求。
REQUEST_INTERVAL = 1.1
SECTORS_PER_SECOND = 75
FIRST_TRACK_OFFSET = 150


class MusicBrainzError(RuntimeError):
    pass


def toc_from_durations(durations_seconds: list[float | None]) -> str | None:
    """Builds a TOC string (first, last, leadout, offsets...) from track durations.

    Rips do not keep the original pregap, so offsets start at 150; MusicBrainz's fuzzy TOC
    lookup tolerates that shift.
    """
    if not durations_seconds or len(durations_seconds) > 99:
        return None
    if any(not duration or duration <= 0 for duration in durations_seconds):
        return None
    offsets = [FIRST_TRACK_OFFSET]
    for duration in durations_seconds[:-1]:
        offsets.append(offsets[-1] + round(duration * SECTORS_PER_SECOND))
    leadout = offsets[-1] + round(durations_seconds[-1] * SECTORS_PER_SECOND)
    return "+".join(str(value) for value in (1, len(offsets), leadout, *offsets))


class MusicBrainzClient:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._last_request = 0.0

    def search_albums(self, album: str, artist: str = "") -> list[AlbumSummary]:
        if not album.strip():
            raise MusicBrainzError("请输入专辑名称。")
        query = f'release:"{_escape(album)}"'
        if artist.strip():
            query += f' AND artist:"{_escape(artist)}"'
        data = self._get("release/", {"query": query, "limit": 40})
        albums = []
        for item in data.get("releases", []):
            media = item.get("media") or []
            if media and not any(_is_cd(medium.get("format")) for medium in media):
                continue
            albums.append(_summary(item))
        return sorted(albums, key=lambda entry: match_score(entry, album, artist), reverse=True)[:20]

    def lookup_toc(self, toc: str, album: str = "", artist: str = "") -> list[AlbumSummary]:
        """Finds releases whose disc TOC is close to the given one; each result points at the matching medium."""
        track_count = int(toc.split("+")[1])
        data = self._get("discid/-", {"toc": toc, "cdstubs": "no", "inc": "artist-credits"})
        albums = []
        for item in data.get("releases", []):
            media = item.get("media") or []
            medium = next(
                (entry for entry in media if entry.get("track-count") == track_count and _is_cd(entry.get("format"))),
                None,
            )
            if medium is None:
                continue
            albums.append(_summary(item, medium=int(medium.get("position", 1)), medium_total=len(media)))
        if album.strip():
            albums.sort(key=lambda entry: match_score(entry, album, artist), reverse=True)
        return albums[:20]

    def get_album(self, release_id: str, medium: int | None = None) -> AlbumMetadata:
        data = self._get(f"release/{release_id}", {"inc": "recordings artist-credits release-groups genres labels"})
        media = [entry for entry in data.get("media") or [] if _is_cd(entry.get("format"))] or data.get("media") or []
        if medium is not None:
            selected = [entry for entry in media if int(entry.get("position", 0)) == medium]
            if not selected:
                raise MusicBrainzError("没有找到匹配的光盘。")
        else:
            selected = media
        disc_count = len(media) or 1
        album_artist = _credit(data.get("artist-credit")) or "未知歌手"
        tracks = []
        for entry in selected:
            disc_number = int(entry.get("position", 1)) if disc_count > 1 else 1
            entry_tracks = entry.get("tracks") or []
            for index, track in enumerate(entry_tracks, 1):
                tracks.append(
                    TrackMetadata(
                        title=track.get("title") or (track.get("recording") or {}).get("title") or f"Track {index}",
                        artist=_credit(track.get("artist-credit")) or album_artist,
                        track_number=int(track.get("position", index)),
                        track_count=len(entry_tracks),
                        disc_number=disc_number,
                        disc_count=disc_count,
                        duration_ms=int(track.get("length") or 0),
                    )
                )
        if not tracks:
            raise MusicBrainzError("这张唱片没有可匹配的曲目。")
        group = data.get("release-group") or {}
        if (data.get("cover-art-archive") or {}).get("front"):
            artwork_url = f"{COVER_ART}/release/{release_id}/front"
        elif group.get("id"):
            artwork_url = f"{COVER_ART}/release-group/{group['id']}/front"
        else:
            artwork_url = ""
        return AlbumMetadata(
            title=data.get("title", ""),
            artist=album_artist,
            album_artist=album_artist,
            release_date=data.get("date", "") or group.get("first-release-date", ""),
            genre=_top_genre(data.get("genres")) or _top_genre(group.get("genres")),
            artwork_url=artwork_url,
            collection_id=release_id,
            tracks=tracks,
            source="musicbrainz",
        )

    def download_cover(self, artwork_url: str, size: int) -> bytes:
        if not artwork_url:
            raise MusicBrainzError("这张唱片没有可用封面。")
        # Cover Art Archive 提供 250/500/1200 缩略图；更大尺寸需要原图，原图可能是超大扫描件。
        thumbnail = f"{artwork_url}-{500 if size <= 500 else 1200}"
        urls = [artwork_url, thumbnail] if size > 1200 else [thumbnail, artwork_url]
        last_error: Exception | None = None
        for url in urls:
            try:
                return fetch_cover(url, size, {"User-Agent": _user_agent()}, self.timeout)
            except (requests.RequestException, OSError) as exc:
                last_error = exc
        raise MusicBrainzError(f"封面下载失败：{last_error}")

    def _get(self, path: str, params: dict) -> dict:
        last_error = ""
        for attempt in range(3):
            self._throttle()
            try:
                response = requests.get(
                    f"{API}/{path}",
                    params={**params, "fmt": "json"},
                    headers={"User-Agent": _user_agent(), "Accept": "application/json"},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise MusicBrainzError(f"无法连接 MusicBrainz：{exc}") from exc
            if response.status_code in (429, 503):
                last_error = "MusicBrainz 服务器繁忙，请稍后再试。"
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code == 404:
                raise MusicBrainzError("MusicBrainz 没有找到对应的唱片。")
            try:
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as exc:
                raise MusicBrainzError(f"无法连接 MusicBrainz：{exc}") from exc
            except ValueError as exc:
                raise MusicBrainzError("MusicBrainz 返回了无法识别的数据。") from exc
            if isinstance(data, dict) and data.get("error"):
                raise MusicBrainzError(str(data["error"]))
            return data
        raise MusicBrainzError(last_error)

    def _throttle(self) -> None:
        with self._lock:
            remaining = REQUEST_INTERVAL - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request = time.monotonic()


def _user_agent() -> str:
    return f"DiscTag/{__version__} ( https://github.com/pretenderlu/DiscTag )"


def _escape(value: str) -> str:
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", value.strip())


def _is_cd(media_format: str | None) -> bool:
    return media_format is None or "CD" in media_format


def _credit(credits: list[dict] | None) -> str:
    return "".join(f"{entry.get('name') or (entry.get('artist') or {}).get('name', '')}{entry.get('joinphrase', '')}"
                   for entry in credits or []).strip()


def _top_genre(genres: list[dict] | None) -> str:
    if not genres:
        return ""
    best = max(genres, key=lambda entry: entry.get("count", 0))
    return string.capwords(best.get("name", ""))


def _summary(item: dict, medium: int | None = None, medium_total: int | None = None) -> AlbumSummary:
    media = item.get("media") or []
    if medium is not None:
        track_count = next((entry.get("track-count", 0) for entry in media if int(entry.get("position", 0)) == medium), 0)
    else:
        track_count = int(item.get("track-count") or sum(entry.get("track-count", 0) for entry in media))
    labels = [
        (info.get("catalog-number") or "").strip()
        for info in item.get("label-info") or []
        if (info.get("catalog-number") or "").strip()
    ]
    details = [part for part in (
        (item.get("date") or "")[:4],
        item.get("disambiguation", ""),
        labels[0] if labels else "",
        f"CD {medium}/{medium_total}" if medium is not None and (medium_total or 0) > 1 else "",
    ) if part]
    return AlbumSummary(
        collection_id=item["id"],
        title=item.get("title", "未知专辑"),
        artist=_credit(item.get("artist-credit")) or "未知歌手",
        release_date=item.get("date", ""),
        track_count=int(track_count or 0),
        country=item.get("country") or "—",
        source="musicbrainz",
        medium=medium,
        detail=" · ".join(details),
    )
