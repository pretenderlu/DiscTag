from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

import requests

from .models import AlbumMetadata, AlbumSummary, TrackMetadata


class AppleMusicWebError(RuntimeError):
    pass


class AppleMusicWebClient:
    def __init__(self, timeout: float = 25):
        self.timeout = timeout

    def search_albums(self, album: str, artist: str = "") -> list[AlbumSummary]:
        term = " ".join(part.strip() for part in (artist, album) if part.strip())
        if not term:
            raise AppleMusicWebError("请输入专辑名称。")
        root = self._get_page_data("https://music.apple.com/cn/search", {"term": term})
        albums = {}
        for section in root.get("sections", []):
            for item in section.get("items", []):
                descriptor = item.get("contentDescriptor", {})
                if descriptor.get("kind") != "album":
                    continue
                collection_id = descriptor.get("identifiers", {}).get("storeAdamID")
                if not collection_id:
                    continue
                collection_id = int(collection_id)
                if collection_id in albums:
                    continue
                albums[collection_id] = AlbumSummary(
                    collection_id=collection_id,
                    title=_item_title(item),
                    artist=_item_artist(item),
                    track_count=int(item.get("trackCount", 0) or 0),
                    artwork_url=_artwork_url(item),
                    country="CN",
                )
        return sorted(
            albums.values(),
            key=lambda entry: _match_score(entry, album, artist),
            reverse=True,
        )[:15]

    def get_album(self, collection_id: int) -> AlbumMetadata:
        root = self._get_page_data(f"https://music.apple.com/cn/album/_/{collection_id}", {})
        sections = root.get("sections", [])
        header = next(
            (
                item
                for section in sections
                for item in section.get("items", [])
                if item.get("contentDescriptor", {}).get("kind") == "album"
                and int(item.get("contentDescriptor", {}).get("identifiers", {}).get("storeAdamID", 0)) == collection_id
                and item.get("title")
            ),
            None,
        )
        if header is None:
            raise AppleMusicWebError("Apple Music 没有返回这张专辑的详细资料。")
        artist = _item_artist(header)
        songs = [
            item
            for section in sections
            if str(section.get("id", "")).startswith("track-list")
            for item in section.get("items", [])
            if item.get("contentDescriptor", {}).get("kind") == "song"
        ]
        songs.sort(key=lambda item: (int(item.get("discNumber", 1)), int(item.get("trackNumber", 0))))
        disc_count = max((int(item.get("discNumber", 1)) for item in songs), default=1)
        tracks = [
            TrackMetadata(
                title=item.get("title", f"Track {index}"),
                artist=item.get("artistName") or artist,
                track_number=int(item.get("trackNumber", index)),
                track_count=len(songs),
                disc_number=int(item.get("discNumber", 1)),
                disc_count=disc_count,
                duration_ms=int(item.get("duration", 0) or 0),
            )
            for index, item in enumerate(songs, 1)
        ]
        if not tracks:
            raise AppleMusicWebError("这张专辑没有可匹配的曲目。")
        quaternary = header.get("quaternaryTitle", "")
        year_match = re.search(r"(?:19|20)\d{2}", quaternary)
        genre = quaternary.split("·", 1)[0].strip() if quaternary else ""
        return AlbumMetadata(
            title=header.get("title", ""),
            artist=artist,
            album_artist=artist,
            release_date=year_match.group(0) if year_match else "",
            genre=genre,
            artwork_url=_artwork_url(header),
            collection_id=collection_id,
            tracks=tracks,
        )

    def _get_page_data(self, url: str, params: dict) -> dict:
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DiscTag/1.0; +https://github.com/pretenderlu/DiscTag)",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            response.encoding = "utf-8"
            match = re.search(r'<script[^>]+id="serialized-server-data"[^>]*>(.*?)</script>', response.text, re.S)
            if not match:
                raise AppleMusicWebError("Apple Music 页面没有返回可识别的专辑数据。")
            payload = json.loads(match.group(1))
            return payload["data"][0]["data"]
        except requests.RequestException as exc:
            raise AppleMusicWebError(f"无法连接 Apple Music：{exc}") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AppleMusicWebError("Apple Music 页面结构发生了变化，暂时无法解析。") from exc


def _item_title(item: dict) -> str:
    for key in ("title", "headline", "accessibilityLabel"):
        if item.get(key):
            return str(item[key])
    for link in item.get("titleLinks") or []:
        if link.get("title"):
            return str(link["title"])
    return "未知专辑"


def _item_artist(item: dict) -> str:
    links = item.get("subtitleLinks") or item.get("tertiaryLinks") or []
    names = [str(link["title"]) for link in links if link.get("title")]
    if names:
        return "、".join(names)
    subtitle = item.get("subtitle") or item.get("subheadline") or item.get("artistName") or ""
    if "·" in subtitle:
        subtitle = subtitle.split("·")[-1]
    return subtitle.strip() or "未知歌手"


def _artwork_url(item: dict) -> str:
    artwork = item.get("artwork") or {}
    url = artwork.get("dictionary", {}).get("url", "") if isinstance(artwork, dict) else ""
    return url.replace("{w}", "100").replace("{h}", "100").replace("{f}", "jpg")


def _match_score(entry: AlbumSummary, album: str, artist: str) -> float:
    album_score = SequenceMatcher(None, entry.title.casefold(), album.casefold()).ratio()
    artist_score = SequenceMatcher(None, entry.artist.casefold(), artist.casefold()).ratio() if artist else 0.5
    exact_bonus = 0.25 if entry.title.casefold() == album.casefold() else 0
    return album_score * 0.72 + artist_score * 0.28 + exact_bonus
