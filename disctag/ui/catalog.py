"""Catalog search, album selection, source switching and the Discogs token."""
from __future__ import annotations

import copy
from tkinter import messagebox

from ..i18n import tr
from ..itunes import ITUNES_REGIONS
from ..models import AlbumMetadata, AlbumSummary
from ..musicbrainz import MusicBrainzError, toc_from_durations
from ..ranking import EXACT, DurationFit, candidates_to_verify, rank_results, result_key, verify_candidates
from .common import (
    SOURCE_DISCOGS,
    SOURCE_HINTS,
    SOURCE_ITUNES,
    SOURCE_MUSICBRAINZ,
    _region_code,
)


class CatalogMixin:
    def _invalidate_metadata_requests(self) -> None:
        self.search_request_id += 1
        self.album_request_id += 1
        self.cover_request_id += 1
        self.search_button.configure(state="disabled" if self.updating else "normal")

    def _clear_album(self) -> None:
        if self.updating:
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
        self.album_info_var.set(tr("搜索并选择专辑，或进入手动模式"))
        self._refresh_tracks()
        self.status_var.set(tr("已清空专辑资料，可输入新专辑；已导入的 WAV 保持不变"))
        self.album_entry.focus_set()

    def _search(self) -> None:
        if self.updating:
            return
        source = self.metadata_source_var.get()
        if not self.album_var.get().strip() and not (source == SOURCE_MUSICBRAINZ and self.sources):
            hint = tr("请先输入专辑名称。")
            if source == SOURCE_MUSICBRAINZ:
                hint = tr("请输入专辑名称，或先导入 WAV 以按音轨时长识别光盘。")
            messagebox.showwarning(tr("缺少专辑名称"), hint, parent=self.root)
            return
        region = self.region_var.get()
        album = self.album_var.get().strip()
        artist = self.artist_var.get().strip()
        token = self.discogs_token_var.get().strip()
        if source == SOURCE_DISCOGS and not token:
            messagebox.showwarning(tr("需要 Discogs 令牌"), tr("请先点击“申请令牌”创建 Personal Access Token，再粘贴到令牌输入框。"), parent=self.root)
            self.discogs_token_entry.focus_set()
            return
        self._save_discogs_token()
        self._invalidate_metadata_requests()
        request_id = self.search_request_id
        self.search_button.configure(state="disabled")
        if source == SOURCE_DISCOGS:
            self.status_var.set(tr("正在查询 Discogs 实体唱片曲库…"))
        elif source == SOURCE_MUSICBRAINZ:
            self.status_var.set(tr("正在查询 MusicBrainz…") if not self.sources else tr("正在按音轨时长在 MusicBrainz 识别光盘…"))
        elif region == "ALL":
            self.status_var.set(tr("正在并行查询全部地区…"))
        elif region == "CN":
            self.status_var.set(tr("正在查询中国大陆 Apple Music 公开网页…"))
        else:
            self.status_var.set(tr("正在查询 {0} iTunes…", ITUNES_REGIONS[region]))

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
                       and self.status_var.set(tr("正在按本地 WAV 时长核对候选版本…")))
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
            warning = tr("；{0} 个地区查询失败", len(self.client.last_warnings)) if source == SOURCE_ITUNES and self.client.last_warnings else ""
            exact = sum(marker == "✓" for marker in self.result_markers.values())
            fit_text = tr("；{0} 个版本与本地时长吻合（✓）", exact) if exact else ""
            if not exact and any(marker == "≈" for marker in self.result_markers.values()):
                fit_text = tr("；≈ 表示可按时长补出缺曲")
            self.status_var.set(tr("找到 {0} 个专辑版本{1}{2}", len(results), fit_text, warning) if results else tr("没有找到专辑，请更换关键词或地区"))
            if results:
                self.results_tree.selection_set("0")
                self.results_tree.focus("0")
            elif source == SOURCE_ITUNES and self.client.last_warnings:
                messagebox.showwarning(tr("地区查询失败"), "\n".join(self.client.last_warnings), parent=self.root)

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
        self.status_var.set(tr("{0} 查询失败", self.metadata_source_var.get()))
        messagebox.showerror(tr("搜索失败"), str(error), parent=self.root)

    def _album_selected(self, _event=None) -> None:
        if self.updating:
            return
        selection = self.results_tree.selection()
        if not selection:
            return
        summary = self.results[int(selection[0])]
        if self.album and self.metadata_dirty:
            replace = messagebox.askyesno(
                tr("替换当前专辑资料"),
                tr("更换专辑会清除当前的手动补曲和曲目修改，是否继续？"),
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
        self.status_var.set(tr("正在载入 {0}（{1}）…", summary.title, summary.country))

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
            self.status_var.set(tr("已载入《{0}》，请核对曲目对应关系", album.title))
            if cover_request_id == self.cover_request_id:
                self.cover_data = cover
                self.cover_is_local = False
                if cover:
                    self._show_cover(cover)
                else:
                    self._clear_cover()
                    self.status_var.set(tr("专辑已载入；{0}，可选择本地封面", cover_error))
            elif not self.cover_is_local:
                self.cover_data = None
                self._clear_cover()
                if album.artwork_url:
                    self._cover_size_changed()
                else:
                    self.status_var.set(tr("专辑已载入，没有在线封面，可选择本地封面"))
            if alignment_message:
                self.status_var.set(alignment_message)

        self._run_async(work, done, lambda error: self._album_load_failed(error, request_id))

    def _album_load_failed(self, error: Exception, request_id: int) -> None:
        if request_id != self.album_request_id:
            return
        self.status_var.set(tr("专辑资料载入失败"))
        messagebox.showerror(tr("载入失败"), str(error), parent=self.root)

    def _metadata_source_changed(self, _event=None) -> None:
        source = self.metadata_source_var.get()
        if source == SOURCE_DISCOGS:
            self.region_label.pack_forget()
            self.region_combo.pack_forget()
            self.token_header.pack(fill="x", before=self.search_button.master)
            self.discogs_token_entry.pack(fill="x", pady=(4, 6), before=self.search_button.master)
            self.search_button.configure(text=tr("搜索 Discogs"))
        elif source == SOURCE_MUSICBRAINZ:
            for widget in (self.region_label, self.region_combo, self.token_header, self.discogs_token_entry):
                widget.pack_forget()
            self.search_button.configure(text=tr("搜索 MusicBrainz"))
        else:
            self.token_header.pack_forget()
            self.discogs_token_entry.pack_forget()
            self.region_label.pack(anchor="w", before=self.search_button.master)
            self.region_combo.pack(fill="x", pady=(4, 6), before=self.search_button.master)
            self.search_button.configure(text=tr("搜索 iTunes"))
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
            self.album_info_var.set(tr("搜索并选择专辑，或进入手动模式"))
            self._refresh_tracks()
            self.status_var.set(tr("已切换曲库，专辑名称和歌手已保留，可重新搜索"))

    def _region_changed(self, _event=None) -> None:
        label = self.region_combo.get()
        self.region_var.set(_region_code(label))

    def _discogs_token_ready(self, token: str) -> None:
        if token and not self.discogs_token_var.get():
            self.discogs_token_var.set(token)
        self.discogs_token_loaded = True

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
