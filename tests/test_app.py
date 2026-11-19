import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from disctag.app import DiscTagApp
from disctag.audio import output_directory
from disctag.jobs import CANCELLED, DONE, PENDING, JobQueue
from disctag.models import AlbumMetadata, AlbumSummary, TrackMetadata
from disctag.sources import SourceTrack


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class AppTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = a = DiscTagApp.__new__(DiscTagApp)
        for name in ("album", "artist", "album_artist", "date", "genre", "status", "source",
                     "album_info", "cover_info", "progress"):
            setattr(a, name + "_var", Variable())
        a.album_var.set("Manual Album")
        a.artist_var.set("Artist")
        a.metadata_source_var = Variable("iTunes / Apple Music")
        a.region_var = Variable("US")
        a.discogs_token_var = Variable("")
        a.output_var = Variable(str(self.root))
        a.format_var = Variable("wav")
        a.trash_sources_var = Variable(False)
        from disctag import shortcuts
        with patch("disctag.shortcuts.sys.platform", "win32"):
            a.shortcut_map = shortcuts.load({})
        a._apply_shortcuts()
        a.quality_var = Variable("320 kbps")
        a.cover_size_var = Variable("1200 × 1200")
        a.cover_embed_var = Variable("同 cover.jpg")
        for name in ("root", "search_button", "region_label", "region_combo", "token_header",
                     "discogs_token_entry", "results_tree", "convert_button", "clear_button",
                     "progress", "preview", "cover_label", "album_entry", "enqueue_button", "quality_combo"):
            setattr(a, name, Mock())
        a.results_tree.get_children.return_value = ()
        a.sources = [SourceTrack(self.root / "source.wav")]
        a.source_durations = {}
        a.cue_toc = None
        a.album = None
        a.album_region = ""
        a.loaded_result_iid = None
        a._restoring_result_selection = False
        a.metadata_dirty = False
        a.cover_data = None
        a.cover_is_local = False
        a.search_request_id = a.album_request_id = a.cover_request_id = 0
        a.converting = a.updating = False
        a.update_dialog = None
        a.ui_scale = 1.0
        a.ui_font = "Segoe UI"
        a.ui_semibold = "Segoe UI Semibold"
        a.cjk_font = "Microsoft YaHei UI"
        a.latest_release_url = "https://github.com/pretenderlu/DiscTag/releases/latest"
        a.results = []
        a.job_queue = JobQueue()
        a.queue_run_jobs = []
        a.current_job = None
        a.queue_window = None
        a.cancel_event = None
        a.conversion_thread = None
        a.last_output = None
        a.result_markers = {}
        a.album_cache = {}
        a.client = Mock(last_warnings=[])
        a.discogs_client = Mock()
        for name in ("_save_discogs_token", "_refresh_tracks", "_show_cover", "_update_album_info"):
            setattr(a, name, Mock())
        a._smart_match_missing = Mock(return_value=None)
        self.jobs = []
        a._run_async = lambda work, done, failed: self.jobs.append((work, done, failed))

    def select_album(self, title="Online Album"):
        self.app.results = [AlbumSummary(1, title, "Artist", country="US")]
        self.app.results_tree.selection.return_value = ("0",)
        self.app._album_selected()
        return self.jobs[-1]

    def album(self, title="Online Album", artwork_url=""):
        return AlbumMetadata(title, "Artist", "Artist", artwork_url=artwork_url,
                             tracks=[TrackMetadata("Song", "Artist", 1)])

    def test_overwrite_check_uses_final_track_number(self):
        a = self.app
        a.album = self.album("Manual Album")
        a.album.tracks[0].track_number = 3
        target = output_directory(self.root, a.album) / "01 - Song.wav"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing")
        with patch("disctag.ui.processing.messagebox.askyesno", return_value=False) as ask:
            a._convert()
        ask.assert_called_once()
        self.assertFalse(self.jobs)
        self.assertEqual(target.read_bytes(), b"existing")
        self.assertEqual(a.album.tracks[0].track_number, 3)

    def test_successful_load_remembers_result_row(self):
        _, done, _ = self.select_album()
        self.assertIsNone(self.app.loaded_result_iid)
        done((self.album(), None, None))
        self.assertEqual(self.app.loaded_result_iid, "0")

    def test_declining_album_replace_restores_loaded_selection(self):
        a = self.app
        a.results = [AlbumSummary(1, "Loaded", "Artist", country="US"), AlbumSummary(2, "Other", "Artist", country="JP")]
        a.album = self.album("Loaded")
        a.metadata_dirty = True
        a.loaded_result_iid = "0"
        a.results_tree.selection.return_value = ("1",)
        a.results_tree.exists.return_value = True
        request_id = a.album_request_id
        with patch("disctag.ui.catalog.messagebox.askyesno", return_value=False) as ask:
            a._album_selected()
            ask.assert_called_once()
            # 恢复高亮时 Treeview 会再触发一次选择事件，必须被忽略。
            self.assertTrue(a._restoring_result_selection)
            a.results_tree.selection.return_value = ("0",)
            a._album_selected(object())
            ask.assert_called_once()
        a.results_tree.selection_set.assert_called_once_with("0")
        a.results_tree.focus.assert_called_with("0")
        a.results_tree.see.assert_called_with("0")
        a.results_tree.selection_remove.assert_not_called()
        self.assertFalse(self.jobs)
        self.assertEqual(a.album_request_id, request_id)
        self.assertEqual(a.album.title, "Loaded")
        reset = a.root.after_idle.call_args.args[0]
        reset()
        self.assertFalse(a._restoring_result_selection)

    def test_declining_album_replace_without_loaded_row_clears_selection(self):
        a = self.app
        a.results = [AlbumSummary(1, "Other", "Artist", country="US")]
        a.album = self.album("Manual Album")
        a.metadata_dirty = True
        a.results_tree.selection.return_value = ("0",)
        with patch("disctag.ui.catalog.messagebox.askyesno", return_value=False):
            a._album_selected()
        a.results_tree.selection_set.assert_not_called()
        a.results_tree.selection_remove.assert_called_once_with("0")
        self.assertFalse(self.jobs)

    def test_result_row_is_forgotten_when_results_reset(self):
        a = self.app
        for reset in (lambda: a._manual_mode(), lambda: a._show_results(),
                      lambda: a._metadata_source_changed(object()), lambda: a._clear_album()):
            a.loaded_result_iid = "0"
            reset()
            self.assertIsNone(a.loaded_result_iid)

    def test_switching_source_restores_search_and_ignores_old_callbacks(self):
        a = self.app
        a._search()
        _, done, failed = self.jobs[-1]
        a.metadata_source_var.set("Discogs")
        a._metadata_source_changed(object())
        a.search_button.configure.assert_called_with(state="normal")
        with patch("disctag.ui.catalog.messagebox.showerror") as error:
            done([AlbumSummary(1, "Old", "Artist")])
            failed(RuntimeError("old request"))
        self.assertFalse(a.results)
        error.assert_not_called()

    def test_source_switch_does_not_enable_search_while_busy(self):
        self.app.updating = True
        self.app._metadata_source_changed(object())
        self.app.search_button.configure.assert_called_with(state="disabled")
        self.app.updating = False
        self.app.converting = True
        self.app._metadata_source_changed(object())
        self.app.search_button.configure.assert_called_with(state="normal")

    def test_manual_mode_invalidates_pending_album(self):
        _, done, failed = self.select_album()
        self.app._manual_mode()
        with patch("disctag.ui.catalog.messagebox.showerror") as error:
            done((self.album(), None, None))
            failed(RuntimeError("old request"))
        self.assertEqual(self.app.album.title, "Manual Album")
        self.assertTrue(self.app.metadata_dirty)
        error.assert_not_called()

    def test_import_invalidates_pending_album(self):
        _, done, _ = self.select_album()
        self.app.loaded_result_iid = "0"
        source = self.root / "new.wav"
        source.touch()
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(self.root)):
            self.app._import_wav()
        done((self.album(), None, None))
        self.assertIsNone(self.app.album)
        self.assertIsNone(self.app.loaded_result_iid)
        self.assertEqual(self.app.sources, [SourceTrack(source)])

    def write_image_cue(self, folder, name="disc", tracks=3, encoding="utf-8", per_track=False):
        import wave

        folder.mkdir(parents=True, exist_ok=True)
        lines = ["REM GENRE Anime", "REM DATE 2003", 'PERFORMER "歌手"', 'TITLE "专辑"']
        if not per_track:
            with wave.open(str(folder / f"{name}.wav"), "wb") as audio:
                audio.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
                audio.writeframes(bytes(4 * 44100 * tracks))
            lines.append(f'FILE "{name}.wav" WAVE')
        for number in range(1, tracks + 1):
            if per_track:
                (folder / f"{number:02d}.wav").write_bytes(b"dummy")
                lines.append(f'FILE "{number:02d}.wav" WAVE')
            start = 0 if per_track else (number - 1) * 75
            lines += [f"  TRACK {number:02d} AUDIO", f'    TITLE "曲{number}"',
                      *(['    PERFORMER "客串"'] if number == 2 else []),
                      f"    INDEX 01 00:{start // 75:02d}:00"]
        cue = folder / f"{name}.cue"
        cue.write_bytes("\n".join(lines).encode(encoding))
        return cue

    def test_import_folder_with_image_cue(self):
        a = self.app
        a.album_var.set("")
        a.date_var.set("")
        folder = self.root / "rip"
        cue = self.write_image_cue(folder, encoding="gbk")
        (folder / "disc.log").write_text("log")
        a.result_markers = {("x",): "✓"}
        a._show_results = Mock()
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)),                 patch("disctag.ui.tracks.filedialog.askopenfilename") as ask:
            a._import_wav()
        ask.assert_not_called()
        self.assertEqual(len(a.sources), 3)
        self.assertTrue(all(source.is_segment and source.cue == cue for source in a.sources))
        self.assertEqual([source.title for source in a.sources], ["曲1", "曲2", "曲3"])
        self.assertEqual([a.source_durations[source] for source in a.sources], [1.0, 1.0, 1.0])
        self.assertEqual((a.album_var.get(), a.artist_var.get(), a.date_var.get(), a.genre_var.get()),
                         ("专辑", "歌手", "2003", "Anime"))
        self.assertEqual(a.cue_toc, "1+3+375+150+225+300")
        self.assertEqual(a.source_var.get(), "disc.cue  ·  CUE 整轨 · 3 首")
        self.assertEqual(a.status_var.get(), "已导入 CUE 整轨：3 首")
        self.assertEqual(a.result_markers, {})
        self.assertIsNone(a.album)

        a._manual_mode()
        self.assertEqual([track.title for track in a.album.tracks], ["曲1", "曲2", "曲3"])
        self.assertEqual([track.artist for track in a.album.tracks], ["歌手", "客串", "歌手"])

    def test_import_folder_with_two_image_cues_asks_which(self):
        a = self.app
        folder = self.root / "rip"
        self.write_image_cue(folder, "disc1", tracks=2)
        second = self.write_image_cue(folder, "disc2", tracks=3)
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)),                 patch("disctag.ui.tracks.filedialog.askopenfilename", return_value=None) as ask:
            a._import_wav()
        ask.assert_called_once()
        self.assertEqual(ask.call_args.kwargs["initialdir"], str(folder))
        self.assertEqual(ask.call_args.kwargs["filetypes"], [("CUE", "*.cue")])
        self.assertEqual(a.sources, [SourceTrack(self.root / "source.wav")])
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)),                 patch("disctag.ui.tracks.filedialog.askopenfilename", return_value=str(second)):
            a._import_wav()
        self.assertEqual(len(a.sources), 3)
        self.assertEqual({source.cue for source in a.sources}, {second})

    def test_imports_flac_ape_and_wav_tracks(self):
        a = self.app
        folder = self.root / "mixed"
        folder.mkdir()
        for name in ("02.ape", "01.flac", "03.wav"):
            (folder / name).write_bytes(b"dummy")
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)):
            a._import_wav()
        self.assertEqual([source.name for source in a.sources], ["01.flac", "02.ape", "03.wav"])
        self.assertFalse(any(source.is_segment for source in a.sources))

    def test_import_status_warns_only_when_wav_output_needs_decoding(self):
        a = self.app
        a.format_var.set("wav")
        for name, files, expected in (
            ("wavs", ("01.wav", "02.wav"), "已导入 2 个音轨文件"),
            ("flacs", ("01.flac", "02.wav"),
             "WAV：FLAC/APE 源会解码为无损 WAV，文件会比源文件大；标签写入 RIFF ID3 块，部分播放器可能读不到"),
        ):
            folder = self.root / name
            folder.mkdir()
            for file in files:
                (folder / file).write_bytes(b"dummy")
            with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)):
                a._import_wav()
            self.assertEqual(a.status_var.get(), expected)

    def test_same_stem_in_several_formats_prefers_wav(self):
        a = self.app
        folder = self.root / "dupes"
        folder.mkdir()
        for name in ("01.FLAC", "01.wav", "01.ape", "02.flac", "02.ape"):
            (folder / name).write_bytes(b"dummy")
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)):
            a._import_wav()
        self.assertEqual([source.name for source in a.sources], ["01.wav", "02.flac"])

    def test_image_cue_wins_over_per_track_files(self):
        a = self.app
        folder = self.root / "rip"
        cue = self.write_image_cue(folder)
        (folder / "99.flac").write_bytes(b"dummy")
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)):
            a._import_wav()
        self.assertEqual(len(a.sources), 3)
        self.assertTrue(all(source.is_segment and source.cue == cue for source in a.sources))

    def test_wav_hint_depends_on_source_formats(self):
        a = self.app
        a.quality_combo = Mock()
        a.sources = [SourceTrack(self.root / "a.wav")]
        a._format_changed()
        self.assertEqual(a.status_var.get(),
                         "WAV：保留原始音频数据，只写入标签（RIFF ID3 块）并另存 cover.jpg；部分播放器可能读不到 WAV 标签")
        a.sources = [SourceTrack(self.root / "a.flac")]
        a._format_changed()
        self.assertEqual(a.status_var.get(),
                         "WAV：FLAC/APE 源会解码为无损 WAV，文件会比源文件大；标签写入 RIFF ID3 块，部分播放器可能读不到")

    def test_per_track_cue_imports_wavs_normally(self):
        a = self.app
        a.cue_toc = "stale"
        folder = self.root / "tracks"
        self.write_image_cue(folder, per_track=True)
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)),                 patch("disctag.ui.tracks.source_duration", return_value=1.0):
            a._import_wav()
        self.assertEqual([source.name for source in a.sources], ["01.wav", "02.wav", "03.wav"])
        self.assertFalse(any(source.is_segment for source in a.sources))
        self.assertIsNone(a.cue_toc)
        self.assertEqual(a.album_var.get(), "Manual Album")

    def test_import_reports_broken_cue_without_wavs(self):
        a = self.app
        folder = self.root / "broken"
        folder.mkdir()
        (folder / "disc.cue").write_text('FILE "gone.flac" WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\n')
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(folder)),                 patch("disctag.ui.tracks.messagebox") as box:
            a._import_wav()
        box.showerror.assert_called_once()
        self.assertIn("gone.flac", box.showerror.call_args.args[1])
        empty = self.root / "empty"
        empty.mkdir()
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(empty)),                 patch("disctag.ui.tracks.messagebox") as box:
            a._import_wav()
        self.assertEqual(box.showwarning.call_args.args[1], "所选文件夹中没有找到 WAV、FLAC、APE 音轨或 CUE 整轨。")
        self.assertEqual(a.sources, [SourceTrack(self.root / "source.wav")])

    def test_musicbrainz_search_uses_cue_toc(self):
        a = self.app
        a.metadata_source_var.set("MusicBrainz")
        a.album_var.set("")
        cue = self.root / "disc.cue"
        a.sources = [SourceTrack(self.root / "disc.wav", 0, 100, 1, cue), SourceTrack(self.root / "disc.wav", 100, None, 2, cue)]
        a.source_durations = {a.sources[0]: 1.33, a.sources[1]: 3.0}
        a.cue_toc = "1+2+475+150+250"
        a.musicbrainz_client = Mock()
        a.musicbrainz_client.lookup_toc.return_value = []
        a.musicbrainz_client.search_albums.return_value = []
        a._search()
        work, _, _ = self.jobs[-1]
        a.cue_toc = None  # 工作线程使用的是搜索开始时捕获的 TOC
        work()
        a.musicbrainz_client.lookup_toc.assert_called_once_with("1+2+475+150+250", "", "Artist")

    def test_clear_invalidates_pending_search(self):
        self.app._search()
        _, done, _ = self.jobs[-1]
        self.app._clear_album()
        done([AlbumSummary(1, "Old", "Artist")])
        self.assertEqual(self.app.album_var.get(), "")
        self.assertFalse(self.app.results)

    def test_old_cover_cannot_replace_new_album_cover(self):
        a = self.app
        a.album = self.album("First", "https://example.invalid/first.jpg")
        a._cover_size_changed()
        _, old_done, old_failed = self.jobs[-1]
        _, album_done, _ = self.select_album("Second")
        album_done((self.album("Second", "https://example.invalid/second.jpg"), b"second cover", None))
        status = a.status_var.get()
        old_done(b"first cover")
        old_failed(RuntimeError("old cover"))
        self.assertEqual(a.cover_data, b"second cover")
        self.assertEqual(a.status_var.get(), status)

    def test_local_cover_selected_during_load_is_preserved(self):
        _, done, _ = self.select_album()
        a = self.app
        a.cover_request_id += 1
        a.cover_is_local = True
        a.cover_data = b"local cover"
        done((self.album(artwork_url="https://example.invalid/cover.jpg"), b"online cover", None))
        self.assertEqual(a.cover_data, b"local cover")
        self.assertEqual(len(self.jobs), 1)

    def test_album_cover_uses_latest_size(self):
        _, done, _ = self.select_album()
        self.app.cover_size_var.set("600 × 600")
        self.app._cover_size_changed()
        done((self.album(artwork_url="https://example.invalid/cover.jpg"), b"old size", None))
        self.jobs[-1][0]()
        self.app.client.download_cover.assert_called_once_with("https://example.invalid/cover.jpg", 600)

    def test_initial_load_downloads_cover_before_exposing_album(self):
        work, done, _ = self.select_album()
        self.app.client.get_album.return_value = self.album(artwork_url="https://example.invalid/cover.jpg")
        self.app.client.download_cover.return_value = b"cover"
        result = work()
        self.assertIsNone(self.app.album)
        done(result)
        self.assertEqual(self.app.cover_data, b"cover")

    def test_cover_worker_uses_captured_source_and_token(self):
        a = self.app
        a.album = self.album(artwork_url="https://example.invalid/cover.jpg")
        a.album.source = "discogs"
        a.discogs_token_var.set("test-token")
        a._cover_size_changed()
        work = self.jobs[-1][0]
        a.album = None
        a.discogs_token_var.set("")
        work()
        a.discogs_client.download_cover.assert_called_once_with("https://example.invalid/cover.jpg", 1200, "test-token")

    def test_search_keeps_working_while_converting(self):
        a = self.app
        a.album = self.album("Manual Album")
        a._convert()
        self.assertTrue(a.converting)
        a._post = lambda callback: None
        a._search()
        work, done, _ = self.jobs[-1]
        a.client.search_albums.return_value = [AlbumSummary(1, "Next", "Artist")]
        done(work())
        self.assertEqual([entry.title for entry in a.results], ["Next"])

    def test_import_caches_wav_durations(self):
        a = self.app
        directory = self.root / "wavs"
        directory.mkdir()
        for name in ("01.wav", "02.wav"):
            (directory / name).write_bytes(b"dummy")
        with patch("disctag.ui.tracks.filedialog.askdirectory", return_value=str(directory)), \
                patch("disctag.ui.tracks.source_duration", side_effect=lambda source: 1.0) as duration:
            a._import_wav()
            self.assertEqual(duration.call_count, 2)
            self.assertEqual(a._source_duration(a.sources[0]), 1.0)
            self.assertEqual(duration.call_count, 2)

    def test_source_duration_reads_uncached_path_once(self):
        a = self.app
        path = SourceTrack(self.root / "other.wav")
        with patch("disctag.ui.tracks.source_duration", return_value=2.5) as duration:
            self.assertEqual(a._source_duration(path), 2.5)
            self.assertEqual(a._source_duration(path), 2.5)
            duration.assert_called_once_with(path)

    def test_local_cover_respects_size_setting(self):
        import io

        from PIL import Image

        a = self.app
        cover = self.root / "cover.jpg"
        Image.new("RGB", (2000, 2000), "blue").save(cover, "JPEG")
        a.cover_size_var.set("600 × 600")
        with patch("disctag.ui.cover.filedialog.askopenfilename", return_value=str(cover)):
            a._choose_cover()
        self.assertEqual(Image.open(io.BytesIO(a.cover_data)).size, (600, 600))
        self.assertTrue(a.cover_is_local)

    def test_move_source_is_blocked_while_updating(self):
        a = self.app
        a.updating = True
        a.tracks_tree = Mock()
        a.tracks_tree.selection.return_value = ("0",)
        a.sources = [SourceTrack(self.root / "a.wav"), SourceTrack(self.root / "b.wav")]
        a.album = AlbumMetadata("Album", "Artist", "Artist",
                                tracks=[TrackMetadata("One", "Artist", 1), TrackMetadata("Two", "Artist", 2)])
        a._move_source(1)
        self.assertEqual([path.name for path in a.sources], ["a.wav", "b.wav"])

    def test_rows_without_local_wav_have_no_preview_icon(self):
        a = self.app
        a.sources = [SourceTrack(self.root / "01.wav")]
        a.source_durations = {a.sources[0]: 1.0}
        a.album = AlbumMetadata("Album", "Artist", "Artist", collection_id=1,
                                tracks=[TrackMetadata("One", "Artist", 1), TrackMetadata("Two", "Artist", 2)])
        a.preview.playing = False
        a.tracks_tree = Mock()
        a.tracks_tree.get_children.return_value = ()
        for name in ("insert_button", "align_button", "up_button"):
            setattr(a, name, Mock())
        a.match_var = Variable()
        DiscTagApp._refresh_tracks(a)
        icons = [call.kwargs["values"][0] for call in a.tracks_tree.insert.call_args_list]
        self.assertEqual(icons, ["▶", ""])
        a.tracks_tree.identify_region.return_value = "cell"
        a.tracks_tree.identify_column.return_value = "#1"
        a.tracks_tree.identify_row.return_value = "1"
        a._track_clicked(Mock(x=5, y=5))
        a.preview.toggle.assert_not_called()

    def test_insert_dialog_default_position_is_clamped(self):
        a = self.app
        a.sources = [SourceTrack(self.root / f"{index:02d}.wav") for index in range(1, 5)]
        a.album = AlbumMetadata("Album", "Artist", "Artist", collection_id=1,
                                tracks=[TrackMetadata("One", "Artist", 1), TrackMetadata("Two", "Artist", 2)])
        a.album_artist_var.set("Artist")
        a.tracks_tree = Mock()
        a.tracks_tree.selection.return_value = ("3",)
        a.root.winfo_rootx.return_value = a.root.winfo_rooty.return_value = 0
        a.root.winfo_width.return_value = a.root.winfo_height.return_value = 800
        toplevel = Mock()
        toplevel.winfo_width.return_value = toplevel.winfo_height.return_value = 200
        with (
            patch("disctag.ui.tracks.tk.Toplevel", return_value=toplevel),
            patch("disctag.ui.tracks.tk.IntVar") as int_var,
            patch("disctag.ui.tracks.tk.StringVar"),
            patch("disctag.ui.tracks.ttk"),
        ):
            a._insert_missing_track()
        int_var.assert_called_once_with(value=3)

    def test_easter_egg_skipped_when_image_missing(self):
        a = self.app
        a.easter_egg_dialog = None
        a.fireworks = None
        a.icon_image = None
        a.root.winfo_screenwidth.return_value = 1920
        with (
            patch("disctag.ui.easter_egg._resource_path", return_value=self.root / "missing.png"),
            patch("disctag.ui.easter_egg.tk.Toplevel") as toplevel,
        ):
            a._show_easter_egg()
        toplevel.assert_not_called()
        self.assertIsNone(a.easter_egg_dialog)

    def test_convert_confirms_cover_overwrite(self):
        a = self.app
        a.album = self.album("Manual Album")
        a.cover_data = b"x"
        directory = output_directory(self.root, a.album)
        directory.mkdir(parents=True)
        (directory / "cover.jpg").write_bytes(b"old")
        jobs_before = len(self.jobs)
        with patch("disctag.ui.processing.messagebox.askyesno", return_value=False) as ask:
            a._convert()
        ask.assert_called_once()
        self.assertEqual(len(self.jobs), jobs_before)

    def test_save_token_is_noop_until_loaded(self):
        a = self.app
        a.discogs_token_loaded = False
        a.discogs_token_var.set("")
        with patch("keyring.set_password") as set_password, patch("keyring.delete_password") as delete_password:
            DiscTagApp._save_discogs_token(a)
            set_password.assert_not_called()
            delete_password.assert_not_called()

    def test_save_token_after_load(self):
        a = self.app
        a.discogs_token_loaded = True
        a.discogs_token_var.set("")
        with patch("keyring.set_password") as set_password, patch("keyring.delete_password") as delete_password:
            DiscTagApp._save_discogs_token(a)
            delete_password.assert_called_once_with("DiscTag", "discogs_token")
            set_password.assert_not_called()
        a.discogs_token_var.set("tok")
        with patch("keyring.set_password") as set_password, patch("keyring.delete_password") as delete_password:
            DiscTagApp._save_discogs_token(a)
            set_password.assert_called_once_with("DiscTag", "discogs_token", "tok")
            delete_password.assert_not_called()

    def test_save_token_skips_keyring_when_unchanged(self):
        a = self.app
        a.discogs_token_var.set("")
        a.discogs_token_loaded = False
        DiscTagApp._discogs_token_ready(a, "")
        with patch("keyring.set_password") as set_password, patch("keyring.delete_password") as delete_password:
            DiscTagApp._save_discogs_token(a)
            DiscTagApp._save_discogs_token(a)
        delete_password.assert_not_called()
        set_password.assert_not_called()
        a.discogs_token_var.set(" new ")
        with patch("keyring.set_password") as set_password, patch("keyring.delete_password") as delete_password:
            DiscTagApp._save_discogs_token(a)
            DiscTagApp._save_discogs_token(a)
        set_password.assert_called_once_with("DiscTag", "discogs_token", "new")
        delete_password.assert_not_called()

    def test_save_token_deletes_stored_token_once(self):
        a = self.app
        a.discogs_token_var.set("")
        a.discogs_token_loaded = False
        DiscTagApp._discogs_token_ready(a, "stored")
        a.discogs_token_var.set("")
        with patch("keyring.set_password") as set_password, patch("keyring.delete_password") as delete_password:
            DiscTagApp._save_discogs_token(a)
            DiscTagApp._save_discogs_token(a)
        delete_password.assert_called_once_with("DiscTag", "discogs_token")
        set_password.assert_not_called()

    def test_save_token_retries_after_keyring_error(self):
        a = self.app
        a.discogs_token_loaded = True
        a._saved_discogs_token = ""
        a.discogs_token_var.set("tok")
        with patch("keyring.set_password", side_effect=[RuntimeError("locked"), None]) as set_password:
            DiscTagApp._save_discogs_token(a)
            DiscTagApp._save_discogs_token(a)
            DiscTagApp._save_discogs_token(a)
        self.assertEqual(set_password.call_count, 2)

    def test_discogs_token_ready(self):
        a = self.app
        a.discogs_token_var.set("")
        a.discogs_token_loaded = False
        a._discogs_token_ready("stored")
        self.assertEqual(a.discogs_token_var.get(), "stored")
        self.assertTrue(a.discogs_token_loaded)
        a.discogs_token_var.set("typed")
        a._discogs_token_ready("stored")
        self.assertEqual(a.discogs_token_var.get(), "typed")

    def test_map_binding_only_fires_for_root(self):
        from disctag import windowing

        root = Mock()
        windowing.configure_native_window(root, "#000000")
        callback = root.bind.call_args.args[1]
        root.after.assert_not_called()
        with patch("disctag.windowing.apply_native_window_style") as apply_style:
            callback(Mock(widget=Mock()))
            apply_style.assert_not_called()
            callback(Mock(widget=root))
            apply_style.assert_called_once_with(root, "#000000")

    def test_cover_embed_helpers_round_trip(self):
        from disctag.ui.common import _cover_embed_label, _cover_embed_labels, _cover_embed_value

        self.assertEqual(_cover_embed_labels(),
                         ["不嵌入", "500 × 500", "800 × 800", "1000 × 1000", "同 cover.jpg"])
        for value in ("none", "original", 500, 800, 1000):
            self.assertEqual(_cover_embed_value(_cover_embed_label(value)), value)
        self.assertEqual(_cover_embed_label("bogus"), "同 cover.jpg")
        self.assertEqual(_cover_embed_value("bogus"), "original")

    def test_convert_passes_embed_choice(self):
        a = self.app
        a.album = self.album("Manual Album")
        for label, expected in (("500 × 500", (True, 500)), ("不嵌入", (False, None)), ("同 cover.jpg", (True, None))):
            with self.subTest(label=label):
                a.cover_embed_var.set(label)
                with patch("disctag.ui.processing.convert_album") as convert:
                    a._convert()
                    convert.assert_not_called()
                    work, _, _ = self.jobs[-1]
                    work()
                    self.assertEqual(convert.call_args.args[-2:], expected)
                    a.converting = False
                    a.job_queue = JobQueue()

    def test_cancel_conversion_flow(self):
        from disctag.models import ConversionResult

        a = self.app
        a.album = self.album("Manual Album")
        a._save_settings = Mock()
        a._convert()
        self.assertTrue(a.converting)
        self.assertEqual(a.convert_button.configure.call_args.kwargs["text"], "取消处理")
        a._cancel_conversion()
        self.assertTrue(a.cancel_event.is_set())
        _, done, _ = self.jobs[-1]
        with patch("disctag.ui.processing.messagebox") as box:
            done(ConversionResult(self.root, cancelled=True))
            box.showinfo.assert_called_once()
        self.assertFalse(a.converting)
        self.assertIsNone(a.cancel_event)
        self.assertEqual(a.convert_button.configure.call_args.kwargs["text"], "开始处理")
        self.assertEqual(a.job_queue.jobs[0].status, CANCELLED)

    def queue_album(self, folder, title):
        a = self.app
        a.sources = [SourceTrack(self.root / folder / "01.wav")]
        a.album = self.album(title)
        a.album_var.set(title)
        self.assertTrue(a._enqueue_current())

    def test_queue_refuses_album_with_conflicting_output(self):
        a = self.app
        self.queue_album("one", "First")
        a.sources = [SourceTrack(self.root / "two" / "01.wav")]
        with patch("disctag.ui.processing.messagebox") as box:
            self.assertFalse(a._enqueue_current())
        box.showwarning.assert_called_once()
        self.assertEqual(box.showwarning.call_args.args[0], "输出文件冲突")
        self.assertIn("《First》", box.showwarning.call_args.args[1])
        box.askyesno.assert_not_called()
        self.assertEqual(len(a.job_queue.jobs), 1)

    def test_queue_refuses_running_wavs_that_will_be_trashed(self):
        from disctag.jobs import RUNNING

        a = self.app
        a.trash_sources_var.set(True)
        self.queue_album("one", "First")
        a.job_queue.jobs[0].status = RUNNING
        a.album = self.album("Renamed")
        a.album_var.set("Renamed")
        with patch("disctag.ui.processing.messagebox") as box:
            a._convert()
        box.showwarning.assert_called_once()
        self.assertEqual(box.showwarning.call_args.args[0], "无法加入队列")
        self.assertEqual(len(a.job_queue.jobs), 1)
        self.assertFalse(self.jobs)

    def test_queue_runs_albums_in_order_and_reports_once(self):
        from disctag.models import ConversionResult

        a = self.app
        a._save_settings = Mock()
        self.queue_album("one", "First")
        self.queue_album("two", "Second")
        self.queue_album("two", "Second (edited)")
        self.assertEqual([job.title for job in a.job_queue.jobs], ["First", "Second (edited)"])
        a.sources, a.album = [], None
        a._convert()
        with patch("disctag.ui.processing.messagebox") as box:
            for expected in ("First", "Second (edited)"):
                self.assertEqual(a.current_job.title, expected)
                _, done, _ = self.jobs[-1]
                done(ConversionResult(self.root, converted_files=[self.root / "x.flac"]))
            box.showinfo.assert_called_once()
            self.assertIn("2 张", box.showinfo.call_args.args[1])
        self.assertEqual([job.status for job in a.job_queue.jobs], [DONE, DONE])
        self.assertFalse(a.converting)

    def test_single_job_reports_cover_write_failure(self):
        from disctag.models import ConversionResult

        a = self.app
        a._save_settings = Mock()
        self.queue_album("one", "First")
        a.sources, a.album = [], None
        a._convert()
        with patch("disctag.ui.processing.messagebox") as box:
            _, done, _ = self.jobs[-1]
            done(ConversionResult(self.root, converted_files=[self.root / "x.flac"], cover_error="disk full"))
        box.showinfo.assert_not_called()
        box.showwarning.assert_called_once()
        self.assertIn("cover.jpg 写入失败：disk full", box.showwarning.call_args.args[1])
        self.assertEqual(a.job_queue.jobs[0].status, DONE)

    def test_queue_report_lists_cover_write_failure(self):
        from disctag.models import ConversionResult

        a = self.app
        a._save_settings = Mock()
        self.queue_album("one", "First")
        self.queue_album("two", "Second")
        a.sources, a.album = [], None
        a._convert()
        with patch("disctag.ui.processing.messagebox") as box:
            _, done, _ = self.jobs[-1]
            done(ConversionResult(self.root, converted_files=[self.root / "x.flac"], cover_error="disk full"))
            _, done, _ = self.jobs[-1]
            done(ConversionResult(self.root, converted_files=[self.root / "y.flac"]))
        box.showwarning.assert_called_once()
        text = box.showwarning.call_args.args[1]
        self.assertIn("《First》", text)
        self.assertIn("cover.jpg 写入失败：disk full", text)
        self.assertNotIn("《Second》", text)
        self.assertEqual([job.status for job in a.job_queue.jobs], [DONE, DONE])

    def test_cancel_keeps_rest_of_queue_pending(self):
        from disctag.models import ConversionResult

        a = self.app
        a._save_settings = Mock()
        self.queue_album("one", "First")
        self.queue_album("two", "Second")
        a.sources, a.album = [], None
        a._convert()
        a._cancel_conversion()
        _, done, _ = self.jobs[-1]
        with patch("disctag.ui.processing.messagebox"):
            done(ConversionResult(self.root, cancelled=True))
        self.assertEqual([job.status for job in a.job_queue.jobs], [CANCELLED, PENDING])
        self.assertFalse(a.converting)
        self.assertEqual(len(self.jobs), 1)

    def test_failed_album_does_not_stop_queue(self):
        from disctag.models import ConversionResult

        a = self.app
        a._save_settings = Mock()
        self.queue_album("one", "First")
        self.queue_album("two", "Second")
        a.sources, a.album = [], None
        a._convert()
        _, _, failed = self.jobs[-1]
        failed(RuntimeError("disk full"))
        _, done, _ = self.jobs[-1]
        with patch("disctag.ui.processing.messagebox") as box:
            done(ConversionResult(self.root, converted_files=[self.root / "x.flac"]))
            box.showwarning.assert_called_once()
        self.assertEqual(a.job_queue.jobs[0].message, "disk full")

    def test_convert_with_invalid_current_album_does_not_start_queue(self):
        a = self.app
        self.queue_album("one", "First")
        a.album = None
        with patch("disctag.ui.processing.messagebox.showwarning") as warning:
            a._convert()
        warning.assert_called_once()
        self.assertFalse(a.converting)

    def test_search_ranks_by_local_duration_and_caches_album(self):
        a = self.app
        a.sources = [SourceTrack(self.root / "1.wav"), SourceTrack(self.root / "2.wav")]
        a.source_durations = {a.sources[0]: 200.0, a.sources[1]: 180.0}
        a._post = lambda callback: None
        wrong = AlbumSummary(1, "Album", "Artist", track_count=2, country="US")
        right = AlbumSummary(2, "Album", "Artist", track_count=2, country="JP")
        a.client.search_albums.return_value = [wrong, right]

        def get_album(collection_id, country):
            seconds = (200, 300) if collection_id == 1 else (201, 179)
            return AlbumMetadata("Album", "Artist", "Artist", collection_id=collection_id, tracks=[
                TrackMetadata(f"T{i}", "Artist", i, duration_ms=s * 1000) for i, s in enumerate(seconds, 1)])

        a.client.get_album.side_effect = get_album
        a._search()
        work, done, _ = self.jobs[-1]
        done(work())
        self.assertEqual([entry.collection_id for entry in a.results], [2, 1])
        self.assertEqual(a.results_tree.insert.call_args_list[0].kwargs["values"][0], "✓ JP")
        self.assertIn("1 个版本与本地时长吻合", a.status_var.get())

        a.client.get_album.reset_mock()
        a.results_tree.selection.return_value = ("0",)
        a._album_selected()
        work, _, _ = self.jobs[-1]
        album, _, _ = work()
        a.client.get_album.assert_not_called()
        self.assertEqual(album.collection_id, 2)

    def test_musicbrainz_search_uses_toc_without_album_name(self):
        a = self.app
        a.metadata_source_var.set("MusicBrainz")
        a.album_var.set("")
        a.sources = [SourceTrack(self.root / "1.wav"), SourceTrack(self.root / "2.wav")]
        a.source_durations = {a.sources[0]: 2.0, a.sources[1]: 3.0}
        a.musicbrainz_client = Mock()
        a.musicbrainz_client.lookup_toc.return_value = [AlbumSummary("rel", "Album", "A", track_count=2, country="JP",
                                                                     source="musicbrainz", medium=1)]
        a._search()
        work, done, _ = self.jobs[-1]
        done(work())
        a.musicbrainz_client.lookup_toc.assert_called_once_with("1+2+525+150+300", "", "Artist")
        a.musicbrainz_client.search_albums.assert_not_called()
        self.assertEqual(a.results_tree.insert.call_args.kwargs["values"][0], "✓ JP")

        a.results_tree.selection.return_value = ("0",)
        a._album_selected()
        work, _, _ = self.jobs[-1]
        work()
        a.musicbrainz_client.get_album.assert_called_once_with("rel", 1)

    def test_musicbrainz_toc_verifies_media_of_same_release(self):
        a = self.app
        a.metadata_source_var.set("MusicBrainz")
        a.album_var.set("")
        a.sources = [SourceTrack(self.root / "1.wav"), SourceTrack(self.root / "2.wav")]
        a.source_durations = {a.sources[0]: 2.0, a.sources[1]: 3.0}
        a.musicbrainz_client = Mock()
        a.musicbrainz_client.lookup_toc.return_value = [
            AlbumSummary("rel", "Album", "A", track_count=2, country="JP", source="musicbrainz", medium=1),
            AlbumSummary("rel", "Album", "A", track_count=2, country="JP", source="musicbrainz", medium=2),
        ]

        def get_album(release_id, medium):
            lengths = (9000, 9000) if medium == 1 else (2000, 3000)
            return AlbumMetadata("Album", "A", "A", "", "", "", release_id, [
                TrackMetadata(f"T{n}", "A", n, 2, 1, 1, duration_ms=length) for n, length in enumerate(lengths, 1)
            ], source="musicbrainz")

        a.musicbrainz_client.get_album.side_effect = get_album
        a._search()
        work, done, _ = self.jobs[-1]
        results, fits, albums = work()
        self.assertEqual([entry.medium for entry in results], [2, 1])
        self.assertEqual({key[3]: fit.marker for key, fit in fits.items()}, {1: "", 2: "✓"})
        self.assertEqual(set(albums), {("musicbrainz", "JP", "rel", 1), ("musicbrainz", "JP", "rel", 2)})

    def test_musicbrainz_requires_album_or_wav(self):
        a = self.app
        a.metadata_source_var.set("MusicBrainz")
        a.album_var.set("")
        a.sources = []
        with patch("disctag.ui.catalog.messagebox.showwarning") as warning:
            a._search()
        warning.assert_called_once()
        self.assertEqual(self.jobs, [])

    def test_switch_language_blocked_while_processing(self):
        a = self.app
        a.converting = True
        a._restart = Mock()
        with patch("tkinter.messagebox.showwarning") as warning:
            a._switch_language()
        warning.assert_called_once()
        a._restart.assert_not_called()

    def test_switch_language_saves_and_restarts(self):
        from disctag import i18n

        a = self.app
        a._save_settings = Mock()
        a._restart = Mock()
        with patch("tkinter.messagebox.askyesno", return_value=True):
            a._switch_language()
        self.assertEqual(a.language_setting, "en" if i18n.language() == "zh" else "zh")
        a._save_settings.assert_called_once()
        a._restart.assert_called_once()

    def key(self, keysym, state=0):
        return Mock(keysym=keysym, state=state)

    def test_table_shortcuts_dispatch_and_stop_treeview_handling(self):
        a = self.app
        a._edit_track, a._toggle_playback, a._move_source = Mock(), Mock(), Mock()
        a.tracks_tree = Mock()
        a.tracks_tree.selection.return_value = ("2",)
        with patch("disctag.shortcuts.sys.platform", "win32"):
            self.assertEqual(a._on_table_key(self.key("Return")), "break")
            self.assertEqual(a._on_table_key(self.key("space")), "break")
            self.assertEqual(a._on_table_key(self.key("Up", 0x4)), "break")
            self.assertIsNone(a._on_table_key(self.key("Up")))
            self.assertIsNone(a._on_table_key(self.key("o", 0x4)))
        a._edit_track.assert_called_once()
        a._toggle_playback.assert_called_once_with(2)
        a._move_source.assert_called_once_with(-1)

    def test_global_shortcuts_ignore_table_actions(self):
        a = self.app
        a._import_wav, a._edit_track = Mock(), Mock()
        with patch("disctag.shortcuts.sys.platform", "win32"):
            self.assertEqual(a._on_global_key(self.key("o", 0x4)), "break")
            self.assertIsNone(a._on_global_key(self.key("Return")))
        a._import_wav.assert_called_once()
        a._edit_track.assert_not_called()

    def test_custom_shortcut_updates_hint_and_settings(self):
        from disctag import shortcuts

        a = self.app
        a._save_settings = Mock()
        a.track_hint_label = Mock()
        a._set_shortcut("edit_track", "F2")
        self.assertIn("F2", a.track_hint_label.configure.call_args.kwargs["text"])
        self.assertEqual(shortcuts.overrides(a.shortcut_map)["edit_track"], "F2")
        a._save_settings.assert_called_once()
        a._set_shortcut("edit_track", "")
        self.assertIn("双击", a.track_hint_label.configure.call_args.kwargs["text"])

    def update_info(self, notes=""):
        from disctag.updates import UpdateInfo

        return UpdateInfo(
            "9.9.9",
            "https://github.com/pretenderlu/DiscTag/releases/tag/v9.9.9",
            download_url="https://github.com/pretenderlu/DiscTag/releases/download/v9.9.9/DiscTagSetup-v9.9.9.exe",
            installer_name="DiscTagSetup-v9.9.9.exe",
            size=1234,
            notes=notes,
        )

    def show_update_dialog(self, info):
        a = self.app
        a.root.winfo_rootx.return_value = 100
        a.root.winfo_rooty.return_value = 100
        a.root.winfo_width.return_value = 1200
        a.root.winfo_height.return_value = 800
        toplevel = Mock()
        toplevel.winfo_width.return_value = 400
        toplevel.winfo_height.return_value = 300
        toplevel.winfo_exists.return_value = True
        with patch("disctag.ui.updates.tk.Toplevel", return_value=toplevel) as toplevel_class, \
                patch("disctag.ui.updates.tk.Text") as text, \
                patch("disctag.ui.updates.ttk.Frame"), \
                patch("disctag.ui.updates.ttk.Label"), \
                patch("disctag.ui.updates.ttk.Scrollbar"), \
                patch("disctag.ui.updates.ttk.Button") as button:
            a._show_update_dialog(info)
        return toplevel_class, toplevel, text, button

    def dialog_button(self, button, text):
        for call in button.call_args_list:
            if call.kwargs.get("text") == text:
                return call.kwargs["command"]
        raise AssertionError(f"no dialog button labelled {text}")

    def test_open_latest_release_shows_update_dialog_on_windows(self):
        a = self.app
        a.latest_update = self.update_info()
        a._show_update_dialog = Mock()
        with patch("disctag.ui.updates.sys") as app_sys, patch("disctag.ui.updates.webbrowser") as browser:
            app_sys.platform = "win32"
            a._open_latest_release()
        a._show_update_dialog.assert_called_once_with(a.latest_update)
        browser.open.assert_not_called()

    def test_open_latest_release_without_download_opens_browser(self):
        a = self.app
        a.latest_update = self.update_info()
        a.latest_release_url = a.latest_update.url
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform), \
                    patch("disctag.ui.updates.sys") as app_sys, \
                    patch("disctag.ui.updates.webbrowser") as browser:
                app_sys.platform = platform
                a._open_latest_release()
            browser.open.assert_called_once_with(a.latest_update.url, new=2)

    def test_start_update_download_opens_dialog(self):
        a = self.app
        a.latest_update = self.update_info()
        a._show_update_dialog = Mock()
        a._start_update_download()
        a._show_update_dialog.assert_called_once_with(a.latest_update)
        self.assertFalse(self.jobs)

    def test_start_update_download_blocked_while_converting(self):
        a = self.app
        a.converting = True
        a.latest_update = self.update_info()
        a._show_update_dialog = Mock()
        with patch("disctag.ui.updates.messagebox.showwarning") as warning:
            a._start_update_download()
        warning.assert_called_once()
        a._show_update_dialog.assert_not_called()
        self.assertFalse(self.jobs)

    def test_start_update_download_blocked_by_pending_queue(self):
        a = self.app
        self.queue_album("one", "Queued")
        a.latest_update = self.update_info()
        a._show_update_dialog = Mock()
        with patch("disctag.ui.updates.messagebox.showwarning") as warning:
            a._start_update_download()
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[0], "无法更新")
        a._show_update_dialog.assert_not_called()
        self.assertFalse(self.jobs)

    def test_begin_update_download_blocked_by_pending_queue(self):
        a = self.app
        self.queue_album("one", "Queued")
        with patch("disctag.ui.updates.messagebox.showwarning") as warning:
            a._begin_update_download(self.update_info())
        warning.assert_called_once()
        self.assertFalse(a.updating)
        self.assertFalse(self.jobs)

    def test_begin_update_download_disables_queue_actions(self):
        a = self.app
        a.queue_window = Mock()
        a._begin_update_download(self.update_info())
        a.enqueue_button.configure.assert_called_with(state="disabled")
        a.queue_window.refresh.assert_called()
        a.queue_window.refresh.reset_mock()
        with patch("disctag.ui.updates.messagebox.askyesnocancel", return_value=None):
            a._update_failed(RuntimeError("boom"))
        a.enqueue_button.configure.assert_called_with(state="normal")
        a.queue_window.refresh.assert_called()

    def test_queue_window_start_disabled_while_updating(self):
        from disctag.ui.queue_window import QueueWindow

        a = self.app
        self.queue_album("one", "Queued")
        window = QueueWindow.__new__(QueueWindow)
        window.app = a
        window.tree = Mock()
        window.tree.selection.return_value = ()
        for name in ("remove_button", "retry_button", "clear_button", "start_button"):
            setattr(window, name, Mock())
        a.updating = True
        window._update_buttons()
        window.start_button.configure.assert_called_with(state="disabled")
        a.updating = False
        window._update_buttons()
        window.start_button.configure.assert_called_with(state="normal")

    def test_install_update_stops_preview(self):
        a = self.app
        a._save_settings = Mock()
        order = []
        a.preview.stop.side_effect = lambda: order.append("stop")
        a.root.destroy.side_effect = lambda: order.append("destroy")
        with patch("disctag.ui.updates.subprocess.Popen", side_effect=lambda *args, **kwargs: order.append("popen")):
            a._install_update(self.root / "DiscTagSetup.exe")
        self.assertEqual(order, ["stop", "popen", "destroy"])

    def test_update_dialog_yes_starts_download(self):
        a = self.app
        info = self.update_info()
        a._begin_update_download = Mock()
        _, _, _, button = self.show_update_dialog(info)
        self.dialog_button(button, "是")()
        a._begin_update_download.assert_called_once_with(info)

    def test_update_dialog_no_closes_without_browser(self):
        a = self.app
        info = self.update_info()
        a._begin_update_download = Mock()
        _, toplevel, _, button = self.show_update_dialog(info)
        with patch("disctag.ui.updates.webbrowser") as browser:
            self.dialog_button(button, "否")()
        browser.open.assert_not_called()
        a._begin_update_download.assert_not_called()
        toplevel.destroy.assert_called_once()
        self.assertIsNone(a.update_dialog)

    def test_update_dialog_shows_release_notes(self):
        info = self.update_info(notes="- 修复若干问题\n- 新增下载重试\n")
        _, _, text, _ = self.show_update_dialog(info)
        text.return_value.insert.assert_called_once_with("1.0", "- 修复若干问题\n- 新增下载重试")
        text.return_value.configure.assert_any_call(state="disabled")

    def test_update_dialog_is_not_duplicated(self):
        a = self.app
        info = self.update_info()
        toplevel_class, toplevel, _, _ = self.show_update_dialog(info)
        toplevel_class.assert_called_once()
        self.assertIs(a.update_dialog, toplevel)
        with patch("disctag.ui.updates.tk.Toplevel") as again:
            a._show_update_dialog(info)
        again.assert_not_called()
        self.assertIs(a.update_dialog, toplevel)

    def test_begin_update_download_starts_download(self):
        a = self.app
        a._begin_update_download(self.update_info())
        self.assertTrue(a.updating)
        self.assertEqual(len(self.jobs), 1)
        a.convert_button.configure.assert_called_with(state="disabled")
        a.clear_button.configure.assert_called_with(state="disabled")

    def test_update_failed_retry_restarts_download(self):
        a = self.app
        a.latest_update = self.update_info()
        a.updating = True
        a._start_update_download = Mock()
        with patch("disctag.ui.updates.messagebox.askyesnocancel", return_value=True), \
                patch("disctag.ui.updates.webbrowser") as browser:
            a._update_failed(RuntimeError("boom"))
        a._start_update_download.assert_called_once_with()
        browser.open.assert_not_called()
        self.assertFalse(a.updating)
        a.convert_button.configure.assert_called_with(state="normal")

    def test_update_failed_no_opens_release_page(self):
        a = self.app
        a.latest_update = self.update_info()
        a.updating = True
        a._start_update_download = Mock()
        with patch("disctag.ui.updates.messagebox.askyesnocancel", return_value=False), \
                patch("disctag.ui.updates.webbrowser") as browser:
            a._update_failed(RuntimeError("boom"))
        browser.open.assert_called_once_with(a.latest_update.url, new=2)
        a._start_update_download.assert_not_called()
        self.assertFalse(a.updating)

    def test_update_failed_cancel_does_nothing(self):
        a = self.app
        a.latest_update = self.update_info()
        a.updating = True
        a._start_update_download = Mock()
        with patch("disctag.ui.updates.messagebox.askyesnocancel", return_value=None), \
                patch("disctag.ui.updates.webbrowser") as browser:
            a._update_failed(RuntimeError("boom"))
        browser.open.assert_not_called()
        a._start_update_download.assert_not_called()
        self.assertFalse(a.updating)
