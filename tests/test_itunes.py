import io
import unittest
from unittest.mock import Mock, patch

import requests
from PIL import Image

from disctag.catalog_common import http_session
from disctag.itunes import ITunesClient


def jpeg(size=600):
    output = io.BytesIO()
    Image.new("RGB", (size, size), "red").save(output, "JPEG")
    return output.getvalue()


class ITunesCoverTests(unittest.TestCase):
    def test_download_cover_rewrites_size(self):
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            response = Mock()
            if len(requested) == 1:
                response.raise_for_status.side_effect = requests.HTTPError("404")
            else:
                response.headers = {}
                response.iter_content.return_value = [jpeg(600)]
            return response

        client = ITunesClient()
        with patch("disctag.catalog_common.http_session", return_value=Mock(get=Mock(side_effect=fake_get))):
            data = client.download_cover("https://example.apple/100x100bb.jpg", 1200)
        self.assertTrue(requested[0].startswith("https://example.apple/1200x1200bb.jpg"))
        self.assertTrue(requested[1].startswith("https://example.apple/600x600bb.jpg"))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (600, 600))

    def test_download_cover_strips_dimension_suffix(self):
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            response = Mock(headers={})
            response.iter_content.return_value = [jpeg(600)]
            return response

        client = ITunesClient()
        with patch("disctag.catalog_common.http_session", return_value=Mock(get=Mock(side_effect=fake_get))):
            client.download_cover("https://example.apple/100x100bb-60.jpg", 1200)
        self.assertTrue(requested[0].endswith("1200x1200bb.jpg"))


class ITunesLookupTests(unittest.TestCase):
    def test_collection_object_is_used_even_after_track_items(self):
        client = ITunesClient()
        client._get = Mock(return_value={"results": [
            {"wrapperType": "track", "kind": "song", "collectionId": 7, "trackName": "Song", "trackNumber": 1,
             "discNumber": 1, "artistName": "Singer", "collectionName": "Track Copy", "primaryGenreName": "Track Genre"},
            {"wrapperType": "collection", "collectionId": 7, "collectionName": "Album", "artistName": "Band",
             "discCount": 2, "primaryGenreName": "Rock", "releaseDate": "2001-02-03T00:00:00Z"},
        ]})
        album = client.get_album(7, "JP")
        self.assertEqual((album.title, album.artist, album.genre, album.release_date), ("Album", "Band", "Rock", "2001-02-03"))
        self.assertEqual([(t.title, t.disc_count) for t in album.tracks], [("Song", 2)])


class HttpSessionTests(unittest.TestCase):
    def test_session_is_shared_and_pooled(self):
        session = http_session()
        self.assertIs(http_session(), session)
        for prefix in ("https://", "http://"):
            adapter = session.get_adapter(f"{prefix}example.com")
            self.assertEqual((adapter._pool_connections, adapter._pool_maxsize), (8, 16))
