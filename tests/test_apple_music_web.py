import json
import unittest
from unittest.mock import Mock, patch

import requests

from disctag.apple_music_web import AppleMusicWebClient, AppleMusicWebError
from disctag.itunes import ITunesClient


def page(root):
    return '<script type="application/json" id="serialized-server-data">' + json.dumps({"data": [{"data": root}]}) + '</script>'


def get_for(html):
    response = Mock()
    response.text = html
    return patch("disctag.apple_music_web.requests.get", return_value=response)


def album_item(adam_id, title, **extra):
    return {"contentDescriptor": {"kind": "album", "identifiers": {"storeAdamID": str(adam_id)}}, "title": title, **extra}


def song(title, disc, track, **extra):
    return {"contentDescriptor": {"kind": "song"}, "title": title, "discNumber": disc, "trackNumber": track, **extra}


class SearchTests(unittest.TestCase):
    def test_search_albums_parses_items(self):
        root = {"sections": [{"items": [
            album_item(1, "Target", subtitleLinks=[{"title": "A"}, {"title": "B"}],
                       artwork={"dictionary": {"url": "https://x/{w}x{h}bb.{f}"}}, trackCount=10),
            {"contentDescriptor": {"kind": "song"}, "title": "Not an album"},
            album_item(1, "Duplicate"),
            album_item(2, "Other", subtitle="专辑 · Solo"),
        ]}]}
        client = AppleMusicWebClient()
        with get_for(page(root)):
            results = client.search_albums("Target")
        self.assertEqual([entry.collection_id for entry in results], [1, 2])
        first, second = results
        self.assertEqual((first.title, first.artist, first.country), ("Target", "A、B", "CN"))
        self.assertEqual(first.artwork_url, "https://x/100x100bb.jpg")
        self.assertEqual(first.track_count, 10)
        self.assertEqual(second.artist, "Solo")

    def test_search_albums_requires_a_term(self):
        client = AppleMusicWebClient()
        with patch("disctag.apple_music_web.requests.get") as get:
            with self.assertRaises(AppleMusicWebError):
                client.search_albums("", "")
            get.assert_not_called()


class GetAlbumTests(unittest.TestCase):
    def root(self):
        return {"sections": [
            {"id": "header", "items": [album_item(123, "Alb", quaternaryTitle="流行 · 2019年",
                                                  subtitleLinks=[{"title": "Singer"}])]},
            {"id": "related", "items": [song("Excluded", 1, 1)]},
            {"id": "track-list-1", "items": [
                song("D2T1", 2, 1, artistName="Guest", duration=90000),
                song("D1T2", 1, 2, duration=120000),
                song("D1T1", 1, 1, duration=60000),
            ]},
        ]}

    def test_get_album_parses_tracks(self):
        client = AppleMusicWebClient()
        with get_for(page(self.root())):
            album = client.get_album(123)
        self.assertEqual((album.title, album.artist, album.genre, album.release_date), ("Alb", "Singer", "流行", "2019"))
        self.assertEqual([t.title for t in album.tracks], ["D1T1", "D1T2", "D2T1"])
        self.assertEqual([(t.disc_number, t.track_number) for t in album.tracks], [(1, 1), (1, 2), (2, 1)])
        self.assertEqual([t.disc_count for t in album.tracks], [2, 2, 2])
        self.assertEqual(album.tracks[0].artist, "Singer")
        self.assertEqual(album.tracks[2].artist, "Guest")
        self.assertEqual([t.duration_ms for t in album.tracks], [60000, 120000, 90000])

    def test_missing_header_is_rejected(self):
        client = AppleMusicWebClient()
        with get_for(page({"sections": [{"id": "track-list-1", "items": [song("T", 1, 1)]}]})):
            with self.assertRaises(AppleMusicWebError):
                client.get_album(123)

    def test_page_without_script_tag_is_rejected(self):
        client = AppleMusicWebClient()
        with get_for("<html>no data</html>"):
            with self.assertRaises(AppleMusicWebError):
                client.get_album(123)

    def test_invalid_json_is_rejected(self):
        client = AppleMusicWebClient()
        html = '<script id="serialized-server-data">{oops</script>'
        with get_for(html):
            with self.assertRaises(AppleMusicWebError):
                client.get_album(123)

    def test_request_failure_is_wrapped(self):
        client = AppleMusicWebClient()
        with patch("disctag.apple_music_web.requests.get", side_effect=requests.ConnectionError("down")):
            with self.assertRaises(AppleMusicWebError):
                client.get_album(123)


class DelegationTests(unittest.TestCase):
    def test_cn_country_delegates_to_china_client(self):
        client = ITunesClient()
        client.china_client = Mock()
        client.china_client.search_albums.return_value = ["hit"]
        client.china_client.get_album.return_value = "album"
        self.assertEqual(client.search_albums("A", "B", "CN"), ["hit"])
        client.china_client.search_albums.assert_called_once_with("A", "B")
        self.assertEqual(client.get_album(1, "CN"), "album")
        client.china_client.get_album.assert_called_once_with(1)
