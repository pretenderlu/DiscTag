import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from disctag import shortcuts as sc


class FromEventTests(unittest.TestCase):
    def test_windows_modifiers(self):
        self.assertEqual(sc.from_event("f", 0x4, "win32"), "Ctrl+F")
        self.assertEqual(sc.from_event("F", 0x4 | 0x1, "win32"), "Ctrl+Shift+F")
        self.assertEqual(sc.from_event("Up", 0x20000, "win32"), "Alt+Up")

    def test_numlock_and_capslock_are_ignored_on_windows(self):
        self.assertEqual(sc.from_event("space", 0x8, "win32"), "Space")
        self.assertEqual(sc.from_event("F", 0x2, "win32"), "F")

    def test_macos_command_and_option(self):
        self.assertEqual(sc.from_event("Return", 0x8, "darwin"), "Cmd+Enter")
        self.assertEqual(sc.from_event("o", 0x10, "darwin"), "Alt+O")

    def test_key_names(self):
        self.assertEqual(sc.from_event("KP_Enter", 0, "win32"), "Enter")
        self.assertEqual(sc.from_event("F5", 0, "win32"), "F5")
        self.assertEqual(sc.from_event("Prior", 0, "win32"), "PageUp")

    def test_bare_modifier_returns_none(self):
        self.assertIsNone(sc.from_event("Control_L", 0x4, "win32"))

    def test_unknown_ime_keysym_returns_none(self):
        for platform in ("win32", "darwin"):
            self.assertIsNone(sc.from_event("??", 0, platform))
            self.assertIsNone(sc.from_event("??", 0x4, platform))
            self.assertIsNone(sc.from_event("", 0, platform))

    def test_shifted_symbol_keeps_tk_keysym(self):
        self.assertEqual(sc.from_event("exclam", 0x4 | 0x1, "win32"), "Ctrl+Shift+exclam")


class ValidateTests(unittest.TestCase):
    def test_navigation_keys_are_reserved(self):
        self.assertIsNotNone(sc.validate("Up", sc.TABLE))
        self.assertIsNotNone(sc.validate("Esc", sc.TABLE))
        self.assertIsNone(sc.validate("Ctrl+Up", sc.TABLE))

    def test_editing_shortcuts_are_reserved(self):
        self.assertIsNotNone(sc.validate("Ctrl+C", sc.GLOBAL))
        self.assertIsNotNone(sc.validate("Cmd+V", sc.GLOBAL))
        self.assertIsNone(sc.validate("Ctrl+Shift+C", sc.GLOBAL))

    def test_global_needs_modifier_or_function_key(self):
        self.assertIsNotNone(sc.validate("Space", sc.GLOBAL))
        self.assertIsNotNone(sc.validate("Shift+P", sc.GLOBAL))
        self.assertIsNone(sc.validate("F5", sc.GLOBAL))
        self.assertIsNone(sc.validate("Alt+P", sc.GLOBAL))
        self.assertIsNone(sc.validate("Space", sc.TABLE))

    def test_alt_f4_is_reserved(self):
        self.assertIsNotNone(sc.validate("Alt+F4", sc.GLOBAL))

    def test_defaults_are_valid_and_unique(self):
        for platform in ("win32", "darwin"):
            mapping = sc.load({}, platform)
            values = [value for value in mapping.values() if value]
            self.assertEqual(len(values), len(set(values)))
            for action in sc.actions():
                if mapping[action.id]:
                    self.assertIsNone(sc.validate(mapping[action.id], action.scope), action.id)


class LoadTests(unittest.TestCase):
    def test_platform_defaults(self):
        self.assertEqual(sc.load({}, "win32")["search"], "Ctrl+F")
        self.assertEqual(sc.load({}, "darwin")["search"], "Cmd+F")

    def test_saved_override_and_unbinding(self):
        mapping = sc.load({"search": "F3", "edit_track": ""}, "win32")
        self.assertEqual(mapping["search"], "F3")
        self.assertEqual(mapping["edit_track"], "")

    def test_invalid_or_duplicate_saved_values_fall_back(self):
        mapping = sc.load({"search": "Space", "import_wav": 5, "start": "Ctrl+F"}, "win32")
        self.assertEqual(mapping["search"], "Ctrl+F")
        self.assertEqual(mapping["import_wav"], "Ctrl+O")
        self.assertEqual(mapping["start"], "Ctrl+Enter")

    def test_overrides_round_trip(self):
        mapping = sc.load({"search": "F3"}, "win32")
        self.assertEqual(sc.overrides(mapping, "win32"), {"search": "F3"})
        self.assertEqual(sc.load(sc.overrides(mapping, "win32"), "win32"), mapping)

    def test_conflict(self):
        mapping = sc.load({}, "win32")
        self.assertEqual(sc.conflict(mapping, "Ctrl+F", "start"), "search")
        self.assertIsNone(sc.conflict(mapping, "Ctrl+F", "search"))


class MacOSReservedTests(unittest.TestCase):
    RESERVED = (("q", 0x8), ("w", 0x8), ("h", 0x8), ("m", 0x8), ("Tab", 0x8), ("space", 0x8), ("Escape", 0x8 | 0x10))

    def test_macos_system_shortcuts_are_reserved(self):
        for keysym, state in self.RESERVED:
            spec = sc.from_event(keysym, state, "darwin")
            for scope in (sc.TABLE, sc.GLOBAL):
                self.assertEqual(sc.validate(spec, scope), "这是 macOS 系统快捷键，请换一个", spec)

    def test_other_macos_combinations_are_allowed(self):
        for spec in ("Cmd+Shift+Q", "Cmd+Alt+W", "Cmd+Esc", "Cmd+O"):
            self.assertIsNone(sc.validate(spec, sc.GLOBAL), spec)

    def test_windows_is_not_affected(self):
        for keysym, state in self.RESERVED:
            spec = sc.from_event(keysym, state | 0x4, "win32")
            self.assertNotIn("Cmd", spec)
            self.assertNotEqual(sc.validate(spec, sc.TABLE), "这是 macOS 系统快捷键，请换一个", spec)
        self.assertIsNone(sc.validate("Ctrl+Q", sc.GLOBAL))
        self.assertEqual(sc.load({"import_wav": "Ctrl+Q"}, "win32")["import_wav"], "Ctrl+Q")

    def test_saved_reserved_override_falls_back_to_default(self):
        mapping = sc.load({"import_wav": "Cmd+Q", "show_queue": "Cmd+Space"}, "darwin")
        self.assertEqual(mapping["import_wav"], "Cmd+O")
        self.assertEqual(mapping["show_queue"], "")


class DisplayTests(unittest.TestCase):
    def test_display(self):
        self.assertEqual(sc.display("Ctrl+Up", "win32"), "Ctrl+↑")
        self.assertEqual(sc.display("Cmd+Shift+F", "darwin"), "⌘⇧F")
        self.assertEqual(sc.display("Space", "win32"), "空格")
        self.assertEqual(sc.display("", "win32"), "未设置")

    def test_display_symbol_keys(self):
        self.assertEqual(sc.display("Shift+exclam", "win32"), "Shift+!")
        self.assertEqual(sc.display("Ctrl+Shift+question", "win32"), "Ctrl+Shift+?")
        self.assertEqual(sc.display("Shift+asciitilde", "win32"), "Shift+~")
        self.assertEqual(sc.display("Cmd+Shift+parenleft", "darwin"), "⌘⇧(")
        self.assertEqual(sc.display("Ctrl+Shift+F", "win32"), "Ctrl+Shift+F")


class WindowEscapeTests(unittest.TestCase):
    def app(self):
        return SimpleNamespace(_px=lambda value: value, root=Mock(), shortcut_map=sc.load({}, "win32"),
                               shortcut_window=None, queue_window=None, job_queue=Mock(jobs=[]),
                               converting=False, updating=False)

    def escape_handler(self, window):
        handlers = [call.args[1] for call in window.window.bind.call_args_list if call.args[0] == "<Escape>"]
        self.assertEqual(len(handlers), 1)
        return handlers[0]

    def test_escape_closes_shortcut_window(self):
        from disctag.ui import shortcut_window

        app = self.app()
        with patch.object(shortcut_window, "tk"), patch.object(shortcut_window, "ttk"):
            window = shortcut_window.ShortcutWindow(app)
        app.shortcut_window = window
        self.escape_handler(window)(object())
        window.window.destroy.assert_called_once()
        self.assertIsNone(app.shortcut_window)

    def test_escape_closes_queue_window(self):
        from disctag.ui import queue_window

        app = self.app()
        with patch.object(queue_window, "tk"), patch.object(queue_window, "ttk"),                 patch.object(queue_window.QueueWindow, "refresh"):
            window = queue_window.QueueWindow(app)
        app.queue_window = window
        self.escape_handler(window)(object())
        window.window.destroy.assert_called_once()
        self.assertIsNone(app.queue_window)

    def test_escape_in_recorder_only_closes_recorder(self):
        from disctag.ui import shortcut_window

        owner = Mock()
        dialog = shortcut_window.CaptureDialog.__new__(shortcut_window.CaptureDialog)
        dialog.owner, dialog.action, dialog.window = owner, sc.actions()[0], Mock()
        result = dialog._on_key(SimpleNamespace(keysym="Escape", state=0))
        self.assertEqual(result, "break")
        dialog.window.destroy.assert_called_once()
        owner.window.destroy.assert_not_called()
        owner.assign.assert_not_called()


if __name__ == "__main__":
    unittest.main()
