"""Conversion jobs and the queue that runs them one album at a time."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .audio import output_directory, output_path
from .i18n import tr
from .models import AlbumMetadata, ConversionFailure, ConversionResult
from .sources import SourceTrack
from .trash import move_to_trash, trash_name

PENDING = "pending"
RUNNING = "running"
DONE = "done"
PARTIAL = "partial"
FAILED = "failed"
CANCELLED = "cancelled"


def status_label(status: str) -> str:
    """Localized job status; built on call so the current UI language is used."""
    labels = {
        PENDING: tr("等待中"),
        RUNNING: tr("处理中"),
        DONE: tr("已完成"),
        PARTIAL: tr("部分失败"),
        FAILED: tr("失败"),
        CANCELLED: tr("已取消"),
    }
    return labels.get(status, status)


FORMAT_LABELS = {"wav": "WAV", "flac": "FLAC", "mp3": "MP3"}


@dataclass
class ConversionJob:
    sources: list[SourceTrack]
    album: AlbumMetadata
    output_root: Path
    output_format: str
    mp3_quality: str
    cover_data: bytes | None
    embed_cover: bool
    embed_max_size: int | None
    trash_sources: bool = False
    status: str = PENDING
    message: str = ""
    result: ConversionResult | None = None

    def __post_init__(self) -> None:
        self.sources = [SourceTrack.of(source) for source in self.sources]

    @property
    def title(self) -> str:
        return self.album.title

    @property
    def artist(self) -> str:
        return self.album.album_artist or self.album.artist

    @property
    def format_label(self) -> str:
        label = FORMAT_LABELS.get(self.output_format, self.output_format.upper())
        return f"{label} {self.mp3_quality}" if self.output_format == "mp3" else label

    @property
    def status_label(self) -> str:
        return status_label(self.status)

    @property
    def finished(self) -> bool:
        return self.status in {DONE, PARTIAL, FAILED, CANCELLED}

    def finish(self, result: ConversionResult) -> None:
        self.result = result
        converted = len(result.converted_files)
        if result.cancelled:
            self.status = CANCELLED
            self.message = tr("已完成 {0} 首后取消", converted)
        elif result.failures:
            self.status = PARTIAL
            self.message = tr("成功 {0} 首，失败 {1} 首", converted, len(result.failures))
        else:
            self.status = DONE
            self.message = tr("{0} 首", converted)
        if result.cover_error:
            self.message += tr("；cover.jpg 写入失败：{0}", result.cover_error)
        if result.trashed_sources:
            self.message += tr("；源文件已移到{0}", trash_name())
        if result.trash_failures:
            self.status = PARTIAL
            self.message += tr("；{0} 个源文件未能移到{1}，已保留", len(result.trash_failures), trash_name())
        if result.trash_skipped:
            self.message += tr("；未全部成功，源文件已全部保留")

    def fail(self, error: Exception) -> None:
        self.status = FAILED
        self.message = str(error)

    def same_input(self, sources: list[SourceTrack | Path]) -> bool:
        return [source.key() for source in self.sources] == [SourceTrack.of(source).key() for source in sources]

    def trash_paths(self) -> list[Path]:
        """Files moved to the trash after success: the WAVs, or for CUE tracks the disc image(s) and the .cue."""
        paths: list[Path] = []
        for source in self.sources:
            paths.append(source.path)
        for source in self.sources:
            if source.cue is not None:
                paths.append(source.cue)
        unique: dict[str, Path] = {}
        for path in paths:
            unique.setdefault(os.path.normcase(os.path.abspath(path)), path)
        return list(unique.values())

    def output_paths(self) -> set[Path]:
        """Every file the job writes, normalised (absolute, case-folded on Windows) so paths can be compared."""
        directory = output_directory(self.output_root, self.album)
        paths = [output_path(directory, track, self.output_format) for track in self.album.tracks]
        if self.cover_data:
            paths.append(directory / "cover.jpg")
        return {Path(os.path.normcase(os.path.abspath(path))) for path in paths}


def trash_sources_if_complete(job: ConversionJob, result: ConversionResult, mover=move_to_trash) -> None:
    """Moves the job's source files to the trash, but only if every track was written successfully."""
    if not job.trash_sources:
        return
    complete = (
        not result.cancelled
        and not result.failures
        and len(result.converted_files) == len(job.sources)
        and all(path.is_file() and path.stat().st_size > 0 for path in result.converted_files)
    )
    if not complete:
        result.trash_skipped = True
        return
    moved, failures = mover(job.trash_paths())
    result.trashed_sources = list(moved)
    result.trash_failures = [ConversionFailure(path, message) for path, message in failures]


@dataclass
class JobQueue:
    jobs: list[ConversionJob] = field(default_factory=list)

    def add(self, job: ConversionJob) -> bool:
        """Adds a job; a pending job for the same WAV files is replaced in place. Returns True if replaced."""
        for index, existing in enumerate(self.jobs):
            if existing.status == PENDING and existing.same_input(job.sources):
                self.jobs[index] = job
                return True
        self.jobs.append(job)
        return False

    def conflict(self, job: ConversionJob) -> tuple[str, ConversionJob] | None:
        """Finds an unfinished job that would clash with ``job``.

        Returns ``("running_trash", existing)`` when the same WAVs are being processed and will be moved to the
        trash, ``("output", existing)`` when both jobs would write the same output file, otherwise None. A pending
        job for the same WAVs is not a conflict because ``add`` replaces it.
        """
        outputs = job.output_paths()
        for existing in self.jobs:
            if existing.status not in {PENDING, RUNNING}:
                continue
            same_input = existing.same_input(job.sources)
            if existing.status == PENDING and same_input:
                continue
            if existing.status == RUNNING and existing.trash_sources and same_input:
                return "running_trash", existing
            if existing.output_paths() & outputs:
                return "output", existing
        return None

    def next_pending(self) -> ConversionJob | None:
        return next((job for job in self.jobs if job.status == PENDING), None)

    def pending_count(self) -> int:
        return sum(job.status == PENDING for job in self.jobs)

    def remove(self, index: int) -> bool:
        if 0 <= index < len(self.jobs) and self.jobs[index].status != RUNNING:
            del self.jobs[index]
            return True
        return False

    def clear_finished(self) -> int:
        before = len(self.jobs)
        self.jobs = [job for job in self.jobs if not job.finished]
        return before - len(self.jobs)

    def retry(self, index: int) -> bool:
        """Puts a failed, partial or cancelled job back into the queue."""
        if 0 <= index < len(self.jobs) and self.jobs[index].status in {PARTIAL, FAILED, CANCELLED}:
            job = self.jobs[index]
            job.status, job.message, job.result = PENDING, "", None
            return True
        return False
