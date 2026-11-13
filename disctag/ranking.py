"""Ranks catalog search results by how well they fit the imported WAV files."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from .matching import align_tracks_by_duration
from .models import AlbumMetadata, AlbumSummary, TrackMetadata

EXACT_TOLERANCE_MS = 3000
VERIFY_LIMIT = 6

EXACT = "exact"
ALIGNED = "aligned"
MISMATCH = "mismatch"


@dataclass(frozen=True)
class DurationFit:
    kind: str
    mean_difference_ms: float = 0.0

    @property
    def marker(self) -> str:
        return {EXACT: "✓", ALIGNED: "≈"}.get(self.kind, "")


def duration_fit(local_ms: list[float | None], tracks: list[TrackMetadata]) -> DurationFit | None:
    """Compares local durations with an album's tracks; None when either side lacks durations."""
    if not local_ms or any(not duration or duration <= 0 for duration in local_ms):
        return None
    if not tracks or any(track.duration_ms <= 0 for track in tracks):
        return None
    if len(local_ms) == len(tracks):
        differences = [abs(local - track.duration_ms) for local, track in zip(local_ms, tracks)]
        mean = sum(differences) / len(differences)
        return DurationFit(EXACT if max(differences) <= EXACT_TOLERANCE_MS else MISMATCH, mean)
    if len(local_ms) > len(tracks):
        aligned = align_tracks_by_duration(local_ms, tracks)
        if aligned is not None:
            pairs = [(local, track) for local, track in zip(local_ms, aligned) if track is not None]
            mean = sum(abs(local - track.duration_ms) for local, track in pairs) / len(pairs)
            return DurationFit(ALIGNED, mean)
    return DurationFit(MISMATCH)


def candidates_to_verify(results: list[AlbumSummary], local_count: int, limit: int = VERIFY_LIMIT) -> list[AlbumSummary]:
    """Top results whose track count could plausibly match the local files (0 means unknown)."""
    return [entry for entry in results if entry.track_count <= local_count][:limit]


def verify_candidates(
    candidates: list[AlbumSummary],
    local_ms: list[float | None],
    load: Callable[[AlbumSummary], AlbumMetadata],
    max_workers: int = 4,
) -> tuple[dict[tuple, DurationFit], dict[tuple, AlbumMetadata]]:
    """Loads candidate albums in parallel; failures are skipped since ranking is best-effort."""
    fits: dict[tuple, DurationFit] = {}
    albums: dict[tuple, AlbumMetadata] = {}
    if not candidates:
        return fits, albums

    def attempt(entry: AlbumSummary):
        try:
            return entry, load(entry)
        except Exception:
            return entry, None

    with ThreadPoolExecutor(max_workers=min(max_workers, len(candidates))) as executor:
        for entry, album in executor.map(attempt, candidates):
            if album is None:
                continue
            key = result_key(entry)
            albums[key] = album
            fit = duration_fit(local_ms, album.tracks)
            if fit is not None:
                fits[key] = fit
    return fits, albums


def rank_results(results: list[AlbumSummary], fits: dict[tuple, DurationFit], local_count: int) -> list[AlbumSummary]:
    """Stable re-rank: exact fit, then alignable, then same track count, then the rest.

    Within a tier the original text-relevance order is kept: different masterings of one album
    differ by fractions of a second, so ranking by mean difference would only sort noise.
    """

    def tier(entry: AlbumSummary) -> int:
        fit = fits.get(result_key(entry))
        if fit and fit.kind == EXACT:
            return 0
        if fit and fit.kind == ALIGNED:
            return 1
        if fit is None and local_count and entry.track_count == local_count:
            return 2
        return 3

    return sorted(results, key=tier)


def result_key(entry: AlbumSummary) -> tuple:
    return entry.source, entry.country, entry.collection_id
