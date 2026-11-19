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

    def test_labels_follow_language_switch_after_import(self):
        from disctag.audio import safe_component
        from disctag.itunes import itunes_region_name
        from disctag.jobs import DONE, status_label
        from disctag.ui.common import SOURCE_DISCOGS, _region_label, source_hint
        from disctag.ui.shortcut_window import scope_label

        try:
            i18n.set_language("en")
            self.assertEqual(status_label(DONE), EN["已完成"])
            self.assertEqual(itunes_region_name("JP"), EN["日本"])
            self.assertEqual(_region_label("JP"), EN["{0}（{1}）"].format(EN["日本"], "JP"))
            self.assertEqual(source_hint(SOURCE_DISCOGS), EN["Discogs 收录实体唱片的地区版本、再版与目录号。\n需要个人令牌，请求频率受限。"])
            self.assertEqual(scope_label("table"), EN["曲目表"])
            self.assertEqual(safe_component(""), EN["未命名"])
            i18n.set_language("zh")
            self.assertEqual(status_label(DONE), "已完成")
            self.assertEqual(itunes_region_name("JP"), "日本")
            self.assertEqual(safe_component(""), "未命名")
        finally:
            i18n.set_language("zh")

    def test_no_tr_at_import_time(self):
        """tr() must only run inside functions; module/class-level calls and default arguments freeze the language."""
        offenders = []

        def visit(node, path, in_function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" and not in_function:
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for child in [*node.args.defaults, *(d for d in node.args.kw_defaults if d),
                              *getattr(node, "decorator_list", [])]:
                    visit(child, path, in_function)
                for child in node.body if isinstance(node.body, list) else [node.body]:
                    visit(child, path, True)
                return
            for child in ast.iter_child_nodes(node):
                visit(child, path, in_function)

        for path in PACKAGE.rglob("*.py"):
            visit(ast.parse(path.read_text(encoding="utf-8")), path, False)
        self.assertEqual(offenders, [])

    def test_resolve(self):
        self.assertEqual(i18n.resolve("en"), "en")
        self.assertEqual(i18n.resolve("zh"), "zh")
        self.assertIn(i18n.resolve("auto"), i18n.SUPPORTED)


if __name__ == "__main__":
    unittest.main()
