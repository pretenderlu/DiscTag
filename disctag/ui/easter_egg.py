"""Seven clicks on the header icon."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from ..fireworks import Fireworks
from ..i18n import tr
from .common import (
    _resource_path,
)


class EasterEggMixin:
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
        dialog.title(tr("DiscTag · 水友驱动开发"))
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
        close_button = ttk.Button(button_frame, text=tr("好耶，继续整理音乐"), style="Accent.TButton", command=self._close_easter_egg)
        close_button.pack(pady=self._px(9))
        close_button.focus_set()
        dialog.protocol("WM_DELETE_WINDOW", self._close_easter_egg)
        dialog.bind("<Escape>", lambda _event: self._close_easter_egg())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        self.status_var.set(tr("你发现了隐藏彩蛋：水友驱动开发 · 点击画面可追加烟花"))

    def _close_easter_egg(self) -> None:
        if self.fireworks:
            self.fireworks.stop()
            self.fireworks = None
        self.easter_egg_image = None
        if self.easter_egg_dialog and self.easter_egg_dialog.winfo_exists():
            self.easter_egg_dialog.destroy()
        self.easter_egg_dialog = None
