import tempfile
import unittest
from pathlib import Path

from disctag.cue import CueError, cue_sources, cue_toc, is_image_cue, parse_cue, read_cue_text
from disctag.sources import SourceTrack

IMAGE_CUE = """REM GENRE "J-Pop"
REM DATE 2001
REM COMMENT "ExactAudioCopy v1.6"
CATALOG 4988001234567
PERFORMER "Disc Artist"
TITLE "Disc Title"
FILE "image.wav" WAVE
  TRACK 01 AUDIO
    TITLE "First"
    ISRC JPXX00000001
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second"
    PERFORMER "Guest"
    FLAGS DCP
    INDEX 00 02:58:00
    INDEX 01 03:00:00
  TRACK 03 AUDIO
    TITLE Third
    PREGAP 00:02:00
    INDEX 01 06:40:00
"""


class CueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, text, name="disc.cue", encoding="utf-8", files=("image.wav",)):
        for file_name in files:
            (self.root / file_name).write_bytes(b"")
        path = self.root / name
        path.write_bytes(text.encode(encoding))
        return path

    def test_encodings(self):
        text = 'TITLE "{0}"\nFILE "image.wav" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n'
        cases = [
            ("utf-8-sig", "中文专辑"),
            ("utf-8", "中文专辑 ünïcode"),
            ("gbk", "中文专辑：夜曲"),
            ("shift_jis", "ひらがなとカタカナの歌"),
            ("utf-16", "中文专辑"),
            ("big5", "周杰倫 范特西 愛在西元前"),
            ("big5", "陳奕迅 十年 與你們分享"),
        ]
        for encoding, title in cases:
            with self.subTest(encoding=encoding):
                path = self.write(text.format(title), encoding=encoding)
                self.assertEqual(parse_cue(path).title, title)
                self.assertNotIn("\ufeff", read_cue_text(path))

    def test_disc_and_track_fields(self):
        sheet = parse_cue(self.write(IMAGE_CUE))
        self.assertEqual((sheet.title, sheet.performer, sheet.date, sheet.genre),
                         ("Disc Title", "Disc Artist", "2001", "J-Pop"))
        self.assertEqual([entry.title for entry in sheet.tracks], ["First", "Second", "Third"])
        self.assertEqual([entry.performer for entry in sheet.tracks], ["Disc Artist", "Guest", "Disc Artist"])
        self.assertEqual([entry.index01 for entry in sheet.tracks], [0, 13500, 30000])
        self.assertEqual(sheet.tracks[1].index00, 13350)
        self.assertIsNone(sheet.tracks[0].index00)

    def test_segments_keep_gap_with_previous_track(self):
        cue = self.write(IMAGE_CUE)
        sources = cue_sources(parse_cue(cue), cue)
        self.assertEqual([(s.start_frame, s.end_frame) for s in sources], [(0, 13500), (13500, 30000), (30000, None)])
        self.assertEqual([s.number for s in sources], [1, 2, 3])
        self.assertTrue(all(s.is_segment and s.cue == cue for s in sources))
        self.assertEqual(sources[1].name, "image.wav [02]")
        self.assertEqual(sources[1].performer, "Guest")
        self.assertTrue(is_image_cue(parse_cue(cue)))

    def test_hidden_track_audio_is_skipped(self):
        cue = self.write('FILE "image.wav" WAVE\n TRACK 01 AUDIO\n  INDEX 00 00:00:00\n  INDEX 01 00:30:00\n'
                         ' TRACK 02 AUDIO\n  INDEX 01 01:00:00\n')
        sources = cue_sources(parse_cue(cue), cue)
        self.assertEqual(sources[0].start_frame, 2250)

    def test_multiple_files_and_non_audio_tracks(self):
        cue = self.write(
            'FILE "a.flac" WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\n TRACK 02 AUDIO\n  INDEX 01 01:00:00\n'
            'FILE "b.wav" WAVE\n TRACK 03 AUDIO\n  INDEX 00 00:00:00\n  INDEX 01 00:02:00\n'
            'FILE "data.bin" BINARY\n TRACK 04 MODE1/2352\n  TITLE "Data"\n  INDEX 01 00:00:00\n',
            files=("a.flac", "b.wav"),
        )
        sheet = parse_cue(cue)
        sources = cue_sources(sheet, cue)
        self.assertEqual([s.number for s in sources], [1, 2, 3])
        self.assertEqual([s.path.name for s in sources], ["a.flac", "a.flac", "b.wav"])
        self.assertEqual([(s.start_frame, s.end_frame) for s in sources], [(0, 4500), (4500, None), (150, None)])
        self.assertTrue(is_image_cue(sheet))
        self.assertIsNone(cue_toc(sources, 99999))

    def test_per_track_cue_is_not_an_image(self):
        cue = self.write('FILE "01.wav" WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\n'
                         'FILE "02.wav" WAVE\n TRACK 02 AUDIO\n  INDEX 01 00:00:00\n', files=("01.wav", "02.wav"))
        sheet = parse_cue(cue)
        self.assertFalse(is_image_cue(sheet))
        self.assertEqual([s.end_frame for s in cue_sources(sheet, cue)], [None, None])

    def test_file_resolution(self):
        text = 'FILE "{0}" WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\n'
        cases = [("IMAGE.WAV", "image.wav"), ("image.wav", "image.FLAC"), ("C:\\rips\\image.wav", "image.ape")]
        for index, (referenced, actual) in enumerate(cases):
            with self.subTest(referenced=referenced):
                folder = self.root / str(index)
                folder.mkdir()
                (folder / actual).write_bytes(b"")
                cue = folder / "disc.cue"
                cue.write_text(text.format(referenced), encoding="utf-8")
                self.assertEqual(parse_cue(cue).tracks[0].file.name, actual)
        missing = self.root / "missing.cue"
        missing.write_text(text.format("nothere.wav"), encoding="utf-8")
        with self.assertRaisesRegex(CueError, "nothere.wav"):
            parse_cue(missing)

    def test_unquoted_file_name_with_spaces(self):
        cue = self.write("FILE my image.wav WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\n", files=("my image.wav",))
        self.assertEqual(parse_cue(cue).tracks[0].file.name, "my image.wav")

    def test_errors(self):
        cases = {
            "no audio": 'FILE "image.wav" BINARY\n TRACK 01 MODE1/2352\n  INDEX 01 00:00:00\n',
            "no index 01": 'FILE "image.wav" WAVE\n TRACK 01 AUDIO\n  INDEX 00 00:00:00\n',
            "bad time": 'FILE "image.wav" WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:61:00\n',
            "bad frames": 'FILE "image.wav" WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:00:75\n',
            "garbage time": 'FILE "image.wav" WAVE\n TRACK 01 AUDIO\n  INDEX 01 abc\n',
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(CueError):
                parse_cue(self.write(text))

    def test_cue_toc(self):
        cue = self.write(IMAGE_CUE)
        sources = cue_sources(parse_cue(cue), cue)
        # 偏移 = INDEX 01 + 150；引导区之后的 leadout = 整轨总帧数 + 150。
        self.assertEqual(cue_toc(sources, 45000), "1+3+45150+150+13650+30150")
        self.assertIsNone(cue_toc([SourceTrack(self.root / "a.wav")], 45000))
        self.assertIsNone(cue_toc(sources, None))
        self.assertIsNone(cue_toc(sources, 30000))


if __name__ == "__main__":
    unittest.main()
