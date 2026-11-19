from __future__ import annotations

import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mutagen import MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.monkeysaudio import MonkeysAudio
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from PIL import Image, ImageOps

from .i18n import tr
from .models import AlbumMetadata, ConversionFailure, ConversionResult, TrackMetadata, renumber_tracks
from .sources import FRAMES_PER_SECOND, SourceTrack


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
    raise AudioError(tr("未找到 FFmpeg。请安装 FFmpeg，或重新获取包含 FFmpeg 的 DiscTag 安装包。"))


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


@dataclass(frozen=True)
class _WavLayout:
    fmt_chunk: bytes
    data_offset: int
    data_size: int
    block_align: int
    sample_rate: int
    bits: int


def _wav_layout(path: Path) -> _WavLayout:
    """Locates the ``fmt `` and ``data`` chunks of a RIFF/WAVE file (PCM, float and WAVE_FORMAT_EXTENSIBLE)."""
    file_size = path.stat().st_size
    with open(path, "rb") as stream:
        header = stream.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise AudioError(tr("不是有效的 WAV 文件：{0}", path.name))
        fmt_chunk = None
        data_offset = data_size = None
        position = 12
        while position + 8 <= file_size and (fmt_chunk is None or data_offset is None):
            stream.seek(position)
            chunk_id, size = struct.unpack("<4sI", stream.read(8))
            body = position + 8
            if chunk_id == b"fmt ":
                fmt_chunk = stream.read(size)
            elif chunk_id == b"data":
                data_offset = body
                # 流式写入的 WAV 可能把长度记为 0 或 0xFFFFFFFF，按实际文件大小截断。
                data_size = min(size, file_size - body) if size else file_size - body
            position = body + size + (size & 1)
    if fmt_chunk is None or len(fmt_chunk) < 16 or data_offset is None:
        raise AudioError(tr("不是有效的 WAV 文件：{0}", path.name))
    _tag, _channels, sample_rate, _byte_rate, block_align, bits = struct.unpack("<HHIIHH", fmt_chunk[:16])
    if not sample_rate or not block_align:
        raise AudioError(tr("不是有效的 WAV 文件：{0}", path.name))
    return _WavLayout(fmt_chunk, data_offset, data_size - data_size % block_align, block_align, sample_rate, bits)


def audio_info(path: Path) -> tuple[int, int, float]:
    """Returns (sample rate, bits per sample, length in seconds) of a WAV, FLAC or APE file."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".flac":
            info = FLAC(path).info
            return info.sample_rate, info.bits_per_sample, info.length
        if suffix == ".ape":
            info = MonkeysAudio(path).info
            return info.sample_rate, info.bits_per_sample or 16, info.length
        if suffix == ".wav":
            try:
                layout = _wav_layout(path)
            except (AudioError, struct.error):
                info = WAVE(path).info
                return info.sample_rate, info.bits_per_sample, info.length
            return layout.sample_rate, layout.bits, layout.data_size / layout.block_align / layout.sample_rate
    except (OSError, MutagenError) as exc:
        raise AudioError(tr("无法读取音频文件 {0}：{1}", path.name, exc)) from exc
    raise AudioError(tr("不支持的音频格式：{0}", path.name))


def source_duration(source: SourceTrack | Path) -> float | None:
    source = SourceTrack.of(source)
    if not source.is_segment:
        if source.path.suffix.lower() == ".wav":
            return wav_duration(source.path)
        try:
            return audio_info(source.path)[2]
        except AudioError:
            return None
    if source.end_frame is not None:
        return (source.end_frame - source.start_frame) / FRAMES_PER_SECOND
    try:
        length = audio_info(source.path)[2] - source.start_frame / FRAMES_PER_SECOND
    except AudioError:
        return None
    return length if length > 0 else None


def _segment_samples(source: SourceTrack, sample_rate: int) -> tuple[int, int | None]:
    start = source.start_frame * sample_rate // FRAMES_PER_SECOND
    end = None if source.end_frame is None else source.end_frame * sample_rate // FRAMES_PER_SECOND
    return start, end


def decode_to_wav(
    source: SourceTrack,
    destination: Path,
    ffmpeg: str | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Writes one source track as a WAV file, sample-exactly."""
    if source.path.suffix.lower() != ".wav":
        sample_rate, bits, _length = audio_info(source.path)
        codec = "pcm_s16le" if bits <= 16 else "pcm_s24le" if bits <= 24 else "pcm_s32le"
        command = [
            ffmpeg or find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source.path), "-map", "0:a:0", "-vn",
        ]
        if source.is_segment:
            command += ["-af", _trim_filter(*_segment_samples(source, sample_rate))]
        command += ["-map_metadata", "-1", "-c:a", codec, str(destination)]
        _run_ffmpeg(command, cancel)
        return
    if not source.is_segment:
        shutil.copyfile(source.path, destination)
        return
    try:
        layout = _wav_layout(source.path)
    except (OSError, struct.error) as exc:
        raise AudioError(tr("无法读取音频文件 {0}：{1}", source.path.name, exc)) from exc
    total = layout.data_size // layout.block_align
    start, end = _segment_samples(source, layout.sample_rate)
    end = total if end is None else min(end, total)
    if start >= end:
        raise AudioError(tr("CUE 音轨超出整轨文件长度：{0}", source.name))
    length = (end - start) * layout.block_align
    fmt = layout.fmt_chunk + (b"\x00" if len(layout.fmt_chunk) & 1 else b"")
    riff_size = 4 + 8 + len(fmt) + 8 + length + (length & 1)
    with open(source.path, "rb") as reader, open(destination, "wb") as writer:
        writer.write(b"RIFF" + struct.pack("<I", riff_size) + b"WAVE")
        writer.write(b"fmt " + struct.pack("<I", len(layout.fmt_chunk)) + fmt)
        writer.write(b"data" + struct.pack("<I", length))
        reader.seek(layout.data_offset + start * layout.block_align)
        remaining = length
        while remaining:
            if cancel is not None and cancel.is_set():
                raise ConversionCancelled(tr("已取消处理。"))
            block = reader.read(min(remaining, 1 << 20))
            if not block:
                raise AudioError(tr("CUE 音轨超出整轨文件长度：{0}", source.name))
            writer.write(block)
            remaining -= len(block)
        if length & 1:
            writer.write(b"\x00")


def _trim_filter(start: int, end: int | None) -> str:
    trim = f"atrim=start_sample={start}" + ("" if end is None else f":end_sample={end}")
    return f"{trim},asetpts=PTS-STARTPTS"


def clean_track_title(path: Path) -> str:
    title = re.sub(r"^\s*\d+\s*[-._ ]+\s*", "", path.stem).strip()
    return title or path.stem


def safe_component(value: str, fallback: str | None = None) -> str:
    fallback = tr("未命名") if fallback is None else fallback
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(".")
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = fallback
    if value.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = f"_{value}"
    return value[:120].rstrip(" .") or fallback


def output_directory(root: Path, album: AlbumMetadata) -> Path:
    artist = safe_component(album.album_artist or album.artist, tr("未知歌手"))
    title = safe_component(album.title, tr("未知专辑"))
    return root.expanduser() / artist / title


def output_path(directory: Path, track: TrackMetadata, extension: str) -> Path:
    if track.disc_count > 1:
        prefix = f"{track.disc_number}-{track.track_number:02d}"
    else:
        prefix = f"{track.track_number:02d}"
    return directory / f"{prefix} - {safe_component(track.title, 'Track')}.{extension}"


def convert_album(
    sources: list[SourceTrack | Path],
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
    sources = [SourceTrack.of(source) for source in sources]
    if len(sources) != len(album.tracks):
        raise AudioError(tr("本地音轨与专辑曲目数量不一致，请插入缺失曲目、重新匹配或改用手动模式。"))
    if any(track.origin == "auto-manual" for track in album.tracks):
        raise AudioError(tr("仍有待确认的缺曲，请按实体 CD 曲目表填写真实歌名并保存。"))
    if output_format not in {"wav", "flac", "mp3"}:
        raise AudioError(tr("不支持的输出格式。"))
    renumber_tracks(album.tracks)
    needs_ffmpeg = output_format != "wav" or any(
        source.path.suffix.lower() != ".wav" for source in sources
    )
    ffmpeg = find_ffmpeg() if needs_ffmpeg else None
    directory = output_directory(output_root, album)
    destinations = [output_path(directory, track, output_format) for track in album.tracks]
    # 单曲 WAV 与 CUE 整轨文件一样都不能被覆盖。
    source_files = list(dict.fromkeys(source.path for source in sources))
    source_paths = {path.resolve() for path in source_files}
    if any(
        destination.resolve() in source_paths
        or (destination.exists() and any(path.exists() and destination.samefile(path) for path in source_files))
        for destination in destinations
    ):
        raise AudioError(tr("输出文件会覆盖源文件，请选择其他输出目录以保留原始音轨。"))
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
                action = tr("正在整理") if output_format == "wav" else tr("正在转换")
                progress(index - 1, total, tr("{0}：{1}", action, track.title))
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
                progress(index, total, tr("已完成 {0}/{1}", index, total))

        if cover_data and result.converted_files:
            temporary_cover = Path(staging) / "cover.jpg"
            try:
                temporary_cover.write_bytes(cover_data)
                os.replace(temporary_cover, directory / "cover.jpg")
            except OSError as exc:
                # 音轨已全部写好，封面失败只作为警告报告，不计入失败曲目。
                result.cover_error = str(exc)
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
    source: SourceTrack | Path,
    destination: Path,
    output_format: str,
    mp3_quality: str,
    cancel: threading.Event | None = None,
) -> None:
    source = SourceTrack.of(source)
    if output_format == "wav":
        decode_to_wav(source, destination, ffmpeg, cancel)
        return
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source.path),
        "-map",
        "0:a:0",
        "-vn",
    ]
    if source.is_segment:
        sample_rate = audio_info(source.path)[0]
        command.extend(["-af", _trim_filter(*_segment_samples(source, sample_rate))])
    command.extend([
        "-map_metadata",
        "-1",
        "-c:a",
        "flac" if output_format == "flac" else "libmp3lame",
    ])
    if output_format == "flac":
        command.extend(["-compression_level", "5"])
    elif mp3_quality == "V0":
        command.extend(["-q:a", "0"])
    else:
        command.extend(["-b:a", "320k"])
    command.append(str(destination))
    _run_ffmpeg(command, cancel)


def _run_ffmpeg(command: list[str], cancel: threading.Event | None = None) -> None:
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
                        raise ConversionCancelled(tr("已取消处理。")) from None
                    if time.monotonic() > deadline:
                        raise AudioError(tr("FFmpeg 处理超时。")) from None
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if returncode != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", "replace").strip().splitlines()
            raise AudioError(message[-1] if message else tr("FFmpeg 退出代码：{0}", returncode))


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
