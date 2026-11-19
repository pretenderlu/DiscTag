import io
import os
import random
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from PIL import Image

from disctag.audio import AudioError, convert_album, find_ffmpeg, output_directory, output_path
from disctag.models import AlbumMetadata, TrackMetadata
from disctag.sources import SourceTrack


def write_wav(path, sample=b"\x01\x00"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        audio.writeframes(sample * 4410)


class AudioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.album = AlbumMetadata("Album", "Artist", "Artist", tracks=[TrackMetadata("Song", "Artist", 1)])
        self.source = self.root / "source.wav"
        write_wav(self.source)

    def test_reordered_inputs_cannot_be_overwritten(self):
        self.album.tracks.append(TrackMetadata("Other", "Artist", 2))
        directory = output_directory(self.root, self.album)
        first, second = [output_path(directory, track, "wav") for track in self.album.tracks]
        write_wav(first)
        write_wav(second, b"\x02\x00")
        original = [first.read_bytes(), second.read_bytes()]
        with self.assertRaisesRegex(AudioError, "源 WAV"):
            convert_album([second, first], self.album, self.root, "wav")
        self.assertEqual([first.read_bytes(), second.read_bytes()], original)

    def test_same_input_output_is_rejected(self):
        path = output_path(output_directory(self.root, self.album), self.album.tracks[0], "wav")
        write_wav(path)
        original = path.read_bytes()
        with self.assertRaises(AudioError):
            convert_album([path], self.album, self.root, "wav")
        self.assertEqual(path.read_bytes(), original)

    def test_alias_of_source_is_rejected(self):
        target = output_path(output_directory(self.root, self.album), self.album.tracks[0], "wav")
        target.parent.mkdir(parents=True)
        try:
            os.link(self.source, target)
        except OSError:
            self.skipTest("hard links not supported")
        original = self.source.read_bytes()
        with self.assertRaises(AudioError):
            convert_album([self.source], self.album, self.root, "wav")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(target.read_bytes(), original)

    def test_wav_tags_cover_and_pcm_preserve_source(self):
        cover = io.BytesIO()
        Image.new("RGB", (16, 16), "red").save(cover, "JPEG")
        original = self.source.read_bytes()
        result = convert_album([self.source], self.album, self.root, "wav", cover_data=cover.getvalue())
        self.assertFalse(result.failures)
        tagged = WAVE(result.converted_files[0])
        self.assertEqual(str(tagged["TIT2"]), "Song")
        self.assertEqual(tagged.tags.getall("APIC")[0].data, cover.getvalue())
        self.assertEqual((result.output_directory / "cover.jpg").read_bytes(), cover.getvalue())
        with wave.open(str(self.source)) as source, wave.open(str(result.converted_files[0])) as output:
            self.assertEqual(source.readframes(4410), output.readframes(4410))
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(list(result.output_directory.glob(".disctag-*")))

    def cover(self, size=1200):
        buffer = io.BytesIO()
        Image.new("RGB", (size, size), "red").save(buffer, "JPEG")
        return buffer.getvalue()

    def test_embed_cover_false_keeps_cover_jpg_only(self):
        cover = self.cover()
        result = convert_album([self.source], self.album, self.root, "wav", cover_data=cover, embed_cover=False)
        self.assertFalse(result.failures)
        tagged = WAVE(result.converted_files[0])
        self.assertFalse(tagged.tags.getall("APIC"))
        self.assertEqual((result.output_directory / "cover.jpg").read_bytes(), cover)

    def test_embed_max_size_shrinks_only_embedded_image(self):
        cover = self.cover(1200)
        result = convert_album([self.source], self.album, self.root, "wav", cover_data=cover, embed_max_size=500)
        self.assertFalse(result.failures)
        tagged = WAVE(result.converted_files[0])
        embedded = Image.open(io.BytesIO(tagged.tags.getall("APIC")[0].data))
        self.assertEqual(embedded.size, (500, 500))
        self.assertEqual((result.output_directory / "cover.jpg").read_bytes(), cover)

    def test_embed_max_size_keeps_small_cover_unchanged(self):
        cover = self.cover(600)
        result = convert_album([self.source], self.album, self.root, "wav", cover_data=cover, embed_max_size=1000)
        self.assertFalse(result.failures)
        tagged = WAVE(result.converted_files[0])
        self.assertEqual(tagged.tags.getall("APIC")[0].data, cover)

    def test_default_embedding_uses_original_bytes(self):
        cover = self.cover()
        result = convert_album([self.source], self.album, self.root, "wav", cover_data=cover)
        self.assertFalse(result.failures)
        tagged = WAVE(result.converted_files[0])
        self.assertEqual(tagged.tags.getall("APIC")[0].data, cover)

    def test_cancel_before_start_converts_nothing(self):
        import threading

        cancel = threading.Event()
        cancel.set()
        result = convert_album([self.source], self.album, self.root, "wav", cover_data=self.cover(), cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.converted_files)
        self.assertFalse((result.output_directory / "cover.jpg").exists())
        self.assertFalse(list(result.output_directory.glob(".disctag-*")))

    def test_cancel_between_tracks_keeps_finished_tracks(self):
        import threading

        from disctag import audio

        self.album.tracks.append(TrackMetadata("Second", "Artist", 2))
        second = self.root / "second.wav"
        write_wav(second)
        cancel = threading.Event()
        original = audio._convert_file

        def convert_then_cancel(*args):
            original(*args)
            cancel.set()

        with patch("disctag.audio._convert_file", side_effect=convert_then_cancel):
            result = convert_album([self.source, second], self.album, self.root, "wav", cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.converted_files), 1)
        self.assertFalse(result.failures)

    def test_cancel_kills_running_ffmpeg(self):
        import subprocess
        import threading
        from unittest.mock import Mock

        from disctag.audio import ConversionCancelled, _convert_file

        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("ffmpeg", 0.2), 0]
        process.poll.return_value = None
        cancel = threading.Event()
        cancel.set()
        with patch("disctag.audio.subprocess.Popen", return_value=process):
            with self.assertRaises(ConversionCancelled):
                _convert_file("ffmpeg", self.source, self.root / "out.flac", "flac", "320 kbps", cancel)
        process.kill.assert_called_once()

    def test_ffmpeg_error_message_is_reported(self):
        from unittest.mock import Mock

        from disctag.audio import _convert_file

        def fake_popen(command, stderr, **kwargs):
            stderr.write(b"first line\nInvalid data found\n")
            return Mock(wait=Mock(return_value=1), poll=Mock(return_value=1))

        with patch("disctag.audio.subprocess.Popen", side_effect=fake_popen):
            with self.assertRaisesRegex(AudioError, "Invalid data found"):
                _convert_file("ffmpeg", self.source, self.root / "out.flac", "flac", "320 kbps")

    def test_cover_not_written_when_every_track_fails(self):
        with patch("disctag.audio._tag_wave", side_effect=OSError("tag failed")):
            result = convert_album([self.source], self.album, self.root, "wav", cover_data=self.cover())
        self.assertEqual(len(result.failures), 1)
        self.assertFalse((result.output_directory / "cover.jpg").exists())

    def test_cover_write_failure_keeps_album_result(self):
        real_replace = os.replace

        def replace(src, dst):
            if Path(dst).name == "cover.jpg":
                raise PermissionError("cover locked")
            return real_replace(src, dst)

        with patch("disctag.audio.os.replace", side_effect=replace):
            result = convert_album([self.source], self.album, self.root, "wav", cover_data=self.cover())
        self.assertEqual(result.failures, [])
        self.assertEqual(len(result.converted_files), 1)
        self.assertTrue(result.converted_files[0].is_file())
        self.assertIn("cover locked", result.cover_error)
        self.assertFalse((result.output_directory / "cover.jpg").exists())

    def test_tag_failure_preserves_existing_output(self):
        target = output_path(output_directory(self.root, self.album), self.album.tracks[0], "wav")
        write_wav(target, b"\x02\x00")
        original = target.read_bytes()
        with patch("disctag.audio._tag_wave", side_effect=OSError("tag failed")):
            result = convert_album([self.source], self.album, self.root, "wav")
        self.assertEqual(len(result.failures), 1)
        self.assertFalse(result.converted_files)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(list(target.parent.glob(".disctag-*")))

    def test_old_temporary_filename_is_safe_as_input(self):
        source = output_directory(self.root, self.album) / ".01 - Song.tmp.wav"
        write_wav(source)
        original = source.read_bytes()
        result = convert_album([source], self.album, self.root, "wav")
        self.assertFalse(result.failures)
        self.assertEqual(source.read_bytes(), original)

    def test_multi_disc_track_totals_are_per_disc(self):
        album = AlbumMetadata(
            "Album", "Artist", "Artist",
            tracks=[
                TrackMetadata("A1", "Artist", 1, disc_number=1, disc_count=2),
                TrackMetadata("A2", "Artist", 2, disc_number=1, disc_count=2),
                TrackMetadata("B1", "Artist", 1, disc_number=2, disc_count=2),
                TrackMetadata("B2", "Artist", 2, disc_number=2, disc_count=2),
            ],
        )
        sources = [self.root / name for name in ("a1.wav", "a2.wav", "b1.wav", "b2.wav")]
        for index, path in enumerate(sources):
            write_wav(path, bytes([index + 1, 0]))
        result = convert_album(sources, album, self.root, "wav")
        self.assertFalse(result.failures)
        tagged = [WAVE(path) for path in result.converted_files]
        self.assertEqual([str(audio["TRCK"]) for audio in tagged], ["1/2", "2/2", "1/2", "2/2"])
        self.assertEqual([str(audio["TPOS"]) for audio in tagged], ["1/2", "1/2", "2/2", "2/2"])

    def test_flac_and_mp3_conversion(self):
        try:
            find_ffmpeg()
        except AudioError:
            self.skipTest("FFmpeg is not installed")
        for format_name, reader in (("flac", FLAC), ("mp3", MP3)):
            with self.subTest(format=format_name):
                result = convert_album([self.source], self.album, self.root, format_name)
                self.assertFalse(result.failures)
                audio = reader(result.converted_files[0])
                title = audio["title"][0] if format_name == "flac" else str(audio["TIT2"])
                self.assertEqual(title, "Song")
                self.assertGreater(audio.info.length, 0)

    def test_float_wav_duration_falls_back_to_mutagen(self):
        import struct

        path = self.root / "float.wav"
        frames = b"\x00\x00\x00\x00" * 44100
        fmt = struct.pack("<HHIIHH", 3, 1, 44100, 176400, 4, 32)
        data = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(frames)) + frames
        path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(data)) + b"WAVE" + data)
        from disctag.audio import wav_duration

        self.assertAlmostEqual(wav_duration(path), 1.0, places=2)


def write_image_wav(path, fmt_tag, bits, frames, extensible=False, channels=2, rate=44100):
    """A WAV disc image with an odd-sized LIST chunk before the data, to exercise the RIFF parser."""
    import struct

    block_align = channels * bits // 8
    if extensible:
        sub_format = struct.pack("<IHH8s", fmt_tag, 0, 0x0010, b"\x80\x00\x00\xaa\x008\x9bq")
        fmt = struct.pack("<HHIIHHHHI16s", 0xFFFE, channels, rate, rate * block_align, block_align, bits, 22, bits, 3,
                          sub_format)
    else:
        fmt = struct.pack("<HHIIHH", fmt_tag, channels, rate, rate * block_align, block_align, bits)
    pcm = random.Random(bits).randbytes(frames * block_align)
    body = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"LIST" + struct.pack("<I", 5) + b"INFOx\x00"
            + b"data" + struct.pack("<I", len(pcm)) + pcm)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)
    return pcm, block_align


def data_chunk(path):
    import struct

    raw = path.read_bytes()
    position = 12
    while position + 8 <= len(raw):
        chunk_id, size = struct.unpack("<4sI", raw[position:position + 8])
        if chunk_id == b"data":
            return raw[position + 8:position + 8 + size]
        position += 8 + size + (size & 1)
    raise AssertionError("no data chunk")


CUE_TEXT = """PERFORMER "Disc Artist"
TITLE "Disc"
FILE "{0}" WAVE
  TRACK 01 AUDIO
    TITLE "One"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Two"
    INDEX 00 00:00:70
    INDEX 01 00:01:00
  TRACK 03 AUDIO
    TITLE "Three"
    INDEX 01 00:02:00
"""


class CueImageTests(unittest.TestCase):
    # 3.5 秒整轨：第 1 轨 0–1 秒，第 2 轨 1–2 秒，第 3 轨 2 秒到结尾。
    FRAMES = 44100 * 7 // 2

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.album = AlbumMetadata("Album", "Artist", "Artist", tracks=[
            TrackMetadata(title, "Artist", number, 3) for number, title in enumerate(("One", "Two", "Three"), 1)
        ])

    def image(self, name="image.wav", fmt_tag=1, bits=16, extensible=False, folder="rip"):
        from disctag.cue import cue_sources, parse_cue

        image = self.root / folder / name
        pcm, block_align = write_image_wav(image, fmt_tag, bits, self.FRAMES, extensible)
        cue = image.with_suffix(".cue")
        cue.write_text(CUE_TEXT.format(name), encoding="utf-8")
        return image, cue, cue_sources(parse_cue(cue), cue), pcm, block_align

    def test_wav_image_segments_are_sample_exact(self):
        for fmt_tag, bits, extensible in ((1, 16, False), (1, 24, False), (3, 32, True)):
            with self.subTest(bits=bits, extensible=extensible):
                image, cue, sources, pcm, block_align = self.image(folder=f"rip{bits}", fmt_tag=fmt_tag, bits=bits,
                                                                   extensible=extensible)
                original = image.read_bytes(), cue.read_bytes()
                output = self.root / f"out{bits}"
                with patch("disctag.audio.find_ffmpeg", side_effect=AssertionError("ffmpeg not needed")):
                    result = convert_album(sources, self.album, output, "wav")
                self.assertFalse(result.failures)
                bounds = [(0, 44100), (44100, 88200), (88200, self.FRAMES)]
                for path, (start, end), title in zip(result.converted_files, bounds, ("One", "Two", "Three"),
                                                     strict=True):
                    self.assertEqual(data_chunk(path), pcm[start * block_align:end * block_align])
                    self.assertEqual(str(WAVE(path)["TIT2"]), title)
                    with open(path, "rb") as written, open(image, "rb") as source:
                        # fmt 块原样复制（含 WAVE_FORMAT_EXTENSIBLE 扩展字段）。
                        self.assertEqual(written.read(12)[:4], b"RIFF")
                        self.assertEqual(written.read(8 + (40 if extensible else 16))[8:],
                                         source.read(20 + (40 if extensible else 16))[20:])
                self.assertEqual((image.read_bytes(), cue.read_bytes()), original)

    def test_image_cannot_be_overwritten(self):
        directory = output_directory(self.root, self.album)
        target = output_path(directory, self.album.tracks[0], "wav")
        from disctag.cue import cue_sources, parse_cue

        write_image_wav(target, 1, 16, self.FRAMES)
        cue = directory / "disc.cue"
        cue.write_text(CUE_TEXT.format(target.name), encoding="utf-8")
        original = target.read_bytes()
        with self.assertRaisesRegex(AudioError, "源 WAV"):
            convert_album(cue_sources(parse_cue(cue), cue), self.album, self.root, "wav")
        self.assertEqual(target.read_bytes(), original)

    def test_source_duration_and_audio_info(self):
        from disctag.audio import audio_info, source_duration

        image, _cue, sources, _pcm, _ = self.image()
        self.assertEqual(audio_info(image), (44100, 16, 3.5))
        self.assertEqual([source_duration(source) for source in sources], [1.0, 1.0, 1.5])
        self.assertIsNone(source_duration(SourceTrack(self.root / "missing.wav", 0, None, 1, Path("x.cue"))))

    def test_compressed_image_segments_go_through_ffmpeg(self):
        from disctag import audio

        source = SourceTrack(self.root / "image.ape", 75, 150, 2, self.root / "image.cue")
        last = SourceTrack(self.root / "image.ape", 150, None, 3, self.root / "image.cue")
        with patch("disctag.audio.audio_info", return_value=(44100, 24, 10.0)), \
                patch("disctag.audio._run_ffmpeg") as run:
            audio.extract_wav_segment(source, self.root / "a.wav", "ffmpeg")
            audio._convert_file("ffmpeg", last, self.root / "b.flac", "flac", "V0")
        wav_command, flac_command = (call.args[0] for call in run.call_args_list)
        self.assertEqual(wav_command[wav_command.index("-af") + 1], "atrim=start_sample=44100:end_sample=88200,asetpts=PTS-STARTPTS")
        self.assertEqual(wav_command[wav_command.index("-c:a") + 1], "pcm_s24le")
        self.assertEqual(flac_command[flac_command.index("-vn") + 1:flac_command.index("-vn") + 3],
                         ["-af", "atrim=start_sample=88200,asetpts=PTS-STARTPTS"])
        self.assertEqual(flac_command[flac_command.index("-c:a") + 1], "flac")

    def test_compressed_image_to_wav_requires_ffmpeg(self):
        source = SourceTrack(self.root / "image.flac", 0, 75, 1, self.root / "image.cue")
        album = AlbumMetadata("Album", "Artist", "Artist", tracks=[TrackMetadata("One", "Artist", 1)])
        with patch("disctag.audio.find_ffmpeg", side_effect=AudioError("no ffmpeg")):
            with self.assertRaisesRegex(AudioError, "no ffmpeg"):
                convert_album([source], album, self.root / "out", "wav")

    def test_plain_file_conversion_command_is_unchanged(self):
        from disctag import audio

        with patch("disctag.audio._run_ffmpeg") as run:
            audio._convert_file("ffmpeg", self.root / "a.wav", self.root / "a.flac", "flac", "V0")
        self.assertEqual(run.call_args.args[0], [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(self.root / "a.wav"),
            "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-c:a", "flac", "-compression_level", "5",
            str(self.root / "a.flac"),
        ])
