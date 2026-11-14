"""Window listing queued albums with their processing status."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from ..i18n import tr
from ..jobs import CANCELLED, DONE, FAILED, PARTIAL, RUNNING

if TYPE_CHECKING:
    from ..app import DiscTagApp

STATUS_TAGS = {RUNNING: "running", DONE: "done", PARTIAL: "problem", FAILED: "problem", CANCELLED: "cancelled"}


class QueueWindow:
    def __init__(self, app: DiscTagApp):
        self.app = app
        px = app._px
        self.window = tk.Toplevel(app.root)
        self.window.title(tr("处理队列"))
        self.window.transient(app.root)
        self.window.minsize(px(640), px(320))
        self.window.geometry(f"{px(860)}x{px(420)}")
        self.window.configure(bg="#FFFFFF")
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        body = ttk.Frame(self.window, style="Card.TFrame", padding=px(16))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=tr("处理队列"), style="Title.Card.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text=tr("按顺序逐张处理。处理期间可以继续导入、校对下一张 CD 并加入队列。"),
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(2, px(10)))

        table = ttk.Frame(body, style="Card.TFrame")
        table.pack(fill="both", expand=True)
        columns = ("status", "album", "artist", "tracks", "format", "message")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for key, text, width, anchor, stretch in (
            ("status", tr("状态"), 72, "center", False),
            ("album", tr("专辑"), 200, "w", True),
            ("artist", tr("歌手"), 140, "w", True),
            ("tracks", tr("曲目"), 52, "center", False),
            ("format", tr("格式"), 82, "center", False),
            ("message", tr("说明"), 200, "w", True),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=px(width), anchor=anchor, stretch=stretch)
        self.tree.tag_configure("running", background="#EAE6FF")
        self.tree.tag_configure("done", foreground="#167A5B")
        self.tree.tag_configure("problem", background="#FFF0D9", foreground="#8B5100")
        self.tree.tag_configure("cancelled", foreground="#73778C")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_buttons())

        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x", pady=(px(12), 0))
        self.remove_button = ttk.Button(actions, text=tr("移除"), command=self._remove)
        self.remove_button.pack(side="left")
        self.retry_button = ttk.Button(actions, text=tr("重新排队"), command=self._retry)
        self.retry_button.pack(side="left", padx=(px(8), 0))
        self.clear_button = ttk.Button(actions, text=tr("清除已结束"), command=self._clear_finished)
        self.clear_button.pack(side="left", padx=(px(8), 0))
        ttk.Button(actions, text=tr("关闭"), command=self.close).pack(side="right")
        self.start_button = ttk.Button(actions, text=tr("开始处理队列"), style="Accent.TButton", command=self._start)
        self.start_button.pack(side="right", padx=(0, px(8)))
        self.refresh()

    def exists(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def close(self) -> None:
        if self.exists():
            self.window.destroy()
        self.app.queue_window = None

    def refresh(self) -> None:
        if not self.exists():
            return
        selection = self._selected_index()
        self.tree.delete(*self.tree.get_children())
        for index, job in enumerate(self.app.job_queue.jobs):
            tag = STATUS_TAGS.get(job.status)
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(job.status_label, job.title, job.artist, len(job.sources), job.format_label, job.message),
                tags=(tag,) if tag else (),
            )
        if selection is not None and selection < len(self.app.job_queue.jobs):
            self.tree.selection_set(str(selection))
        self._update_buttons()

    def _selected_index(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _update_buttons(self) -> None:
        index = self._selected_index()
        jobs = self.app.job_queue.jobs
        job = jobs[index] if index is not None and index < len(jobs) else None
        self.remove_button.configure(state="normal" if job and job.status != RUNNING else "disabled")
        self.retry_button.configure(state="normal" if job and job.status in {PARTIAL, FAILED, CANCELLED} else "disabled")
        self.clear_button.configure(state="normal" if any(item.finished for item in jobs) else "disabled")
        can_start = not self.app.converting and not self.app.updating and self.app.job_queue.pending_count() > 0
        self.start_button.configure(state="normal" if can_start else "disabled")

    def _remove(self) -> None:
        index = self._selected_index()
        if index is not None and self.app.job_queue.remove(index):
            self.app._refresh_queue_view()

    def _retry(self) -> None:
        index = self._selected_index()
        if index is not None and self.app.job_queue.retry(index):
            self.app._refresh_queue_view()

    def _clear_finished(self) -> None:
        if self.app.job_queue.clear_finished():
            self.app._refresh_queue_view()

    def _start(self) -> None:
        if not self.app.updating:
            self.app._start_queue()
