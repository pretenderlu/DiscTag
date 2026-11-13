import unittest
from unittest.mock import Mock

from disctag.discogs import DiscogsClient, DiscogsError, _artist_names, _clean_artist


class DiscogsTests(unittest.TestCase):
    def parse(self, items):
        client = DiscogsClient()
        client._get = Mock(return_value={"title": "Album", "artists": [{"name": "Artist"}], "tracklist": items})
        return client.get_album(1, "")

    def track(self, title, position, duration="1:00"):
        return {"type_": "track", "title": title, "position": position, "duration": duration}

    def test_headings_are_not_audio_tracks(self):
        album = self.parse([
            {"type_": "heading", "title": "Suite", "position": ""},
            self.track("First", "1"), self.track("Second", "2"),
        ])
        self.assertEqual([t.title for t in album.tracks], ["First", "Second"])
        self.assertEqual([t.track_count for t in album.tracks], [2, 2])

    def test_index_with_distinct_tracks_is_expanded(self):
        album = self.parse([{"type_": "index", "title": "Suite", "artists": [{"name": "Soloist"}],
                             "sub_tracks": [self.track("First", "1"), self.track("Second", "2")]}])
        self.assertEqual([t.title for t in album.tracks], ["Suite (First)", "Suite (Second)"])
        self.assertEqual([t.artist for t in album.tracks], ["Soloist", "Soloist"])

    def test_subtracks_share_one_physical_track(self):
        album = self.parse([{"type_": "index", "title": "Medley", "sub_tracks": [
            self.track("First", "1.1"), self.track("Second", "1.2", "2:00")]}])
        self.assertEqual(len(album.tracks), 1)
        self.assertEqual(album.tracks[0].duration_ms, 180000)
        self.assertEqual(album.tracks[0].track_number, 1)

    def test_single_track_with_subtracks_is_not_expanded(self):
        track = self.track("Medley", "1", "3:00")
        track["sub_tracks"] = [self.track("First", "1.1"), self.track("Second", "1.2")]
        album = self.parse([track])
        self.assertEqual(len(album.tracks), 1)
        self.assertEqual(album.tracks[0].title, "Medley")
        self.assertEqual(album.tracks[0].duration_ms, 180000)

    def test_multiple_discs_and_missing_subtrack_duration(self):
        album = self.parse([self.track("First", "CD1-1"), self.track("Second", "CD2-1.1"),
                            self.track("Third", "CD2-1.2", "")])
        self.assertEqual([(t.disc_number, t.track_number) for t in album.tracks], [(1, 1), (2, 1)])
        self.assertEqual([t.disc_count for t in album.tracks], [2, 2])
        self.assertEqual(album.tracks[1].duration_ms, 0)

    def test_index_without_children_is_rejected(self):
        with self.assertRaises(DiscogsError):
            self.parse([{"type_": "index", "title": "Suite"}])

    def test_index_without_track_positions_is_rejected(self):
        with self.assertRaises(DiscogsError):
            self.parse([{"type_": "index", "title": "Suite", "sub_tracks": [self.track("First", "")]}])

    def test_fallback_position_does_not_merge_unrelated_tracks(self):
        album = self.parse([self.track("Vinyl", "A1"), self.track("CD", "1")])
        self.assertEqual(len(album.tracks), 2)

    def test_merged_subtracks_keep_both_artists(self):
        first, second = self.track("First", "1.1"), self.track("Second", "1.2")
        first["artists"], second["artists"] = [{"name": "Alice"}], [{"name": "Bob"}]
        album = self.parse([first, second])
        self.assertEqual(album.tracks[0].artist, "Alice、Bob")

    def test_artist_names_strip_disambiguation(self):
        self.assertEqual(_artist_names([{"name": "Placebo (2)"}]), "Placebo")
        self.assertEqual(_artist_names([{"name": "Prince", "anv": "The Artist"}]), "The Artist")

    def test_artist_names_honor_joins(self):
        artists = [{"name": "A (3)", "join": "&"}, {"name": "B", "join": ","},
                   {"name": "C", "join": ""}, {"name": "D", "join": "feat."}]
        self.assertEqual(_artist_names(artists), "A & B, C、D")

    def test_clean_artist(self):
        self.assertEqual(_clean_artist("*NSYNC"), "*NSYNC")
        self.assertEqual(_clean_artist("Foo (2)*"), "Foo")

    def test_search_cleans_artist_name(self):
        client = DiscogsClient()
        client._get = Mock(return_value={"results": [
            {"type": "release", "id": 5, "title": "Placebo (2)* - Album", "year": 1996}]})
        results = client.search_albums("Album", "Placebo", "tok")
        self.assertEqual(results[0].artist, "Placebo")
        self.assertEqual(results[0].title, "Album")
        self.assertEqual(client._get.call_args.args[1]["format"], "CD")

    def test_download_cover_omits_authorization(self):
        import io

        from PIL import Image

        content = io.BytesIO()
        Image.new("RGB", (16, 16), "red").save(content, "JPEG")
        response = Mock(headers={})
        response.iter_content.return_value = [content.getvalue()]
        with unittest.mock.patch("disctag.discogs.requests.get", return_value=response) as get:
            DiscogsClient().download_cover("https://img.discogs.example/cover.jpg", 600, "secret")
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])

    def test_release_date_strips_trailing_zero_parts(self):
        for released, expected in (("1995-03-00", "1995-03"), ("1995-00-00", "1995")):
            with self.subTest(released=released):
                client = DiscogsClient()
                client._get = Mock(return_value={"title": "Album", "artists": [{"name": "Artist"}],
                                                 "released": released, "tracklist": [self.track("Song", "1")]})
                self.assertEqual(client.get_album(1, "").release_date, expected)
