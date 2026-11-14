from __future__ import annotations

import copy
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from . import __version__
from .audio import (
    clean_track_title,
    convert_album,
    find_ffmpeg,
    natural_key,
    output_directory,
    output_path,
    wav_duration,
)
from .discogs import DiscogsClient
from .editing import (
    MANUAL_ORIGINS,
    EditError,
    album_info_text,
    can_insert,
    delete_manual_track,
    duration_mismatch,
    fill_missing_by_duration,
    insert_manual_track,
    manual_tracks,
    match_status,
    track_label,
)
from .itunes import COVER_SIZES, ITUNES_REGIONS, ITunesClient
from .fireworks import Fireworks
from .models import AlbumMetadata, AlbumSummary, ConversionResult, renumber_tracks
from .playback import AudioPreview
from .musicbrainz import MusicBrainzClient, MusicBrainzError, toc_from_durations
from .ranking import EXACT, DurationFit, candidates_to_verify, rank_results, result_key, verify_candidates
from .rounded_panel import RoundedPanel
from .rounded_style import apply_rounded_styles
from .updates import download_update, check_for_updates
from .windowing import apply_native_window_style, configure_native_window


BACKGROUND = "#F3F5FA"
CARD = "#FFFFFF"
INK = "#202236"
MUTED = "#73778C"
ACCENT = "#6857E5"
ACCENT_DARK = "#5140C8"
BORDER = "#E3E6EF"
SUCCESS = "#167A5B"
DANGER = "#B34452"
REPOSITORY_URL = "https://github.com/pretenderlu/DiscTag"
LATEST_RELEASE_URL = f"{REPOSITORY_URL}/releases/latest"
COVER_EMBED_SIZES = (500, 800, 1000)
SOURCE_ITUNES = "iTunes / Apple Music"
SOURCE_DISCOGS = "Discogs"
SOURCE_MUSICBRAINZ = "MusicBrainz"
SOURCE_HINTS = {
    SOURCE_ITUNES: "全部地区：美国、日本、中国大陆、中国香港、中国台湾。\n不同地区的专辑版本会分别保留。",
    SOURCE_DISCOGS: "Discogs 收录实体唱片的地区版本、再版与目录号。\n需要个人令牌，请求频率受限。",
    SOURCE_MUSICBRAINZ: "已导入 WAV 时会先按音轨时长识别光盘（TOC），可不填专辑名。\n✓ 表示与本地音轨吻合；数据来自 MusicBrainz 与 Cover Art Archive。",
}


class DiscTagApp:
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

    def _discogs_token_ready(self, token: str) -> None:
        if token and not self.discogs_token_var.get():
            self.discogs_token_var.set(token)
        self.discogs_token_loaded = True

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
        height = max(minimum_height, min(self._px(1000), int(screen_height * 0.92)))
        self.root.minsize(minimum_width, minimum_height)
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _px(self, value: float) -> int:
        return max(1, round(value * self.ui_scale))

    def run(self) -> None:
        self.root.mainloop()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BACKGROUND, foreground=INK, font=(self.ui_font, 11))
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=(self.ui_font, 11))
        style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED, font=(self.ui_font, 10))
        style.configure("Title.Card.TLabel", background=CARD, foreground=INK, font=(self.ui_semibold, 15))
        style.configure("Match.Card.TLabel", background=CARD, foreground=MUTED, font=(self.ui_font, 10))
        style.configure(
            "TEntry",
            fieldbackground="#F8F9FC",
            foreground=INK,
            bordercolor="#DCE0EB",
            lightcolor="#DCE0EB",
            darkcolor="#DCE0EB",
            padding=self._px(9),
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)], fieldbackground=[("focus", CARD)])
        style.configure(
            "TCombobox",
            fieldbackground="#F8F9FC",
            foreground=INK,
            background="#F8F9FC",
            bordercolor="#DCE0EB",
            lightcolor="#DCE0EB",
            darkcolor="#DCE0EB",
            arrowcolor=ACCENT,
            arrowsize=self._px(13),
            relief="flat",
            padding=(self._px(10), self._px(11)),
        )
        style.map(
            "TCombobox",
            bordercolor=[("focus", ACCENT)],
            fieldbackground=[("readonly", "#F8F9FC")],
            background=[("readonly", "#F8F9FC"), ("active", "#EEF0F6")],
            arrowcolor=[("readonly", ACCENT), ("active", ACCENT_DARK)],
            selectbackground=[("readonly", "#F8F9FC")],
            selectforeground=[("readonly", INK)],
        )
        self.root.option_add("*TCombobox*Listbox.background", CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#EAE6FF")
        self.root.option_add("*TCombobox*Listbox.selectForeground", INK)
        self.root.option_add("*TCombobox*Listbox.font", (self.ui_font, 10))
        style.configure(
            "TButton",
            font=(self.ui_font, 10),
            padding=(self._px(10), self._px(10)),
            borderwidth=0,
            relief="flat",
            background="#EEF0F6",
            foreground="#34384A",
            focusthickness=1,
            focuscolor="#C9C2FF",
        )
        style.map(
            "TButton",
            background=[("disabled", "#F5F6F9"), ("pressed", "#D9DDE9"), ("active", "#E3E6F0")],
            foreground=[("disabled", "#A4A8B5")],
        )
        for button_style in ("Accent.TButton", "Convert.TButton"):
            style.configure(
                button_style,
                background=ACCENT,
                foreground="#FFFFFF",
                font=(self.ui_semibold, 10),
                padding=(self._px(10), self._px(10)),
                borderwidth=0,
                relief="flat",
            )
            style.map(
                button_style,
                background=[("disabled", "#C8C3EA"), ("pressed", "#4535B4"), ("active", ACCENT_DARK)],
                foreground=[("disabled", "#F2F0FA")],
            )
        style.configure(
            "Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=INK,
            rowheight=self._px(36),
            borderwidth=0,
            relief="flat",
            font=(self.ui_font, 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#F5F6FA",
            foreground=MUTED,
            font=(self.ui_semibold, 10),
            padding=(self._px(7), self._px(9)),
            borderwidth=0,
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#EAE6FF")], foreground=[("selected", INK)])
        style.map("Treeview.Heading", background=[("active", "#F5F6FA")])
        for selector_style in ("TRadiobutton", "TCheckbutton"):
            style.configure(
                selector_style,
                background=CARD,
                foreground=INK,
                font=(self.ui_font, 10),
                indicatorcolor="#F8F9FC",
                selectcolor=ACCENT,
                bordercolor="#C8CDDB",
                focusthickness=0,
            )
            style.map(
                selector_style,
                indicatorcolor=[("active", "#EAE6FF"), ("selected", ACCENT)],
                selectcolor=[("selected", ACCENT), ("active", ACCENT_DARK)],
            )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#E8EAF2",
            background=ACCENT,
            bordercolor="#E8EAF2",
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=self._px(8),
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#CDD2DF",
            troughcolor=CARD,
            bordercolor=CARD,
            lightcolor=CARD,
            darkcolor=CARD,
            arrowcolor=MUTED,
            arrowsize=self._px(12),
        )
        style.map("Vertical.TScrollbar", background=[("active", "#AEB5C8"), ("pressed", "#979FB5")])
        self.rounded_style_images = apply_rounded_styles(self.root, style, self.ui_scale)

    def _load_icon(self) -> None:
        icon_path = _resource_path("assets/icon.png")
        if not icon_path.is_file():
            return
        image = Image.open(icon_path).convert("RGBA")
        self.icon_image = ImageTk.PhotoImage(image.resize((256, 256), Image.Resampling.LANCZOS))
        self.root.iconphoto(True, self.icon_image)
        header_size = self._px(62)
        self.header_icon = ImageTk.PhotoImage(image.resize((header_size, header_size), Image.Resampling.LANCZOS))

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg="#1D1C31", height=self._px(96))
        header.pack(fill="x")
        header.pack_propagate(False)
        header_content = tk.Frame(header, bg="#1D1C31")
        header_content.pack(fill="both", expand=True, padx=self._px(26), pady=self._px(16))
        if hasattr(self, "header_icon"):
            self.header_icon_label = tk.Label(header_content, image=self.header_icon, bg="#1D1C31")
            self.header_icon_label.pack(side="left", padx=(0, self._px(15)))
            self.header_icon_label.bind("<Button-1>", self._icon_clicked)
        titles = tk.Frame(header_content, bg="#1D1C31")
        titles.pack(side="left", fill="y")
        tk.Label(titles, text="DiscTag", bg="#1D1C31", fg="#FFFFFF", font=(self.ui_semibold, 24)).pack(anchor="w")
        tk.Label(titles, text="让每一张 CD，都有完整而漂亮的音乐资料", bg="#1D1C31", fg="#BAB8D0", font=(self.cjk_font, 10)).pack(anchor="w")
        tk.Label(header_content, text="WAV  →  WAV / FLAC / MP3", bg="#1D1C31", fg="#BDB5FF", font=(self.ui_semibold, 12)).pack(side="right", pady=self._px(14))

        body = ttk.Frame(self.root, padding=(self._px(22), self._px(18), self._px(22), self._px(12)))
        body.pack(fill="both", expand=True)
        source_panel = RoundedPanel(body, padding=self._px(16), radius=self._px(10), fit_height=True)
        source_card = source_panel.content
        source_panel.pack(fill="x", pady=(0, self._px(12)))
        ttk.Label(source_card, text="1  导入 CD 音轨", style="Title.Card.TLabel").pack(side="left", padx=(0, self._px(18)))
        ttk.Button(source_card, text="选择 WAV 文件夹", command=self._import_wav).pack(side="left")
        ttk.Label(source_card, textvariable=self.source_var, style="Muted.Card.TLabel").pack(side="left", padx=self._px(16), fill="x", expand=True)

        content = ttk.Frame(body)
        content.pack(fill="both", expand=True)
        left_panel = RoundedPanel(content, padding=self._px(18), width=self._px(405), radius=self._px(10))
        left = left_panel.content
        left_panel.pack(side="left", fill="y", padx=(0, self._px(12)))
        left_panel.pack_propagate(False)
        right_panel = RoundedPanel(content, padding=self._px(18), radius=self._px(10))
        right = right_panel.content
        right_panel.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="2  匹配专辑资料", style="Title.Card.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(left, text="专辑名称", style="Card.TLabel").pack(anchor="w")
        self.album_entry = ttk.Entry(left, textvariable=self.album_var)
        self.album_entry.pack(fill="x", pady=(4, 6))
        ttk.Label(left, text="歌手名称", style="Card.TLabel").pack(anchor="w")
        ttk.Entry(left, textvariable=self.artist_var).pack(fill="x", pady=(4, 6))
        ttk.Label(left, text="曲库来源", style="Card.TLabel").pack(anchor="w")
        self.metadata_source_combo = ttk.Combobox(
            left,
            textvariable=self.metadata_source_var,
            values=(SOURCE_ITUNES, SOURCE_DISCOGS, SOURCE_MUSICBRAINZ),
            state="readonly",
        )
        self.metadata_source_combo.pack(fill="x", pady=(4, 6))
        self.metadata_source_combo.bind("<<ComboboxSelected>>", self._metadata_source_changed)
        self.token_header = ttk.Frame(left, style="Card.TFrame")
        ttk.Label(self.token_header, text="Discogs 令牌", style="Card.TLabel").pack(side="left")
        token_link = ttk.Label(self.token_header, text="申请令牌", style="Card.TLabel", foreground=ACCENT, cursor="hand2")
        token_link.pack(side="right")
        token_link.bind("<Button-1>", lambda _event: webbrowser.open("https://www.discogs.com/settings/developers", new=2))
        token_link.bind("<Enter>", lambda _event: token_link.configure(font=(self.ui_font, 10, "underline")))
        token_link.bind("<Leave>", lambda _event: token_link.configure(font=(self.ui_font, 10)))
        self.discogs_token_entry = ttk.Entry(left, textvariable=self.discogs_token_var, show="●")
        self.region_label = ttk.Label(left, text="iTunes 区域", style="Card.TLabel")
        self.region_combo = ttk.Combobox(left, state="readonly", values=_region_labels())
        self.region_combo.set(_region_label(self.region_var.get()))
        self.region_combo.bind("<<ComboboxSelected>>", self._region_changed)

        search_row = ttk.Frame(left, style="Card.TFrame")
        search_row.pack(fill="x", pady=(0, 8))
        for column in range(3):
            search_row.columnconfigure(column, weight=1, uniform="search-actions")
        self.search_button = ttk.Button(search_row, text="搜索 iTunes", style="Accent.TButton", command=self._search)
        self.search_button.grid(row=0, column=0, sticky="ew", padx=4)
        self.manual_button = ttk.Button(search_row, text="手动模式", command=self._manual_mode)
        self.manual_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.clear_button = ttk.Button(search_row, text="清除", command=self._clear_album)
        self.clear_button.grid(row=0, column=2, sticky="ew", padx=4)
        self._metadata_source_changed()

        ttk.Label(left, text="搜索结果 · 选择后自动载入曲目", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 5))
        results_panel = RoundedPanel(
            left,
            padding=self._px(3),
            height=self._px(140),
            radius=self._px(7),
            inset=self._px(8),
            outline="#DCE0EB",
            parent_background=CARD,
        )
        results_frame = results_panel.content
        results_panel.pack(fill="both", expand=True)
        columns = ("region", "album", "artist")
        self.results_tree = ttk.Treeview(results_frame, columns=columns, show="headings", selectmode="browse", height=3)
        self.results_tree.heading("region", text="地区")
        self.results_tree.heading("album", text="专辑")
        self.results_tree.heading("artist", text="歌手")
        self.results_tree.column("region", width=self._px(60), anchor="center", stretch=False)
        self.results_tree.column("album", width=self._px(150))
        self.results_tree.column("artist", width=self._px(115))
        result_scroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=result_scroll.set)
        self.results_tree.pack(side="left", fill="both", expand=True)
        result_scroll.pack(side="right", fill="y")
        self.results_tree.bind("<<TreeviewSelect>>", self._album_selected)
        self.region_hint_label = ttk.Label(
            left,
            text=SOURCE_HINTS.get(self.metadata_source_var.get(), ""),
            style="Muted.Card.TLabel",
            justify="left",
            wraplength=self._px(360),
        )
        self.region_hint_label.pack(anchor="w", pady=(10, 0))

        album_top = ttk.Frame(right, style="Card.TFrame")
        album_top.pack(fill="x", pady=(0, 12))
        cover_column = ttk.Frame(album_top, style="Card.TFrame")
        cover_column.pack(side="left", padx=(0, self._px(18)))
        self.cover_label = tk.Label(cover_column, text="专辑封面", width=20, height=8, bg="#F0F1F6", fg=MUTED, font=(self.cjk_font, 11))
        self.cover_label.pack()
        ttk.Label(cover_column, textvariable=self.cover_info_var, style="Muted.Card.TLabel").pack(pady=(2, 0))
        details = ttk.Frame(album_top, style="Card.TFrame")
        details.pack(side="left", fill="both", expand=True)
        ttk.Label(details, text="3  校对并处理", style="Title.Card.TLabel").pack(anchor="w", pady=(0, 3))
        ttk.Label(details, textvariable=self.album_info_var, style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 7))
        fields = ttk.Frame(details, style="Card.TFrame")
        fields.pack(fill="x")
        ttk.Label(fields, text="专辑歌手", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(fields, textvariable=self.album_artist_var).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(fields, text="发行日期", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(fields, textvariable=self.date_var, width=13).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(fields, text="流派", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(fields, textvariable=self.genre_var, width=12).grid(row=1, column=2, sticky="ew")
        fields.columnconfigure(0, weight=1)
        cover_row = ttk.Frame(details, style="Card.TFrame")
        cover_row.pack(fill="x", pady=(8, 0))
        ttk.Label(cover_row, text="封面分辨率", style="Card.TLabel").pack(side="left", padx=(0, 6))
        self.cover_size_combo = ttk.Combobox(
            cover_row,
            textvariable=self.cover_size_var,
            values=_cover_size_labels(),
            state="readonly",
            width=10,
        )
        self.cover_size_combo.pack(side="left")
        self.cover_size_combo.bind("<<ComboboxSelected>>", self._cover_size_changed)
        ttk.Label(cover_row, text="嵌入选项", style="Card.TLabel").pack(side="left", padx=(8, 6))
        self.cover_embed_combo = ttk.Combobox(
            cover_row,
            textvariable=self.cover_embed_var,
            values=_cover_embed_labels(),
            state="readonly",
            width=10,
        )
        self.cover_embed_combo.pack(side="left")
        ttk.Button(cover_row, text="本地封面", width=8, command=self._choose_cover).pack(side="left", padx=(8, 0))
        ttk.Label(
            details,
            text="封面分辨率决定 cover.jpg 的尺寸；嵌入选项决定写进音频文件的封面",
            style="Muted.Card.TLabel",
            wraplength=self._px(560),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        track_tools = ttk.Frame(right, style="Card.TFrame")
        track_tools.pack(fill="x", pady=(0, 6))
        ttk.Label(track_tools, textvariable=self.match_var, style="Match.Card.TLabel").pack(side="left", fill="x", expand=True)
        self.align_button = ttk.Button(track_tools, text="时长匹配", command=self._smart_match_missing)
        self.insert_button = ttk.Button(track_tools, text="插入缺曲", command=self._insert_missing_track)
        self.up_button = ttk.Button(track_tools, text="上移", width=6, command=lambda: self._move_source(-1))
        self.up_button.pack(side="left", padx=2)
        ttk.Button(track_tools, text="下移", width=6, command=lambda: self._move_source(1)).pack(side="left", padx=2)
        ttk.Button(track_tools, text="编辑曲目", width=9, command=self._edit_track).pack(side="left", padx=(2, 0))

        tracks_panel = RoundedPanel(
            right,
            padding=self._px(3),
            radius=self._px(7),
            inset=self._px(8),
            outline="#DCE0EB",
            parent_background=CARD,
        )
        tracks_frame = tracks_panel.content
        tracks_panel.pack(fill="both", expand=True)
        track_columns = ("preview", "number", "source", "title", "artist", "duration")
        self.tracks_tree = ttk.Treeview(tracks_frame, columns=track_columns, show="headings", selectmode="browse", height=5)
        headings = {"preview": "试听", "number": "曲序", "source": "本地 WAV", "title": "写入的歌曲名", "artist": "歌手", "duration": "时长"}
        for key, value in headings.items():
            self.tracks_tree.heading(key, text=value)
        self.tracks_tree.column("preview", width=self._px(48), anchor="center", stretch=False)
        self.tracks_tree.column("number", width=self._px(48), anchor="center", stretch=False)
        self.tracks_tree.column("source", width=self._px(150))
        self.tracks_tree.column("title", width=self._px(190))
        self.tracks_tree.column("artist", width=self._px(125))
        self.tracks_tree.column("duration", width=self._px(58), anchor="center", stretch=False)
        self.tracks_tree.tag_configure("playing", background="#EAE6FF", foreground=ACCENT_DARK)
        self.tracks_tree.tag_configure("manual", background="#F0EBFF", foreground=ACCENT_DARK)
        self.tracks_tree.tag_configure("auto-manual", background="#FFF0D9", foreground="#8B5100")
        self.tracks_tree.tag_configure("duration-warning", background="#FFF3DF")
        track_scroll = ttk.Scrollbar(tracks_frame, orient="vertical", command=self.tracks_tree.yview)
        self.tracks_tree.configure(yscrollcommand=track_scroll.set)
        self.tracks_tree.pack(side="left", fill="both", expand=True)
        track_scroll.pack(side="right", fill="y")
        self.tracks_tree.bind("<Button-1>", self._track_clicked)
        self.tracks_tree.bind("<Double-1>", lambda _event: self._edit_track())

        output_panel = RoundedPanel(body, padding=14, radius=self._px(10), fit_height=True)
        output_card = output_panel.content
        output_panel.pack(side="bottom", fill="x", pady=(12, 8))
        output_row = ttk.Frame(output_card, style="Card.TFrame")
        output_row.pack(fill="x")
        ttk.Label(output_row, text="输出目录", style="Card.TLabel").pack(side="left", padx=(0, 8))
        ttk.Entry(output_row, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text="浏览", command=self._choose_output).pack(side="left", padx=(8, 0))
        ttk.Button(output_row, text="打开目录", command=self._open_output).pack(side="left", padx=(6, 0))
        action_row = ttk.Frame(output_card, style="Card.TFrame")
        action_row.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(action_row, text="保留 WAV", value="wav", variable=self.format_var, command=self._format_changed).pack(side="left")
        ttk.Radiobutton(action_row, text="FLAC 无损", value="flac", variable=self.format_var, command=self._format_changed).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(action_row, text="MP3", value="mp3", variable=self.format_var, command=self._format_changed).pack(side="left", padx=(12, 8))
        self.quality_combo = ttk.Combobox(action_row, textvariable=self.quality_var, values=("320 kbps", "V0"), state="readonly", width=10)
        self.quality_combo.pack(side="left")
        self.progress = ttk.Progressbar(action_row, variable=self.progress_var, maximum=1)
        self.progress.pack(side="left", fill="x", expand=True, padx=18)
        self.convert_button = ttk.Button(action_row, text="开始处理", style="Convert.TButton", command=self._convert)
        self.convert_button.pack(side="right")
        self._format_changed()

        status_bar = ttk.Frame(self.root)
        status_bar.pack(side="bottom", fill="x")
        status = ttk.Label(status_bar, textvariable=self.status_var, padding=(self._px(22), 0, self._px(12), self._px(10)), anchor="w")
        status.pack(side="left", fill="x", expand=True)
        version_frame = tk.Frame(status_bar, bg=BACKGROUND)
        version_frame.pack(side="right", padx=(self._px(12), self._px(22)))
        self.github_link = tk.Label(
            version_frame,
            text=f"GitHub  ·  v{__version__}",
            bg=BACKGROUND,
            fg=ACCENT,
            font=(self.ui_font, 10),
            cursor="hand2",
            padx=0,
            pady=self._px(7),
        )
        self.github_link.pack(side="left")
        self.update_dot = tk.Label(
            version_frame,
            text="●",
            bg=BACKGROUND,
            fg="#1A9B72",
            font=(self.ui_font, 9),
            cursor="hand2",
            padx=0,
        )
        self.github_link.bind("<Button-1>", lambda _event: self._open_latest_release())
        self.update_dot.bind("<Button-1>", lambda _event: self._open_latest_release())

    def _icon_clicked(self, _event=None) -> None:
        if self.easter_egg_dialog and self.easter_egg_dialog.winfo_exists():
            return
        now = time.monotonic()
        if now - self.first_icon_click_time > 2.5:
            self.icon_click_count = 1
            self.first_icon_click_time = now
        else:
            self.icon_click_count += 1
        if self.icon_click_count >= 7:
            self.icon_click_count = 0
            self.first_icon_click_time = 0.0
            self._show_easter_egg()

    def _show_easter_egg(self) -> None:
        dialog = tk.Toplevel(self.root)
        self.easter_egg_dialog = dialog
        dialog.title("DiscTag · 水友驱动开发")
        dialog.configure(bg="#F5F0E7")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        if self.icon_image:
            dialog.iconphoto(False, self.icon_image)
        width = min(self._px(1100), int(self.root.winfo_screenwidth() * 0.85))
        height = round(width * 647 / 1685)
        image = Image.open(_resource_path("assets/easter-egg-preview.png")).convert("RGB")
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        self.easter_egg_image = ImageTk.PhotoImage(image)
        canvas = tk.Canvas(dialog, width=width, height=height, highlightthickness=0, bg="#F5F0E7")
        canvas.pack()
        canvas.create_image(0, 0, anchor="nw", image=self.easter_egg_image)
        self.fireworks = Fireworks(canvas, width, height, self.ui_scale)
        self.fireworks.start()
        canvas.bind("<Button-1>", lambda event: self.fireworks.burst(event.x, event.y))
        button_frame = tk.Frame(dialog, bg="#F5F0E7")
        button_frame.pack(fill="x")
        close_button = ttk.Button(button_frame, text="好耶，继续整理音乐", style="Accent.TButton", command=self._close_easter_egg)
        close_button.pack(pady=self._px(9))
        close_button.focus_set()
        dialog.protocol("WM_DELETE_WINDOW", self._close_easter_egg)
        dialog.bind("<Escape>", lambda _event: self._close_easter_egg())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        self.status_var.set("你发现了隐藏彩蛋：水友驱动开发 · 点击画面可追加烟花")

    def _close_easter_egg(self) -> None:
        if self.fireworks:
            self.fireworks.stop()
            self.fireworks = None
        self.easter_egg_image = None
        if self.easter_egg_dialog and self.easter_egg_dialog.winfo_exists():
            self.easter_egg_dialog.destroy()
        self.easter_egg_dialog = None

    def _import_wav(self) -> None:
        if self.converting or self.updating:
            return
        selected = filedialog.askdirectory(title="选择包含 WAV 音轨的文件夹")
        if not selected:
            return
        directory = Path(selected)
        files = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".wav"), key=natural_key)
        if not files:
            messagebox.showwarning("没有 WAV 文件", "所选文件夹中没有找到 .wav 文件。", parent=self.root)
            return
        self.preview.stop()
        self._invalidate_metadata_requests()
        self.sources = files
        self.source_durations = {path: wav_duration(path) for path in files}
        if self.result_markers:
            # 时长标记针对上一批 WAV，换了音轨后不再成立。
            self.result_markers = {}
            selection = self.results_tree.selection()
            self._show_results()
            if selection:
                self.results_tree.selection_set(selection)
        self.album = None
        self.album_region = ""
        self.metadata_dirty = False
        self.cover_data = None
        self.source_var.set(f"{directory}  ·  {len(files)} 首")
        self.album_info_var.set("搜索并选择专辑，或进入手动模式")
        self._clear_cover()
        self._refresh_tracks()
        self.status_var.set(f"已导入 {len(files)} 个 WAV 文件")

    def _source_duration(self, path: Path) -> float | None:
        if path not in self.source_durations:
            self.source_durations[path] = wav_duration(path)
        return self.source_durations[path]

    def _invalidate_metadata_requests(self) -> None:
        self.search_request_id += 1
        self.album_request_id += 1
        self.cover_request_id += 1
        self.search_button.configure(state="disabled" if self.converting or self.updating else "normal")

    def _clear_album(self) -> None:
        if self.converting or self.updating:
            return
        self._invalidate_metadata_requests()
        for variable in (self.album_var, self.artist_var, self.album_artist_var, self.date_var, self.genre_var):
            variable.set("")
        self.results = []
        self.result_markers = {}
        self.album_cache = {}
        self.results_tree.delete(*self.results_tree.get_children())
        self.album = None
        self.album_region = ""
        self.metadata_dirty = False
        self.cover_data = None
        self._clear_cover()
        self.album_info_var.set("搜索并选择专辑，或进入手动模式")
        self._refresh_tracks()
        self.status_var.set("已清空专辑资料，可输入新专辑；已导入的 WAV 保持不变")
        self.album_entry.focus_set()

    def _search(self) -> None:
        if self.converting or self.updating:
            return
        source = self.metadata_source_var.get()
        if not self.album_var.get().strip() and not (source == SOURCE_MUSICBRAINZ and self.sources):
            hint = "请先输入专辑名称。"
            if source == SOURCE_MUSICBRAINZ:
                hint = "请输入专辑名称，或先导入 WAV 以按音轨时长识别光盘。"
            messagebox.showwarning("缺少专辑名称", hint, parent=self.root)
            return
        region = self.region_var.get()
        album = self.album_var.get().strip()
        artist = self.artist_var.get().strip()
        token = self.discogs_token_var.get().strip()
        if source == SOURCE_DISCOGS and not token:
            messagebox.showwarning("需要 Discogs 令牌", "请先点击“申请令牌”创建 Personal Access Token，再粘贴到令牌输入框。", parent=self.root)
            self.discogs_token_entry.focus_set()
            return
        self._save_discogs_token()
        self._invalidate_metadata_requests()
        request_id = self.search_request_id
        self.search_button.configure(state="disabled")
        if source == SOURCE_DISCOGS:
            self.status_var.set("正在查询 Discogs 实体唱片曲库…")
        elif source == SOURCE_MUSICBRAINZ:
            self.status_var.set("正在查询 MusicBrainz…" if not self.sources else "正在按音轨时长在 MusicBrainz 识别光盘…")
        elif region == "ALL":
            self.status_var.set("正在并行查询全部地区…")
        elif region == "CN":
            self.status_var.set("正在查询中国大陆 Apple Music 公开网页…")
        else:
            self.status_var.set(f"正在查询 {ITUNES_REGIONS[region]} iTunes…")

        local_ms = [
            duration * 1000 if (duration := self._source_duration(path)) is not None else None
            for path in self.sources
        ]

        def work():
            if source == SOURCE_DISCOGS:
                # Discogs 有请求频率限制，不逐个拉取详情核对时长。
                return self.discogs_client.search_albums(album, artist, token), {}, {}
            if source == SOURCE_MUSICBRAINZ:
                return self._search_musicbrainz(album, artist, local_ms)
            results = self.client.search_albums(album, artist, region)
            if not local_ms:
                return results, {}, {}
            self._post(lambda: request_id == self.search_request_id
                       and self.status_var.set("正在按本地 WAV 时长核对候选版本…"))
            candidates = candidates_to_verify(results, len(local_ms))
            fits, albums = verify_candidates(
                candidates, local_ms, lambda entry: self.client.get_album(entry.collection_id, entry.country)
            )
            return rank_results(results, fits, len(local_ms)), fits, albums

        def done(payload):
            if request_id != self.search_request_id:
                return
            results, fits, albums = payload
            self.search_button.configure(state="normal")
            self.results = results
            self.album_cache = albums
            self.result_markers = {key: fit.marker for key, fit in fits.items() if fit.marker}
            self._show_results()
            warning = f"；{len(self.client.last_warnings)} 个地区查询失败" if source == SOURCE_ITUNES and self.client.last_warnings else ""
            exact = sum(marker == "✓" for marker in self.result_markers.values())
            fit_text = f"；{exact} 个版本与本地时长吻合（✓）" if exact else ""
            if not exact and any(marker == "≈" for marker in self.result_markers.values()):
                fit_text = "；≈ 表示可按时长补出缺曲"
            self.status_var.set(f"找到 {len(results)} 个专辑版本{fit_text}{warning}" if results else "没有找到专辑，请更换关键词或地区")
            if results:
                self.results_tree.selection_set("0")
                self.results_tree.focus("0")
            elif source == SOURCE_ITUNES and self.client.last_warnings:
                messagebox.showwarning("地区查询失败", "\n".join(self.client.last_warnings), parent=self.root)

        self._run_async(work, done, lambda error: self._search_failed(error, request_id))

    def _search_musicbrainz(self, album: str, artist: str, local_ms: list[float | None]):
        """TOC lookup from the local WAV durations first, then a text search when an album name is given."""
        results: list[AlbumSummary] = []
        fits: dict[tuple, DurationFit] = {}
        toc = toc_from_durations([duration / 1000 if duration else None for duration in local_ms])
        toc_error: Exception | None = None
        if toc:
            try:
                for entry in self.musicbrainz_client.lookup_toc(toc, album, artist):
                    fits[result_key(entry)] = DurationFit(EXACT)
                    results.append(entry)
            except MusicBrainzError as exc:
                toc_error = exc
        if album:
            matched = {entry.collection_id for entry in results}
            results.extend(entry for entry in self.musicbrainz_client.search_albums(album, artist) if entry.collection_id not in matched)
        elif toc_error is not None:
            raise toc_error
        return rank_results(results, fits, len(local_ms)), fits, {}

    def _load_album(self, summary: AlbumSummary, token: str) -> AlbumMetadata:
        if summary.source == "discogs":
            return self.discogs_client.get_album(summary.collection_id, token)
        if summary.source == "musicbrainz":
            return self.musicbrainz_client.get_album(summary.collection_id, summary.medium)
        return self.client.get_album(summary.collection_id, summary.country)

    def _download_cover(self, source: str, artwork_url: str, size: int, token: str) -> bytes:
        if source == "discogs":
            return self.discogs_client.download_cover(artwork_url, size, token)
        if source == "musicbrainz":
            return self.musicbrainz_client.download_cover(artwork_url, size)
        return self.client.download_cover(artwork_url, size)

    def _show_results(self) -> None:
        self.results_tree.delete(*self.results_tree.get_children())
        for index, entry in enumerate(self.results):
            marker = self.result_markers.get(result_key(entry), "")
            region_text = f"{marker} {entry.country}" if marker else entry.country
            title = f"{entry.title} · {entry.detail}" if entry.detail else entry.title
            self.results_tree.insert("", "end", iid=str(index), values=(region_text, title, entry.artist))

    def _search_failed(self, error: Exception, request_id: int) -> None:
        if request_id != self.search_request_id:
            return
        self.search_button.configure(state="normal")
        self.status_var.set(f"{self.metadata_source_var.get()} 查询失败")
        messagebox.showerror("搜索失败", str(error), parent=self.root)

    def _album_selected(self, _event=None) -> None:
        if self.converting or self.updating:
            return
        selection = self.results_tree.selection()
        if not selection:
            return
        summary = self.results[int(selection[0])]
        if self.album and self.metadata_dirty:
            replace = messagebox.askyesno(
                "替换当前专辑资料",
                "更换专辑会清除当前的手动补曲和曲目修改，是否继续？",
                parent=self.root,
            )
            if not replace:
                return
        token = self.discogs_token_var.get().strip()
        cover_size = self._cover_size_value()
        cached = self.album_cache.get(result_key(summary))
        self.album_request_id += 1
        request_id = self.album_request_id
        self.cover_request_id += 1
        cover_request_id = self.cover_request_id
        self.status_var.set(f"正在载入 {summary.title}（{summary.country}）…")

        def work():
            if cached is not None:
                album = copy.deepcopy(cached)
            else:
                album = self._load_album(summary, token)
            try:
                cover = self._download_cover(summary.source, album.artwork_url, cover_size, token)
                return album, cover, None
            except Exception as exc:
                return album, None, str(exc)

        def done(result):
            if request_id != self.album_request_id:
                return
            album, cover, cover_error = result
            self.album = album
            self.album_region = summary.country
            self.metadata_dirty = False
            self.album_var.set(album.title)
            self.artist_var.set(album.artist)
            self.album_artist_var.set(album.album_artist)
            self.date_var.set(album.release_date)
            self.genre_var.set(album.genre)
            self._update_album_info()
            alignment_message = self._smart_match_missing()
            if not alignment_message:
                self._refresh_tracks()
            self.status_var.set(f"已载入《{album.title}》，请核对曲目对应关系")
            if cover_request_id == self.cover_request_id:
                self.cover_data = cover
                self.cover_is_local = False
                if cover:
                    self._show_cover(cover)
                else:
                    self._clear_cover()
                    self.status_var.set(f"专辑已载入；{cover_error}，可选择本地封面")
            elif not self.cover_is_local:
                self.cover_data = None
                self._clear_cover()
                if album.artwork_url:
                    self._cover_size_changed()
                else:
                    self.status_var.set("专辑已载入，没有在线封面，可选择本地封面")
            if alignment_message:
                self.status_var.set(alignment_message)

        self._run_async(work, done, lambda error: self._album_load_failed(error, request_id))

    def _album_load_failed(self, error: Exception, request_id: int) -> None:
        if request_id != self.album_request_id:
            return
        self.status_var.set("专辑资料载入失败")
        messagebox.showerror("载入失败", str(error), parent=self.root)

    def _manual_mode(self) -> None:
        if self.converting or self.updating:
            return
        if not self.sources:
            messagebox.showwarning("请先导入 WAV", "手动模式需要本地 WAV 文件来建立曲目列表。", parent=self.root)
            return
        if not self.album_var.get().strip():
            messagebox.showwarning("缺少专辑名称", "请先填写专辑名称。", parent=self.root)
            return
        if self.album and self.metadata_dirty:
            replace = messagebox.askyesno("进入手动模式", "这会覆盖当前的在线匹配和手动补曲，是否继续？", parent=self.root)
            if not replace:
                return
        self._invalidate_metadata_requests()
        artist = self.artist_var.get().strip() or self.album_artist_var.get().strip() or "未知歌手"
        tracks = manual_tracks(self.sources, artist)
        self.album = AlbumMetadata(
            title=self.album_var.get().strip(),
            artist=artist,
            album_artist=self.album_artist_var.get().strip() or artist,
            release_date=self.date_var.get().strip(),
            genre=self.genre_var.get().strip(),
            tracks=tracks,
        )
        self.album_region = ""
        self.metadata_dirty = True
        self.album_artist_var.set(self.album.album_artist)
        self._update_album_info()
        self._refresh_tracks()
        self.status_var.set("手动资料已建立，可逐首编辑歌曲名和歌手")

    def _update_album_info(self) -> None:
        if not self.album:
            return
        self.album_info_var.set(album_info_text(self.album, self.album_region))

    def _refresh_tracks(self) -> None:
        self.tracks_tree.delete(*self.tracks_tree.get_children())
        tracks = self.album.tracks if self.album else []
        count = max(len(self.sources), len(tracks))
        duration_warnings = 0
        for index in range(count):
            source = self.sources[index] if index < len(self.sources) else None
            track = tracks[index] if index < len(tracks) else None
            number = track_label(track, index)
            title = track.title if track else (clean_track_title(source) if source else "—")
            if track and track.origin == "manual":
                title = f"[手动] {title}"
            elif track and track.origin == "auto-manual":
                title = f"[待确认] {title}"
            artist = track.artist if track else (self.artist_var.get() if source else "—")
            local_duration = self._source_duration(source) if source else None
            duration = _duration(local_duration * 1000) if local_duration is not None else (_duration(track.duration_ms) if track else "—")
            mismatch = duration_mismatch(local_duration, track)
            if mismatch:
                duration_warnings += 1
            if track and track.origin in MANUAL_ORIGINS:
                tag = track.origin
            else:
                tag = "duration-warning" if mismatch else ""
            is_playing = bool(source and self.preview.playing and self.preview.path == source)
            tags = (["playing"] if is_playing else []) + ([tag] if tag else [])
            preview_icon = "■" if is_playing else "▶"
            self.tracks_tree.insert("", "end", iid=str(index), values=(preview_icon, number, source.name if source else "—", title, artist, duration), tags=tags)
        if can_insert(self.album, len(self.sources)):
            self.insert_button.pack(side="left", padx=2, before=self.up_button)
            self.align_button.pack(side="left", padx=2, before=self.insert_button)
        else:
            self.align_button.pack_forget()
            self.insert_button.pack_forget()
        self.match_var.set(match_status(len(self.sources), self.album, duration_warnings))

    def _track_clicked(self, event) -> str | None:
        if self.converting or self.tracks_tree.identify_region(event.x, event.y) != "cell":
            return None
        if self.tracks_tree.identify_column(event.x) != "#1":
            return None
        row = self.tracks_tree.identify_row(event.y)
        if not row:
            return None
        self.tracks_tree.selection_set(row)
        self._toggle_playback(int(row))
        return "break"

    def _toggle_playback(self, index: int) -> None:
        if self.converting or not 0 <= index < len(self.sources):
            return
        try:
            self.preview.toggle(self.sources[index])
        except RuntimeError as exc:
            messagebox.showerror("无法试听", str(exc), parent=self.root)

    def _playback_changed(self, playing: bool, path: Path) -> None:
        for iid in self.tracks_tree.get_children():
            index = int(iid)
            source = self.sources[index] if index < len(self.sources) else None
            is_playing = bool(playing and source == path)
            values = list(self.tracks_tree.item(iid, "values"))
            values[0] = "■" if is_playing else "▶"
            tags = [tag for tag in self.tracks_tree.item(iid, "tags") if tag != "playing"]
            if is_playing:
                tags.insert(0, "playing")
            self.tracks_tree.item(iid, values=values, tags=tags)
        if playing:
            self.status_var.set(f"正在试听：{path.name}")
        elif self.status_var.get().startswith("正在试听"):
            self.status_var.set("试听已停止")

    def _move_source(self, offset: int) -> None:
        if self.converting or self.updating:
            return
        selection = self.tracks_tree.selection()
        if not selection or not self.sources:
            return
        index = int(selection[0])
        target = index + offset
        if index >= len(self.sources) or not 0 <= target < len(self.sources):
            return
        self.sources[index], self.sources[target] = self.sources[target], self.sources[index]
        self.metadata_dirty = True
        self._refresh_tracks()
        self.tracks_tree.selection_set(str(target))
        self.tracks_tree.focus(str(target))

    def _smart_match_missing(self) -> str | None:
        if not can_insert(self.album, len(self.sources)):
            return None
        durations = [duration * 1000 if (duration := self._source_duration(path)) is not None else None for path in self.sources]
        try:
            missing_positions = fill_missing_by_duration(self.album, durations, self.album_artist_var.get() or self.album.artist)
        except EditError as exc:
            message = str(exc)
            self.status_var.set(message)
            return message
        self.metadata_dirty = True
        self._update_album_info()
        self._refresh_tracks()
        first_missing = missing_positions[0] - 1
        self.tracks_tree.selection_set(str(first_missing))
        self.tracks_tree.focus(str(first_missing))
        self.tracks_tree.see(str(first_missing))
        positions = "、".join(f"{position:02d}" for position in missing_positions)
        message = f"已按时长补出第 {positions} 首并标为待确认；请查阅实体 CD 曲目表，双击填写真实歌名"
        self.status_var.set(message)
        return message

    def _insert_missing_track(self) -> None:
        if self.converting or self.updating:
            return
        if not self.album or self.album.collection_id is None or len(self.sources) <= len(self.album.tracks):
            messagebox.showinfo("无需插入", "当前没有可由手动缺曲补齐的数量差异。", parent=self.root)
            return
        selection = self.tracks_tree.selection()
        default_position = int(selection[0]) + 1 if selection else len(self.album.tracks) + 1
        dialog = tk.Toplevel(self.root)
        dialog.title("插入缺失曲目")
        dialog.configure(bg=CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=self._px(22))
        frame.pack(fill="both", expand=True)
        position_var = tk.IntVar(value=default_position)
        title_var = tk.StringVar()
        artist_var = tk.StringVar(value=self.album_artist_var.get() or self.album.artist)
        ttk.Label(frame, text="按实体 CD 补充缺失曲目", style="Title.Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(
            frame,
            text="请查阅 CD 封底或内页的曲目表，确认正确曲序和歌名。\n后续在线曲目会自动顺移，歌曲名称保持不变。",
            style="Muted.Card.TLabel",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))
        ttk.Label(frame, text="插入到 CD 曲序", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(
            frame,
            textvariable=position_var,
            values=tuple(range(1, len(self.album.tracks) + 2)),
            state="readonly",
            width=8,
        ).grid(row=2, column=1, sticky="w", pady=5, padx=(12, 0))
        ttk.Label(frame, text="歌曲名称", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        title_entry = ttk.Entry(frame, textvariable=title_var, width=38)
        title_entry.grid(row=3, column=1, sticky="ew", pady=5, padx=(12, 0))
        ttk.Label(frame, text="歌手", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=artist_var, width=38).grid(row=4, column=1, sticky="ew", pady=5, padx=(12, 0))

        def save():
            if not title_var.get().strip():
                messagebox.showwarning("缺少歌曲名", "请按实体 CD 曲目表填写歌曲名称。", parent=dialog)
                return
            if self._insert_track_at(position_var.get(), title_var.get(), artist_var.get()):
                dialog.destroy()

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="插入并顺移", style="Accent.TButton", command=save).pack(side="left")
        title_entry.focus_set()
        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

    def _insert_track_at(self, position: int, title: str, artist: str = "") -> bool:
        if not self.album or not insert_manual_track(
            self.album, len(self.sources), position, title,
            artist.strip() or self.album_artist_var.get() or self.album.artist,
        ):
            return False
        index = position - 1
        self.metadata_dirty = True
        self._update_album_info()
        self._refresh_tracks()
        self.tracks_tree.selection_set(str(index))
        self.tracks_tree.focus(str(index))
        self.tracks_tree.see(str(index))
        self.status_var.set(f"已在第 {position:02d} 首插入手动曲目，后续曲目已顺移")
        return True

    def _delete_manual_track(self, index: int) -> bool:
        if not self.album or not delete_manual_track(self.album, index):
            return False
        self.metadata_dirty = True
        self._update_album_info()
        self._refresh_tracks()
        if self.album.tracks:
            selected = min(index, len(self.album.tracks) - 1)
            self.tracks_tree.selection_set(str(selected))
            self.tracks_tree.focus(str(selected))
        self.status_var.set("已移除手动缺曲，可重新选择插入位置或使用时长匹配")
        return True

    def _edit_track(self) -> None:
        if self.converting or self.updating:
            return
        selection = self.tracks_tree.selection()
        if not selection or not self.album:
            return
        index = int(selection[0])
        if index >= len(self.album.tracks):
            return
        track = self.album.tracks[index]
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑曲目")
        dialog.configure(bg=CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=20)
        frame.pack(fill="both", expand=True)
        title_var = tk.StringVar(value=track.title)
        artist_var = tk.StringVar(value=track.artist)
        ttk.Label(frame, text=f"曲序 {track.track_number:02d}", style="Title.Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        ttk.Label(frame, text="歌曲名", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=5)
        title_entry = ttk.Entry(frame, textvariable=title_var, width=40)
        title_entry.grid(row=1, column=1, sticky="ew", pady=5, padx=(12, 0))
        ttk.Label(frame, text="歌手", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=artist_var, width=40).grid(row=2, column=1, sticky="ew", pady=5, padx=(12, 0))

        def save():
            if not title_var.get().strip():
                messagebox.showwarning("缺少歌曲名", "歌曲名不能为空。", parent=dialog)
                return
            if track.origin == "auto-manual" and title_var.get().strip() == track.title:
                messagebox.showwarning("请确认真实歌名", "请按实体 CD 曲目表修改占位名称，再保存确认。", parent=dialog)
                return
            track.title = title_var.get().strip()
            track.artist = artist_var.get().strip() or self.album.artist
            if track.origin == "auto-manual":
                track.origin = "manual"
            self.metadata_dirty = True
            self._refresh_tracks()
            self.tracks_tree.selection_set(str(index))
            dialog.destroy()

        def delete_manual():
            confirmed = messagebox.askyesno(
                "删除手动缺曲",
                "删除后，后续在线曲目会恢复顺移前的位置。是否继续？",
                parent=dialog,
            )
            if confirmed and self._delete_manual_track(index):
                dialog.destroy()

        if track.origin in MANUAL_ORIGINS and self.album.collection_id is not None:
            ttk.Button(frame, text="删除手动曲目", command=delete_manual).grid(row=3, column=0, sticky="w", pady=(16, 0))
        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.grid(row=3, column=1, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存", style="Accent.TButton", command=save).pack(side="left")
        title_entry.focus_set()
        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

    def _cover_size_value(self) -> int:
        return int(self.cover_size_var.get().split(" ")[0])

    def _cover_embed_choice(self) -> tuple[bool, int | None]:
        value = _cover_embed_value(self.cover_embed_var.get())
        if value == "none":
            return False, None
        if value == "original":
            return True, None
        return True, int(value)

    def _cover_size_changed(self, _event=None) -> None:
        self.cover_request_id += 1
        request_id = self.cover_request_id
        size = self._cover_size_value()
        if not self.album or not self.album.artwork_url or self.cover_is_local:
            self.status_var.set(f"封面分辨率已设为 {size}×{size}，将在下次在线下载时生效")
            return
        album = self.album
        artwork_url = album.artwork_url
        token = self.discogs_token_var.get().strip()
        self.status_var.set(f"正在获取最高 {size}×{size} 的封面…")

        def work():
            return self._download_cover(album.source, artwork_url, size, token)

        def done(data: bytes):
            if request_id != self.cover_request_id or self.album is not album:
                return
            self.cover_data = data
            self.cover_is_local = False
            self._show_cover(data)
            self.status_var.set(f"封面已更新 · {self.cover_info_var.get()}")

        def failed(error: Exception):
            if request_id == self.cover_request_id and self.album is album:
                self.status_var.set(f"封面下载失败：{error}")

        self._run_async(work, done, failed)

    def _choose_cover(self) -> None:
        if self.converting or self.updating:
            return
        selected = filedialog.askopenfilename(title="选择专辑封面", filetypes=[("图片", "*.jpg *.jpeg *.png *.webp"), ("所有文件", "*.*")])
        if not selected:
            return
        try:
            image = Image.open(selected)
            image = ImageOps.exif_transpose(image).convert("RGB")
            size = self._cover_size_value()
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, "JPEG", quality=94, optimize=True)
            self.cover_request_id += 1
            self.cover_data = output.getvalue()
            self.cover_is_local = True
            self._show_cover(self.cover_data)
            self.status_var.set("已使用本地封面")
        except OSError as exc:
            messagebox.showerror("封面读取失败", str(exc), parent=self.root)

    def _show_cover(self, data: bytes) -> None:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        self.cover_info_var.set(f"实际 {image.width}×{image.height}")
        size = self._px(164)
        image = ImageOps.contain(image, (size, size), Image.Resampling.LANCZOS)
        self.cover_preview = ImageTk.PhotoImage(image)
        self.cover_label.configure(image=self.cover_preview, text="", width=size, height=size)

    def _clear_cover(self) -> None:
        self.cover_preview = None
        self.cover_is_local = False
        self.cover_info_var.set("")
        self.cover_label.configure(image="", text="专辑封面", width=20, height=8)

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="选择输出根目录", initialdir=self.output_var.get() or str(Path.home()))
        if selected:
            self.output_var.set(selected)

    def _open_output(self) -> None:
        path = self.last_output or Path(self.output_var.get()).expanduser()
        if not path.is_dir():
            messagebox.showinfo("目录尚不存在", "完成一次处理后，即可在这里打开输出目录。", parent=self.root)
            return
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _convert(self) -> None:
        if self.converting or self.updating:
            return
        if not self.sources:
            messagebox.showwarning("缺少 WAV", "请先选择包含 WAV 音轨的文件夹。", parent=self.root)
            return
        if not self.album:
            messagebox.showwarning("缺少专辑资料", "请搜索并选择专辑，或使用手动模式。", parent=self.root)
            return
        if len(self.sources) != len(self.album.tracks):
            messagebox.showwarning("曲目数量不一致", "请使用时长匹配、手动插入缺曲、重新选择专辑，或改用手动模式。", parent=self.root)
            return
        if any(track.origin == "auto-manual" for track in self.album.tracks):
            messagebox.showwarning("缺曲仍待确认", "请查阅实体 CD 曲目表，双击“待确认”行填写真实歌名并保存，然后再处理。", parent=self.root)
            return
        if not self.album_var.get().strip() or not self.artist_var.get().strip():
            messagebox.showwarning("资料不完整", "专辑名称和歌手名称不能为空。", parent=self.root)
            return
        if not self.output_var.get().strip():
            messagebox.showwarning("缺少输出目录", "请选择输出根目录。", parent=self.root)
            return
        if self.format_var.get() != "wav":
            try:
                find_ffmpeg()
            except Exception as exc:
                messagebox.showerror("FFmpeg 不可用", str(exc), parent=self.root)
                return
        album = copy.deepcopy(self.album)
        album.title = self.album_var.get().strip()
        album.artist = self.artist_var.get().strip()
        album.album_artist = self.album_artist_var.get().strip() or album.artist
        album.release_date = self.date_var.get().strip()
        album.genre = self.genre_var.get().strip()
        renumber_tracks(album.tracks)
        output_root = Path(self.output_var.get().strip()).expanduser()
        directory = output_directory(output_root, album)
        existing = [output_path(directory, track, self.format_var.get()) for track in album.tracks]
        if self.cover_data:
            existing.append(directory / "cover.jpg")
        if any(path.exists() for path in existing):
            overwrite = messagebox.askyesno("确认覆盖", "输出目录中已有同名曲目或封面。继续处理会覆盖这些文件，是否继续？", parent=self.root)
            if not overwrite:
                return
        sources = list(self.sources)
        cover = self.cover_data
        output_format = self.format_var.get()
        quality = self.quality_var.get()
        embed_cover, embed_max_size = self._cover_embed_choice()
        self.preview.stop()
        self.converting = True
        cancel = self.cancel_event = threading.Event()
        self._invalidate_metadata_requests()
        self.convert_button.configure(text="取消处理", command=self._cancel_conversion)
        self.clear_button.configure(state="disabled")
        self.progress_var.set(0)
        self.progress.configure(maximum=len(sources))
        self.status_var.set("正在准备处理…")

        def progress(current: int, total: int, text: str):
            self._post(lambda: self._conversion_progress(current, total, text))

        def work():
            return convert_album(
                sources, album, output_root, output_format, quality, cover, progress, embed_cover, embed_max_size,
                cancel=cancel,
            )

        self.conversion_thread = self._run_async(work, self._conversion_done, self._conversion_failed)

    def _cancel_conversion(self) -> None:
        if self.converting and self.cancel_event is not None and not self.cancel_event.is_set():
            self.cancel_event.set()
            self.convert_button.configure(state="disabled")
            self.status_var.set("正在取消，当前曲目停止后结束…")

    def _finish_conversion(self) -> None:
        self.converting = False
        self.cancel_event = None
        self.conversion_thread = None
        self.convert_button.configure(text="开始处理", command=self._convert, state="normal")
        self.search_button.configure(state="normal")
        self.clear_button.configure(state="normal")

    def _conversion_progress(self, current: int, _total: int, text: str) -> None:
        if self.converting:
            self.progress_var.set(current)
            self.status_var.set(text)

    def _conversion_done(self, result: ConversionResult) -> None:
        self._finish_conversion()
        self.last_output = result.output_directory
        if result.cancelled:
            self.status_var.set(f"已取消 · 已完成 {len(result.converted_files)} 首")
            messagebox.showinfo(
                "已取消处理",
                f"已完成 {len(result.converted_files)} 首，其余曲目未处理。\n\n{result.output_directory}",
                parent=self.root,
            )
            self._save_settings()
            return
        self.progress_var.set(len(self.sources))
        if result.failures:
            details = "\n".join(f"{failure.source.name}：{failure.message}" for failure in result.failures[:6])
            self.status_var.set(f"完成 {len(result.converted_files)} 首，失败 {len(result.failures)} 首")
            messagebox.showwarning("部分曲目处理失败", f"成功 {len(result.converted_files)} 首，失败 {len(result.failures)} 首。\n\n{details}", parent=self.root)
        else:
            self.status_var.set(f"处理完成 · {result.output_directory}")
            messagebox.showinfo("处理完成", f"已生成 {len(result.converted_files)} 首音乐，标签与封面处理完成。\n\n{result.output_directory}", parent=self.root)
        self._save_settings()

    def _conversion_failed(self, error: Exception) -> None:
        self._finish_conversion()
        self.status_var.set("处理失败")
        messagebox.showerror("处理失败", str(error), parent=self.root)

    def _check_for_updates(self) -> None:
        def work():
            return check_for_updates(__version__)

        def done(info):
            if not info:
                return
            self.latest_update = info
            self.latest_release_url = info.url
            if not self.update_dot.winfo_ismapped():
                self.update_dot.pack(side="left", padx=(self._px(6), 0))
            action = "点击圆点查看更新" if info.download_url else "点击右下角打开发布页"
            self.status_var.set(f"发现新版本 {info.version} · {action}")

        self._run_async(work, done, lambda _error: None)

    def _open_latest_release(self) -> None:
        if sys.platform == "win32" and self.latest_update and self.latest_update.download_url:
            self._start_update_download()
        else:
            webbrowser.open(self.latest_release_url, new=2)

    def _start_update_download(self) -> None:
        if self.updating:
            return
        if self.converting:
            messagebox.showwarning("正在处理专辑", "请等待当前专辑处理完成后再更新。", parent=self.root)
            return
        info = self.latest_update
        if not info:
            return
        self._show_update_dialog(info)

    def _show_update_dialog(self, info) -> None:
        if self.update_dialog and self.update_dialog.winfo_exists():
            return
        dialog = tk.Toplevel(self.root)
        self.update_dialog = dialog
        dialog.title("自动更新")
        dialog.configure(bg=CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=self._px(22))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"发现新版本 {info.version}", style="Title.Card.TLabel").pack(anchor="w")
        if info.notes:
            notes_frame = ttk.Frame(frame, style="Card.TFrame")
            notes_frame.pack(fill="x", pady=(self._px(12), 0))
            notes = tk.Text(
                notes_frame,
                wrap="word",
                height=8,
                width=52,
                font=(self.cjk_font, 10),
                bg="#F8F9FC",
                fg=INK,
                relief="flat",
                highlightthickness=1,
                highlightbackground="#DCE0EB",
                padx=self._px(10),
                pady=self._px(8),
            )
            notes_scroll = ttk.Scrollbar(notes_frame, orient="vertical", command=notes.yview)
            notes.configure(yscrollcommand=notes_scroll.set)
            notes.pack(side="left", fill="both", expand=True)
            notes_scroll.pack(side="right", fill="y")
            notes.insert("1.0", info.notes.strip())
            notes.configure(state="disabled")
        release_link = ttk.Label(
            frame,
            text="查看发布页并手动下载",
            style="Card.TLabel",
            foreground=ACCENT,
            cursor="hand2",
        )
        release_link.pack(anchor="w", pady=(self._px(14), 0))
        release_link.bind("<Button-1>", lambda _event: webbrowser.open(info.url, new=2))
        release_link.bind("<Enter>", lambda _event: release_link.configure(font=(self.ui_font, 11, "underline")))
        release_link.bind("<Leave>", lambda _event: release_link.configure(font=(self.ui_font, 11)))
        ttk.Label(frame, text="是否下载并自动安装？", style="Card.TLabel").pack(anchor="w", pady=(self._px(16), 0))
        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.pack(anchor="e", pady=(self._px(12), 0))
        ttk.Button(buttons, text="否", command=self._close_update_dialog).pack(side="left", padx=(0, 8))
        yes_button = ttk.Button(buttons, text="是", style="Accent.TButton", command=lambda: self._begin_update_download(info))
        yes_button.pack(side="left")
        yes_button.bind("<Return>", lambda _event: self._begin_update_download(info))
        yes_button.focus_set()
        dialog.protocol("WM_DELETE_WINDOW", self._close_update_dialog)
        dialog.bind("<Escape>", lambda _event: self._close_update_dialog())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

    def _close_update_dialog(self) -> None:
        if self.update_dialog and self.update_dialog.winfo_exists():
            self.update_dialog.destroy()
        self.update_dialog = None

    def _begin_update_download(self, info) -> None:
        self._close_update_dialog()
        if self.updating:
            return
        if self.converting:
            messagebox.showwarning("正在处理专辑", "请等待当前专辑处理完成后再更新。", parent=self.root)
            return
        self.updating = True
        self._invalidate_metadata_requests()
        self.convert_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        self.progress_var.set(0)
        self.progress.configure(maximum=info.size or 1)
        destination = Path(tempfile.gettempdir()) / "DiscTag" / "updates" / info.installer_name

        def work():
            def progress(downloaded: int, total: int):
                self._post(lambda: self._update_download_progress(downloaded, total))

            return download_update(info, destination, progress)

        self.status_var.set("正在下载更新…")
        self._run_async(work, self._install_update, self._update_failed)

    def _update_download_progress(self, downloaded: int, total: int) -> None:
        self.progress_var.set(downloaded)
        if total:
            self.status_var.set(f"正在下载更新 · {downloaded / total:.0%}")
        else:
            self.status_var.set(f"已下载 {downloaded / 1024 / 1024:.1f} MB")

    def _install_update(self, installer: Path) -> None:
        self.updating = False
        self.status_var.set("更新包校验完成，正在安装…")
        self._save_settings()
        try:
            subprocess.Popen(
                [str(installer), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"],
                cwd=installer.parent,
            )
        except OSError as exc:
            self._update_failed(exc)
            return
        self.root.destroy()

    def _update_failed(self, error: Exception) -> None:
        self.updating = False
        self.convert_button.configure(state="normal")
        self.search_button.configure(state="normal")
        self.clear_button.configure(state="normal")
        self.status_var.set(f"自动更新失败：{error}")
        choice = messagebox.askyesnocancel(
            "自动更新失败",
            f"{error}\n\n选择\"是\"重试下载，选择\"否\"打开发布页手动下载。",
            parent=self.root,
        )
        if choice:
            self._start_update_download()
        elif choice is False and self.latest_update:
            webbrowser.open(self.latest_update.url, new=2)

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

    def _format_changed(self) -> None:
        self.quality_combo.configure(state="readonly" if self.format_var.get() == "mp3" else "disabled")
        if not self.converting:
            if self.format_var.get() == "wav":
                self.status_var.set("保留 WAV：不重新编码，标签写入 RIFF ID3 块，并另存 cover.jpg；播放器兼容性可能不同")
            else:
                self.status_var.set("就绪")

    def _metadata_source_changed(self, _event=None) -> None:
        source = self.metadata_source_var.get()
        if source == SOURCE_DISCOGS:
            self.region_label.pack_forget()
            self.region_combo.pack_forget()
            self.token_header.pack(fill="x", before=self.search_button.master)
            self.discogs_token_entry.pack(fill="x", pady=(4, 6), before=self.search_button.master)
            self.search_button.configure(text="搜索 Discogs")
        elif source == SOURCE_MUSICBRAINZ:
            for widget in (self.region_label, self.region_combo, self.token_header, self.discogs_token_entry):
                widget.pack_forget()
            self.search_button.configure(text="搜索 MusicBrainz")
        else:
            self.token_header.pack_forget()
            self.discogs_token_entry.pack_forget()
            self.region_label.pack(anchor="w", before=self.search_button.master)
            self.region_combo.pack(fill="x", pady=(4, 6), before=self.search_button.master)
            self.search_button.configure(text="搜索 iTunes")
        hint_label = getattr(self, "region_hint_label", None)
        if hint_label is not None:
            hint_label.configure(text=SOURCE_HINTS.get(source, ""))
        if _event is not None:
            self._invalidate_metadata_requests()
            self.results = []
            self.result_markers = {}
            self.album_cache = {}
            self.results_tree.delete(*self.results_tree.get_children())
            self.album = None
            self.album_region = ""
            self.metadata_dirty = False
            self.cover_data = None
            self._clear_cover()
            self.album_info_var.set("搜索并选择专辑，或进入手动模式")
            self._refresh_tracks()
            self.status_var.set("已切换曲库，专辑名称和歌手已保留，可重新搜索")

    def _read_discogs_token(self) -> str:
        try:
            import keyring

            return keyring.get_password("DiscTag", "discogs_token") or ""
        except Exception:
            return ""

    def _save_discogs_token(self) -> None:
        if not getattr(self, "discogs_token_loaded", False):
            return
        import keyring

        token = self.discogs_token_var.get().strip()
        try:
            if token:
                keyring.set_password("DiscTag", "discogs_token", token)
            else:
                keyring.delete_password("DiscTag", "discogs_token")
        except Exception:
            pass

    def _region_changed(self, _event=None) -> None:
        label = self.region_combo.get()
        self.region_var.set(_region_code(label))

    def _close(self) -> None:
        if self.converting and not messagebox.askyesno("处理仍在进行", "现在退出会中断未完成的处理，确定退出吗？", parent=self.root):
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


def _resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / relative


def _settings_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "DiscTag" / "settings.json"


def _region_labels() -> list[str]:
    return ["全部地区（美 / 日 / 中 / 港 / 台）", *(f"{name}（{code}）" for code, name in ITUNES_REGIONS.items())]


def _region_label(code: str) -> str:
    if code == "ALL":
        return _region_labels()[0]
    return f"{ITUNES_REGIONS.get(code, '美国')}（{code if code in ITUNES_REGIONS else 'US'}）"


def _region_code(label: str) -> str:
    if label.startswith("全部"):
        return "ALL"
    for code, name in ITUNES_REGIONS.items():
        if label == f"{name}（{code}）":
            return code
    return "US"


def _cover_size_labels() -> list[str]:
    return [_cover_size_label(size) for size in COVER_SIZES]


def _cover_size_label(size: int) -> str:
    return f"{size} × {size}"


def _cover_embed_labels() -> list[str]:
    return ["不嵌入", *(_cover_size_label(size) for size in COVER_EMBED_SIZES), "同 cover.jpg"]


def _cover_embed_label(value) -> str:
    if value == "none":
        return "不嵌入"
    if value in COVER_EMBED_SIZES:
        return _cover_size_label(value)
    return "同 cover.jpg"


def _cover_embed_value(label: str):
    if label == "不嵌入":
        return "none"
    for size in COVER_EMBED_SIZES:
        if label == _cover_size_label(size):
            return size
    return "original"


def _duration(milliseconds: float | int | None) -> str:
    if not milliseconds:
        return "—"
    seconds = round(milliseconds / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"
