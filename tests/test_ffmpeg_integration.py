import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp3 import BitrateMode

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
