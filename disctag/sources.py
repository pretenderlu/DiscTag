"""Local audio sources: a per-track file, or one track cut out of a CUE disc image."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# CD 帧：每秒 75 帧，CUE 中的 mm:ss:ff 以此为单位。
FRAMES_PER_SECOND = 75


@dataclass(frozen=True)
class SourceTrack:
    path: Path
    start_frame: int = 0
    end_frame: int | None = None
    number: int = 0
    cue: Path | None = None
    title: str = ""
    performer: str = ""

    @property
    def is_segment(self) -> bool:
        return self.cue is not None

    @property
    def name(self) -> str:
        return f"{self.path.name} [{self.number:02d}]" if self.is_segment else self.path.name

    @classmethod
    def of(cls, value: SourceTrack | Path | str) -> SourceTrack:
        return value if isinstance(value, SourceTrack) else cls(Path(value))

    def key(self) -> tuple:
        """Identity of the audio this source refers to, independent of path spelling and CUE text."""
        return os.path.normcase(os.path.abspath(self.path)), self.start_frame, self.end_frame
