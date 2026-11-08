import unittest
from pathlib import Path

from disctag.editing import (
    EditError,
    album_info_text,
    can_insert,
    delete_manual_track,
    duration_mismatch,
    fill_missing_by_duration,
    insert_manual_track,
    manual_tracks,
    match_status,
    track_label,
)
from disctag.models import AlbumMetadata, TrackMetadata


def album(*tracks, collection_id=None):
    return AlbumMetadata("Album", "Artist", "Artist", collection_id=collection_id, tracks=list(tracks))


def track(title="T", duration_ms=0, **kwargs):
    return TrackMetadata(title, "Artist", kwargs.pop("track_number", 1), duration_ms=duration_ms, **kwargs)


class ManualTracksTests(unittest.TestCase):
    def test_builds_manual_tracks(self):
        tracks = manual_tracks([Path("01 - First.wav"), Path("02 - Second.wav")], "Singer")
        self.assertEqual([t.title for t in tracks], ["First", "Second"])
        self.assertEqual([(t.track_number, t.track_count, t.origin) for t in tracks],
                         [(1, 2, "manual"), (2, 2, "manual")])
        self.assertEqual([t.artist for t in tracks], ["Singer", "Singer"])


class CanInsertTests(unittest.TestCase):
    def test_truth_table(self):
        online = album(track(), collection_id=5)
        manual = album(track())
        self.assertFalse(can_insert(None, 3))
        self.assertFalse(can_insert(manual, 3))
        self.assertFalse(can_insert(online, 1))
        self.assertTrue(can_insert(online, 2))


class FillMissingTests(unittest.TestCase):
    def test_fills_gap_and_renumbers(self):
        first, second = track("One", 60000), track("Two", 120000)
        record = album(first, second, collection_id=5)
        missing = fill_missing_by_duration(record, [60000, 999000, 120000], "Singer")
        self.assertEqual(missing, [2])
        self.assertEqual(len(record.tracks), 3)
        placeholder = record.tracks[1]
        self.assertEqual((placeholder.title, placeholder.artist, placeholder.origin), ("待确认曲目 02", "Singer", "auto-manual"))
        self.assertEqual([t.track_number for t in record.tracks], [1, 2, 3])
        self.assertEqual((record.tracks[0].title, record.tracks[0].duration_ms), ("One", 60000))
        self.assertEqual((record.tracks[2].title, record.tracks[2].duration_ms), ("Two", 120000))

    def test_multi_disc_is_rejected(self):
        record = album(track(disc_count=2), track(disc_number=2, disc_count=2), collection_id=5)
        original = list(record.tracks)
        with self.assertRaises(EditError):
            fill_missing_by_duration(record, [1, 2, 3], "Singer")
        self.assertEqual(record.tracks, original)

    def test_unalignable_durations_are_rejected(self):
        record = album(track(duration_ms=60000), track(duration_ms=120000), collection_id=5)
        original = list(record.tracks)
        with self.assertRaises(EditError):
            fill_missing_by_duration(record, [5000, 6000, 7000], "Singer")
        self.assertEqual(record.tracks, original)


class InsertTests(unittest.TestCase):
    def test_middle_insert_renumbers(self):
        record = album(track("One"), track("Two"), collection_id=5)
        self.assertTrue(insert_manual_track(record, 3, 2, " Bonus ", "Guest"))
        self.assertEqual([(t.title, t.track_number, t.track_count) for t in record.tracks],
                         [("One", 1, 3), ("Bonus", 2, 3), ("Two", 3, 3)])
        self.assertEqual(record.tracks[1].origin, "manual")
        self.assertEqual(record.tracks[1].artist, "Guest")

    def test_invalid_insertions_return_false(self):
        record = album(track(), collection_id=5)
        self.assertFalse(insert_manual_track(record, 2, 1, "  ", "A"))
        self.assertFalse(insert_manual_track(record, 1, 1, "Song", "A"))
        self.assertFalse(insert_manual_track(record, 2, 3, "Song", "A"))
        self.assertEqual(len(record.tracks), 1)


class DeleteTests(unittest.TestCase):
    def test_only_manual_origins_are_removed(self):
        online, manual, auto = track("A"), track("B", origin="manual"), track("C", origin="auto-manual")
        record = album(online, manual, auto)
        self.assertFalse(delete_manual_track(record, 0))
        self.assertFalse(delete_manual_track(record, 9))
        self.assertTrue(delete_manual_track(record, 1))
        self.assertEqual([t.title for t in record.tracks], ["A", "C"])
        self.assertTrue(delete_manual_track(record, 1))
        self.assertEqual([t.title for t in record.tracks], ["A"])


class LabelTests(unittest.TestCase):
    def test_track_label(self):
        self.assertEqual(track_label(None, 4), "05")
        self.assertEqual(track_label(track(track_number=2), 0), "02")
        self.assertEqual(track_label(track(track_number=3, disc_number=2, disc_count=2), 0), "2-03")

    def test_duration_mismatch_threshold(self):
        target = track(duration_ms=60000)
        self.assertFalse(duration_mismatch(70.0, target))
        self.assertTrue(duration_mismatch(70.001, target))
        self.assertFalse(duration_mismatch(None, target))
        self.assertFalse(duration_mismatch(70.001, track(duration_ms=0)))
        self.assertFalse(duration_mismatch(70.001, None))


class InfoTests(unittest.TestCase):
    def test_album_info_text(self):
        record = album(track(), track(origin="manual"), collection_id=5)
        record.genre, record.release_date = "Rock", "2020"
        self.assertEqual(album_info_text(record, "US"), "US · 2 首（1 首 iTunes + 1 首手动） · Rock · 2020")
        self.assertEqual(album_info_text(record, ""), "手动模式 · 2 首（1 首 iTunes + 1 首手动） · Rock · 2020")
        plain = album(track())
        self.assertEqual(album_info_text(plain, ""), "手动模式 · 1 首 · 未分类 · 日期未知")

    def test_match_status_branches(self):
        record = album(track(), track())
        self.assertEqual(match_status(0, None, 0), "先导入 WAV 文件")
        self.assertEqual(match_status(2, None, 0), "已导入 2 首 · 尚未匹配专辑")
        self.assertEqual(match_status(4, record, 0), "本地多 2 首 · 请对照实体 CD，使用时长匹配或插入缺曲")
        self.assertEqual(match_status(1, record, 0), "本地少 1 首 · 请核对实体 CD 版本或重新匹配")
        self.assertEqual(match_status(2, record, 1), "2 首已对应 · 双击编辑 / 上下移动 · 橙行时长不同")
        self.assertEqual(match_status(2, record, 0), "2 首已对应 · 双击编辑 / 上下移动")
