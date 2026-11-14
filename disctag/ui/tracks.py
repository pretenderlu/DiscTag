"""Importing WAVs, the track table, preview playback and track editing."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..audio import (
    clean_track_title,
    natural_key,
    wav_duration,
)
from ..editing import (
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
from ..i18n import tr
from ..models import AlbumMetadata
from .common import (
    CARD,
    _duration,
)


class TracksMixin:
    def _import_wav(self) -> None:
        if self.updating:
            return
        selected = filedialog.askdirectory(title=tr("选择包含 WAV 音轨的文件夹"))
        if not selected:
            return
        directory = Path(selected)
        files = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".wav"), key=natural_key)
        if not files:
            messagebox.showwarning(tr("没有 WAV 文件"), tr("所选文件夹中没有找到 .wav 文件。"), parent=self.root)
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
        self.source_var.set(tr("{0}  ·  {1} 首", directory, len(files)))
        self.album_info_var.set(tr("搜索并选择专辑，或进入手动模式"))
        self._clear_cover()
        self._refresh_tracks()
        self.status_var.set(tr("已导入 {0} 个 WAV 文件", len(files)))

    def _source_duration(self, path: Path) -> float | None:
        if path not in self.source_durations:
            self.source_durations[path] = wav_duration(path)
        return self.source_durations[path]

    def _manual_mode(self) -> None:
        if self.updating:
            return
        if not self.sources:
            messagebox.showwarning(tr("请先导入 WAV"), tr("手动模式需要本地 WAV 文件来建立曲目列表。"), parent=self.root)
            return
        if not self.album_var.get().strip():
            messagebox.showwarning(tr("缺少专辑名称"), tr("请先填写专辑名称。"), parent=self.root)
            return
        if self.album and self.metadata_dirty:
            replace = messagebox.askyesno(tr("进入手动模式"), tr("这会覆盖当前的在线匹配和手动补曲，是否继续？"), parent=self.root)
            if not replace:
                return
        self._invalidate_metadata_requests()
        artist = self.artist_var.get().strip() or self.album_artist_var.get().strip() or tr("未知歌手")
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
        self.status_var.set(tr("手动资料已建立，可逐首编辑歌曲名和歌手"))

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
                title = tr("[手动] {0}", title)
            elif track and track.origin == "auto-manual":
                title = tr("[待确认] {0}", title)
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
        if self.tracks_tree.identify_region(event.x, event.y) != "cell":
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
        if not 0 <= index < len(self.sources):
            return
        try:
            self.preview.toggle(self.sources[index])
        except RuntimeError as exc:
            messagebox.showerror(tr("无法试听"), str(exc), parent=self.root)

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
            self.status_var.set(tr("正在试听：{0}", path.name))
        elif self.status_var.get().startswith(tr("正在试听：{0}", "")):
            self.status_var.set(tr("试听已停止"))

    def _move_source(self, offset: int) -> None:
        if self.updating:
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
        positions = tr("、").join(f"{position:02d}" for position in missing_positions)
        message = tr("已按时长补出第 {0} 首并标为待确认；请查阅实体 CD 曲目表，双击填写真实歌名", positions)
        self.status_var.set(message)
        return message

    def _insert_missing_track(self) -> None:
        if self.updating:
            return
        if not self.album or self.album.collection_id is None or len(self.sources) <= len(self.album.tracks):
            messagebox.showinfo(tr("无需插入"), tr("当前没有可由手动缺曲补齐的数量差异。"), parent=self.root)
            return
        selection = self.tracks_tree.selection()
        default_position = int(selection[0]) + 1 if selection else len(self.album.tracks) + 1
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("插入缺失曲目"))
        dialog.configure(bg=CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=self._px(22))
        frame.pack(fill="both", expand=True)
        position_var = tk.IntVar(value=default_position)
        title_var = tk.StringVar()
        artist_var = tk.StringVar(value=self.album_artist_var.get() or self.album.artist)
        ttk.Label(frame, text=tr("按实体 CD 补充缺失曲目"), style="Title.Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(
            frame,
            text=tr("请查阅 CD 封底或内页的曲目表，确认正确曲序和歌名。\n后续在线曲目会自动顺移，歌曲名称保持不变。"),
            style="Muted.Card.TLabel",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))
        ttk.Label(frame, text=tr("插入到 CD 曲序"), style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(
            frame,
            textvariable=position_var,
            values=tuple(range(1, len(self.album.tracks) + 2)),
            state="readonly",
            width=8,
        ).grid(row=2, column=1, sticky="w", pady=5, padx=(12, 0))
        ttk.Label(frame, text=tr("歌曲名称"), style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        title_entry = ttk.Entry(frame, textvariable=title_var, width=38)
        title_entry.grid(row=3, column=1, sticky="ew", pady=5, padx=(12, 0))
        ttk.Label(frame, text=tr("歌手"), style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=artist_var, width=38).grid(row=4, column=1, sticky="ew", pady=5, padx=(12, 0))

        def save():
            if not title_var.get().strip():
                messagebox.showwarning(tr("缺少歌曲名"), tr("请按实体 CD 曲目表填写歌曲名称。"), parent=dialog)
                return
            if self._insert_track_at(position_var.get(), title_var.get(), artist_var.get()):
                dialog.destroy()

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text=tr("取消"), command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=tr("插入并顺移"), style="Accent.TButton", command=save).pack(side="left")
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
        self.status_var.set(tr("已在第 {0:02d} 首插入手动曲目，后续曲目已顺移", position))
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
        self.status_var.set(tr("已移除手动缺曲，可重新选择插入位置或使用时长匹配"))
        return True

    def _edit_track_from_key(self, _event=None) -> str:
        self._edit_track()
        return "break"

    def _edit_track(self) -> None:
        if self.updating:
            return
        selection = self.tracks_tree.selection()
        if not selection or not self.album:
            return
        index = int(selection[0])
        if index >= len(self.album.tracks):
            return
        track = self.album.tracks[index]
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("编辑曲目"))
        dialog.configure(bg=CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=20)
        frame.pack(fill="both", expand=True)
        title_var = tk.StringVar(value=track.title)
        artist_var = tk.StringVar(value=track.artist)
        ttk.Label(frame, text=tr("曲序 {0:02d}", track.track_number), style="Title.Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        ttk.Label(frame, text=tr("歌曲名"), style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=5)
        title_entry = ttk.Entry(frame, textvariable=title_var, width=40)
        title_entry.grid(row=1, column=1, sticky="ew", pady=5, padx=(12, 0))
        ttk.Label(frame, text=tr("歌手"), style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=artist_var, width=40).grid(row=2, column=1, sticky="ew", pady=5, padx=(12, 0))

        def close():
            dialog.destroy()
            # 焦点回到曲目表的同一行，可继续用 ↑ ↓ 和回车逐首编辑。
            if index < len(self.tracks_tree.get_children()):
                self.tracks_tree.focus(str(index))
            self.tracks_tree.focus_set()

        def save():
            if not title_var.get().strip():
                messagebox.showwarning(tr("缺少歌曲名"), tr("歌曲名不能为空。"), parent=dialog)
                return
            if track.origin == "auto-manual" and title_var.get().strip() == track.title:
                messagebox.showwarning(tr("请确认真实歌名"), tr("请按实体 CD 曲目表修改占位名称，再保存确认。"), parent=dialog)
                return
            track.title = title_var.get().strip()
            track.artist = artist_var.get().strip() or self.album.artist
            if track.origin == "auto-manual":
                track.origin = "manual"
            self.metadata_dirty = True
            self._refresh_tracks()
            self.tracks_tree.selection_set(str(index))
            close()

        def delete_manual():
            confirmed = messagebox.askyesno(
                tr("删除手动缺曲"),
                tr("删除后，后续在线曲目会恢复顺移前的位置。是否继续？"),
                parent=dialog,
            )
            if confirmed and self._delete_manual_track(index):
                close()

        if track.origin in MANUAL_ORIGINS and self.album.collection_id is not None:
            ttk.Button(frame, text=tr("删除手动曲目"), command=delete_manual).grid(row=3, column=0, sticky="w", pady=(16, 0))
        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.grid(row=3, column=1, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text=tr("取消"), command=close).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=tr("保存"), style="Accent.TButton", command=save).pack(side="left")
        title_entry.focus_set()
        dialog.protocol("WM_DELETE_WINDOW", close)
        for key in ("<Return>", "<KP_Enter>"):
            dialog.bind(key, lambda _event: save())
        dialog.bind("<Escape>", lambda _event: close())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
