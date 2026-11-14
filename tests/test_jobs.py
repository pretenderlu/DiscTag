import tempfile
import unittest
from pathlib import Path

from disctag.jobs import CANCELLED, DONE, FAILED, PARTIAL, PENDING, RUNNING, ConversionJob, JobQueue
from disctag.models import AlbumMetadata, ConversionFailure, ConversionResult


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def job(self, folder="a", title="Album", output_format="flac"):
        sources = [self.root / folder / "01.wav", self.root / folder / "02.wav"]
        return ConversionJob(sources, AlbumMetadata(title, "Artist", "Artist"), self.root / "out",
                             output_format, "V0", None, True, None)

    def test_pending_job_for_same_wavs_is_replaced(self):
        queue = JobQueue()
        self.assertFalse(queue.add(self.job("a", "Old")))
        self.assertFalse(queue.add(self.job("b")))
        self.assertTrue(queue.add(self.job("a", "New")))
        self.assertEqual([job.title for job in queue.jobs], ["New", "Album"])

    def test_finished_job_is_not_replaced(self):
        queue = JobQueue()
        queue.add(self.job("a"))
        queue.jobs[0].status = DONE
        self.assertFalse(queue.add(self.job("a")))
        self.assertEqual(len(queue.jobs), 2)

    def test_next_pending_and_counts(self):
        queue = JobQueue([self.job("a"), self.job("b"), self.job("c")])
        queue.jobs[0].status = DONE
        self.assertIs(queue.next_pending(), queue.jobs[1])
        self.assertEqual(queue.pending_count(), 2)

    def test_running_job_cannot_be_removed(self):
        queue = JobQueue([self.job("a"), self.job("b")])
        queue.jobs[0].status = RUNNING
        self.assertFalse(queue.remove(0))
        self.assertTrue(queue.remove(1))
        self.assertFalse(queue.remove(5))

    def test_clear_finished_and_retry(self):
        queue = JobQueue([self.job(str(i)) for i in range(4)])
        for job, status in zip(queue.jobs, (DONE, FAILED, PENDING, CANCELLED), strict=True):
            job.status = status
        self.assertTrue(queue.retry(1))
        self.assertFalse(queue.retry(2))
        self.assertEqual(queue.clear_finished(), 2)
        self.assertEqual([job.status for job in queue.jobs], [PENDING, PENDING])

    def test_finish_sets_status(self):
        job = self.job()
        job.finish(ConversionResult(self.root, converted_files=[self.root / "1.flac"]))
        self.assertEqual((job.status, job.message), (DONE, "1 首"))
        job.finish(ConversionResult(self.root, failures=[ConversionFailure(self.root, "x")]))
        self.assertEqual(job.status, PARTIAL)
        job.finish(ConversionResult(self.root, cancelled=True))
        self.assertEqual(job.status, CANCELLED)
        job.fail(RuntimeError("boom"))
        self.assertEqual((job.status, job.message, job.status_label), (FAILED, "boom", "失败"))

    def test_labels(self):
        self.assertEqual(self.job(output_format="mp3").format_label, "MP3 V0")
        self.assertEqual(self.job().format_label, "FLAC")
        self.assertEqual(self.job().status, PENDING)


if __name__ == "__main__":
    unittest.main()
