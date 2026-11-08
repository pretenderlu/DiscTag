from __future__ import annotations

from PIL import Image, ImageDraw, ImageTk


def apply_rounded_styles(root, style, scale: float) -> list[ImageTk.PhotoImage]:
    images: list[ImageTk.PhotoImage] = []
    size = max(96, round(96 * scale))
    minimum = max(16, round(16 * scale))
    border = max(6, round(6 * scale))

    def rounded_image(fill: str, outline: str, radius: int = 5, corner: str | None = "#FFFFFF") -> ImageTk.PhotoImage:
        background = corner if corner else (0, 0, 0, 0)
        image = Image.new("RGBA", (size, size), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, size - 1, size - 1),
            radius=max(4, round(radius * scale)),
            fill=fill,
            outline=outline,
            width=1,
        )
        photo = ImageTk.PhotoImage(image, master=root)
        images.append(photo)
        return photo

    button = rounded_image("#EEF0F6", "#EEF0F6")
    button_active = rounded_image("#E3E6F0", "#E3E6F0")
    button_pressed = rounded_image("#D9DDE9", "#D9DDE9")
    button_disabled = rounded_image("#F5F6F9", "#F5F6F9")
    accent = rounded_image("#6857E5", "#6857E5")
    accent_active = rounded_image("#5140C8", "#5140C8")
    accent_pressed = rounded_image("#4535B4", "#4535B4")
    accent_disabled = rounded_image("#C8C3EA", "#C8C3EA")
    field = rounded_image("#F8F9FC", "#DCE0EB")
    field_focus = rounded_image("#FFFFFF", "#6857E5")
    field_disabled = rounded_image("#F5F6F9", "#E3E6EF")

    style.element_create(
        "DiscTag.Button.border",
        "image",
        button,
        ("pressed", button_pressed),
        ("active", button_active),
        ("disabled", button_disabled),
        border=border,
        sticky="nsew",
        width=minimum,
        height=minimum,
    )
    style.element_create(
        "DiscTagAccent.Button.border",
        "image",
        accent,
        ("pressed", accent_pressed),
        ("active", accent_active),
        ("disabled", accent_disabled),
        border=border,
        sticky="nsew",
        width=minimum,
        height=minimum,
    )
    for element_name in ("DiscTag.Entry.field", "DiscTag.Combobox.field"):
        style.element_create(
            element_name,
            "image",
            field,
            ("focus", field_focus),
            ("disabled", field_disabled),
            border=border,
            sticky="nsew",
            width=minimum,
            height=minimum,
        )

    def button_layout(element_name: str):
        return [
            (
                element_name,
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Button.padding",
                            {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]},
                        )
                    ],
                },
            )
        ]

    style.layout("TButton", button_layout("DiscTag.Button.border"))
    style.layout("Accent.TButton", button_layout("DiscTagAccent.Button.border"))
    style.layout("Convert.TButton", button_layout("DiscTagAccent.Button.border"))
    style.layout(
        "TEntry",
        [
            (
                "DiscTag.Entry.field",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Entry.padding",
                            {"sticky": "nswe", "children": [("Entry.textarea", {"sticky": "nswe"})]},
                        )
                    ],
                },
            )
        ],
    )
    style.layout(
        "TCombobox",
        [
            (
                "DiscTag.Combobox.field",
                {
                    "sticky": "nswe",
                    "children": [
                        ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                        (
                            "Combobox.padding",
                            {"sticky": "nswe", "children": [("Combobox.textarea", {"sticky": "nswe"})]},
                        )
                    ],
                },
            )
        ],
    )
    style.layout("Card.TFrame", [("Frame.border", {"sticky": "nswe"})])
    style.layout(
        "Treeview",
        [("Treeview.padding", {"sticky": "nswe", "children": [("Treeview.treearea", {"sticky": "nswe"})]})],
    )
    style.configure("TButton", anchor="center")
    style.configure("TEntry", borderwidth=0, relief="flat", background="#FFFFFF")
    style.configure(
        "TCombobox",
        borderwidth=0,
        lightcolor="#F8F9FC",
        darkcolor="#F8F9FC",
    )
    return images
