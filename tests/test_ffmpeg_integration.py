import math
import os
import struct
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.mp3 import MP3, BitrateMode

from disctag.audio import _convert_file

FFMPEG = os.environ.get("DISCTAG_FFMPEG")


def sine(samples: int, sampwidth: int, float_fmt: bool = False) -> bytes:
    out = bytearray()
    for i in range(samples):
        v = 0.5 * math.sin(2 * math.pi * 440 * i / 44100)
        if float_fmt:
            out += struct.pack("<f", v)
        elif sampwidth == 3:
            out += int(v * 8388607).to_bytes(3, "little", signed=True)
        else:
            out += struct.pack("<h", int(v * 32767))
        out += out[-4 if float_fmt else -sampwidth:]
    return bytes(out)


def write_pcm_wav(path: Path, fmt_tag: int, bits: int, frames: bytes, extensible: bool = False) -> None:
    channels, rate = 2, 44100
    block_align = channels * bits // 8
    byte_rate = rate * block_align
    if extensible:
        sub_format = struct.pack("<IHH8s", fmt_tag, 0, 0x0010, b"\x80\x00\x00\xaa\x008\x9bq")
        fmt = struct.pack("<HHIIHHHHI16s",
                          0xFFFE, channels, rate, byte_rate, block_align, bits, 22, bits, 3, sub_format)
    else:
        fmt = struct.pack("<HHIIHH", fmt_tag, channels, rate, byte_rate, block_align, bits)
    data = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(frames)) + frames
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(data)) + b"WAVE" + data)


@unittest.skipUnless(FFMPEG, "DISCTAG_FFMPEG is not set")
class FFmpegIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_pcm_wav(self.root / "s16.wav", 1, 16, sine(88200, 2))
        write_pcm_wav(self.root / "s24.wav", 1, 24, sine(88200, 3))
        write_pcm_wav(self.root / "f32.wav", 3, 32, sine(88200, 4, float_fmt=True), extensible=True)
        import subprocess

        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.root / "s16.wav"),
                        "-map_metadata", "-1", "-c:a", "flac", str(self.root / "s16.flac")], check=True)

    def convert(self, name: str, output_format: str, quality: str = "320 kbps") -> Path:
        destination = self.root / f"{name}.{output_format}"
        _convert_file(FFMPEG, self.root / f"{name}.wav", destination, output_format, quality)
        return destination

    def test_flac(self):
        for name, bits in (("s16", 16), ("s24", 24), ("f32", 24)):
            with self.subTest(name=name):
                audio = FLAC(self.convert(name, "flac"))
                self.assertEqual(audio.info.sample_rate, 44100)
                self.assertEqual(audio.info.channels, 2)
                self.assertEqual(audio.info.bits_per_sample, bits)
                self.assertAlmostEqual(audio.info.length, 2.0, delta=0.1)

    def test_flac_embed_cover_false_has_no_picture(self):
        import io

        from PIL import Image

        from disctag.audio import convert_album
        from disctag.models import AlbumMetadata, TrackMetadata

        cover = io.BytesIO()
        Image.new("RGB", (64, 64), "red").save(cover, "JPEG")
        album = AlbumMetadata("Album", "Artist", "Artist", tracks=[TrackMetadata("Song", "Artist", 1)])
        result = convert_album([self.root / "s16.wav"], album, self.root / "out", "flac",
                               cover_data=cover.getvalue(), embed_cover=False)
        self.assertFalse(result.failures)
        self.assertFalse(FLAC(result.converted_files[0]).pictures)
        self.assertEqual((result.output_directory / "cover.jpg").read_bytes(), cover.getvalue())

    def test_per_track_flac_decodes_to_wav_byte_exact(self):
        import wave

        from disctag.audio import decode_to_wav
        from disctag.sources import SourceTrack

        destination = self.root / "decoded.wav"
        decode_to_wav(SourceTrack(self.root / "s16.flac"), destination, FFMPEG)
        with wave.open(str(destination), "rb") as decoded, wave.open(str(self.root / "s16.wav"), "rb") as original:
            self.assertEqual(decoded.getparams()[:4], original.getparams()[:4])
            self.assertEqual(decoded.readframes(88200), original.readframes(88200))

    def test_per_track_flac_to_flac_and_mp3_are_tagged(self):
        from disctag.audio import convert_album
        from disctag.models import AlbumMetadata, TrackMetadata
        from disctag.sources import SourceTrack

        album = AlbumMetadata("Album", "Artist", "Artist", tracks=[TrackMetadata("Song", "Artist", 1)])
        source = SourceTrack(self.root / "s16.flac")
        for output_format in ("flac", "mp3"):
            with self.subTest(output_format=output_format):
                result = convert_album([source], album, self.root / f"out-{output_format}", output_format)
                self.assertFalse(result.failures)
                output = result.converted_files[0]
                tag = FLAC(output)["title"][0] if output_format == "flac" else str(MP3(output)["TIT2"])
                self.assertEqual(tag, "Song")
        # 原始 flac 源未被改动。
        self.assertTrue(FLAC(self.root / "s16.flac").info.length > 0)

    def test_mp3(self):
        for name in ("s16", "s24", "f32"):
            with self.subTest(name=name, quality="320 kbps"):
                audio = MP3(self.convert(name, "mp3", "320 kbps"))
                self.assertEqual(audio.info.sample_rate, 44100)
                self.assertEqual(audio.info.bitrate, 320000)
                self.assertEqual(audio.info.bitrate_mode, BitrateMode.CBR)
                self.assertAlmostEqual(audio.info.length, 2.0, delta=0.2)
            with self.subTest(name=name, quality="V0"):
                audio = MP3(self.convert(name, "mp3", "V0"))
                self.assertEqual(audio.info.sample_rate, 44100)
                self.assertEqual(audio.info.bitrate_mode, BitrateMode.VBR)
                self.assertAlmostEqual(audio.info.length, 2.0, delta=0.2)


@unittest.skipUnless(FFMPEG, "DISCTAG_FFMPEG is not set")
class FFmpegCueImageTests(unittest.TestCase):
    """A FLAC disc image + CUE is cut sample-exactly, whatever the output format."""

    SAMPLES = 44100 * 4
    # 轨道起点（CD 帧）：0、100、213 —— 有意不落在整秒上。
    STARTS = (0, 100, 213)

    def setUp(self):
        import subprocess

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pcm = b"".join(struct.pack("<hh", (i * 7) % 65536 - 32768, 32767 - (i * 3) % 65536)
                            for i in range(self.SAMPLES))
        ramp = self.root / "ramp.wav"
        write_pcm_wav(ramp, 1, 16, self.pcm)
        image = self.root / "rip" / "image.flac"
        image.parent.mkdir()
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(ramp), "-c:a", "flac",
                        str(image)], check=True)
        lines = ['TITLE "Disc"', 'FILE "image.wav" WAVE']  # CUE 写的是 .wav，整轨已另压为 .flac
        for number, start in enumerate(self.STARTS, 1):
            lines += [f"  TRACK {number:02d} AUDIO", f'    TITLE "T{number}"',
                      f"    INDEX 01 00:{start // 75:02d}:{start % 75:02d}"]
        cue = image.with_suffix(".cue")
        cue.write_text("\n".join(lines) + "\n", encoding="utf-8")
        from disctag.cue import cue_sources, parse_cue

        self.sources = cue_sources(parse_cue(cue), cue)
        self.assertEqual(self.sources[0].path, image)

    def album(self):
        from disctag.models import AlbumMetadata, TrackMetadata

        return AlbumMetadata("Album", "Artist", "Artist", tracks=[
            TrackMetadata(f"T{number}", "Artist", number, 3) for number in range(1, 4)
        ])

    def expected(self):
        bounds = [start * 588 for start in self.STARTS] + [self.SAMPLES]
        return [self.pcm[start * 4:end * 4] for start, end in zip(bounds, bounds[1:], strict=False)]

    def decode(self, path: Path) -> bytes:
        import subprocess

        # 内置 FFmpeg 只带 wav/flac/mp3 封装器，先解码为 WAV 再取 data 块。
        decoded = path.with_name(path.stem + ".decoded.wav")
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-map_metadata", "-1",
                        "-c:a", "pcm_s16le", str(decoded)], check=True)
        raw = decoded.read_bytes()
        decoded.unlink()
        position = 12
        while position + 8 <= len(raw):
            chunk_id, size = struct.unpack("<4sI", raw[position:position + 8])
            if chunk_id == b"data":
                return raw[position + 8:position + 8 + size]
            position += 8 + size + (size & 1)
        raise AssertionError("no data chunk")

    def convert(self, output_format: str):
        from disctag.audio import convert_album

        result = convert_album(self.sources, self.album(), self.root / output_format, output_format)
        self.assertFalse(result.failures)
        self.assertEqual(len(result.converted_files), 3)
        return result.converted_files

    def test_wav(self):
        for path, expected in zip(self.convert("wav"), self.expected(), strict=True):
            self.assertEqual(self.decode(path), expected)
            self.assertEqual(path.read_bytes().count(expected[:4096]), 1)

    def test_flac(self):
        for path, expected in zip(self.convert("flac"), self.expected(), strict=True):
            self.assertEqual(FLAC(path)["title"], [path.stem.split(" - ")[1]])
            self.assertEqual(self.decode(path), expected)

    def test_mp3(self):
        for path, expected in zip(self.convert("mp3"), self.expected(), strict=True):
            self.assertAlmostEqual(MP3(path).info.length, len(expected) / 4 / 44100, delta=0.1)
