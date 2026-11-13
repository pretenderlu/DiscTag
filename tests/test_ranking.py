import unittest

from disctag.models import AlbumMetadata, AlbumSummary, TrackMetadata
from disctag.ranking import (
    ALIGNED,
    EXACT,
    MISMATCH,
    DurationFit,
    candidates_to_verify,
    duration_fit,
    rank_results,
    result_key,
    verify_candidates,
)


def tracks(*seconds):
    return [TrackMetadata(f"T{i}", "A", i, duration_ms=int(s * 1000)) for i, s in enumerate(seconds, 1)]


def ms(*seconds):
    return [s * 1000 for s in seconds]


class DurationFitTests(unittest.TestCase):
    def test_exact_within_tolerance(self):
        fit = duration_fit(ms(200, 180), tracks(201, 178))
        self.assertEqual(fit.kind, EXACT)
        self.assertAlmostEqual(fit.mean_difference_ms, 1500)
        self.assertEqual(fit.marker, "✓")

    def test_same_count_but_different_durations(self):
        self.assertEqual(duration_fit(ms(200, 180), tracks(200, 240)).kind, MISMATCH)

    def test_local_extra_track_aligns(self):
        fit = duration_fit(ms(200, 95, 180), tracks(200, 180))
        self.assertEqual(fit.kind, ALIGNED)
        self.assertEqual(fit.marker, "≈")

    def test_online_has_more_tracks(self):
        self.assertEqual(duration_fit(ms(200), tracks(200, 180)).kind, MISMATCH)

    def test_missing_durations_return_none(self):
        self.assertIsNone(duration_fit([200000, None], tracks(200, 180)))
        self.assertIsNone(duration_fit(ms(200, 180), tracks(200, 0)))
        self.assertIsNone(duration_fit([], tracks(200)))


class RankingTests(unittest.TestCase):
    def summary(self, collection_id, track_count=0, country="US"):
        return AlbumSummary(collection_id, f"Album {collection_id}", "A", track_count=track_count, country=country)

    def test_rank_order(self):
        results = [self.summary(1, 12), self.summary(2, 10), self.summary(3, 10), self.summary(4, 9), self.summary(5, 10)]
        fits = {
            result_key(results[2]): DurationFit(EXACT, 900),
            result_key(results[3]): DurationFit(ALIGNED, 100),
            result_key(results[4]): DurationFit(EXACT, 200),
            result_key(results[1]): DurationFit(MISMATCH),
        }
        ranked = rank_results(results, fits, 10)
        self.assertEqual([entry.collection_id for entry in ranked], [3, 5, 4, 1, 2])

    def test_unverified_same_count_beats_other_counts(self):
        results = [self.summary(1, 12), self.summary(2, 10)]
        self.assertEqual([e.collection_id for e in rank_results(results, {}, 10)], [2, 1])

    def test_candidates_skip_albums_with_more_tracks(self):
        results = [self.summary(1, 12), self.summary(2, 10), self.summary(3, 0), self.summary(4, 8)]
        self.assertEqual([e.collection_id for e in candidates_to_verify(results, 10, limit=2)], [2, 3])

    def test_verify_skips_failures(self):
        good, bad = self.summary(1, 2), self.summary(2, 2, "JP")

        def load(entry):
            if entry is bad:
                raise RuntimeError("down")
            return AlbumMetadata("Album", "A", "A", collection_id=1, tracks=tracks(200, 180))

        fits, albums = verify_candidates([good, bad], ms(200, 180), load)
        self.assertEqual(fits[result_key(good)].kind, EXACT)
        self.assertNotIn(result_key(bad), albums)


if __name__ == "__main__":
    unittest.main()
