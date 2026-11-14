"""Output options, the conversion queue and its reports."""
from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

from ..audio import (
    convert_album,
    find_ffmpeg,
    output_directory,
    output_path,
)
from ..i18n import tr
from ..jobs import CANCELLED, DONE, FAILED, PARTIAL, RUNNING, ConversionJob, trash_sources_if_complete
from ..models import ConversionResult, renumber_tracks
from ..trash import trash_name
from .queue_window import QueueWindow


class ProcessingMixin:
    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title=tr("选择输出根目录"), initialdir=self.output_var.get() or str(Path.home()))
        if selected:
            self.output_var.set(selected)

    def _open_output(self) -> None:
        path = self.last_output or Path(self.output_var.get()).expanduser()
        if not path.is_dir():
            messagebox.showinfo(tr("目录尚不存在"), tr("完成一次处理后，即可在这里打开输出目录。"), parent=self.root)
            return
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _format_changed(self) -> None:
        self.quality_combo.configure(state="readonly" if self.format_var.get() == "mp3" else "disabled")
        if not self.converting:
            if self.format_var.get() == "wav":
                self.status_var.set(tr("WAV 不转码：输出仍为 WAV，只写入标签（RIFF ID3 块）并另存 cover.jpg；部分播放器可能读不到 WAV 标签"))
            else:
                self.status_var.set(tr("就绪"))

    def _prepare_job(self) -> ConversionJob | None:
        """Validates the current album and snapshots it into a job; shows a message and returns None if not ready."""
        if not self.sources:
            messagebox.showwarning(tr("缺少 WAV"), tr("请先选择包含 WAV 音轨的文件夹。"), parent=self.root)
            return None
        if not self.album:
            messagebox.showwarning(tr("缺少专辑资料"), tr("请搜索并选择专辑，或使用手动模式。"), parent=self.root)
            return None
        if len(self.sources) != len(self.album.tracks):
            messagebox.showwarning(tr("曲目数量不一致"), tr("请使用时长匹配、手动插入缺曲、重新选择专辑，或改用手动模式。"), parent=self.root)
            return None
        if any(track.origin == "auto-manual" for track in self.album.tracks):
            messagebox.showwarning(tr("缺曲仍待确认"), tr("请查阅实体 CD 曲目表，双击“待确认”行填写真实歌名并保存，然后再处理。"), parent=self.root)
            return None
        if not self.album_var.get().strip() or not self.artist_var.get().strip():
            messagebox.showwarning(tr("资料不完整"), tr("专辑名称和歌手名称不能为空。"), parent=self.root)
            return None
        if not self.output_var.get().strip():
            messagebox.showwarning(tr("缺少输出目录"), tr("请选择输出根目录。"), parent=self.root)
            return None
        if self.format_var.get() != "wav":
            try:
                find_ffmpeg()
            except Exception as exc:
                messagebox.showerror(tr("FFmpeg 不可用"), str(exc), parent=self.root)
                return None
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
            overwrite = messagebox.askyesno(tr("确认覆盖"), tr("输出目录中已有同名曲目或封面。继续处理会覆盖这些文件，是否继续？"), parent=self.root)
            if not overwrite:
                return None
        embed_cover, embed_max_size = self._cover_embed_choice()
        return ConversionJob(
            sources=list(self.sources),
            album=album,
            output_root=output_root,
            output_format=self.format_var.get(),
            mp3_quality=self.quality_var.get(),
            cover_data=self.cover_data,
            embed_cover=embed_cover,
            embed_max_size=embed_max_size,
            trash_sources=bool(self.trash_sources_var.get()),
        )

    def _enqueue_current(self) -> bool:
        job = self._prepare_job()
        if job is None:
            return False
        replaced = self.job_queue.add(job)
        self._refresh_queue_view()
        position = self.job_queue.jobs.index(job) + 1
        action = tr("已更新队列中的") if replaced else tr("已加入队列")
        self.status_var.set(tr("{0}《{1}》（第 {2} 项）· 可以导入下一张 CD", action, job.title, position))
        return True

    def _add_to_queue(self) -> None:
        if self.updating:
            return
        self._enqueue_current()

    def _convert(self) -> None:
        """Queues the current album (if any) and starts processing the queue."""
        if self.converting or self.updating:
            return
        has_current = bool(self.sources or self.album)
        if has_current or not self.job_queue.pending_count():
            if not self._enqueue_current():
                return
        self._start_queue()

    def _start_queue(self) -> None:
        if self.converting or not self.job_queue.pending_count():
            return
        self.converting = True
        self.cancel_event = threading.Event()
        self.queue_run_jobs = []
        self.convert_button.configure(text=tr("取消处理"), command=self._cancel_conversion)
        self._run_next_job()

    def _run_next_job(self) -> None:
        job = self.job_queue.next_pending()
        if job is None or self.cancel_event is None or self.cancel_event.is_set():
            self._finish_queue()
            return
        job.status = RUNNING
        self.queue_run_jobs.append(job)
        self.current_job = job
        self._refresh_queue_view()
        if self.preview.playing and self.preview.path in job.sources:
            self.preview.stop()
        self.progress_var.set(0)
        self.progress.configure(maximum=len(job.sources))
        prefix = self._job_prefix(job)
        self.status_var.set(tr("{0}正在准备处理《{1}》…", prefix, job.title))
        cancel = self.cancel_event

        def progress(current: int, total: int, text: str):
            self._post(lambda: self._conversion_progress(current, total, f"{prefix}{text}"))

        def work():
            result = convert_album(
                job.sources, job.album, job.output_root, job.output_format, job.mp3_quality, job.cover_data, progress,
                job.embed_cover, job.embed_max_size,
                cancel=cancel,
            )
            trash_sources_if_complete(job, result)
            return result

        self.conversion_thread = self._run_async(work, lambda result: self._job_done(job, result),
                                                 lambda error: self._job_failed(job, error))

    def _job_prefix(self, job: ConversionJob) -> str:
        total = len(self.queue_run_jobs) + self.job_queue.pending_count()
        return f"[{self.queue_run_jobs.index(job) + 1}/{total}] " if total > 1 else ""

    def _cancel_conversion(self) -> None:
        if self.converting and self.cancel_event is not None and not self.cancel_event.is_set():
            self.cancel_event.set()
            self.convert_button.configure(state="disabled")
            self.status_var.set(tr("正在取消，当前曲目停止后结束；队列中其余专辑会保留…"))

    def _conversion_progress(self, current: int, _total: int, text: str) -> None:
        if self.converting:
            self.progress_var.set(current)
            self.status_var.set(text)

    def _job_done(self, job: ConversionJob, result: ConversionResult) -> None:
        job.finish(result)
        self.last_output = result.output_directory
        if result.trashed_sources and self.sources and job.same_input(self.sources):
            # 当前界面显示的正是已移到回收站的 WAV，清空列表以免试听或再次处理不存在的文件。
            if self.preview.playing:
                self.preview.stop()
            self.sources = []
            self.source_durations = {}
            self.source_var.set(tr("源 WAV 已移到{0}", trash_name()))
            self._refresh_tracks()
        self._refresh_queue_view()
        self._run_next_job()

    def _job_failed(self, job: ConversionJob, error: Exception) -> None:
        job.fail(error)
        self._refresh_queue_view()
        self._run_next_job()

    def _finish_queue(self) -> None:
        jobs = self.queue_run_jobs
        self.converting = False
        self.cancel_event = None
        self.conversion_thread = None
        self.current_job = None
        self.queue_run_jobs = []
        self.convert_button.configure(text=tr("开始处理"), command=self._convert, state="normal")
        self._refresh_queue_view()
        self._save_settings()
        if len(jobs) == 1:
            self._report_single_job(jobs[0])
        elif jobs:
            self._report_queue(jobs)

    def _report_single_job(self, job: ConversionJob) -> None:
        result = job.result
        if job.status == FAILED or result is None:
            self.status_var.set(tr("处理失败"))
            messagebox.showerror(tr("处理失败"), job.message, parent=self.root)
        elif result.cancelled:
            self.status_var.set(tr("已取消 · 已完成 {0} 首", len(result.converted_files)))
            messagebox.showinfo(
                tr("已取消处理"),
                tr("已完成 {0} 首，其余曲目未处理。\n\n{1}", len(result.converted_files), result.output_directory)
                + self._trash_note(job),
                parent=self.root,
            )
        elif result.failures:
            self.progress_var.set(len(job.sources))
            details = "\n".join(tr("{0}：{1}", failure.source.name, failure.message) for failure in result.failures[:6])
            self.status_var.set(tr("完成 {0} 首，失败 {1} 首", len(result.converted_files), len(result.failures)))
            messagebox.showwarning(tr("部分曲目处理失败"), tr("成功 {0} 首，失败 {1} 首。\n\n{2}", len(result.converted_files), len(result.failures), details) + self._trash_note(job), parent=self.root)
        else:
            self.progress_var.set(len(job.sources))
            self.status_var.set(tr("处理完成 · {0}", result.output_directory))
            text = tr("已生成 {0} 首音乐，标签与封面处理完成。\n\n{1}", len(result.converted_files), result.output_directory) + self._trash_note(job)
            if result.trash_failures:
                messagebox.showwarning(tr("部分源 WAV 未能移到{0}", trash_name()), text, parent=self.root)
            else:
                messagebox.showinfo(tr("处理完成"), text, parent=self.root)

    def _trash_note(self, job: ConversionJob) -> str:
        result = job.result
        if not job.trash_sources or result is None:
            return ""
        if result.trash_skipped:
            return "\n\n" + tr("未全部成功，源 WAV 已全部保留。")
        note = "\n\n" + tr("{0} 个源 WAV 已移到{1}，可从{1}恢复。", len(result.trashed_sources), trash_name())
        if result.trash_failures:
            details = "\n".join(tr("{0}：{1}", failure.source.name, failure.message) for failure in result.trash_failures[:6])
            note += "\n\n" + tr("以下文件未能移动，已保留在原位置：\n{0}", details)
        return note

    def _trash_sources_toggled(self) -> None:
        if self.trash_sources_var.get():
            messagebox.showinfo(
                tr("完成后移到{0}", trash_name()),
                tr("开启后，每张专辑全部处理成功时，导入的源 WAV 会被移到{0}，需要时可从{0}恢复。\n\n"
                   "只要有曲目失败或中途取消，就会保留全部源 WAV；同一文件夹中的其他文件不会改动。", trash_name()),
                parent=self.root,
            )

    def _report_queue(self, jobs: list[ConversionJob]) -> None:
        done = sum(job.status == DONE for job in jobs)
        problems = [job for job in jobs if job.status in {PARTIAL, FAILED}]
        cancelled = any(job.status == CANCELLED for job in jobs)
        remaining = self.job_queue.pending_count()
        summary = tr("完成 {0} 张", done)
        if problems:
            summary += tr("，{0} 张有问题", len(problems))
        if cancelled:
            summary += tr("，已取消（队列中还剩 {0} 张）", remaining)
        self.status_var.set(tr("队列处理结束 · {0}", summary))
        details = "\n".join(tr("《{0}》：{1} · {2}", job.title, job.status_label, job.message) for job in problems[:8])
        text = tr("本次处理了 {0} 张专辑：{1}。", len(jobs), summary)
        if details:
            text += tr("\n\n{0}\n\n可在“队列”中查看并重试。", details)
        if problems:
            messagebox.showwarning(tr("队列处理结束"), text, parent=self.root)
        else:
            messagebox.showinfo(tr("队列处理结束"), text, parent=self.root)

    def _queue_button_text(self) -> str:
        active = sum(not job.finished for job in self.job_queue.jobs)
        return tr("队列 · {0}", active) if active else tr("队列")

    def _refresh_queue_view(self) -> None:
        button = getattr(self, "queue_button", None)
        if button is not None:
            button.configure(text=self._queue_button_text())
        window = getattr(self, "queue_window", None)
        if window is not None:
            window.refresh()

    def _show_queue(self) -> None:
        if self.queue_window is not None and self.queue_window.exists():
            self.queue_window.focus()
            return
        self.queue_window = QueueWindow(self)
