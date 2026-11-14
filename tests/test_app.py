import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from disctag.app import DiscTagApp
from disctag.audio import output_directory
from disctag.models import AlbumMetadata, AlbumSummary, TrackMetadata


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
        a.quality_var = Variable("320 kbps")
        a.cover_size_var = Variable("1200 × 1200")
        a.cover_embed_var = Variable("同 cover.jpg")
        for name in ("root", "search_button", "region_label", "region_combo", "token_header",
                     "discogs_token_entry", "results_tree", "convert_button", "clear_button",
                     "progress", "preview", "cover_label", "album_entry"):
            setattr(a, name, Mock())
        a.results_tree.get_children.return_value = ()
        a.sources = [self.root / "source.wav"]
        a.source_durations = {}
        a.album = None
        a.album_region = ""
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
        with patch("disctag.app.messagebox.askyesno", return_value=False) as ask:
            a._convert()
        ask.assert_called_once()
        self.assertFalse(self.jobs)
        self.assertEqual(target.read_bytes(), b"existing")
        self.assertEqual(a.album.tracks[0].track_number, 3)

    def test_switching_source_restores_search_and_ignores_old_callbacks(self):
        a = self.app
        a._search()
        _, done, failed = self.jobs[-1]
        a.metadata_source_var.set("Discogs")
        a._metadata_source_changed(object())
        a.search_button.configure.assert_called_with(state="normal")
        with patch("disctag.app.messagebox.showerror") as error:
            done([AlbumSummary(1, "Old", "Artist")])
            failed(RuntimeError("old request"))
        self.assertFalse(a.results)
        error.assert_not_called()

    def test_source_switch_does_not_enable_search_while_busy(self):
        for flag in ("converting", "updating"):
            with self.subTest(flag=flag):
                setattr(self.app, flag, True)
                self.app._metadata_source_changed(object())
                self.app.search_button.configure.assert_called_with(state="disabled")
                setattr(self.app, flag, False)

    def test_manual_mode_invalidates_pending_album(self):
        _, done, failed = self.select_album()
        self.app._manual_mode()
        with patch("disctag.app.messagebox.showerror") as error:
            done((self.album(), None, None))
            failed(RuntimeError("old request"))
        self.assertEqual(self.app.album.title, "Manual Album")
        self.assertTrue(self.app.metadata_dirty)
        error.assert_not_called()

    def test_import_invalidates_pending_album(self):
        _, done, _ = self.select_album()
        source = self.root / "new.wav"
        source.touch()
        with patch("disctag.app.filedialog.askdirectory", return_value=str(self.root)):
            self.app._import_wav()
        done((self.album(), None, None))
        self.assertIsNone(self.app.album)
        self.assertEqual(self.app.sources, [source])

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

    def test_conversion_invalidates_pending_search(self):
        a = self.app
        a.album = self.album("Manual Album")
        a._search()
        _, done, _ = self.jobs[-1]
        a._convert()
        done([AlbumSummary(1, "Old", "Artist")])
        self.assertTrue(a.converting)
        self.assertFalse(a.results)
        a.search_button.configure.assert_called_with(state="disabled")

    def test_import_caches_wav_durations(self):
        a = self.app
        directory = self.root / "wavs"
        directory.mkdir()
        for name in ("01.wav", "02.wav"):
            (directory / name).write_bytes(b"dummy")
        with patch("disctag.app.filedialog.askdirectory", return_value=str(directory)), \
                patch("disctag.app.wav_duration", side_effect=lambda path: 1.0) as duration:
            a._import_wav()
            self.assertEqual(duration.call_count, 2)
            self.assertEqual(a._source_duration(a.sources[0]), 1.0)
            self.assertEqual(duration.call_count, 2)

    def test_source_duration_reads_uncached_path_once(self):
        a = self.app
        path = self.root / "other.wav"
        with patch("disctag.app.wav_duration", return_value=2.5) as duration:
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
        with patch("disctag.app.filedialog.askopenfilename", return_value=str(cover)):
            a._choose_cover()
        self.assertEqual(Image.open(io.BytesIO(a.cover_data)).size, (600, 600))
        self.assertTrue(a.cover_is_local)

    def test_move_source_is_blocked_while_converting(self):
        a = self.app
        a.converting = True
        a.tracks_tree = Mock()
        a.tracks_tree.selection.return_value = ("0",)
        a.sources = [self.root / "a.wav", self.root / "b.wav"]
        a.album = AlbumMetadata("Album", "Artist", "Artist",
                                tracks=[TrackMetadata("One", "Artist", 1), TrackMetadata("Two", "Artist", 2)])
        a._move_source(1)
        self.assertEqual([path.name for path in a.sources], ["a.wav", "b.wav"])

    def test_convert_confirms_cover_overwrite(self):
        a = self.app
        a.album = self.album("Manual Album")
        a.cover_data = b"x"
        directory = output_directory(self.root, a.album)
        directory.mkdir(parents=True)
        (directory / "cover.jpg").write_bytes(b"old")
        jobs_before = len(self.jobs)
        with patch("disctag.app.messagebox.askyesno", return_value=False) as ask:
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
        from disctag.app import _cover_embed_label, _cover_embed_labels, _cover_embed_value

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
                with patch("disctag.app.convert_album") as convert:
                    a._convert()
                    convert.assert_not_called()
                    work, _, _ = self.jobs[-1]
                    work()
                    self.assertEqual(convert.call_args.args[-2:], expected)
                    a.converting = False

    def test_cancel_conversion_flow(self):
        from disctag.models import ConversionResult

        a = self.app
        a.album = self.album("Manual Album")
        a._save_settings = Mock()
        with patch("disctag.app.convert_album"):
            a._convert()
        self.assertTrue(a.converting)
        self.assertEqual(a.convert_button.configure.call_args.kwargs["text"], "取消处理")
        a._cancel_conversion()
        self.assertTrue(a.cancel_event.is_set())
        with patch("disctag.app.messagebox") as box:
            a._conversion_done(ConversionResult(self.root, cancelled=True))
            box.showinfo.assert_called_once()
        self.assertFalse(a.converting)
        self.assertIsNone(a.cancel_event)
        self.assertEqual(a.convert_button.configure.call_args.kwargs["text"], "开始处理")

    def test_search_ranks_by_local_duration_and_caches_album(self):
        a = self.app
        a.sources = [self.root / "1.wav", self.root / "2.wav"]
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
        a.sources = [self.root / "1.wav", self.root / "2.wav"]
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

    def test_musicbrainz_requires_album_or_wav(self):
        a = self.app
        a.metadata_source_var.set("MusicBrainz")
        a.album_var.set("")
        a.sources = []
        with patch("disctag.app.messagebox.showwarning") as warning:
            a._search()
        warning.assert_called_once()
        self.assertEqual(self.jobs, [])

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
        with patch("disctag.app.tk.Toplevel", return_value=toplevel) as toplevel_class, \
                patch("disctag.app.tk.Text") as text, \
                patch("disctag.app.ttk.Frame"), \
                patch("disctag.app.ttk.Label"), \
                patch("disctag.app.ttk.Scrollbar"), \
                patch("disctag.app.ttk.Button") as button:
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
        with patch("disctag.app.sys") as app_sys, patch("disctag.app.webbrowser") as browser:
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
                    patch("disctag.app.sys") as app_sys, \
                    patch("disctag.app.webbrowser") as browser:
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
        with patch("disctag.app.messagebox.showwarning") as warning:
            a._start_update_download()
        warning.assert_called_once()
        a._show_update_dialog.assert_not_called()
        self.assertFalse(self.jobs)

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
        with patch("disctag.app.webbrowser") as browser:
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
        with patch("disctag.app.tk.Toplevel") as again:
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
        with patch("disctag.app.messagebox.askyesnocancel", return_value=True), \
                patch("disctag.app.webbrowser") as browser:
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
        with patch("disctag.app.messagebox.askyesnocancel", return_value=False), \
                patch("disctag.app.webbrowser") as browser:
            a._update_failed(RuntimeError("boom"))
        browser.open.assert_called_once_with(a.latest_update.url, new=2)
        a._start_update_download.assert_not_called()
        self.assertFalse(a.updating)

    def test_update_failed_cancel_does_nothing(self):
        a = self.app
        a.latest_update = self.update_info()
        a.updating = True
        a._start_update_download = Mock()
        with patch("disctag.app.messagebox.askyesnocancel", return_value=None), \
                patch("disctag.app.webbrowser") as browser:
            a._update_failed(RuntimeError("boom"))
        browser.open.assert_not_called()
        a._start_update_download.assert_not_called()
        self.assertFalse(a.updating)
