"""Checking, downloading and installing new releases."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from .. import __version__
from ..i18n import tr
from ..updates import check_for_updates, download_update
from .common import (
    ACCENT,
    CARD,
    INK,
)


class UpdateMixin:
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
            action = tr("点击圆点查看更新") if info.download_url else tr("点击右下角打开发布页")
            self.status_var.set(tr("发现新版本 {0} · {1}", info.version, action))

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
            messagebox.showwarning(tr("正在处理专辑"), tr("请等待当前专辑处理完成后再更新。"), parent=self.root)
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
        dialog.title(tr("自动更新"))
        dialog.configure(bg=CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=self._px(22))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=tr("发现新版本 {0}", info.version), style="Title.Card.TLabel").pack(anchor="w")
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
            text=tr("查看发布页并手动下载"),
            style="Card.TLabel",
            foreground=ACCENT,
            cursor="hand2",
        )
        release_link.pack(anchor="w", pady=(self._px(14), 0))
        release_link.bind("<Button-1>", lambda _event: webbrowser.open(info.url, new=2))
        release_link.bind("<Enter>", lambda _event: release_link.configure(font=(self.ui_font, 11, "underline")))
        release_link.bind("<Leave>", lambda _event: release_link.configure(font=(self.ui_font, 11)))
        ttk.Label(frame, text=tr("是否下载并自动安装？"), style="Card.TLabel").pack(anchor="w", pady=(self._px(16), 0))
        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.pack(anchor="e", pady=(self._px(12), 0))
        ttk.Button(buttons, text=tr("否"), command=self._close_update_dialog).pack(side="left", padx=(0, 8))
        yes_button = ttk.Button(buttons, text=tr("是"), style="Accent.TButton", command=lambda: self._begin_update_download(info))
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
            messagebox.showwarning(tr("正在处理专辑"), tr("请等待当前专辑处理完成后再更新。"), parent=self.root)
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

        self.status_var.set(tr("正在下载更新…"))
        self._run_async(work, self._install_update, self._update_failed)

    def _update_download_progress(self, downloaded: int, total: int) -> None:
        self.progress_var.set(downloaded)
        if total:
            self.status_var.set(tr("正在下载更新 · {0:.0%}", downloaded / total))
        else:
            self.status_var.set(tr("已下载 {0:.1f} MB", downloaded / 1024 / 1024))

    def _install_update(self, installer: Path) -> None:
        self.updating = False
        self.status_var.set(tr("更新包校验完成，正在安装…"))
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
        self.status_var.set(tr("自动更新失败：{0}", error))
        choice = messagebox.askyesnocancel(
            tr("自动更新失败"),
            tr("{0}\n\n选择\"是\"重试下载，选择\"否\"打开发布页手动下载。", error),
            parent=self.root,
        )
        if choice:
            self._start_update_download()
        elif choice is False and self.latest_update:
            webbrowser.open(self.latest_update.url, new=2)
