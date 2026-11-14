"""Ttk styles and window icons."""
from __future__ import annotations

from tkinter import ttk

from PIL import Image, ImageTk

from ..rounded_style import apply_rounded_styles
from .common import (
    ACCENT,
    ACCENT_DARK,
    BACKGROUND,
    CARD,
    INK,
    MUTED,
    _resource_path,
)


class ThemeMixin:
    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BACKGROUND, foreground=INK, font=(self.ui_font, 11))
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=(self.ui_font, 11))
        style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED, font=(self.ui_font, 10))
        style.configure("Title.Card.TLabel", background=CARD, foreground=INK, font=(self.ui_semibold, 15))
        style.configure("Match.Card.TLabel", background=CARD, foreground=MUTED, font=(self.ui_font, 10))
        style.configure(
            "TEntry",
            fieldbackground="#F8F9FC",
            foreground=INK,
            bordercolor="#DCE0EB",
            lightcolor="#DCE0EB",
            darkcolor="#DCE0EB",
            padding=self._px(9),
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)], fieldbackground=[("focus", CARD)])
        style.configure(
            "TCombobox",
            fieldbackground="#F8F9FC",
            foreground=INK,
            background="#F8F9FC",
            bordercolor="#DCE0EB",
            lightcolor="#DCE0EB",
            darkcolor="#DCE0EB",
            arrowcolor=ACCENT,
            arrowsize=self._px(13),
            relief="flat",
            padding=(self._px(10), self._px(11)),
        )
        style.map(
            "TCombobox",
            bordercolor=[("focus", ACCENT)],
            fieldbackground=[("readonly", "#F8F9FC")],
            background=[("readonly", "#F8F9FC"), ("active", "#EEF0F6")],
            arrowcolor=[("readonly", ACCENT), ("active", ACCENT_DARK)],
            selectbackground=[("readonly", "#F8F9FC")],
            selectforeground=[("readonly", INK)],
        )
        self.root.option_add("*TCombobox*Listbox.background", CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#EAE6FF")
        self.root.option_add("*TCombobox*Listbox.selectForeground", INK)
        self.root.option_add("*TCombobox*Listbox.font", (self.ui_font, 10))
        style.configure(
            "TButton",
            font=(self.ui_font, 10),
            padding=(self._px(10), self._px(10)),
            borderwidth=0,
            relief="flat",
            background="#EEF0F6",
            foreground="#34384A",
            focusthickness=1,
            focuscolor="#C9C2FF",
        )
        style.map(
            "TButton",
            background=[("disabled", "#F5F6F9"), ("pressed", "#D9DDE9"), ("active", "#E3E6F0")],
            foreground=[("disabled", "#A4A8B5")],
        )
        for button_style in ("Accent.TButton", "Convert.TButton"):
            style.configure(
                button_style,
                background=ACCENT,
                foreground="#FFFFFF",
                font=(self.ui_semibold, 10),
                padding=(self._px(10), self._px(10)),
                borderwidth=0,
                relief="flat",
            )
            style.map(
                button_style,
                background=[("disabled", "#C8C3EA"), ("pressed", "#4535B4"), ("active", ACCENT_DARK)],
                foreground=[("disabled", "#F2F0FA")],
            )
        style.configure(
            "Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=INK,
            rowheight=self._px(36),
            borderwidth=0,
            relief="flat",
            font=(self.ui_font, 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#F5F6FA",
            foreground=MUTED,
            font=(self.ui_semibold, 10),
            padding=(self._px(7), self._px(9)),
            borderwidth=0,
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#EAE6FF")], foreground=[("selected", INK)])
        style.map("Treeview.Heading", background=[("active", "#F5F6FA")])
        for selector_style in ("TRadiobutton", "TCheckbutton"):
            style.configure(
                selector_style,
                background=CARD,
                foreground=INK,
                font=(self.ui_font, 10),
                indicatorcolor="#F8F9FC",
                selectcolor=ACCENT,
                bordercolor="#C8CDDB",
                focusthickness=0,
            )
            style.map(
                selector_style,
                indicatorcolor=[("active", "#EAE6FF"), ("selected", ACCENT)],
                selectcolor=[("selected", ACCENT), ("active", ACCENT_DARK)],
            )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#E8EAF2",
            background=ACCENT,
            bordercolor="#E8EAF2",
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=self._px(8),
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#CDD2DF",
            troughcolor=CARD,
            bordercolor=CARD,
            lightcolor=CARD,
            darkcolor=CARD,
            arrowcolor=MUTED,
            arrowsize=self._px(12),
        )
        style.map("Vertical.TScrollbar", background=[("active", "#AEB5C8"), ("pressed", "#979FB5")])
        self.rounded_style_images = apply_rounded_styles(self.root, style, self.ui_scale)

    def _load_icon(self) -> None:
        icon_path = _resource_path("assets/icon.png")
        if not icon_path.is_file():
            return
        image = Image.open(icon_path).convert("RGBA")
        self.icon_image = ImageTk.PhotoImage(image.resize((256, 256), Image.Resampling.LANCZOS))
        self.root.iconphoto(True, self.icon_image)
        header_size = self._px(62)
        self.header_icon = ImageTk.PhotoImage(image.resize((header_size, header_size), Image.Resampling.LANCZOS))
