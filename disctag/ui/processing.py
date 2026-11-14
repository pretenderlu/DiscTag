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
from ..jobs import CANCELLED, DONE, FAILED, PARTIAL, RUNNING, ConversionJob
from ..models import ConversionResult, renumber_tracks
from .queue_window import QueueWindow


class ProcessingMixin:
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

    def _format_changed(self) -> None:
        self.quality_combo.configure(state="readonly" if self.format_var.get() == "mp3" else "disabled")
        if not self.converting:
            if self.format_var.get() == "wav":
                self.status_var.set("保留 WAV：不重新编码，标签写入 RIFF ID3 块，并另存 cover.jpg；播放器兼容性可能不同")
            else:
                self.status_var.set("就绪")

    def _prepare_job(self) -> ConversionJob | None:
        """Validates the current album and snapshots it into a job; shows a message and returns None if not ready."""
        if not self.sources:
            messagebox.showwarning("缺少 WAV", "请先选择包含 WAV 音轨的文件夹。", parent=self.root)
            return None
        if not self.album:
            messagebox.showwarning("缺少专辑资料", "请搜索并选择专辑，或使用手动模式。", parent=self.root)
            return None
        if len(self.sources) != len(self.album.tracks):
            messagebox.showwarning("曲目数量不一致", "请使用时长匹配、手动插入缺曲、重新选择专辑，或改用手动模式。", parent=self.root)
            return None
        if any(track.origin == "auto-manual" for track in self.album.tracks):
            messagebox.showwarning("缺曲仍待确认", "请查阅实体 CD 曲目表，双击“待确认”行填写真实歌名并保存，然后再处理。", parent=self.root)
            return None
        if not self.album_var.get().strip() or not self.artist_var.get().strip():
            messagebox.showwarning("资料不完整", "专辑名称和歌手名称不能为空。", parent=self.root)
            return None
        if not self.output_var.get().strip():
            messagebox.showwarning("缺少输出目录", "请选择输出根目录。", parent=self.root)
            return None
        if self.format_var.get() != "wav":
            try:
                find_ffmpeg()
            except Exception as exc:
                messagebox.showerror("FFmpeg 不可用", str(exc), parent=self.root)
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
            overwrite = messagebox.askyesno("确认覆盖", "输出目录中已有同名曲目或封面。继续处理会覆盖这些文件，是否继续？", parent=self.root)
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
        )

    def _enqueue_current(self) -> bool:
        job = self._prepare_job()
        if job is None:
            return False
        replaced = self.job_queue.add(job)
        self._refresh_queue_view()
        position = self.job_queue.jobs.index(job) + 1
        action = "已更新队列中的" if replaced else "已加入队列"
        self.status_var.set(f"{action}《{job.title}》（第 {position} 项）· 可以导入下一张 CD")
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
        self.convert_button.configure(text="取消处理", command=self._cancel_conversion)
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
        self.status_var.set(f"{prefix}正在准备处理《{job.title}》…")
        cancel = self.cancel_event

        def progress(current: int, total: int, text: str):
            self._post(lambda: self._conversion_progress(current, total, f"{prefix}{text}"))

        def work():
            return convert_album(
                job.sources, job.album, job.output_root, job.output_format, job.mp3_quality, job.cover_data, progress,
                job.embed_cover, job.embed_max_size,
                cancel=cancel,
            )

        self.conversion_thread = self._run_async(work, lambda result: self._job_done(job, result),
                                                 lambda error: self._job_failed(job, error))

    def _job_prefix(self, job: ConversionJob) -> str:
        total = len(self.queue_run_jobs) + self.job_queue.pending_count()
        return f"[{self.queue_run_jobs.index(job) + 1}/{total}] " if total > 1 else ""

    def _cancel_conversion(self) -> None:
        if self.converting and self.cancel_event is not None and not self.cancel_event.is_set():
            self.cancel_event.set()
            self.convert_button.configure(state="disabled")
            self.status_var.set("正在取消，当前曲目停止后结束；队列中其余专辑会保留…")

    def _conversion_progress(self, current: int, _total: int, text: str) -> None:
        if self.converting:
            self.progress_var.set(current)
            self.status_var.set(text)

    def _job_done(self, job: ConversionJob, result: ConversionResult) -> None:
        job.finish(result)
        self.last_output = result.output_directory
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
        self.convert_button.configure(text="开始处理", command=self._convert, state="normal")
        self._refresh_queue_view()
        self._save_settings()
        if len(jobs) == 1:
            self._report_single_job(jobs[0])
        elif jobs:
            self._report_queue(jobs)

    def _report_single_job(self, job: ConversionJob) -> None:
        result = job.result
        if job.status == FAILED or result is None:
            self.status_var.set("处理失败")
            messagebox.showerror("处理失败", job.message, parent=self.root)
        elif result.cancelled:
            self.status_var.set(f"已取消 · 已完成 {len(result.converted_files)} 首")
            messagebox.showinfo(
                "已取消处理",
                f"已完成 {len(result.converted_files)} 首，其余曲目未处理。\n\n{result.output_directory}",
                parent=self.root,
            )
        elif result.failures:
            self.progress_var.set(len(job.sources))
            details = "\n".join(f"{failure.source.name}：{failure.message}" for failure in result.failures[:6])
            self.status_var.set(f"完成 {len(result.converted_files)} 首，失败 {len(result.failures)} 首")
            messagebox.showwarning("部分曲目处理失败", f"成功 {len(result.converted_files)} 首，失败 {len(result.failures)} 首。\n\n{details}", parent=self.root)
        else:
            self.progress_var.set(len(job.sources))
            self.status_var.set(f"处理完成 · {result.output_directory}")
            messagebox.showinfo("处理完成", f"已生成 {len(result.converted_files)} 首音乐，标签与封面处理完成。\n\n{result.output_directory}", parent=self.root)

    def _report_queue(self, jobs: list[ConversionJob]) -> None:
        done = sum(job.status == DONE for job in jobs)
        problems = [job for job in jobs if job.status in {PARTIAL, FAILED}]
        cancelled = any(job.status == CANCELLED for job in jobs)
        remaining = self.job_queue.pending_count()
        summary = f"完成 {done} 张"
        if problems:
            summary += f"，{len(problems)} 张有问题"
        if cancelled:
            summary += f"，已取消（队列中还剩 {remaining} 张）"
        self.status_var.set(f"队列处理结束 · {summary}")
        details = "\n".join(f"《{job.title}》：{job.status_label} · {job.message}" for job in problems[:8])
        text = f"本次处理了 {len(jobs)} 张专辑：{summary}。"
        if details:
            text += f"\n\n{details}\n\n可在“队列”中查看并重试。"
        if problems:
            messagebox.showwarning("队列处理结束", text, parent=self.root)
        else:
            messagebox.showinfo("队列处理结束", text, parent=self.root)

    def _queue_button_text(self) -> str:
        active = sum(not job.finished for job in self.job_queue.jobs)
        return f"队列 · {active}" if active else "队列"

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
