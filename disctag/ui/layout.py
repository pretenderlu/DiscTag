"""Builds the main window widgets."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from .. import __version__, i18n
from ..i18n import tr
from ..rounded_panel import RoundedPanel
from .common import (
    ACCENT,
    ACCENT_DARK,
    BACKGROUND,
    CARD,
    MUTED,
    SOURCE_DISCOGS,
    SOURCE_HINTS,
    SOURCE_ITUNES,
    SOURCE_MUSICBRAINZ,
    _cover_embed_labels,
    _cover_size_labels,
    _region_label,
    _region_labels,
)


class LayoutMixin:
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
        tk.Label(titles, text=tr("让每一张 CD，都有完整而漂亮的音乐资料"), bg="#1D1C31", fg="#BAB8D0", font=(self.cjk_font, 10)).pack(anchor="w")
        tk.Label(header_content, text="WAV  →  WAV / FLAC / MP3", bg="#1D1C31", fg="#BDB5FF", font=(self.ui_semibold, 12)).pack(side="right", pady=self._px(14))

        body = ttk.Frame(self.root, padding=(self._px(22), self._px(18), self._px(22), self._px(12)))
        body.pack(fill="both", expand=True)
        source_panel = RoundedPanel(body, padding=self._px(16), radius=self._px(10), fit_height=True)
        source_card = source_panel.content
        source_panel.pack(fill="x", pady=(0, self._px(12)))
        ttk.Label(source_card, text=tr("1  导入 CD 音轨"), style="Title.Card.TLabel").pack(side="left", padx=(0, self._px(18)))
        ttk.Button(source_card, text=tr("选择 WAV 文件夹"), command=self._import_wav).pack(side="left")
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

        ttk.Label(left, text=tr("2  匹配专辑资料"), style="Title.Card.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(left, text=tr("专辑名称"), style="Card.TLabel").pack(anchor="w")
        self.album_entry = ttk.Entry(left, textvariable=self.album_var)
        self.album_entry.pack(fill="x", pady=(4, 6))
        ttk.Label(left, text=tr("歌手名称"), style="Card.TLabel").pack(anchor="w")
        ttk.Entry(left, textvariable=self.artist_var).pack(fill="x", pady=(4, 6))
        ttk.Label(left, text=tr("曲库来源"), style="Card.TLabel").pack(anchor="w")
        self.metadata_source_combo = ttk.Combobox(
            left,
            textvariable=self.metadata_source_var,
            values=(SOURCE_ITUNES, SOURCE_DISCOGS, SOURCE_MUSICBRAINZ),
            state="readonly",
        )
        self.metadata_source_combo.pack(fill="x", pady=(4, 6))
        self.metadata_source_combo.bind("<<ComboboxSelected>>", self._metadata_source_changed)
        self.token_header = ttk.Frame(left, style="Card.TFrame")
        ttk.Label(self.token_header, text=tr("Discogs 令牌"), style="Card.TLabel").pack(side="left")
        token_link = ttk.Label(self.token_header, text=tr("申请令牌"), style="Card.TLabel", foreground=ACCENT, cursor="hand2")
        token_link.pack(side="right")
        token_link.bind("<Button-1>", lambda _event: webbrowser.open("https://www.discogs.com/settings/developers", new=2))
        token_link.bind("<Enter>", lambda _event: token_link.configure(font=(self.ui_font, 10, "underline")))
        token_link.bind("<Leave>", lambda _event: token_link.configure(font=(self.ui_font, 10)))
        self.discogs_token_entry = ttk.Entry(left, textvariable=self.discogs_token_var, show="●")
        self.region_label = ttk.Label(left, text=tr("iTunes 区域"), style="Card.TLabel")
        self.region_combo = ttk.Combobox(left, state="readonly", values=_region_labels())
        self.region_combo.set(_region_label(self.region_var.get()))
        self.region_combo.bind("<<ComboboxSelected>>", self._region_changed)

        search_row = ttk.Frame(left, style="Card.TFrame")
        search_row.pack(fill="x", pady=(0, 8))
        for column in range(3):
            # 搜索按钮的文字随曲库来源变化（如“搜索 MusicBrainz”），给它更宽的一列。
            search_row.columnconfigure(column, weight=4 if column == 0 else 3, uniform="search-actions")
        self.search_button = ttk.Button(search_row, text=tr("搜索 iTunes"), style="Accent.TButton", command=self._search)
        self.search_button.grid(row=0, column=0, sticky="ew", padx=4)
        self.manual_button = ttk.Button(search_row, text=tr("手动模式"), command=self._manual_mode)
        self.manual_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.clear_button = ttk.Button(search_row, text=tr("清除"), command=self._clear_album)
        self.clear_button.grid(row=0, column=2, sticky="ew", padx=4)
        self._metadata_source_changed()

        ttk.Label(left, text=tr("搜索结果 · 选择后自动载入曲目"), style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 5))
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
        self.results_tree.heading("region", text=tr("地区"))
        self.results_tree.heading("album", text=tr("专辑"))
        self.results_tree.heading("artist", text=tr("歌手"))
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
        # 先于结果列表占位：窗口较矮时由可滚动的结果列表收缩，提示文字不被裁掉。
        self.region_hint_label.pack(side="bottom", anchor="w", pady=(10, 0), before=results_panel)

        album_top = ttk.Frame(right, style="Card.TFrame")
        album_top.pack(fill="x", pady=(0, 12))
        cover_column = ttk.Frame(album_top, style="Card.TFrame")
        cover_column.pack(side="left", padx=(0, self._px(18)))
        self.cover_label = tk.Label(cover_column, text=tr("专辑封面"), width=20, height=8, bg="#F0F1F6", fg=MUTED, font=(self.cjk_font, 11))
        self.cover_label.pack()
        ttk.Label(cover_column, textvariable=self.cover_info_var, style="Muted.Card.TLabel").pack(pady=(2, 0))
        details = ttk.Frame(album_top, style="Card.TFrame")
        details.pack(side="left", fill="both", expand=True)
        ttk.Label(details, text=tr("3  校对并处理"), style="Title.Card.TLabel").pack(anchor="w", pady=(0, 3))
        ttk.Label(details, textvariable=self.album_info_var, style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 7))
        fields = ttk.Frame(details, style="Card.TFrame")
        fields.pack(fill="x")
        ttk.Label(fields, text=tr("专辑歌手"), style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(fields, textvariable=self.album_artist_var).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(fields, text=tr("发行日期"), style="Card.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(fields, textvariable=self.date_var, width=13).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(fields, text=tr("流派"), style="Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(fields, textvariable=self.genre_var, width=12).grid(row=1, column=2, sticky="ew")
        fields.columnconfigure(0, weight=1)
        cover_row = ttk.Frame(details, style="Card.TFrame")
        cover_row.pack(fill="x", pady=(8, 0))
        ttk.Label(cover_row, text=tr("封面分辨率"), style="Card.TLabel").pack(side="left", padx=(0, 6))
        self.cover_size_combo = ttk.Combobox(
            cover_row,
            textvariable=self.cover_size_var,
            values=_cover_size_labels(),
            state="readonly",
            width=10,
        )
        self.cover_size_combo.pack(side="left")
        self.cover_size_combo.bind("<<ComboboxSelected>>", self._cover_size_changed)
        ttk.Label(cover_row, text=tr("嵌入选项"), style="Card.TLabel").pack(side="left", padx=(8, 6))
        self.cover_embed_combo = ttk.Combobox(
            cover_row,
            textvariable=self.cover_embed_var,
            values=_cover_embed_labels(),
            state="readonly",
            width=10,
        )
        self.cover_embed_combo.pack(side="left")
        ttk.Button(cover_row, text=tr("本地封面"), command=self._choose_cover).pack(side="left", padx=(8, 0))
        ttk.Label(
            details,
            text=tr("封面分辨率决定 cover.jpg 的尺寸；嵌入选项决定写进音频文件的封面"),
            style="Muted.Card.TLabel",
            wraplength=self._px(560),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        track_tools = ttk.Frame(right, style="Card.TFrame")
        track_tools.pack(fill="x", pady=(0, 6))
        ttk.Label(track_tools, textvariable=self.match_var, style="Match.Card.TLabel").pack(side="left", fill="x", expand=True)
        self.align_button = ttk.Button(track_tools, text=tr("时长匹配"), command=self._smart_match_missing)
        self.insert_button = ttk.Button(track_tools, text=tr("插入缺曲"), command=self._insert_missing_track)
        self.up_button = ttk.Button(track_tools, text=tr("上移"), width=6, command=lambda: self._move_source(-1))
        self.up_button.pack(side="left", padx=2)
        ttk.Button(track_tools, text=tr("下移"), width=6, command=lambda: self._move_source(1)).pack(side="left", padx=2)
        ttk.Button(track_tools, text=tr("编辑曲目"), width=9, command=self._edit_track).pack(side="left", padx=(2, 0))

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
        headings = {"preview": tr("试听"), "number": tr("曲序"), "source": tr("本地 WAV"), "title": tr("写入的歌曲名"), "artist": tr("歌手"), "duration": tr("时长")}
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
        ttk.Label(output_row, text=tr("输出目录"), style="Card.TLabel").pack(side="left", padx=(0, 8))
        ttk.Entry(output_row, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text=tr("浏览"), command=self._choose_output).pack(side="left", padx=(8, 0))
        ttk.Button(output_row, text=tr("打开目录"), command=self._open_output).pack(side="left", padx=(6, 0))
        action_row = ttk.Frame(output_card, style="Card.TFrame")
        action_row.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(action_row, text=tr("保留 WAV"), value="wav", variable=self.format_var, command=self._format_changed).pack(side="left")
        ttk.Radiobutton(action_row, text=tr("FLAC 无损"), value="flac", variable=self.format_var, command=self._format_changed).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(action_row, text="MP3", value="mp3", variable=self.format_var, command=self._format_changed).pack(side="left", padx=(12, 8))
        self.quality_combo = ttk.Combobox(action_row, textvariable=self.quality_var, values=("320 kbps", "V0"), state="readonly", width=10)
        self.quality_combo.pack(side="left")
        self.progress = ttk.Progressbar(action_row, variable=self.progress_var, maximum=1)
        self.progress.pack(side="left", fill="x", expand=True, padx=18)
        self.convert_button = ttk.Button(action_row, text=tr("开始处理"), style="Convert.TButton", command=self._convert)
        self.convert_button.pack(side="right")
        self.enqueue_button = ttk.Button(action_row, text=tr("加入队列"), command=self._add_to_queue)
        self.enqueue_button.pack(side="right", padx=(0, self._px(8)))
        self.queue_button = ttk.Button(action_row, text=tr("队列"), width=8, command=self._show_queue)
        self.queue_button.pack(side="right", padx=(0, self._px(8)))
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
        self.language_link = tk.Label(
            version_frame,
            text="English" if i18n.language() == "zh" else "中文",
            bg=BACKGROUND,
            fg=ACCENT,
            font=(self.ui_font, 10),
            cursor="hand2",
            padx=0,
            pady=self._px(7),
        )
        self.language_link.pack(side="left", padx=(0, self._px(14)))
        self.language_link.bind("<Button-1>", lambda _event: self._switch_language())
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
