from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import requests
from PIL import Image, ImageOps

from . import __version__
from .apple_music_web import AppleMusicWebClient
from .models import AlbumMetadata, AlbumSummary, TrackMetadata


ITUNES_REGIONS = {
    "US": "美国",
    "JP": "日本",
    "CN": "中国大陆",
    "HK": "中国香港",
    "TW": "中国台湾",
}
COVER_SIZES = (600, 1200, 2400, 3000)


class ITunesError(RuntimeError):
    pass


class ITunesClient:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout
        self.china_client = AppleMusicWebClient(timeout)
        self.last_warnings: list[str] = []

    def search_albums(self, album: str, artist: str = "", country: str = "US") -> list[AlbumSummary]:
        country = country.upper()
        self.last_warnings = []
        if country == "ALL":
            return self._search_all_regions(album, artist)
        return self._search_region(album, artist, country)

    def _search_region(self, album: str, artist: str, country: str) -> list[AlbumSummary]:
        if country == "CN":
            return self.china_client.search_albums(album, artist)
        term = " ".join(part.strip() for part in (artist, album) if part.strip())
        if not term:
            raise ITunesError("请输入专辑名称。")
        data = self._get(
            "https://itunes.apple.com/search",
            {
                "term": term,
                "media": "music",
                "entity": "album",
                "country": country,
                "limit": 30,
            },
        )
        albums = []
        for item in data.get("results", []):
            if item.get("wrapperType") != "collection" or not item.get("collectionId"):
                continue
            albums.append(
                AlbumSummary(
                    collection_id=int(item["collectionId"]),
                    title=item.get("collectionName", "未知专辑"),
                    artist=item.get("artistName", "未知歌手"),
                    release_date=_release_date(item.get("releaseDate", "")),
                    genre=item.get("primaryGenreName", ""),
                    track_count=int(item.get("trackCount", 0)),
                    artwork_url=item.get("artworkUrl100", ""),
                    country=country,
                )
            )
        return sorted(albums, key=lambda entry: _match_score(entry, album, artist), reverse=True)[:15]

    def _search_all_regions(self, album: str, artist: str) -> list[AlbumSummary]:
        albums: list[AlbumSummary] = []
        with ThreadPoolExecutor(max_workers=len(ITUNES_REGIONS)) as executor:
            futures = {
                executor.submit(self._search_region, album, artist, region): region
                for region in ITUNES_REGIONS
            }
            for future in as_completed(futures):
                region = futures[future]
                try:
                    albums.extend(future.result())
                except Exception as exc:
                    self.last_warnings.append(f"{ITUNES_REGIONS[region]}：{exc}")
        unique = {(entry.country, entry.collection_id): entry for entry in albums}
        return sorted(
            unique.values(),
            key=lambda entry: _match_score(entry, album, artist),
            reverse=True,
        )[:75]

    def get_album(self, collection_id: int, country: str = "US") -> AlbumMetadata:
        if country.upper() == "CN":
            return self.china_client.get_album(collection_id)
        data = self._get(
            "https://itunes.apple.com/lookup",
            {
                "id": collection_id,
                "entity": "song",
                "country": country.upper(),
                "limit": 500,
            },
        )
        results = data.get("results", [])
        collection = next(
            (item for item in results if int(item.get("collectionId", 0)) == collection_id),
            None,
        )
        if collection is None:
            raise ITunesError("iTunes 没有返回这张专辑的详细资料。")
        songs = [item for item in results if item.get("wrapperType") == "track" and item.get("kind") == "song"]
        songs.sort(key=lambda item: (int(item.get("discNumber", 1)), int(item.get("trackNumber", 0))))
        disc_count = int(collection.get("discCount", 1) or 1)
        tracks = [
            TrackMetadata(
                title=item.get("trackName", f"Track {index}"),
                artist=item.get("artistName", collection.get("artistName", "")),
                track_number=int(item.get("trackNumber", index)),
                track_count=len(songs),
                disc_number=int(item.get("discNumber", 1)),
                disc_count=int(item.get("discCount", disc_count) or disc_count),
                duration_ms=int(item.get("trackTimeMillis", 0) or 0),
            )
            for index, item in enumerate(songs, 1)
        ]
        if not tracks:
            raise ITunesError("这张专辑没有可匹配的曲目。")
        artist = collection.get("artistName", "")
        return AlbumMetadata(
            title=collection.get("collectionName", ""),
            artist=artist,
            album_artist=artist,
            release_date=_release_date(collection.get("releaseDate", "")),
            genre=collection.get("primaryGenreName", ""),
            artwork_url=collection.get("artworkUrl100", ""),
            collection_id=collection_id,
            tracks=tracks,
        )

    def download_cover(self, artwork_url: str, size: int = 1200) -> bytes:
        if not artwork_url:
            raise ITunesError("这张专辑没有可用封面。")
        if size not in COVER_SIZES:
            raise ITunesError("不支持的封面规格。")
        candidate_sizes = [size, *(candidate for candidate in reversed(COVER_SIZES) if candidate < size), 100]
        urls = []
        for candidate in candidate_sizes:
            url = re.sub(r"\d+x\d+(?:bb|bf|cc)?(?:-\d+)?(\.[A-Za-z]+)$", rf"{candidate}x{candidate}bb\1", artwork_url)
            if url not in urls:
                urls.append(url)
        last_error = None
        for url in urls:
            try:
                response = requests.get(url, headers={"User-Agent": f"DiscTag/{__version__}"}, timeout=self.timeout)
                response.raise_for_status()
                if len(response.content) > 25 * 1024 * 1024:
                    raise ITunesError("封面文件过大。")
                image = Image.open(io.BytesIO(response.content))
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=94, optimize=True)
                return output.getvalue()
            except (requests.RequestException, OSError, ITunesError) as exc:
                last_error = exc
        raise ITunesError(f"封面下载失败：{last_error}")

    def _get(self, url: str, params: dict) -> dict:
        try:
            response = requests.get(url, params=params, headers={"User-Agent": f"DiscTag/{__version__}"}, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise ITunesError(f"无法连接 iTunes：{exc}") from exc
        except ValueError as exc:
            raise ITunesError("iTunes 返回了无法识别的数据。") from exc
        if data.get("errorMessage"):
            raise ITunesError(str(data["errorMessage"]))
        return data


def _release_date(value: str) -> str:
    return value[:10] if value else ""


def _match_score(entry: AlbumSummary, album: str, artist: str) -> float:
    album_score = SequenceMatcher(None, entry.title.casefold(), album.casefold()).ratio()
    artist_score = SequenceMatcher(None, entry.artist.casefold(), artist.casefold()).ratio() if artist else 0.5
    exact_bonus = 0.25 if entry.title.casefold() == album.casefold() else 0
    return album_score * 0.72 + artist_score * 0.28 + exact_bonus
