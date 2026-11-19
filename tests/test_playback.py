import tempfile
import unittest
from itertools import count
from pathlib import Path
from unittest.mock import Mock, patch

from disctag.playback import AudioPreview, _estimated_duration


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
            self.assertEqual(on_change.call_args_list[-1].args, (False, path_b))

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
