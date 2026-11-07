import unittest

from disctag.matching import align_tracks_by_duration
from disctag.models import TrackMetadata


class MatchingTests(unittest.TestCase):
    def test_missing_tracks_are_marked_without_changing_metadata(self):
        tracks = [TrackMetadata("First", "Artist", 1, duration_ms=100000),
                  TrackMetadata("Last", "Artist", 2, duration_ms=300000)]
        aligned = align_tracks_by_duration([100000, 200000, 300000], tracks)
        self.assertEqual([track.title if track else None for track in aligned], ["First", None, "Last"])
        self.assertIsNot(aligned[0], tracks[0])
        self.assertEqual([track.track_number for track in tracks], [1, 2])
        self.assertIsNone(align_tracks_by_duration([100000, None, 300000], tracks))
