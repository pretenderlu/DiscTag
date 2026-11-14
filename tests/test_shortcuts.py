import unittest

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


class DisplayTests(unittest.TestCase):
    def test_display(self):
        self.assertEqual(sc.display("Ctrl+Up", "win32"), "Ctrl+↑")
        self.assertEqual(sc.display("Cmd+Shift+F", "darwin"), "⌘⇧F")
        self.assertEqual(sc.display("Space", "win32"), "空格")
        self.assertEqual(sc.display("", "win32"), "未设置")


if __name__ == "__main__":
    unittest.main()
