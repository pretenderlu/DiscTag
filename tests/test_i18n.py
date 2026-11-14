import ast
import string
import unittest
from pathlib import Path

from disctag import i18n
from disctag.locales.en import EN

PACKAGE = Path(__file__).resolve().parent.parent / "disctag"


def used_keys() -> dict[str, str]:
    keys = {}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                keys.setdefault(node.args[0].value, f"{path.name}:{node.lineno}")
    return keys


def fields(template: str) -> list[tuple]:
    return sorted((name, spec) for _, name, spec, _ in string.Formatter().parse(template) if name is not None)


class TranslationTests(unittest.TestCase):
    def test_every_string_has_an_english_translation(self):
        missing = {key: where for key, where in used_keys().items() if key not in EN}
        self.assertEqual(missing, {})

    def test_no_unused_translations(self):
        self.assertEqual(sorted(set(EN) - set(used_keys())), [])

    def test_placeholders_match(self):
        mismatched = [key for key, value in EN.items() if fields(key) != fields(value)]
        self.assertEqual(mismatched, [])

    def test_tr_switches_language(self):
        try:
            i18n.set_language("en")
            self.assertEqual(i18n.tr("已完成 {0}/{1}", 2, 5), "Done 2/5")
            self.assertEqual(i18n.tr("没有翻译的文字"), "没有翻译的文字")
            i18n.set_language("zh")
            self.assertEqual(i18n.tr("已完成 {0}/{1}", 2, 5), "已完成 2/5")
        finally:
            i18n.set_language("zh")

    def test_resolve(self):
        self.assertEqual(i18n.resolve("en"), "en")
        self.assertEqual(i18n.resolve("zh"), "zh")
        self.assertIn(i18n.resolve("auto"), i18n.SUPPORTED)


if __name__ == "__main__":
    unittest.main()
