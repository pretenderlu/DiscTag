"""CUE sheet parsing and splitting a disc image into per-track sources."""
from __future__ import annotations

import codecs
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from .i18n import tr
from .sources import SourceTrack

IMAGE_EXTENSIONS = (".wav", ".flac", ".ape")
# MusicBrainz TOC：第 1 轨之前固定有 2 秒（150 帧）的引导区。
TOC_LEAD_IN = 150

_TIME = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})$")
_KANA = re.compile(r"[\u3040-\u30ff]")


class CueError(ValueError):
    pass


@dataclass
class CueEntry:
    number: int
    title: str
    performer: str
    file: Path
    index01: int
    index00: int | None = None


@dataclass
class CueSheet:
    title: str = ""
    performer: str = ""
    date: str = ""
    genre: str = ""
    tracks: list[CueEntry] = field(default_factory=list)


def read_cue_text(path: Path) -> str:
    data = Path(path).read_bytes()
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", "replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace").lstrip("\ufeff")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("shift_jis")
    except UnicodeDecodeError:
        pass
    else:
        # gb18030 几乎能解码任何字节序列，因此先认出含假名的日文 CUE。
        if _KANA.search(text):
            return text
    try:
        gbk_text = data.decode("gb18030")
    except UnicodeDecodeError:
        gbk_text = None
    if gbk_text is not None and _is_gb2312(gbk_text):
        return gbk_text
    # Big5（繁体）字节按 GBK 解码时常落到 GB2312 以外的生僻字，此时优先尝试 Big5。
    try:
        return data.decode("big5")
    except UnicodeDecodeError:
        pass
    return gbk_text if gbk_text is not None else data.decode("latin-1")


def _is_gb2312(text: str) -> bool:
    try:
        text.encode("gb2312")
    except UnicodeEncodeError:
        return False
    return True


def _parse_time(value: str) -> int:
    match = _TIME.match(value)
    if not match:
        raise CueError(tr("CUE 中的时间格式无效：{0}", value))
    minutes, seconds, frames = (int(part) for part in match.groups())
    if seconds >= 60 or frames >= 75:
        raise CueError(tr("CUE 中的时间格式无效：{0}", value))
    return (minutes * 60 + seconds) * 75 + frames


def _value(rest: str) -> str:
    rest = rest.strip()
    if rest.startswith('"'):
        end = rest.find('"', 1)
        return rest[1:end] if end > 0 else rest[1:]
    return rest


def _file_name(rest: str) -> str:
    rest = rest.strip()
    if rest.startswith('"'):
        return _value(rest)
    parts = rest.rsplit(None, 1)
    return parts[0] if len(parts) == 2 else rest


def resolve_cue_file(directory: Path, name: str) -> Path:
    """Finds the audio file a FILE line refers to, tolerating case changes and a recompressed image."""
    base = PureWindowsPath(name).name
    try:
        entries = [entry for entry in directory.iterdir() if entry.is_file()]
    except OSError:
        entries = []
    folded = base.casefold()
    exact = directory / name
    if exact.is_file():
        # 大小写不敏感的文件系统上也返回磁盘上的真实文件名。
        if exact.parent == directory:
            return next((entry for entry in entries if entry.name == exact.name), None) or next(
                (entry for entry in entries if entry.name.casefold() == folded), exact
            )
        return exact
    for entry in entries:
        if entry.name.casefold() == folded:
            return entry
    stem = os.path.splitext(base)[0].casefold()
    for extension in IMAGE_EXTENSIONS:
        for entry in entries:
            if entry.stem.casefold() == stem and entry.suffix.lower() == extension:
                return entry
    raise CueError(tr("找不到 CUE 引用的音频文件：{0}", name))


def parse_cue(path: Path) -> CueSheet:
    path = Path(path)
    try:
        text = read_cue_text(path)
    except OSError as exc:
        raise CueError(tr("无法读取 CUE 文件 {0}：{1}", path.name, exc)) from exc
    sheet = CueSheet()
    resolved: dict[str, Path] = {}
    current_file: str | None = None
    current: dict | None = None
    pending: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue
        command, _, rest = line.partition(" ")
        command = command.upper()
        if command == "FILE":
            current_file = _file_name(rest)
            current = None
        elif command == "TRACK":
            parts = rest.split()
            current = None
            if len(parts) >= 2 and parts[1].upper() == "AUDIO" and parts[0].isdigit():
                if current_file is None:
                    raise CueError(tr("CUE 中的音轨缺少 FILE：{0}", path.name))
                # 只解析音频轨用到的文件，数据轨（如 Enhanced CD 的 BINARY）缺失不影响导入。
                if current_file not in resolved:
                    resolved[current_file] = resolve_cue_file(path.parent, current_file)
                current = {"number": int(parts[0]), "title": "", "performer": "", "file": resolved[current_file],
                           "index01": None, "index00": None}
                pending.append(current)
        elif command == "INDEX":
            if current is None:
                continue
            parts = rest.split()
            if len(parts) != 2 or not parts[0].isdigit():
                raise CueError(tr("CUE 中的 INDEX 行无效：{0}", line))
            frames = _parse_time(parts[1])
            if int(parts[0]) == 1:
                current["index01"] = frames
            elif int(parts[0]) == 0:
                current["index00"] = frames
        elif command in {"TITLE", "PERFORMER"}:
            key = command.lower()
            if current is not None:
                current[key] = _value(rest)
            elif not pending:
                setattr(sheet, key, _value(rest))
        elif command == "REM" and not pending:
            parts = rest.strip().split(None, 1)
            if len(parts) == 2 and parts[0].upper() in {"DATE", "GENRE"}:
                setattr(sheet, parts[0].lower(), _value(parts[1]))

    if not pending:
        raise CueError(tr("CUE 中没有音频轨：{0}", path.name))
    for entry in pending:
        if entry["index01"] is None:
            raise CueError(tr("CUE 第 {0} 轨缺少 INDEX 01。", entry["number"]))
        sheet.tracks.append(CueEntry(
            number=entry["number"],
            title=entry["title"],
            performer=entry["performer"] or sheet.performer,
            file=entry["file"],
            index01=entry["index01"],
            index00=entry["index00"],
        ))
    return sheet


def cue_sources(sheet: CueSheet, cue_path: Path) -> list[SourceTrack]:
    """One source per track, from its INDEX 01 to the next track's INDEX 01 in the same file (gaps stay with the
    previous track); audio before track 1's INDEX 01 (hidden track one audio) is skipped."""
    sources = []
    for index, entry in enumerate(sheet.tracks):
        following = sheet.tracks[index + 1] if index + 1 < len(sheet.tracks) else None
        end = following.index01 if following is not None and following.file == entry.file else None
        if end is not None and end <= entry.index01:
            raise CueError(tr("CUE 第 {0} 轨的起止时间无效。", entry.number))
        sources.append(SourceTrack(
            path=entry.file,
            start_frame=entry.index01,
            end_frame=end,
            number=entry.number,
            cue=Path(cue_path),
            title=entry.title,
            performer=entry.performer,
        ))
    return sources


def is_image_cue(sheet: CueSheet) -> bool:
    """True when at least one file holds several tracks; a cue with one file per track is not a disc image."""
    counts = Counter(entry.file for entry in sheet.tracks)
    return any(count > 1 for count in counts.values())


def cue_toc(sources: list[SourceTrack], image_frames: int | None) -> str | None:
    """Exact MusicBrainz TOC when every source is a segment of one disc image."""
    if not sources or len(sources) > 99 or not image_frames:
        return None
    if not all(source.is_segment for source in sources):
        return None
    if len({source.key()[0] for source in sources}) != 1:
        return None
    offsets = [source.start_frame + TOC_LEAD_IN for source in sources]
    leadout = image_frames + TOC_LEAD_IN
    if any(later <= earlier for earlier, later in zip(offsets, offsets[1:], strict=False)) or leadout <= offsets[-1]:
        return None
    return "+".join(str(value) for value in (1, len(offsets), leadout, *offsets))
