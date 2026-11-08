from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from .audio import wav_duration


class AudioPreview:
    def __init__(self, root, on_change):
        self.root = root
        self.on_change = on_change
        self.path: Path | None = None
        self.process: subprocess.Popen | None = None
        self.started = 0.0
        self.duration = 0.0
        self._poll_id = None

    @property
    def playing(self) -> bool:
        return self.path is not None

    def toggle(self, path: Path) -> None:
        if self.playing and self.path == path:
            self.stop()
        else:
            self.play(path)

    def play(self, path: Path) -> None:
        self.stop()
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
            raise RuntimeError(f"无法播放 {path.name}：{exc}") from exc
        self.path = path
        self.started = time.monotonic()
        self.duration = wav_duration(path) or 0.0
        self.on_change(True, path)
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
        self.on_change(False, path)

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
