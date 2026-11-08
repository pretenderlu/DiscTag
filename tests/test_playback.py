import unittest
from itertools import count
from pathlib import Path
from unittest.mock import Mock, patch

from disctag.playback import AudioPreview


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
