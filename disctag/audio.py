from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from mutagen import MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from PIL import Image, ImageOps

from .models import AlbumMetadata, ConversionFailure, ConversionResult, TrackMetadata, renumber_tracks


class AudioError(RuntimeError):
    pass


class ConversionCancelled(AudioError):
    pass


# 单首曲目的 FFmpeg 处理上限，防止异常文件导致进程永久挂起。
FFMPEG_TIMEOUT_SECONDS = 30 * 60


ProgressCallback = Callable[[int, int, str], None]


def find_ffmpeg() -> str:
    override = os.environ.get("DISCTAG_FFMPEG")
    if override and Path(override).is_file():
        return override
    executable = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    roots = []
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        candidate = root / "vendor" / executable
        if candidate.is_file():
            return str(candidate)
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    raise AudioError("未找到 FFmpeg。请安装 FFmpeg，或重新获取包含 FFmpeg 的 DiscTag 安装包。")


def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def wav_duration(path: Path) -> float | None:
    import wave

    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() / audio.getframerate()
    except (OSError, EOFError, wave.Error, ZeroDivisionError):
        pass
    try:
        length = WAVE(path).info.length
        return length if length > 0 else None
    except (OSError, MutagenError):
        return None


def clean_track_title(path: Path) -> str:
    title = re.sub(r"^\s*\d+\s*[-._ ]+\s*", "", path.stem).strip()
    return title or path.stem


def safe_component(value: str, fallback: str = "未命名") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(".")
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = fallback
    if value.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = f"_{value}"
    return value[:120].rstrip(" .") or fallback


def output_directory(root: Path, album: AlbumMetadata) -> Path:
    artist = safe_component(album.album_artist or album.artist, "未知歌手")
    title = safe_component(album.title, "未知专辑")
    return root.expanduser() / artist / title


def output_path(directory: Path, track: TrackMetadata, extension: str) -> Path:
    if track.disc_count > 1:
        prefix = f"{track.disc_number}-{track.track_number:02d}"
    else:
        prefix = f"{track.track_number:02d}"
    return directory / f"{prefix} - {safe_component(track.title, 'Track')}.{extension}"


def convert_album(
    sources: list[Path],
    album: AlbumMetadata,
    output_root: Path,
    output_format: str = "flac",
    mp3_quality: str = "320 kbps",
    cover_data: bytes | None = None,
    progress: ProgressCallback | None = None,
    embed_cover: bool = True,
    embed_max_size: int | None = None,
    *,
    cancel: threading.Event | None = None,
) -> ConversionResult:
    if len(sources) != len(album.tracks):
        raise AudioError("本地 WAV 与专辑曲目数量不一致，请插入缺失曲目、重新匹配或改用手动模式。")
    if any(track.origin == "auto-manual" for track in album.tracks):
        raise AudioError("仍有待确认的缺曲，请按实体 CD 曲目表填写真实歌名并保存。")
    if output_format not in {"wav", "flac", "mp3"}:
        raise AudioError("不支持的输出格式。")
    renumber_tracks(album.tracks)
    ffmpeg = None if output_format == "wav" else find_ffmpeg()
    directory = output_directory(output_root, album)
    destinations = [output_path(directory, track, output_format) for track in album.tracks]
    source_paths = {source.resolve() for source in sources}
    if any(
        destination.resolve() in source_paths
        or (destination.exists() and any(source.exists() and destination.samefile(source) for source in sources))
        for destination in destinations
    ):
        raise AudioError("输出文件会覆盖源 WAV，请选择其他输出目录以保留原始音轨。")
    directory.mkdir(parents=True, exist_ok=True)
    result = ConversionResult(output_directory=directory)
    embedded = embedded_cover(cover_data, embed_max_size) if cover_data and embed_cover else None
    total = len(sources)

    with tempfile.TemporaryDirectory(prefix=".disctag-", dir=directory) as staging:
        for index, (source, track, destination) in enumerate(zip(sources, album.tracks, destinations, strict=True), 1):
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                break
            if progress:
                action = "正在整理" if output_format == "wav" else "正在转换"
                progress(index - 1, total, f"{action}：{track.title}")
            temporary = Path(staging) / destination.name
            try:
                _convert_file(ffmpeg, source, temporary, output_format, mp3_quality, cancel)
                if output_format == "flac":
                    _tag_flac(temporary, album, track, embedded)
                elif output_format == "mp3":
                    _tag_mp3(temporary, album, track, embedded)
                else:
                    _tag_wave(temporary, album, track, embedded)
                os.replace(temporary, destination)
                result.converted_files.append(destination)
            except ConversionCancelled:
                result.cancelled = True
                break
            except Exception as exc:
                result.failures.append(ConversionFailure(source=source, message=str(exc)))
            if progress:
                progress(index, total, f"已完成 {index}/{total}")

        if cover_data and result.converted_files:
            temporary_cover = Path(staging) / "cover.jpg"
            temporary_cover.write_bytes(cover_data)
            os.replace(temporary_cover, directory / "cover.jpg")
    return result


def embedded_cover(cover_data: bytes, max_size: int | None) -> bytes:
    if max_size is None:
        return cover_data
    image = Image.open(io.BytesIO(cover_data))
    if max(image.size) <= max_size:
        return cover_data
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, "JPEG", quality=94, optimize=True)
    return output.getvalue()


def _convert_file(
    ffmpeg: str | None,
    source: Path,
    destination: Path,
    output_format: str,
    mp3_quality: str,
    cancel: threading.Event | None = None,
) -> None:
    if output_format == "wav":
        shutil.copyfile(source, destination)
        return
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-map_metadata",
        "-1",
        "-c:a",
        "flac" if output_format == "flac" else "libmp3lame",
    ]
    if output_format == "flac":
        command.extend(["-compression_level", "5"])
    elif mp3_quality == "V0":
        command.extend(["-q:a", "0"])
    else:
        command.extend(["-b:a", "320k"])
    command.append(str(destination))
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    # stderr 写入临时文件而非管道，轮询等待时不会因缓冲区写满而死锁。
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stderr=errors, **kwargs)
        deadline = time.monotonic() + FFMPEG_TIMEOUT_SECONDS
        try:
            while True:
                try:
                    returncode = process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if cancel is not None and cancel.is_set():
                        raise ConversionCancelled("已取消处理。") from None
                    if time.monotonic() > deadline:
                        raise AudioError("FFmpeg 处理超时。") from None
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if returncode != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", "replace").strip().splitlines()
            raise AudioError(message[-1] if message else f"FFmpeg 退出代码：{returncode}")


def _tag_flac(path: Path, album: AlbumMetadata, track: TrackMetadata, cover_data: bytes | None) -> None:
    audio = FLAC(path)
    audio["title"] = track.title
    audio["artist"] = track.artist or album.artist
    audio["album"] = album.title
    audio["albumartist"] = album.album_artist or album.artist
    audio["tracknumber"] = str(track.track_number)
    audio["tracktotal"] = str(track.track_count)
    audio["discnumber"] = str(track.disc_number)
    audio["disctotal"] = str(track.disc_count)
    if album.release_date:
        audio["date"] = album.release_date
    if album.genre:
        audio["genre"] = album.genre
    if cover_data:
        picture = Picture()
        picture.type = 3
        picture.mime = "image/jpeg"
        picture.desc = "Cover"
        picture.data = cover_data
        audio.add_picture(picture)
    audio.save()


def _tag_mp3(path: Path, album: AlbumMetadata, track: TrackMetadata, cover_data: bytes | None) -> None:
    audio = MP3(path)
    if audio.tags is None:
        audio.add_tags()
    _update_id3(audio.tags, album, track, cover_data)
    audio.save(v2_version=3)


def _tag_wave(path: Path, album: AlbumMetadata, track: TrackMetadata, cover_data: bytes | None) -> None:
    audio = WAVE(path)
    if audio.tags is None:
        audio.add_tags()
    _update_id3(audio.tags, album, track, cover_data)
    audio.save(v2_version=3)


def _update_id3(tags, album: AlbumMetadata, track: TrackMetadata, cover_data: bytes | None) -> None:
    for frame in ("TIT2", "TPE1", "TALB", "TPE2", "TRCK", "TPOS", "TDRC", "TYER", "TDAT", "TCON", "APIC"):
        tags.delall(frame)
    tags.add(TIT2(encoding=3, text=track.title))
    tags.add(TPE1(encoding=3, text=track.artist or album.artist))
    tags.add(TALB(encoding=3, text=album.title))
    tags.add(TPE2(encoding=3, text=album.album_artist or album.artist))
    tags.add(TRCK(encoding=3, text=f"{track.track_number}/{track.track_count}"))
    tags.add(TPOS(encoding=3, text=f"{track.disc_number}/{track.disc_count}"))
    if album.release_date:
        tags.add(TDRC(encoding=3, text=album.release_date))
    if album.genre:
        tags.add(TCON(encoding=3, text=album.genre))
    if cover_data:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_data))
