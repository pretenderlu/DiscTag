import os
import sys
import tempfile
import unittest
from pathlib import Path

from disctag.jobs import CANCELLED, DONE, FAILED, PARTIAL, PENDING, RUNNING, ConversionJob, JobQueue
from disctag.models import AlbumMetadata, ConversionFailure, ConversionResult, TrackMetadata
from disctag.sources import SourceTrack


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

    def track_job(self, folder="a", title="Album", output_format="flac", trash=False, cover=None, root=None):
        job = self.job(folder, title, output_format)
        job.album.tracks = [TrackMetadata("One", "Artist", 1), TrackMetadata("Two", "Artist", 2)]
        job.trash_sources = trash
        job.cover_data = cover
        if root is not None:
            job.output_root = root
        return job

    def test_output_paths_cover_tracks_and_cover(self):
        directory = self.root / "out" / "Artist" / "Album"
        job = self.track_job()
        expected = {directory / "01 - One.flac", directory / "02 - Two.flac"}
        normalise = lambda paths: {Path(os.path.normcase(os.path.abspath(path))) for path in paths}  # noqa: E731
        self.assertEqual(job.output_paths(), normalise(expected))
        job.cover_data = b"x"
        self.assertEqual(job.output_paths(), normalise(expected | {directory / "cover.jpg"}))

    def test_pending_job_for_same_input_is_not_a_conflict(self):
        queue = JobQueue([self.track_job("a")])
        self.assertIsNone(queue.conflict(self.track_job("a", trash=True)))

    def test_different_input_with_same_outputs_conflicts(self):
        queue = JobQueue([self.track_job("a")])
        self.assertEqual(queue.conflict(self.track_job("b")), ("output", queue.jobs[0]))
        self.assertIsNone(queue.conflict(self.track_job("b", "Other Album")))
        self.assertIsNone(queue.conflict(self.track_job("b", output_format="mp3")))

    def test_cover_only_overlap_conflicts(self):
        first = self.track_job("a", cover=b"x")
        first.album.tracks = [TrackMetadata("One", "Artist", 1)]
        second = self.track_job("b", cover=b"y")
        second.album.tracks = [TrackMetadata("Two", "Artist", 2)]
        self.assertEqual(JobQueue([first]).conflict(second), ("output", first))
        second.cover_data = None
        self.assertIsNone(JobQueue([first]).conflict(second))

    def test_running_job_that_trashes_same_input_conflicts(self):
        running = self.track_job("a", trash=True)
        running.status = RUNNING
        queue = JobQueue([running])
        self.assertEqual(queue.conflict(self.track_job("a", "Other Album")), ("running_trash", running))
        running.trash_sources = False
        self.assertIsNone(queue.conflict(self.track_job("a", "Other Album")))
        self.assertEqual(queue.conflict(self.track_job("a")), ("output", running))

    def test_finished_jobs_are_ignored_for_conflicts(self):
        queue = JobQueue([self.track_job("a", trash=True)])
        for status in (DONE, PARTIAL, FAILED, CANCELLED):
            queue.jobs[0].status = status
            self.assertIsNone(queue.conflict(self.track_job("a")))
            self.assertIsNone(queue.conflict(self.track_job("b")))

    @unittest.skipUnless(sys.platform == "win32", "Windows paths are case-insensitive")
    def test_output_conflict_ignores_case_on_windows(self):
        queue = JobQueue([self.track_job("a", root=self.root / "Out")])
        upper = self.track_job("b", "ALBUM", root=self.root / "OUT")
        upper.album.artist = upper.album.album_artist = "ARTIST"
        upper.album.tracks = [TrackMetadata("ONE", "Artist", 1)]
        self.assertEqual(queue.conflict(upper), ("output", queue.jobs[0]))

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

    def test_cover_error_is_a_warning_not_a_failure(self):
        job = self.job()
        job.finish(ConversionResult(self.root, converted_files=[self.root / "1.flac", self.root / "2.flac"],
                                    cover_error="Access denied"))
        self.assertEqual(job.status, DONE)
        self.assertEqual(job.message, "2 首；cover.jpg 写入失败：Access denied")

    def test_labels(self):
        self.assertEqual(self.job(output_format="mp3").format_label, "MP3 V0")
        self.assertEqual(self.job().format_label, "FLAC")
        self.assertEqual(self.job().status, PENDING)


if __name__ == "__main__":
    unittest.main()

    def cue_job(self, folder="cue", starts=(0, 100, 200)):
        image, cue = self.root / folder / "image.flac", self.root / folder / "image.cue"
        ends = [*starts[1:], None]
        sources = [SourceTrack(image, start, end, number, cue, f"T{number}")
                   for number, (start, end) in enumerate(zip(starts, ends, strict=True), 1)]
        return ConversionJob(sources, AlbumMetadata("Album", "Artist", "Artist"), self.root / "out", "flac", "V0",
                             None, True, None)

    def test_same_input_with_cue_segments(self):
        job = self.cue_job()
        same = [SourceTrack(Path(str(source.path).upper() if sys.platform == "win32" else source.path),
                            source.start_frame, source.end_frame, source.number, source.cue, "Other title")
                for source in job.sources]
        self.assertTrue(job.same_input(same))
        self.assertFalse(job.same_input(self.cue_job(starts=(0, 100, 201)).sources))
        self.assertFalse(job.same_input([source.path for source in job.sources]))
        self.assertTrue(self.job().same_input([self.root / "a" / "01.wav", self.root / "a" / "02.wav"]))
        self.assertTrue(all(isinstance(source, SourceTrack) for source in self.job().sources))

    def test_trash_paths(self):
        job = self.cue_job()
        self.assertEqual(job.trash_paths(), [self.root / "cue" / "image.flac", self.root / "cue" / "image.cue"])
        self.assertEqual(self.job().trash_paths(), [self.root / "a" / "01.wav", self.root / "a" / "02.wav"])
