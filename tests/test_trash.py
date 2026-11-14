import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from disctag.jobs import DONE, PARTIAL, ConversionJob, trash_sources_if_complete
from disctag.models import AlbumMetadata, ConversionFailure, ConversionResult
from disctag.trash import move_to_trash


class TrashSourcesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = [self.root / "01.wav", self.root / "02.wav"]
        self.outputs = [self.root / "out" / "01.flac", self.root / "out" / "02.flac"]
        for path in [*self.sources, *self.outputs]:
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"data")

    def job(self, trash=True):
        return ConversionJob(self.sources, AlbumMetadata("A", "B", "B"), self.root / "out", "flac", "V0",
                             None, True, None, trash_sources=trash)

    def result(self, **extra):
        return ConversionResult(self.root / "out", converted_files=list(self.outputs), **extra)

    def test_disabled_by_default(self):
        mover = Mock()
        trash_sources_if_complete(self.job(trash=False), self.result(), mover)
        mover.assert_not_called()

    def test_complete_album_is_trashed(self):
        mover = Mock(return_value=(self.sources, []))
        job, result = self.job(), self.result()
        trash_sources_if_complete(job, result, mover)
        mover.assert_called_once_with(self.sources)
        job.finish(result)
        self.assertEqual(job.status, DONE)
        self.assertEqual(result.trashed_sources, self.sources)

    def test_partial_cancelled_or_missing_output_keeps_sources(self):
        cases = {
            "failure": self.result(failures=[ConversionFailure(self.sources[1], "x")]),
            "cancelled": self.result(cancelled=True),
            "too few outputs": ConversionResult(self.root / "out", converted_files=self.outputs[:1]),
        }
        empty = self.root / "out" / "empty.flac"
        empty.write_bytes(b"")
        cases["empty output"] = ConversionResult(self.root / "out", converted_files=[self.outputs[0], empty])
        for name, result in cases.items():
            with self.subTest(name):
                mover = Mock()
                trash_sources_if_complete(self.job(), result, mover)
                mover.assert_not_called()
                self.assertTrue(result.trash_skipped)

    def test_trash_failure_marks_job_partial(self):
        mover = Mock(return_value=([self.sources[0]], [(self.sources[1], "busy")]))
        job, result = self.job(), self.result()
        trash_sources_if_complete(job, result, mover)
        job.finish(result)
        self.assertEqual(job.status, PARTIAL)
        self.assertEqual(result.trash_failures[0].message, "busy")


class MoveToTrashTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "a.wav"
        self.path.write_bytes(b"x")

    def test_errors_keep_the_file(self):
        with patch("disctag.trash._trash_one", side_effect=OSError("denied")):
            moved, failures = move_to_trash([self.path])
        self.assertEqual(moved, [])
        self.assertEqual(failures, [(self.path, "denied")])
        self.assertTrue(self.path.exists())

    def test_file_still_present_counts_as_failure(self):
        with patch("disctag.trash._trash_one"):
            moved, failures = move_to_trash([self.path])
        self.assertEqual(moved, [])
        self.assertEqual(len(failures), 1)

    def test_missing_file_is_reported(self):
        moved, failures = move_to_trash([self.path.with_name("missing.wav")])
        self.assertEqual((moved, len(failures)), ([], 1))


if __name__ == "__main__":
    unittest.main()
