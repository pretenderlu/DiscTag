from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AlbumSummary:
    collection_id: int | str
    title: str
    artist: str
    release_date: str = ""
    genre: str = ""
    track_count: int = 0
    artwork_url: str = ""
    country: str = ""
    source: str = "itunes"
    # 多碟唱片中与本地音轨匹配的那张光盘（MusicBrainz TOC 识别时使用）。
    medium: int | None = None
    # 结果列表中附加显示的版本信息，例如年份、目录号。
    detail: str = ""


@dataclass
class TrackMetadata:
    title: str
    artist: str
    track_number: int
    track_count: int = 0
    disc_number: int = 1
    disc_count: int = 1
    duration_ms: int = 0
    origin: str = "itunes"


@dataclass
class AlbumMetadata:
    title: str
    artist: str
    album_artist: str
    release_date: str = ""
    genre: str = ""
    artwork_url: str = ""
    collection_id: int | str | None = None
    tracks: list[TrackMetadata] = field(default_factory=list)
    source: str = "itunes"


def renumber_tracks(tracks: list[TrackMetadata]) -> None:
    disc_positions: dict[int, int] = {}
    for track in tracks:
        disc_number = max(1, track.disc_number)
        disc_positions[disc_number] = disc_positions.get(disc_number, 0) + 1
        track.disc_number = disc_number
        track.track_number = disc_positions[disc_number]
    for track in tracks:
        track.track_count = disc_positions[track.disc_number]


@dataclass
class ConversionFailure:
    source: Path
    message: str


@dataclass
class ConversionResult:
    output_directory: Path
    converted_files: list[Path] = field(default_factory=list)
    failures: list[ConversionFailure] = field(default_factory=list)
    cancelled: bool = False
    # 处理完成后移到回收站的源 WAV，以及未能移动（已保留在原位）的文件。
    trashed_sources: list[Path] = field(default_factory=list)
    trash_failures: list[ConversionFailure] = field(default_factory=list)
    # 开启了“移到回收站”，但专辑未全部成功，因此保留了全部源 WAV。
    trash_skipped: bool = False
