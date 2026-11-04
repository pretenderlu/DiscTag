from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import threading
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
from .itunes import ITUNES_REGIONS, ITunesClient
from .matching import align_tracks_by_duration
from .models import AlbumMetadata, AlbumSummary, ConversionResult, TrackMetadata, renumber_tracks


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


class DiscTagApp:
    def __init__(self):
        self.ui_font = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI"
        self.ui_semibold = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI Semibold"
        self.cjk_font = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
        self._enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("DiscTag — CD 音频处理与标签工具")
        self.ui_scale = 1.0
        if sys.platform == "win32":
            pixels_per_inch = self.root.winfo_fpixels("1i")
            self.ui_scale = max(1.0, pixels_per_inch / 96)
            self.root.tk.call("tk", "scaling", pixels_per_inch / 72)
        self._configure_window()
        self.root.configure(bg=BACKGROUND)
        self.settings = self._load_settings()
        self.client = ITunesClient()
        self.sources: list[Path] = []
        self.results: list[AlbumSummary] = []
        self.album: AlbumMetadata | None = None
        self.album_region = ""
        self.metadata_dirty = False
        self.cover_data: bytes | None = None
        self.cover_preview = None
        self.icon_image = None
        self.last_output: Path | None = None
        self.converting = False
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
        self.album_info_var = tk.StringVar(value="搜索并选择专辑，或进入手动模式")
        self.match_var = tk.StringVar(value="先导入 WAV 文件")
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self._configure_styles()
        self._load_icon()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

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
        minimum_width = min(self._px(1100), int(screen_width * 0.96))
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
            bordercolor="#DCE0EB",
            lightcolor="#DCE0EB",
            darkcolor="#DCE0EB",
            arrowcolor=MUTED,
            padding=self._px(8),
        )
        style.map("TCombobox", bordercolor=[("focus", ACCENT)], fieldbackground=[("readonly", "#F8F9FC")])
        style.configure(
            "TButton",
            font=(self.ui_font, 10),
            padding=(self._px(15), self._px(10)),
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
                font=(self.ui_semibold, 11),
                padding=(self._px(18), self._px(11)),
                borderwidth=0,
                relief="flat",
            )
            style.map(
                button_style,
                background=[("disabled", "#C8C3EA"), ("pressed", "#4535B4"), ("active", ACCENT_DARK)],
                foreground=[("disabled", "#F2F0FA")],
            )
        style.configure("Convert.TButton", font=(self.ui_semibold, 12), padding=(self._px(24), self._px(13)))
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
        style.configure(
            "TRadiobutton",
            background=CARD,
            foreground=INK,
            font=(self.ui_font, 10),
            indicatorcolor="#F8F9FC",
            bordercolor="#C8CDDB",
            focusthickness=0,
        )
        style.map("TRadiobutton", indicatorcolor=[("active", "#EAE6FF"), ("selected", ACCENT)])
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
            tk.Label(header_content, image=self.header_icon, bg="#1D1C31").pack(side="left", padx=(0, self._px(15)))
        titles = tk.Frame(header_content, bg="#1D1C31")
        titles.pack(side="left", fill="y")
        tk.Label(titles, text="DiscTag", bg="#1D1C31", fg="#FFFFFF", font=(self.ui_semibold, 24)).pack(anchor="w")
        tk.Label(titles, text="让每一张 CD，都有完整而漂亮的音乐资料", bg="#1D1C31", fg="#BAB8D0", font=(self.cjk_font, 10)).pack(anchor="w")
        tk.Label(header_content, text="WAV  →  WAV / FLAC / MP3", bg="#1D1C31", fg="#BDB5FF", font=(self.ui_semibold, 12)).pack(side="right", pady=self._px(14))

        body = ttk.Frame(self.root, padding=(self._px(22), self._px(18), self._px(22), self._px(12)))
        body.pack(fill="both", expand=True)
        source_card = ttk.Frame(body, style="Card.TFrame", padding=self._px(16))
        source_card.pack(fill="x", pady=(0, self._px(12)))
        ttk.Label(source_card, text="1  导入 CD 音轨", style="Title.Card.TLabel").pack(side="left", padx=(0, self._px(18)))
        ttk.Button(source_card, text="选择 WAV 文件夹", command=self._import_wav).pack(side="left")
        ttk.Label(source_card, textvariable=self.source_var, style="Muted.Card.TLabel").pack(side="left", padx=self._px(16), fill="x", expand=True)

        content = ttk.Frame(body)
        content.pack(fill="both", expand=True)
        left = ttk.Frame(content, style="Card.TFrame", padding=self._px(18), width=self._px(405))
        left.pack(side="left", fill="y", padx=(0, self._px(12)))
        left.pack_propagate(False)
        right = ttk.Frame(content, style="Card.TFrame", padding=self._px(18))
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="2  匹配专辑资料", style="Title.Card.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(left, text="专辑名称", style="Card.TLabel").pack(anchor="w")
        ttk.Entry(left, textvariable=self.album_var).pack(fill="x", pady=(4, 9))
        ttk.Label(left, text="歌手名称", style="Card.TLabel").pack(anchor="w")
        ttk.Entry(left, textvariable=self.artist_var).pack(fill="x", pady=(4, 9))
        ttk.Label(left, text="iTunes 区域", style="Card.TLabel").pack(anchor="w")
        self.region_combo = ttk.Combobox(left, state="readonly", values=_region_labels())
        self.region_combo.pack(fill="x", pady=(4, 10))
        self.region_combo.set(_region_label(self.region_var.get()))
        self.region_combo.bind("<<ComboboxSelected>>", self._region_changed)

        search_row = ttk.Frame(left, style="Card.TFrame")
        search_row.pack(fill="x", pady=(0, 12))
        self.search_button = ttk.Button(search_row, text="搜索 iTunes", style="Accent.TButton", command=self._search)
        self.search_button.pack(side="left", fill="x", expand=True)
        self.manual_button = ttk.Button(search_row, text="手动模式", command=self._manual_mode)
        self.manual_button.pack(side="left", padx=(8, 0))

        ttk.Label(left, text="搜索结果 · 选择后自动载入曲目", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 5))
        results_frame = ttk.Frame(left, style="Card.TFrame")
        results_frame.pack(fill="both", expand=True)
        columns = ("region", "album", "artist")
        self.results_tree = ttk.Treeview(results_frame, columns=columns, show="headings", selectmode="browse", height=5)
        self.results_tree.heading("region", text="地区")
        self.results_tree.heading("album", text="专辑")
        self.results_tree.heading("artist", text="歌手")
        self.results_tree.column("region", width=self._px(48), anchor="center", stretch=False)
        self.results_tree.column("album", width=self._px(150))
        self.results_tree.column("artist", width=self._px(115))
        result_scroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=result_scroll.set)
        self.results_tree.pack(side="left", fill="both", expand=True)
        result_scroll.pack(side="right", fill="y")
        self.results_tree.bind("<<TreeviewSelect>>", self._album_selected)
        ttk.Label(left, text="全部地区会并行查询美、日、中、港、台，\n相同专辑的不同地区版本会分别保留。", style="Muted.Card.TLabel", justify="left").pack(anchor="w", pady=(10, 0))

        album_top = ttk.Frame(right, style="Card.TFrame")
        album_top.pack(fill="x", pady=(0, 12))
        self.cover_label = tk.Label(album_top, text="专辑封面", width=20, height=8, bg="#F0F1F6", fg=MUTED, font=(self.cjk_font, 11))
        self.cover_label.pack(side="left", padx=(0, self._px(18)))
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
        ttk.Button(details, text="选择本地封面", command=self._choose_cover).pack(anchor="w", pady=(8, 0))

        track_tools = ttk.Frame(right, style="Card.TFrame")
        track_tools.pack(fill="x", pady=(0, 6))
        ttk.Label(track_tools, textvariable=self.match_var, style="Match.Card.TLabel").pack(side="left", fill="x", expand=True)
        self.align_button = ttk.Button(track_tools, text="时长匹配", command=self._smart_match_missing)
        self.insert_button = ttk.Button(track_tools, text="插入缺曲", command=self._insert_missing_track)
        self.up_button = ttk.Button(track_tools, text="上移", width=6, command=lambda: self._move_source(-1))
        self.up_button.pack(side="left", padx=2)
        ttk.Button(track_tools, text="下移", width=6, command=lambda: self._move_source(1)).pack(side="left", padx=2)
        ttk.Button(track_tools, text="编辑曲目", width=9, command=self._edit_track).pack(side="left", padx=(2, 0))

        tracks_frame = ttk.Frame(right, style="Card.TFrame")
        tracks_frame.pack(fill="both", expand=True)
        track_columns = ("number", "source", "title", "artist", "duration")
        self.tracks_tree = ttk.Treeview(tracks_frame, columns=track_columns, show="headings", selectmode="browse", height=5)
        headings = {"number": "曲序", "source": "本地 WAV", "title": "写入的歌曲名", "artist": "歌手", "duration": "时长"}
        for key, value in headings.items():
            self.tracks_tree.heading(key, text=value)
        self.tracks_tree.column("number", width=self._px(48), anchor="center", stretch=False)
        self.tracks_tree.column("source", width=self._px(150))
        self.tracks_tree.column("title", width=self._px(190))
        self.tracks_tree.column("artist", width=self._px(125))
        self.tracks_tree.column("duration", width=self._px(58), anchor="center", stretch=False)
        self.tracks_tree.tag_configure("manual", background="#F0EBFF", foreground=ACCENT_DARK)
        self.tracks_tree.tag_configure("auto-manual", background="#FFF0D9", foreground="#8B5100")
        self.tracks_tree.tag_configure("duration-warning", background="#FFF3DF")
        track_scroll = ttk.Scrollbar(tracks_frame, orient="vertical", command=self.tracks_tree.yview)
        self.tracks_tree.configure(yscrollcommand=track_scroll.set)
        self.tracks_tree.pack(side="left", fill="both", expand=True)
        track_scroll.pack(side="right", fill="y")
        self.tracks_tree.bind("<Double-1>", lambda _event: self._edit_track())

        output_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        output_card.pack(side="bottom", fill="x", pady=(12, 8))
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
        self.github_link = tk.Label(
            status_bar,
            text=f"GitHub  ·  v{__version__}",
            bg=BACKGROUND,
            fg=ACCENT,
            font=(self.ui_font, 10),
            cursor="hand2",
            padx=self._px(22),
            pady=self._px(7),
        )
        self.github_link.pack(side="right")
        self.github_link.bind("<Button-1>", lambda _event: webbrowser.open(REPOSITORY_URL, new=2))

    def _import_wav(self) -> None:
        selected = filedialog.askdirectory(title="选择包含 WAV 音轨的文件夹")
        if not selected:
            return
        directory = Path(selected)
        files = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".wav"), key=natural_key)
        if not files:
            messagebox.showwarning("没有 WAV 文件", "所选文件夹中没有找到 .wav 文件。", parent=self.root)
            return
        self.sources = files
        self.album = None
        self.album_region = ""
        self.metadata_dirty = False
        self.cover_data = None
        self.source_var.set(f"{directory}  ·  {len(files)} 首")
        self.album_info_var.set("搜索并选择专辑，或进入手动模式")
        self._clear_cover()
        self._refresh_tracks()
        self.status_var.set(f"已导入 {len(files)} 个 WAV 文件")

    def _search(self) -> None:
        if not self.album_var.get().strip():
            messagebox.showwarning("缺少专辑名称", "请先输入专辑名称。", parent=self.root)
            return
        region = self.region_var.get()
        album = self.album_var.get().strip()
        artist = self.artist_var.get().strip()
        self.search_button.configure(state="disabled")
        self.status_var.set("正在并行查询全部地区…" if region == "ALL" else f"正在查询 {ITUNES_REGIONS[region]} iTunes…")

        def work():
            return self.client.search_albums(album, artist, region)

        def done(results: list[AlbumSummary]):
            self.search_button.configure(state="normal")
            self.results = results
            self.results_tree.delete(*self.results_tree.get_children())
            for index, entry in enumerate(results):
                self.results_tree.insert("", "end", iid=str(index), values=(entry.country, entry.title, entry.artist))
            warning = f"；{len(self.client.last_warnings)} 个地区查询失败" if self.client.last_warnings else ""
            self.status_var.set(f"找到 {len(results)} 个专辑版本{warning}" if results else "没有找到专辑，请更换关键词或地区")
            if results:
                self.results_tree.selection_set("0")
                self.results_tree.focus("0")
            elif self.client.last_warnings:
                messagebox.showwarning("地区查询失败", "\n".join(self.client.last_warnings), parent=self.root)

        self._run_async(work, done, self._search_failed)

    def _search_failed(self, error: Exception) -> None:
        self.search_button.configure(state="normal")
        self.status_var.set("iTunes 查询失败")
        messagebox.showerror("搜索失败", str(error), parent=self.root)

    def _album_selected(self, _event=None) -> None:
        selection = self.results_tree.selection()
        if not selection:
            return
        summary = self.results[int(selection[0])]
        if self.album and self.metadata_dirty:
            replace = messagebox.askyesno(
                "替换当前专辑资料",
                "更换 iTunes 专辑会清除当前的手动补曲和曲目修改，是否继续？",
                parent=self.root,
            )
            if not replace:
                return
        self.status_var.set(f"正在载入 {summary.title}（{summary.country}）…")

        def work():
            album = self.client.get_album(summary.collection_id, summary.country)
            cover_error = None
            try:
                cover = self.client.download_cover(album.artwork_url)
            except Exception as exc:
                cover = None
                cover_error = str(exc)
            return album, cover, cover_error

        def done(result):
            album, cover, cover_error = result
            self.album = album
            self.album_region = summary.country
            self.metadata_dirty = False
            self.cover_data = cover
            self.album_var.set(album.title)
            self.artist_var.set(album.artist)
            self.album_artist_var.set(album.album_artist)
            self.date_var.set(album.release_date)
            self.genre_var.set(album.genre)
            self._update_album_info()
            alignment_message = self._smart_match_missing()
            if not alignment_message:
                self._refresh_tracks()
            if cover:
                self._show_cover(cover)
                self.status_var.set(f"已载入《{album.title}》，请核对曲目对应关系")
            else:
                self._clear_cover()
                self.status_var.set(f"专辑已载入；{cover_error}，可选择本地封面")
            if alignment_message:
                self.status_var.set(alignment_message)

        self._run_async(work, done, self._album_load_failed)

    def _album_load_failed(self, error: Exception) -> None:
        self.status_var.set("专辑资料载入失败")
        messagebox.showerror("载入失败", str(error), parent=self.root)

    def _manual_mode(self) -> None:
        if not self.sources:
            messagebox.showwarning("请先导入 WAV", "手动模式需要本地 WAV 文件来建立曲目列表。", parent=self.root)
            return
        if not self.album_var.get().strip():
            messagebox.showwarning("缺少专辑名称", "请先填写专辑名称。", parent=self.root)
            return
        if self.album and self.metadata_dirty:
            replace = messagebox.askyesno("进入手动模式", "这会覆盖当前的 iTunes 匹配和手动补曲，是否继续？", parent=self.root)
            if not replace:
                return
        artist = self.artist_var.get().strip() or self.album_artist_var.get().strip() or "未知歌手"
        tracks = [
            TrackMetadata(clean_track_title(path), artist, index, len(self.sources), origin="manual")
            for index, path in enumerate(self.sources, 1)
        ]
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
        manual_count = sum(track.origin in {"manual", "auto-manual"} for track in self.album.tracks)
        count_text = f"{len(self.album.tracks)} 首"
        if self.album.collection_id is not None and manual_count:
            count_text += f"（{len(self.album.tracks) - manual_count} 首 iTunes + {manual_count} 首手动）"
        source = self.album_region or "手动模式"
        self.album_info_var.set(
            f"{source} · {count_text} · {self.album.genre or '未分类'} · {self.album.release_date or '日期未知'}"
        )

    def _refresh_tracks(self) -> None:
        self.tracks_tree.delete(*self.tracks_tree.get_children())
        tracks = self.album.tracks if self.album else []
        count = max(len(self.sources), len(tracks))
        duration_warnings = 0
        for index in range(count):
            source = self.sources[index] if index < len(self.sources) else None
            track = tracks[index] if index < len(tracks) else None
            number = f"{track.disc_number}-{track.track_number:02d}" if track and track.disc_count > 1 else (f"{track.track_number:02d}" if track else f"{index + 1:02d}")
            title = track.title if track else (clean_track_title(source) if source else "—")
            if track and track.origin == "manual":
                title = f"[手动] {title}"
            elif track and track.origin == "auto-manual":
                title = f"[待确认] {title}"
            artist = track.artist if track else (self.artist_var.get() if source else "—")
            local_duration = wav_duration(source) if source else None
            duration = _duration(local_duration * 1000) if local_duration is not None else (_duration(track.duration_ms) if track else "—")
            duration_mismatch = bool(
                local_duration is not None
                and track
                and track.duration_ms
                and abs(local_duration * 1000 - track.duration_ms) > 10000
            )
            if duration_mismatch:
                duration_warnings += 1
            if track and track.origin in {"manual", "auto-manual"}:
                tag = track.origin
            else:
                tag = "duration-warning" if duration_mismatch else ""
            self.tracks_tree.insert("", "end", iid=str(index), values=(number, source.name if source else "—", title, artist, duration), tags=(tag,) if tag else ())
        can_insert = bool(self.album and self.album.collection_id is not None and len(self.sources) > len(tracks))
        if can_insert:
            self.insert_button.pack(side="left", padx=2, before=self.up_button)
            self.align_button.pack(side="left", padx=2, before=self.insert_button)
        else:
            self.align_button.pack_forget()
            self.insert_button.pack_forget()
        if not self.sources:
            self.match_var.set("先导入 WAV 文件")
        elif not self.album:
            self.match_var.set(f"已导入 {len(self.sources)} 首 · 尚未匹配专辑")
        elif len(self.sources) > len(tracks):
            self.match_var.set(f"本地多 {len(self.sources) - len(tracks)} 首 · 请对照实体 CD，使用时长匹配或插入缺曲")
        elif len(self.sources) < len(tracks):
            self.match_var.set(f"本地少 {len(tracks) - len(self.sources)} 首 · 请核对实体 CD 版本或重新匹配")
        else:
            warning = " · 橙行时长不同" if duration_warnings else ""
            self.match_var.set(f"{len(self.sources)} 首已对应 · 双击编辑 / 上下移动{warning}")

    def _move_source(self, offset: int) -> None:
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
        if not self.album or self.album.collection_id is None or len(self.sources) <= len(self.album.tracks):
            return None
        if any(track.disc_count > 1 or track.disc_number != 1 for track in self.album.tracks):
            message = "多碟专辑请按实体 CD 曲目表手动插入缺曲"
            self.status_var.set(message)
            return message
        durations = [duration * 1000 if (duration := wav_duration(path)) is not None else None for path in self.sources]
        aligned = align_tracks_by_duration(durations, self.album.tracks)
        if aligned is None:
            message = "时长信息不足或差异过大，无法可靠对齐；请按实体 CD 曲目表手动插入"
            self.status_var.set(message)
            return message
        completed = []
        missing_positions = []
        for index, track in enumerate(aligned):
            if track is None:
                reference = next((item for item in aligned[index + 1:] if item is not None), None)
                if reference is None:
                    reference = next((item for item in reversed(aligned[:index]) if item is not None), None)
                track = TrackMetadata(
                    title=f"待确认曲目 {index + 1:02d}",
                    artist=self.album_artist_var.get() or self.album.artist,
                    track_number=index + 1,
                    track_count=len(aligned),
                    disc_number=reference.disc_number if reference else 1,
                    disc_count=reference.disc_count if reference else 1,
                    origin="auto-manual",
                )
                missing_positions.append(index + 1)
            completed.append(track)
        self.album.tracks = completed
        renumber_tracks(self.album.tracks)
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
            text="请查阅 CD 封底或内页的曲目表，确认正确曲序和歌名。\n后续 iTunes 曲目会自动顺移，歌曲名称保持不变。",
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
        if not self.album or not title.strip() or len(self.sources) <= len(self.album.tracks):
            return False
        if not 1 <= position <= len(self.album.tracks) + 1:
            return False
        index = position - 1
        reference = self.album.tracks[index] if index < len(self.album.tracks) else self.album.tracks[-1]
        track = TrackMetadata(
            title=title.strip(),
            artist=artist.strip() or self.album_artist_var.get() or self.album.artist,
            track_number=position,
            track_count=len(self.album.tracks) + 1,
            disc_number=reference.disc_number,
            disc_count=reference.disc_count,
            origin="manual",
        )
        self.album.tracks.insert(index, track)
        renumber_tracks(self.album.tracks)
        self.metadata_dirty = True
        self._update_album_info()
        self._refresh_tracks()
        self.tracks_tree.selection_set(str(index))
        self.tracks_tree.focus(str(index))
        self.tracks_tree.see(str(index))
        self.status_var.set(f"已在第 {position:02d} 首插入手动曲目，后续曲目已顺移")
        return True

    def _delete_manual_track(self, index: int) -> bool:
        if not self.album or not 0 <= index < len(self.album.tracks):
            return False
        if self.album.tracks[index].origin not in {"manual", "auto-manual"}:
            return False
        self.album.tracks.pop(index)
        renumber_tracks(self.album.tracks)
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
                "删除后，后续 iTunes 曲目会恢复顺移前的位置。是否继续？",
                parent=dialog,
            )
            if confirmed and self._delete_manual_track(index):
                dialog.destroy()

        if track.origin in {"manual", "auto-manual"} and self.album.collection_id is not None:
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

    def _choose_cover(self) -> None:
        selected = filedialog.askopenfilename(title="选择专辑封面", filetypes=[("图片", "*.jpg *.jpeg *.png *.webp"), ("所有文件", "*.*")])
        if not selected:
            return
        try:
            image = Image.open(selected)
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, "JPEG", quality=94, optimize=True)
            self.cover_data = output.getvalue()
            self._show_cover(self.cover_data)
            self.status_var.set("已使用本地封面")
        except OSError as exc:
            messagebox.showerror("封面读取失败", str(exc), parent=self.root)

    def _show_cover(self, data: bytes) -> None:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        size = self._px(164)
        image = ImageOps.contain(image, (size, size), Image.Resampling.LANCZOS)
        self.cover_preview = ImageTk.PhotoImage(image)
        self.cover_label.configure(image=self.cover_preview, text="", width=size, height=size)

    def _clear_cover(self) -> None:
        self.cover_preview = None
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
        if self.converting:
            return
        if not self.sources:
            messagebox.showwarning("缺少 WAV", "请先选择包含 WAV 音轨的文件夹。", parent=self.root)
            return
        if not self.album:
            messagebox.showwarning("缺少专辑资料", "请从 iTunes 选择专辑，或使用手动模式。", parent=self.root)
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
        for track in album.tracks:
            track.track_count = len(album.tracks)
        output_root = Path(self.output_var.get().strip()).expanduser()
        directory = output_directory(output_root, album)
        existing = [output_path(directory, track, self.format_var.get()) for track in album.tracks]
        if any(path.exists() for path in existing):
            overwrite = messagebox.askyesno("确认覆盖", "输出目录中已有同名曲目。继续处理会覆盖这些文件，是否继续？", parent=self.root)
            if not overwrite:
                return
        sources = list(self.sources)
        cover = self.cover_data
        output_format = self.format_var.get()
        quality = self.quality_var.get()
        self.converting = True
        self.convert_button.configure(state="disabled")
        self.search_button.configure(state="disabled")
        self.progress_var.set(0)
        self.progress.configure(maximum=len(sources))
        self.status_var.set("正在准备处理…")

        def progress(current: int, total: int, text: str):
            self.root.after(0, lambda: self._conversion_progress(current, total, text))

        def work():
            return convert_album(sources, album, output_root, output_format, quality, cover, progress)

        self._run_async(work, self._conversion_done, self._conversion_failed)

    def _conversion_progress(self, current: int, _total: int, text: str) -> None:
        if self.converting:
            self.progress_var.set(current)
            self.status_var.set(text)

    def _conversion_done(self, result: ConversionResult) -> None:
        self.converting = False
        self.convert_button.configure(state="normal")
        self.search_button.configure(state="normal")
        self.last_output = result.output_directory
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
        self.converting = False
        self.convert_button.configure(state="normal")
        self.search_button.configure(state="normal")
        self.status_var.set("处理失败")
        messagebox.showerror("处理失败", str(error), parent=self.root)

    def _run_async(self, work, done, failed) -> None:
        def runner():
            try:
                result = work()
            except Exception as exc:
                self.root.after(0, lambda error=exc: failed(error))
            else:
                self.root.after(0, lambda: done(result))

        threading.Thread(target=runner, daemon=True).start()

    def _format_changed(self) -> None:
        self.quality_combo.configure(state="readonly" if self.format_var.get() == "mp3" else "disabled")
        if not self.converting:
            if self.format_var.get() == "wav":
                self.status_var.set("保留 WAV：不重新编码，标签写入 RIFF ID3 块，并另存 cover.jpg；播放器兼容性可能不同")
            else:
                self.status_var.set("就绪")

    def _region_changed(self, _event=None) -> None:
        label = self.region_combo.get()
        self.region_var.set(_region_code(label))

    def _close(self) -> None:
        if self.converting and not messagebox.askyesno("处理仍在进行", "现在退出会中断未完成的处理，确定退出吗？", parent=self.root):
            return
        self._save_settings()
        self.root.destroy()

    def _load_settings(self) -> dict:
        try:
            return json.loads(_settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        settings = {
            "output": self.output_var.get(),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "region": self.region_var.get(),
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


def _duration(milliseconds: float | int | None) -> str:
    if not milliseconds:
        return "—"
    seconds = round(milliseconds / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"
