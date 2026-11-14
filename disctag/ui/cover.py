"""Cover size options, online and local covers, and the preview."""
from __future__ import annotations

import io
from tkinter import filedialog, messagebox

from PIL import Image, ImageOps, ImageTk

from .common import (
    _cover_embed_value,
)


class CoverMixin:
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
        if self.updating:
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
