from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk


def _rounded_points(x1, y1, x2, y2, radius):
    points = [(x1 + radius, y1), (x2 - radius, y1)]

    def arc(cx, cy, start):
        for step in range(9):
            angle = math.radians(start + step * 90 / 8)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    arc(x2 - radius, y1 + radius, -90)
    points.append((x2, y2 - radius))
    arc(x2 - radius, y2 - radius, 0)
    points.append((x1 + radius, y2))
    arc(x1 + radius, y2 - radius, 90)
    points.append((x1, y1 + radius))
    arc(x1 + radius, y1 + radius, 180)
    return [coordinate for point in points for coordinate in point]


class RoundedPanel(tk.Canvas):
    def __init__(
        self,
        parent,
        *,
        padding=0,
        width=None,
        height=None,
        radius=10,
        inset=None,
        fill="#FFFFFF",
        outline="#FFFFFF",
        parent_background="#F3F5FA",
        fit_height=False,
    ):
        super().__init__(
            parent,
            width=width or 1,
            height=height or 1,
            highlightthickness=0,
            bd=0,
            bg=parent_background,
        )
        self.radius = max(1, round(radius))
        self.inset = max(2, self.radius // 3) if inset is None else max(2, round(inset))
        self.fit_height = fit_height
        self.content = ttk.Frame(self, style="Card.TFrame", padding=padding)
        self.shape = self.create_polygon(
            (0, 0, 1, 0, 1, 1, 0, 1),
            smooth=False,
            fill=fill,
            outline="",
        )
        self.border = self.create_polygon(
            (0, 0, 1, 0, 1, 1, 0, 1),
            smooth=False,
            fill="",
            outline=outline,
            width=1,
        )
        self.window = self.create_window((0, 0), window=self.content, anchor="nw")
        self.bind("<Configure>", self._draw)
        self.content.bind("<Configure>", self._fit_content_height)

    def _fit_content_height(self, _event=None):
        if not self.fit_height:
            return
        height = self.content.winfo_reqheight() + self.inset * 2
        if height > 1 and height != self.winfo_height():
            tk.Canvas.configure(self, height=height)

    def _draw(self, event=None):
        width = event.width if event else self.winfo_width()
        height = event.height if event else self.winfo_height()
        if width <= 1 or height <= 1:
            return
        radius = min(self.radius, (width - 2) // 2, (height - 2) // 2)
        x1, y1, x2, y2 = 1, 1, width - 2, height - 2
        points = _rounded_points(x1, y1, x2, y2, radius)
        self.coords(self.shape, *points)
        self.coords(self.border, *points)
        self.coords(self.window, self.inset, self.inset)
        options = {"width": max(1, width - self.inset * 2)}
        if not self.fit_height:
            options["height"] = max(1, height - self.inset * 2)
        self.itemconfigure(self.window, **options)
        self.tag_lower(self.shape)
        self.tag_raise(self.border)
