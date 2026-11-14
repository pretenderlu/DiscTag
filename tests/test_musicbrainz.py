import unittest
from unittest.mock import Mock, patch

from disctag.musicbrainz import MusicBrainzClient, MusicBrainzError, _escape, toc_from_durations


def release(**extra):
    return {
        "id": "rel-1",
        "title": "Album",
        "date": "1999-05-01",
        "country": "JP",
        "artist-credit": [{"name": "A", "joinphrase": " & "}, {"name": "B"}],
        "release-group": {"id": "rg-1", "genres": [{"name": "art rock", "count": 3}, {"name": "pop", "count": 1}]},
        "cover-art-archive": {"front": True},
        "media": [
            {"position": 1, "format": "CD", "track-count": 2, "tracks": [
                {"position": 1, "title": "One", "length": 200000, "artist-credit": [{"name": "A"}]},
                {"position": 2, "title": "Two", "length": 180000},
            ]},
            {"position": 2, "format": "CD", "track-count": 1, "tracks": [
                {"position": 1, "title": "Three", "length": 100000},
            ]},
            {"position": 3, "format": "DVD-Video", "track-count": 1, "tracks": [
                {"position": 1, "title": "Video", "length": 1000},
            ]},
        ],
        **extra,
    }


class TocTests(unittest.TestCase):
    def test_toc_from_durations(self):
        self.assertEqual(toc_from_durations([2.0, 3.0]), "1+2+525+150+300")

    def test_toc_requires_all_durations(self):
        self.assertIsNone(toc_from_durations([2.0, None]))
        self.assertIsNone(toc_from_durations([]))

    def test_escape(self):
        self.assertEqual(_escape('AC/DC: "Live"'), 'AC\\/DC\\: \\"Live\\"')


class ClientTests(unittest.TestCase):
    def client(self, payload):
        client = MusicBrainzClient()
        client._get = Mock(return_value=payload)
        return client

    def test_get_album_all_cd_media(self):
        album = self.client(release()).get_album("rel-1")
        self.assertEqual([t.title for t in album.tracks], ["One", "Two", "Three"])
        self.assertEqual([(t.disc_number, t.disc_count) for t in album.tracks], [(1, 2), (1, 2), (2, 2)])
        self.assertEqual(album.artist, "A & B")
        self.assertEqual(album.tracks[1].artist, "A & B")
        self.assertEqual(album.genre, "Art Rock")
        self.assertEqual(album.source, "musicbrainz")
        self.assertEqual(album.artwork_url, "https://coverartarchive.org/release/rel-1/front")

    def test_get_album_single_medium(self):
        album = self.client(release()).get_album("rel-1", medium=2)
        self.assertEqual([(t.title, t.disc_number, t.disc_count, t.track_count) for t in album.tracks], [("Three", 2, 2, 1)])

    def test_missing_medium(self):
        with self.assertRaises(MusicBrainzError):
            self.client(release()).get_album("rel-1", medium=5)

    def test_release_group_artwork_fallback(self):
        album = self.client(release(**{"cover-art-archive": {"front": False}})).get_album("rel-1")
        self.assertEqual(album.artwork_url, "https://coverartarchive.org/release-group/rg-1/front")

    def test_lookup_toc_points_at_matching_medium(self):
        payload = {"releases": [
            {"id": "box", "title": "Box", "media": [{"position": 1, "format": "CD", "track-count": 9},
                                                     {"position": 2, "format": "CD", "track-count": 2}]},
            {"id": "vinyl", "title": "LP", "media": [{"position": 1, "format": "12-inch Vinyl", "track-count": 2}]},
        ]}
        results = self.client(payload).lookup_toc("1+2+525+150+300")
        self.assertEqual([(r.collection_id, r.medium, r.track_count) for r in results], [("box", 2, 2)])
        self.assertIn("CD 2/2", results[0].detail)

    def test_search_skips_non_cd_releases(self):
        payload = {"releases": [
            {"id": "cd", "title": "Album", "media": [{"format": "CD", "track-count": 10}], "track-count": 10,
             "label-info": [{"catalog-number": "ABC-1"}], "date": "2001"},
            {"id": "lp", "title": "Album", "media": [{"format": "12-inch Vinyl", "track-count": 10}]},
        ]}
        results = self.client(payload).search_albums("Album")
        self.assertEqual([r.collection_id for r in results], ["cd"])
        self.assertEqual(results[0].detail, "2001 · ABC-1")

    def test_busy_server_is_retried(self):
        busy = Mock(status_code=503)
        ok = Mock(status_code=200)
        ok.json.return_value = {"releases": []}
        client = MusicBrainzClient()
        client._throttle = Mock()
        with patch("disctag.musicbrainz.requests.get", side_effect=[busy, ok]), patch("disctag.musicbrainz.time.sleep"):
            self.assertEqual(client._get("release/", {}), {"releases": []})

    def test_cover_prefers_thumbnail_for_small_sizes(self):
        client = MusicBrainzClient()
        with patch("disctag.musicbrainz.fetch_cover", return_value=b"jpg") as fetch:
            client.download_cover("https://coverartarchive.org/release/x/front", 600)
        self.assertEqual(fetch.call_args.args[0], "https://coverartarchive.org/release/x/front-1200")
        with patch("disctag.musicbrainz.fetch_cover", return_value=b"jpg") as fetch:
            client.download_cover("https://coverartarchive.org/release/x/front", 3000)
        self.assertEqual(fetch.call_args.args[0], "https://coverartarchive.org/release/x/front")


if __name__ == "__main__":
    unittest.main()
