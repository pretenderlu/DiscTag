"""Window for viewing and changing the keyboard shortcuts."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from .. import shortcuts
from ..i18n import tr

if TYPE_CHECKING:
    from ..app import DiscTagApp

SCOPE_LABELS = {shortcuts.TABLE: tr("曲目表"), shortcuts.GLOBAL: tr("主窗口")}


class ShortcutWindow:
    def __init__(self, app: DiscTagApp):
        self.app = app
        px = app._px
        self.window = tk.Toplevel(app.root)
        self.window.title(tr("快捷键"))
        self.window.transient(app.root)
        self.window.configure(bg="#FFFFFF")
        self.window.minsize(px(560), px(380))
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        body = ttk.Frame(self.window, style="Card.TFrame", padding=px(16))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=tr("快捷键"), style="Title.Card.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text=tr("选中一项后点“修改”或按回车，再按下新的组合键。“曲目表”类快捷键在曲目表获得焦点时生效；双击曲目始终可以编辑。"),
            style="Muted.Card.TLabel",
            justify="left",
            wraplength=px(620),
        ).pack(anchor="w", pady=(2, px(10)))

        table = ttk.Frame(body, style="Card.TFrame")
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("action", "key", "scope"), show="headings", selectmode="browse", height=9)
        for key, text, width, anchor in (
            ("action", tr("功能"), 240, "w"),
            ("key", tr("按键"), 160, "center"),
            ("scope", tr("生效范围"), 110, "center"),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=px(width), anchor=anchor)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _event: self._change())
        self.tree.bind("<Return>", lambda _event: self._change())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_buttons())

        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x", pady=(px(12), 0))
        self.change_button = ttk.Button(actions, text=tr("修改"), style="Accent.TButton", command=self._change)
        self.change_button.pack(side="left")
        self.clear_button = ttk.Button(actions, text=tr("清除"), command=self._clear)
        self.clear_button.pack(side="left", padx=(px(8), 0))
        ttk.Button(actions, text=tr("恢复默认"), command=self._reset).pack(side="left", padx=(px(8), 0))
        ttk.Button(actions, text=tr("关闭"), command=self.close).pack(side="right")
        self.refresh()
        self.tree.selection_set("0")
        self.tree.focus("0")
        self.tree.focus_set()

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
        self.app.shortcut_window = None

    def refresh(self) -> None:
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for index, action in enumerate(shortcuts.actions()):
            spec = self.app.shortcut_map.get(action.id, "")
            self.tree.insert("", "end", iid=str(index),
                             values=(action.label, shortcuts.display(spec), SCOPE_LABELS[action.scope]))
        if selection:
            self.tree.selection_set(selection)
        self._update_buttons()

    def _selected_action(self) -> shortcuts.Action | None:
        selection = self.tree.selection()
        return shortcuts.actions()[int(selection[0])] if selection else None

    def _update_buttons(self) -> None:
        action = self._selected_action()
        self.change_button.configure(state="normal" if action else "disabled")
        bound = bool(action and self.app.shortcut_map.get(action.id))
        self.clear_button.configure(state="normal" if bound else "disabled")

    def _change(self) -> None:
        action = self._selected_action()
        if action is not None:
            CaptureDialog(self, action)

    def _clear(self) -> None:
        action = self._selected_action()
        if action is not None:
            self.app._set_shortcut(action.id, "")
            self.refresh()

    def _reset(self) -> None:
        if messagebox.askyesno(tr("恢复默认"), tr("将所有快捷键恢复为默认设置？"), parent=self.window):
            self.app._reset_shortcuts()
            self.refresh()

    def assign(self, action: shortcuts.Action, spec: str) -> bool:
        """Assigns a shortcut, asking before taking it away from another action. Returns True if assigned."""
        other_id = shortcuts.conflict(self.app.shortcut_map, spec, action.id)
        if other_id is not None:
            other = next(item for item in shortcuts.actions() if item.id == other_id)
            if not messagebox.askyesno(
                tr("快捷键已被使用"),
                tr("{0} 已用于“{1}”。改为用于“{2}”吗？", shortcuts.display(spec), other.label, action.label),
                parent=self.window,
            ):
                return False
            self.app.shortcut_map[other_id] = ""
        self.app._set_shortcut(action.id, spec)
        self.refresh()
        return True


class CaptureDialog:
    """Waits for the next key combination and assigns it to the action."""

    def __init__(self, owner: ShortcutWindow, action: shortcuts.Action):
        self.owner = owner
        self.action = action
        px = owner.app._px
        self.window = tk.Toplevel(owner.window)
        self.window.title(tr("修改快捷键"))
        self.window.transient(owner.window)
        self.window.configure(bg="#FFFFFF")
        self.window.resizable(False, False)
        frame = ttk.Frame(self.window, style="Card.TFrame", padding=px(20))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=action.label, style="Title.Card.TLabel").pack(anchor="w")
        ttk.Label(frame, text=tr("请按下新的快捷键，按 Esc 取消。"), style="Card.TLabel").pack(anchor="w", pady=(px(8), 0))
        self.error_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.error_var, style="Muted.Card.TLabel", foreground="#B34452",
                  wraplength=px(360), justify="left").pack(anchor="w", pady=(px(6), 0))
        self.window.bind("<KeyPress>", self._on_key)
        self.window.update_idletasks()
        parent = owner.window
        x = parent.winfo_rootx() + (parent.winfo_width() - self.window.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.window.winfo_height()) // 2
        self.window.geometry(f"+{x}+{y}")
        self.window.grab_set()
        self.window.focus_force()

    def _on_key(self, event) -> str:
        spec = shortcuts.from_event(event.keysym, event.state)
        if spec is None:
            return "break"
        if spec == "Esc":
            self._close()
            return "break"
        error = shortcuts.validate(spec, self.action.scope)
        if error:
            self.error_var.set(tr("{0}：{1}", shortcuts.display(spec), error))
            return "break"
        self.window.grab_release()
        if self.owner.assign(self.action, spec):
            self._close()
        else:
            self.window.grab_set()
        return "break"

    def _close(self) -> None:
        if self.window.winfo_exists():
            self.window.grab_release()
            self.window.destroy()
        self.owner.tree.focus_set()
