"""Conversion jobs and the queue that runs them one album at a time."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import AlbumMetadata, ConversionResult

PENDING = "pending"
RUNNING = "running"
DONE = "done"
PARTIAL = "partial"
FAILED = "failed"
CANCELLED = "cancelled"

STATUS_LABELS = {
    PENDING: "等待中",
    RUNNING: "处理中",
    DONE: "已完成",
    PARTIAL: "部分失败",
    FAILED: "失败",
    CANCELLED: "已取消",
}
FORMAT_LABELS = {"wav": "WAV", "flac": "FLAC", "mp3": "MP3"}


@dataclass
class ConversionJob:
    sources: list[Path]
    album: AlbumMetadata
    output_root: Path
    output_format: str
    mp3_quality: str
    cover_data: bytes | None
    embed_cover: bool
    embed_max_size: int | None
    status: str = PENDING
    message: str = ""
    result: ConversionResult | None = None

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
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def finished(self) -> bool:
        return self.status in {DONE, PARTIAL, FAILED, CANCELLED}

    def finish(self, result: ConversionResult) -> None:
        self.result = result
        converted = len(result.converted_files)
        if result.cancelled:
            self.status = CANCELLED
            self.message = f"已完成 {converted} 首后取消"
        elif result.failures:
            self.status = PARTIAL
            self.message = f"成功 {converted} 首，失败 {len(result.failures)} 首"
        else:
            self.status = DONE
            self.message = f"{converted} 首"

    def fail(self, error: Exception) -> None:
        self.status = FAILED
        self.message = str(error)

    def same_input(self, sources: list[Path]) -> bool:
        return [path.resolve() for path in self.sources] == [path.resolve() for path in sources]


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
