import io
import os
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
        os.link(self.source, target)
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
