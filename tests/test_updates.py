import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from disctag.updates import UpdateError, UpdateInfo, check_for_updates, download_update, version_key

DIGEST = "a" * 64


def release(tag, digest=DIGEST, size=10, prerelease=False, body="- 修复若干问题"):
    asset = {"name": "DiscTagSetup-x.exe", "browser_download_url": "https://example.invalid/setup.exe", "size": size}
    if digest is not None:
        asset["digest"] = "sha256:" + digest
    return {"tag_name": tag, "html_url": "https://github.com/pretenderlu/DiscTag/releases/" + tag,
            "assets": [asset], "prerelease": prerelease, "draft": False, "body": body}


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
        self.assertEqual(info.notes, "- 修复若干问题")

    def test_release_notes_come_from_body(self):
        with patch("disctag.updates.requests.get",
                   return_value=payload_response(release("v9.9.9", body="- 新增 A\n- 修复 B"))):
            info = check_for_updates("1.6.5")
        self.assertEqual(info.notes, "- 新增 A\n- 修复 B")

    def test_release_without_body_has_empty_notes(self):
        payload = release("v9.9.9")
        del payload["body"]
        with patch("disctag.updates.requests.get", return_value=payload_response(payload)):
            info = check_for_updates("1.6.5")
        self.assertEqual(info.notes, "")

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

    def failing_response(self, status):
        response = self.stream([])
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Server Error", response=Mock(status_code=status)
        )
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

    def test_download_retries_retryable_status(self):
        content = b"installer-bytes"
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl",
                          sha256=hashlib.sha256(content).hexdigest())
        get = Mock(side_effect=[self.failing_response(504), self.stream([content])])
        with tempfile.TemporaryDirectory() as directory, \
                patch("disctag.updates.time.sleep") as sleep:
            result = self.download(info, get, directory)
            self.assertEqual(result.read_bytes(), content)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_download_falls_back_to_alternate_url(self):
        content = b"installer-bytes"
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl",
                          alternate_url="https://api.github.com/assets/1",
                          sha256=hashlib.sha256(content).hexdigest())
        get = Mock(side_effect=[self.failing_response(504), self.failing_response(504),
                                self.stream([content])])
        with tempfile.TemporaryDirectory() as directory, \
                patch("disctag.updates.time.sleep"):
            result = self.download(info, get, directory)
            self.assertEqual(result.read_bytes(), content)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args_list[2].args[0], "https://api.github.com/assets/1")

    def test_download_without_alternate_only_uses_download_url(self):
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl", sha256=DIGEST)
        get = Mock(return_value=self.failing_response(504))
        with tempfile.TemporaryDirectory() as directory, \
                patch("disctag.updates.time.sleep"):
            with self.assertRaises(UpdateError):
                self.download(info, get, directory)
        self.assertEqual(get.call_count, 3)
        for call in get.call_args_list:
            self.assertEqual(call.args[0], "https://dl")

    def test_download_does_not_retry_client_errors(self):
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl", sha256=DIGEST)
        get = Mock(return_value=self.failing_response(404))
        with tempfile.TemporaryDirectory() as directory, \
                patch("disctag.updates.time.sleep") as sleep:
            with self.assertRaises(UpdateError):
                self.download(info, get, directory)
            self.assertFalse((Path(directory) / "setup.download").exists())
        get.assert_called_once()
        sleep.assert_not_called()

    def test_download_does_not_retry_checksum_mismatch(self):
        content = b"short"
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl",
                          size=100, sha256=hashlib.sha256(content).hexdigest())
        get = Mock(return_value=self.stream([content]))
        with tempfile.TemporaryDirectory() as directory, \
                patch("disctag.updates.time.sleep") as sleep:
            with self.assertRaises(UpdateError):
                self.download(info, get, directory)
        get.assert_called_once()
        sleep.assert_not_called()

    def test_download_fails_after_all_attempts(self):
        info = UpdateInfo("v9.9.9", "https://x", download_url="https://dl",
                          alternate_url="https://api.github.com/assets/1", sha256=DIGEST)
        get = Mock(return_value=self.failing_response(504))
        with tempfile.TemporaryDirectory() as directory, \
                patch("disctag.updates.time.sleep") as sleep:
            with self.assertRaises(UpdateError) as context:
                self.download(info, get, directory)
            self.assertFalse((Path(directory) / "setup.download").exists())
            self.assertFalse((Path(directory) / "setup.exe").exists())
        self.assertIn("下载失败", str(context.exception))
        self.assertEqual(get.call_count, 4)
        self.assertEqual(sleep.call_count, 3)
