import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from disctag.updates import UpdateError, UpdateInfo, check_for_updates, download_update, version_key

DIGEST = "a" * 64


def release(tag, digest=DIGEST, size=10, prerelease=False):
    asset = {"name": "DiscTagSetup-x.exe", "browser_download_url": "https://example.invalid/setup.exe", "size": size}
    if digest is not None:
        asset["digest"] = "sha256:" + digest
    return {"tag_name": tag, "html_url": "https://github.com/pretenderlu/DiscTag/releases/" + tag,
            "assets": [asset], "prerelease": prerelease, "draft": False}


def payload_response(payload):
    response = Mock()
    response.json.return_value = payload
    return response


class UpdateTests(unittest.TestCase):
    def test_version_key(self):
        self.assertGreater(version_key("v1.6.10"), version_key("1.6.9"))
        self.assertEqual(version_key("1.7"), (1, 7, 0, 0))

    def test_newer_release_with_digest_offers_download(self):
        with patch("disctag.updates.requests.get", return_value=payload_response(release("v9.9.9"))):
            info = check_for_updates("1.6.5")
        self.assertEqual(info.download_url, "https://example.invalid/setup.exe")
        self.assertEqual(info.sha256, DIGEST)

    def test_release_without_digest_disables_download(self):
        with patch("disctag.updates.requests.get", return_value=payload_response(release("v9.9.9", digest=None))):
            info = check_for_updates("1.6.5")
        self.assertEqual(info.download_url, "")
        self.assertEqual(info.sha256, "")

    def test_older_or_same_release_is_ignored(self):
        for tag in ("v1.6.5", "v1.6.4"):
            with self.subTest(tag=tag), \
                    patch("disctag.updates.requests.get", return_value=payload_response(release(tag))):
                self.assertIsNone(check_for_updates("1.6.5"))

    def test_prerelease_is_ignored(self):
        with patch("disctag.updates.requests.get",
                   return_value=payload_response(release("v9.9.9", prerelease=True))):
            self.assertIsNone(check_for_updates("1.6.5"))

    def download(self, info, get_mock, directory):
        destination = Path(directory) / "setup.exe"
        with patch("disctag.updates.requests.get", get_mock):
            return download_update(info, destination)

    def stream(self, chunks):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = iter(chunks)
        response.headers = {}
        return response

    def test_download_verifies_sha256(self):
        content = b"installer-bytes"
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl", sha256=hashlib.sha256(content).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            result = self.download(info, Mock(return_value=self.stream([content[:5], content[5:]])), directory)
            self.assertEqual(result.read_bytes(), content)

    def test_download_rejects_bad_sha256(self):
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl", sha256="0" * 64)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UpdateError):
                self.download(info, Mock(return_value=self.stream([b"data"])), directory)
            self.assertFalse((Path(directory) / "setup.exe").exists())
            self.assertFalse((Path(directory) / "setup.download").exists())

    def test_download_rejects_size_mismatch(self):
        content = b"short"
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl",
                          size=100, sha256=hashlib.sha256(content).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UpdateError):
                self.download(info, Mock(return_value=self.stream([content])), directory)
            self.assertFalse((Path(directory) / "setup.exe").exists())

    def test_download_requires_sha256(self):
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl", sha256="")
        with tempfile.TemporaryDirectory() as directory:
            get = Mock()
            with self.assertRaises(UpdateError):
                self.download(info, get, directory)
            get.assert_not_called()
