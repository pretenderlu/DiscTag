"""Dispatches the customizable keyboard shortcuts and keeps the track-table hint in sync."""
from __future__ import annotations

from .. import shortcuts
from ..i18n import tr
from .shortcut_window import ShortcutWindow


class KeyboardMixin:
    def _apply_shortcuts(self) -> None:
        self._shortcut_lookup = {spec: action_id for action_id, spec in self.shortcut_map.items() if spec}
        self._shortcut_scopes = {action.id: action.scope for action in shortcuts.actions()}
        label = getattr(self, "track_hint_label", None)
        if label is not None:
            label.configure(text=self._track_hint_text())

    def _shortcut_action(self, event, scope: str) -> str | None:
        spec = shortcuts.from_event(event.keysym, event.state)
        action_id = self._shortcut_lookup.get(spec) if spec else None
        return action_id if action_id and self._shortcut_scopes.get(action_id) == scope else None

    def _on_table_key(self, event) -> str | None:
        action_id = self._shortcut_action(event, shortcuts.TABLE)
        if action_id is None:
            return None
        self._run_shortcut(action_id)
        # 阻止 Treeview 自带的按键处理，例如 Ctrl+↑ 不应同时移动选中项。
        return "break"

    def _on_global_key(self, event) -> str | None:
        action_id = self._shortcut_action(event, shortcuts.GLOBAL)
        if action_id is None:
            return None
        self._run_shortcut(action_id)
        return "break"

    def _run_shortcut(self, action_id: str) -> None:
        if action_id == "edit_track":
            self._edit_track()
        elif action_id == "toggle_preview":
            selection = self.tracks_tree.selection()
            if selection:
                self._toggle_playback(int(selection[0]))
        elif action_id == "move_up":
            self._move_source(-1)
        elif action_id == "move_down":
            self._move_source(1)
        elif action_id == "import_wav":
            self._import_wav()
        elif action_id == "search":
            self._search()
        elif action_id == "start":
            self._convert()
        elif action_id == "add_to_queue":
            self._add_to_queue()
        elif action_id == "show_queue":
            self._show_queue()

    def _track_hint_text(self) -> str:
        edit = self.shortcut_map.get("edit_track", "")
        preview = self.shortcut_map.get("toggle_preview", "")
        parts = [
            tr("选中曲目后按 {0} 或双击，即可编辑歌曲名和歌手", shortcuts.display(edit))
            if edit else tr("选中曲目后双击，即可编辑歌曲名和歌手"),
        ]
        if preview:
            parts.append(tr("按 {0} 试听 / 停止", shortcuts.display(preview)))
        parts.append(tr("↑ ↓ 切换曲目，编辑窗口中回车保存、Esc 取消"))
        parts.append(tr("右下角“快捷键”可自定义"))
        return tr("；").join(parts) + tr("。")

    def _set_shortcut(self, action_id: str, spec: str) -> None:
        self.shortcut_map[action_id] = spec
        self._apply_shortcuts()
        self._save_settings()

    def _reset_shortcuts(self) -> None:
        self.shortcut_map = shortcuts.load({})
        self._apply_shortcuts()
        self._save_settings()

    def _show_shortcuts(self) -> None:
        window = getattr(self, "shortcut_window", None)
        if window is not None and window.exists():
            window.focus()
            return
        self.shortcut_window = ShortcutWindow(self)
