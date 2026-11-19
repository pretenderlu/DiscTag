import tempfile
import unittest
from itertools import count
from pathlib import Path
from unittest.mock import Mock, patch

from disctag.playback import AudioPreview, _estimated_duration
from disctag.sources import SourceTrack


class PlaybackTests(unittest.TestCase):
    def test_poll_chain_does_not_stack(self):
        root = Mock()
        root.after.side_effect = (f"id{index}" for index in count(1))
        on_change = Mock()
        process = Mock()
        process.poll.return_value = None
        with patch("disctag.playback.sys.platform", "darwin"), \
                patch("disctag.playback.subprocess.Popen", return_value=process), \
                patch("disctag.playback.wav_duration", return_value=10.0):
            preview = AudioPreview(root, on_change)
            path_a, path_b = Path("a.wav"), Path("b.wav")
            preview.play(path_a)
            preview.play(path_b)
            root.after_cancel.assert_called_once_with("id1")
            preview.stop()
            self.assertEqual([call.args[0] for call in root.after_cancel.call_args_list], ["id1", "id2"])
            self.assertEqual(on_change.call_args_list[-1].args, (False, SourceTrack(path_b)))

    def test_unreadable_header_falls_back_to_cd_byte_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.wav"
            path.write_bytes(bytes(44 + 176400 * 2))
            empty = Path(directory) / "empty.wav"
            empty.write_bytes(b"")
            self.assertAlmostEqual(_estimated_duration(path), 2.0)
            self.assertEqual(_estimated_duration(empty), 0.0)
            self.assertEqual(_estimated_duration(Path(directory) / "missing.wav"), 0.0)
            root = Mock()
            with (
                patch("disctag.playback.sys.platform", "darwin"),
                patch("disctag.playback.subprocess.Popen", return_value=Mock()),
                patch("disctag.playback.wav_duration", return_value=None),
            ):
                preview = AudioPreview(root, Mock())
                preview.play(path)
                self.assertAlmostEqual(preview.duration, 2.0)

    def test_windows_poll_finishes_with_estimated_duration(self):
        root = Mock()
        on_change = Mock()
        preview = AudioPreview(root, on_change)
        preview.path = Path("broken.wav")
        preview.duration = 2.0
        with (
            patch("disctag.playback.sys.platform", "win32"),
            patch("disctag.playback.time.monotonic", return_value=preview.started + 3.0),
            patch.dict("sys.modules", {"winsound": Mock()}),
        ):
            preview._poll()
        self.assertFalse(preview.playing)
        on_change.assert_called_once_with(False, Path("broken.wav"))

    def test_segment_preview_extracts_to_temp_and_cleans_up(self):
        import wave

        from disctag import playback

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.wav"
            with wave.open(str(image), "wb") as audio:
                audio.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
                audio.writeframes(bytes(range(256)) * 2756)
            first = SourceTrack(image, 0, 75, 1, Path(directory) / "image.cue")
            second = SourceTrack(image, 75, 150, 2, Path(directory) / "image.cue")
            preview_root = Path(directory) / "preview"
            sound = Mock(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4, SND_PURGE=8)
            root = Mock()
            on_change = Mock()
            with (
                patch("disctag.playback.sys.platform", "win32"),
                patch("disctag.playback.preview_directory", return_value=preview_root),
                patch.dict("sys.modules", {"winsound": sound}),
            ):
                preview = AudioPreview(root, on_change)
                preview.play(first)
                played = Path(sound.PlaySound.call_args.args[0])
                self.assertEqual(played.parent, preview_root)
                self.assertTrue(played.is_file())
                with wave.open(str(played)) as audio:
                    self.assertEqual(audio.getnframes(), 44100)
                self.assertEqual(preview.path, first)
                self.assertAlmostEqual(preview.duration, 1.0)
                on_change.assert_called_with(True, first)

                preview.toggle(second)
                self.assertFalse(played.exists())
                second_file = Path(sound.PlaySound.call_args.args[0])
                self.assertNotEqual(second_file, played)
                preview.toggle(second)
                self.assertFalse(preview.playing)
                self.assertFalse(second_file.exists())
                sound.PlaySound.assert_called_with(None, sound.SND_PURGE)

                (preview_root / "left.wav").write_bytes(b"x")
                playback.cleanup_preview_files()
                self.assertEqual(list(preview_root.iterdir()), [])

    def test_segment_preview_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = SourceTrack(Path(directory) / "missing.wav", 0, 75, 1, Path(directory) / "x.cue")
            with (
                patch("disctag.playback.sys.platform", "darwin"),
                patch("disctag.playback.preview_directory", return_value=Path(directory) / "preview"),
                patch("disctag.playback.subprocess.Popen") as popen,
            ):
                preview = AudioPreview(Mock(), Mock())
                with self.assertRaisesRegex(RuntimeError, "missing.wav"):
                    preview.play(source)
                popen.assert_not_called()
                self.assertFalse(preview.playing)
                self.assertEqual(list((Path(directory) / "preview").iterdir()), [])
