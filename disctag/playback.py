from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .audio import decode_to_wav, source_duration
from .i18n import tr
from .sources import SourceTrack


# CD-DA：44.1 kHz、16 bit、双声道，每秒 176400 字节；WAV 头约 44 字节。
CD_BYTES_PER_SECOND = 176400
WAV_HEADER_BYTES = 44


def _estimated_duration(path: Path) -> float:
    """Fallback length when the WAV header can't be parsed, so the Windows poll still ends."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0.0
    return max(size - WAV_HEADER_BYTES, 0) / CD_BYTES_PER_SECOND


def preview_directory() -> Path:
    return Path(tempfile.gettempdir()) / "DiscTag" / "preview"


def cleanup_preview_files() -> None:
    """Removes leftover CUE preview extracts (e.g. from a previous run)."""
    try:
        entries = list(preview_directory().glob("*.wav"))
    except OSError:
        return
    for entry in entries:
        try:
            entry.unlink()
        except OSError:
            pass


class AudioPreview:
    def __init__(self, root, on_change):
        self.root = root
        self.on_change = on_change
        self.path: SourceTrack | None = None
        # CUE 音轨试听时临时切出的 WAV，停止或换曲时删除。
        self.temporary: Path | None = None
        self.process: subprocess.Popen | None = None
        self.started = 0.0
        self.duration = 0.0
        self._poll_id = None

    @property
    def playing(self) -> bool:
        return self.path is not None

    def toggle(self, source: SourceTrack | Path) -> None:
        source = SourceTrack.of(source)
        if self.playing and self.path == source:
            self.stop()
        else:
            self.play(source)

    def play(self, source: SourceTrack | Path) -> None:
        self.stop()
        source = SourceTrack.of(source)
        path = source.path
        if source.is_segment or source.path.suffix.lower() != ".wav":
            path = self._extract(source)
        try:
            if sys.platform == "win32":
                import winsound

                winsound.PlaySound(
                    str(path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
            else:
                self.process = subprocess.Popen(
                    ["afplay", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except (OSError, RuntimeError) as exc:
            self._remove_temporary()
            raise RuntimeError(tr("无法播放 {0}：{1}", source.name, exc)) from exc
        self.path = source
        self.started = time.monotonic()
        self.duration = source_duration(source) or _estimated_duration(path)
        self.on_change(True, source)
        self._poll_id = self.root.after(250, self._poll)

    def stop(self) -> None:
        if not self.playing:
            return
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        path = self.path
        if sys.platform == "win32":
            import winsound

            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except RuntimeError:
                pass
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.process = None
        self.path = None
        self.duration = 0.0
        self._remove_temporary()
        self.on_change(False, path)

    def _extract(self, source: SourceTrack) -> Path:
        directory = preview_directory()
        destination = directory / f"{uuid.uuid4().hex}.wav"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            decode_to_wav(source, destination)
        except Exception as exc:
            try:
                destination.unlink()
            except OSError:
                pass
            raise RuntimeError(tr("无法播放 {0}：{1}", source.name, exc)) from exc
        self.temporary = destination
        return destination

    def _remove_temporary(self) -> None:
        temporary, self.temporary = self.temporary, None
        if temporary is None:
            return
        try:
            os.remove(temporary)
        except OSError:
            pass

    def _poll(self) -> None:
        self._poll_id = None
        if not self.playing:
            return
        finished = self.process is not None and self.process.poll() is not None
        if sys.platform == "win32" and self.duration:
            finished = time.monotonic() - self.started >= self.duration + 0.25
        if finished:
            self.stop()
        else:
            self._poll_id = self.root.after(250, self._poll)
