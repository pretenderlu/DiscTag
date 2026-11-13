import io
import unittest
from unittest.mock import Mock, patch

import requests
from PIL import Image

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
        with patch("disctag.itunes.requests.get", side_effect=fake_get):
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
        with patch("disctag.itunes.requests.get", side_effect=fake_get):
            client.download_cover("https://example.apple/100x100bb-60.jpg", 1200)
        self.assertTrue(requested[0].endswith("1200x1200bb.jpg"))
