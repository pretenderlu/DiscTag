from __future__ import annotations

from pathlib import Path

from .audio import clean_track_title
from .i18n import tr
from .matching import align_tracks_by_duration
from .models import AlbumMetadata, TrackMetadata, renumber_tracks
from .sources import SourceTrack

MANUAL_ORIGINS = {"manual", "auto-manual"}
DURATION_WARNING_MS = 10000


class EditError(ValueError):
    pass


def manual_tracks(sources: list[SourceTrack | Path], artist: str) -> list[TrackMetadata]:
    sources = [SourceTrack.of(source) for source in sources]
    return [
        TrackMetadata(source_title(source), source.performer or artist, index, len(sources), origin="manual")
        for index, source in enumerate(sources, 1)
    ]


def source_title(source: SourceTrack | Path) -> str:
    """CUE title when there is one, otherwise the file name without its track-number prefix."""
    source = SourceTrack.of(source)
    return source.title or clean_track_title(source.path)


def can_insert(album: AlbumMetadata | None, source_count: int) -> bool:
    return bool(album and album.collection_id is not None and source_count > len(album.tracks))


def fill_missing_by_duration(album: AlbumMetadata, durations_ms: list[float | None], artist: str) -> list[int]:
    # 只拒绝跨多张光盘的曲目表；多碟套装中的单张光盘（如 MusicBrainz 识别出的第 2 碟）可以按时长对齐。
    if len({track.disc_number for track in album.tracks}) > 1:
        raise EditError(tr("多碟专辑请按实体 CD 曲目表手动插入缺曲"))
    aligned = align_tracks_by_duration(durations_ms, album.tracks)
    if aligned is None:
        raise EditError(tr("时长信息不足或差异过大，无法可靠对齐；请按实体 CD 曲目表手动插入"))
    completed = []
    missing_positions = []
    for index, track in enumerate(aligned):
        if track is None:
            reference = next((item for item in aligned[index + 1:] if item is not None), None)
            if reference is None:
                reference = next((item for item in reversed(aligned[:index]) if item is not None), None)
            track = TrackMetadata(
                title=tr("待确认曲目 {0:02d}", index + 1),
                artist=artist,
                track_number=index + 1,
                track_count=len(aligned),
                disc_number=reference.disc_number if reference else 1,
                disc_count=reference.disc_count if reference else 1,
                origin="auto-manual",
            )
            missing_positions.append(index + 1)
        completed.append(track)
    album.tracks = completed
    renumber_tracks(album.tracks)
    return missing_positions


def default_insert_position(selected_index: int | None, track_count: int) -> int:
    """Position offered by the insert dialog: after the selected row, clamped to the valid range."""
    if selected_index is None:
        return track_count + 1
    return max(1, min(selected_index + 1, track_count + 1))


def insert_manual_track(album: AlbumMetadata, source_count: int, position: int, title: str, artist: str) -> bool:
    if not title.strip() or source_count <= len(album.tracks):
        return False
    if not 1 <= position <= len(album.tracks) + 1:
        return False
    index = position - 1
    if index < len(album.tracks):
        reference = album.tracks[index]
    elif album.tracks:
        reference = album.tracks[-1]
    else:
        reference = None
    track = TrackMetadata(
        title=title.strip(),
        artist=artist,
        track_number=position,
        track_count=len(album.tracks) + 1,
        disc_number=reference.disc_number if reference else 1,
        disc_count=reference.disc_count if reference else 1,
        origin="manual",
    )
    album.tracks.insert(index, track)
    renumber_tracks(album.tracks)
    return True


def delete_manual_track(album: AlbumMetadata, index: int) -> bool:
    if not 0 <= index < len(album.tracks):
        return False
    if album.tracks[index].origin not in MANUAL_ORIGINS:
        return False
    album.tracks.pop(index)
    renumber_tracks(album.tracks)
    return True


def track_label(track: TrackMetadata | None, index: int) -> str:
    if track and track.disc_count > 1:
        return f"{track.disc_number}-{track.track_number:02d}"
    if track:
        return f"{track.track_number:02d}"
    return f"{index + 1:02d}"


def duration_mismatch(local_seconds: float | None, track: TrackMetadata | None) -> bool:
    return bool(
        local_seconds is not None
        and track
        and track.duration_ms
        and abs(local_seconds * 1000 - track.duration_ms) > DURATION_WARNING_MS
    )


def album_info_text(album: AlbumMetadata, region: str) -> str:
    manual_count = sum(track.origin in MANUAL_ORIGINS for track in album.tracks)
    count_text = tr("{0} 首", len(album.tracks))
    if album.collection_id is not None and manual_count:
        count_text += tr("（{0} 首在线 + {1} 首手动）", len(album.tracks) - manual_count, manual_count)
    source = region or tr("手动模式")
    return f"{source} · {count_text} · {album.genre or tr('未分类')} · {album.release_date or tr('日期未知')}"


def match_status(source_count: int, album: AlbumMetadata | None, duration_warnings: int) -> str:
    if not source_count:
        return tr("先导入音轨文件")
    if not album:
        return tr("已导入 {0} 首 · 尚未匹配专辑", source_count)
    if source_count > len(album.tracks):
        return tr("本地多 {0} 首 · 请对照实体 CD，使用时长匹配或插入缺曲", source_count - len(album.tracks))
    if source_count < len(album.tracks):
        return tr("本地少 {0} 首 · 请核对实体 CD 版本或重新匹配", len(album.tracks) - source_count)
    warning = tr(" · 橙行时长不同") if duration_warnings else ""
    return tr("{0} 首已对应 · 双击或回车编辑 / 上下移动{1}", source_count, warning)
