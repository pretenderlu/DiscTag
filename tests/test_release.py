import re
import unittest
from pathlib import Path

from disctag import __version__

PROJECT = Path(__file__).resolve().parent.parent


class ReleaseConsistencyTests(unittest.TestCase):
    def test_readme_mentions_current_version(self):
        readme = (PROJECT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"当前版本：**v{__version__}**", readme)
        self.assertIn(f"DiscTagSetup-v{__version__}.exe", readme)
        self.assertEqual(set(re.findall(r"DiscTagSetup-v([\d.]+)\.exe", readme)), {__version__})

    def test_license_notices_are_present(self):
        self.assertTrue((PROJECT / "LICENSE").is_file())
        self.assertTrue((PROJECT / "THIRD_PARTY_NOTICES.md").is_file())
        for name in ("LGPL-2.1.txt", "GPL-2.0.txt"):
            self.assertTrue((PROJECT / "licenses" / name).is_file(), name)

    def test_notices_match_pinned_ffmpeg(self):
        script = (PROJECT / "scripts" / "build_ffmpeg.sh").read_text(encoding="utf-8")
        version = re.search(r"^FFMPEG_VERSION=(\S+)", script, re.M).group(1)
        notices = (PROJECT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn(f"FFmpeg {version}", notices)
        self.assertIn(f"ffmpeg-{version}.tar.xz", notices)


if __name__ == "__main__":
    unittest.main()
