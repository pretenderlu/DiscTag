"""DiscTag main window: startup, threading helpers, settings and shutdown."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from .discogs import DiscogsClient
from .itunes import COVER_SIZES, ITunesClient
from .jobs import ConversionJob, JobQueue
from .models import AlbumMetadata, AlbumSummary
from .musicbrainz import MusicBrainzClient
from .playback import AudioPreview
from .ui.catalog import CatalogMixin
from .ui.common import (
    BACKGROUND,
    COVER_EMBED_SIZES,
    LATEST_RELEASE_URL,
    _cover_embed_label,
    _cover_embed_value,
    _cover_size_label,
    _settings_path,
)
from .ui.cover import CoverMixin
from .ui.easter_egg import EasterEggMixin
from .ui.layout import LayoutMixin
from .ui.processing import ProcessingMixin
from .ui.queue_window import QueueWindow
from .ui.theme import ThemeMixin
from .ui.tracks import TracksMixin
from .ui.updates import UpdateMixin
from .windowing import apply_native_window_style, configure_native_window


class DiscTagApp(ThemeMixin, LayoutMixin, EasterEggMixin, TracksMixin, CatalogMixin, CoverMixin, ProcessingMixin, UpdateMixin):
    def __init__(self):
        self.ui_font = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI"
        self.ui_semibold = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI Semibold"
        self.cjk_font = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
        self._enable_dpi_awareness()
        self.root = tk.Tk()
        try:
            self.root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.root.title("DiscTag — CD 音频处理与标签工具")
        self.ui_scale = 1.0
        if sys.platform == "win32":
            pixels_per_inch = self.root.winfo_fpixels("1i")
            self.ui_scale = max(1.0, pixels_per_inch / 96)
            self.root.tk.call("tk", "scaling", pixels_per_inch / 72)
        self._configure_window()
        configure_native_window(self.root, "#1D1C31")
        self.root.configure(bg=BACKGROUND)
        self.settings = self._load_settings()
        self.client = ITunesClient()
        self.discogs_client = DiscogsClient()
        self.musicbrainz_client = MusicBrainzClient()
        self.preview = AudioPreview(self.root, self._playback_changed)
        self.sources: list[Path] = []
        self.source_durations: dict[Path, float | None] = {}
        self.results: list[AlbumSummary] = []
        self.result_markers: dict[tuple, str] = {}
        self.album_cache: dict[tuple, AlbumMetadata] = {}
        self.album: AlbumMetadata | None = None
        self.album_region = ""
        self.metadata_dirty = False
        self.cover_data: bytes | None = None
        self.cover_preview = None
        self.icon_image = None
        self.last_output: Path | None = None
        self.latest_release_url = LATEST_RELEASE_URL
        self.latest_update = None
        self.updating = False
        self.converting = False
        self.cancel_event: threading.Event | None = None
        self.job_queue = JobQueue()
        self.queue_run_jobs: list[ConversionJob] = []
        self.current_job: ConversionJob | None = None
        self.queue_window: QueueWindow | None = None
        self.conversion_thread: threading.Thread | None = None
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.icon_click_count = 0
        self.first_icon_click_time = 0.0
        self.easter_egg_dialog = None
        self.easter_egg_image = None
        self.update_dialog = None
        self.fireworks = None
        self.album_var = tk.StringVar()
        self.artist_var = tk.StringVar()
        self.album_artist_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.genre_var = tk.StringVar()
        self.source_var = tk.StringVar(value="尚未选择 WAV 文件夹")
        self.output_var = tk.StringVar(value=self.settings.get("output", str(Path.home() / "Music" / "DiscTag")))
        self.format_var = tk.StringVar(value=self.settings.get("format", "flac"))
        self.quality_var = tk.StringVar(value=self.settings.get("quality", "320 kbps"))
        self.region_var = tk.StringVar(value=self.settings.get("region", "US"))
        self.metadata_source_var = tk.StringVar(value=self.settings.get("metadata_source", "iTunes / Apple Music"))
        self.discogs_token_var = tk.StringVar()
        self.discogs_token_loaded = False
        saved_cover_size = self.settings.get("cover_size", 1200)
        if saved_cover_size not in COVER_SIZES:
            saved_cover_size = 1200
        self.cover_size_var = tk.StringVar(value=_cover_size_label(saved_cover_size))
        saved_cover_embed = self.settings.get("cover_embed", "original")
        if saved_cover_embed not in {"none", "original", *COVER_EMBED_SIZES}:
            saved_cover_embed = "original"
        self.cover_embed_var = tk.StringVar(value=_cover_embed_label(saved_cover_embed))
        self.cover_info_var = tk.StringVar()
        self.cover_request_id = 0
        self.album_request_id = 0
        self.search_request_id = 0
        self.cover_is_local = False
        self.album_info_var = tk.StringVar(value="搜索并选择专辑，或进入手动模式")
        self.match_var = tk.StringVar(value="先导入 WAV 文件")
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self._configure_styles()
        self._load_icon()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(50, self._drain_ui_queue)
        self.root.after(300, self._check_for_updates)
        self._reveal()

    def _reveal(self) -> None:
        self.root.update()
        try:
            apply_native_window_style(self.root, "#1D1C31")
        except (OSError, AttributeError):
            pass
        self.root.update_idletasks()
        try:
            self.root.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        self._run_async(self._read_discogs_token, self._discogs_token_ready, lambda _error: self._discogs_token_ready(""))

    @staticmethod
    def _enable_dpi_awareness() -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                raise OSError("Unable to enable per-monitor DPI awareness")
        except (AttributeError, OSError):
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass

    def _configure_window(self) -> None:
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        minimum_width = min(self._px(1179), int(screen_width * 0.96))
        minimum_height = min(self._px(880), int(screen_height * 0.94))
        width = max(minimum_width, min(self._px(1440), int(screen_width * 0.92)))
        height = max(minimum_height, min(self._px(1100), int(screen_height * 0.92)))
        self.root.minsize(minimum_width, minimum_height)
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _px(self, value: float) -> int:
        return max(1, round(value * self.ui_scale))

    def run(self) -> None:
        self.root.mainloop()

    def _run_async(self, work, done, failed) -> threading.Thread:
        def runner():
            try:
                result = work()
            except Exception as exc:
                self._post(lambda error=exc: failed(error))
            else:
                self._post(lambda: done(result))

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        return thread

    def _post(self, callback) -> None:
        """Queues a callback for the Tk main thread; Tk itself must only be touched from that thread."""
        self._ui_queue.put(callback)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                except Exception:
                    import traceback

                    traceback.print_exc()
        except queue.Empty:
            pass
        try:
            self.root.after(30, self._drain_ui_queue)
        except tk.TclError:
            pass

    def _close(self) -> None:
        pending = self.job_queue.pending_count()
        if self.converting:
            message = "现在退出会中断未完成的处理"
            message += f"，队列中还有 {pending} 张专辑未处理" if pending else ""
            if not messagebox.askyesno("处理仍在进行", f"{message}，确定退出吗？", parent=self.root):
                return
        elif pending and not messagebox.askyesno("队列尚未处理", f"队列中还有 {pending} 张专辑未处理，退出后队列会清空。确定退出吗？", parent=self.root):
            return
        if self.converting and self.cancel_event is not None:
            # 让工作线程结束 FFmpeg 并清理临时目录，避免残留进程和 .disctag-* 文件夹。
            self.cancel_event.set()
            if self.conversion_thread is not None:
                self.conversion_thread.join(timeout=5)
        self.preview.stop()
        self._close_easter_egg()
        self._close_update_dialog()
        self._save_settings()
        self.root.destroy()

    def _load_settings(self) -> dict:
        try:
            return json.loads(_settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        self._save_discogs_token()
        settings = {
            "output": self.output_var.get(),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "region": self.region_var.get(),
            "metadata_source": self.metadata_source_var.get(),
            "cover_size": self._cover_size_value(),
            "cover_embed": _cover_embed_value(self.cover_embed_var.get()),
        }
        try:
            path = _settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            pass
