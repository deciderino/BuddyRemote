"""Every language file has exactly the keys and placeholders of en.json.

Qt-free: app.py is only read as text (LANGUAGES / LANGUAGE_NAMES)."""
import ast
import json
import re
import string
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANG_DIR = ROOT / "lang"
EXPECTED = {"de": "Deutsch", "en": "English", "es": "Español", "fr": "Français",
            "it": "Italiano", "cs": "Čeština", "ja": "日本語", "ko": "한국어"}


def load(code):
    return json.loads((LANG_DIR / f"{code}.json").read_text(encoding="utf-8"))


def placeholders(s):
    """Names used by str.format, e.g. {'name', 'port'}; also fails on broken braces."""
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f is not None)


def app_constant(name):
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    m = re.search(rf"^{name} = (.+?)\n(?=\S)", src, re.M | re.S)
    return ast.literal_eval(m.group(1).split("\n#")[0])


class LangFiles(unittest.TestCase):
    def setUp(self):
        self.en = load("en")

    def test_all_files_present(self):
        files = sorted(p.stem for p in LANG_DIR.glob("*.json"))
        self.assertEqual(files, sorted(EXPECTED))

    def test_same_keys(self):
        for code in EXPECTED:
            with self.subTest(lang=code):
                d = load(code)
                self.assertEqual(set(d) - set(self.en), set(), "extra keys")
                self.assertEqual(set(self.en) - set(d), set(), "missing keys")

    def test_same_placeholders(self):
        for code in EXPECTED:
            d = load(code)
            for key, en_val in self.en.items():
                with self.subTest(lang=code, key=key):
                    self.assertEqual(placeholders(d[key]), placeholders(en_val))

    def test_format_works(self):
        for code in EXPECTED:
            d = load(code)
            for key, en_val in self.en.items():
                names = placeholders(en_val)
                if names:
                    with self.subTest(lang=code, key=key):
                        d[key].format(**{n: "X" for n in names})

    def test_values_are_nonempty_strings(self):
        for code in EXPECTED:
            for key, val in load(code).items():
                with self.subTest(lang=code, key=key):
                    self.assertIsInstance(val, str)
                    self.assertTrue(val.strip())

    def test_same_line_breaks(self):
        for code in EXPECTED:
            d = load(code)
            for key, en_val in self.en.items():
                with self.subTest(lang=code, key=key):
                    self.assertEqual(d[key].count("\n"), en_val.count("\n"))

    def test_app_language_list(self):
        self.assertEqual(app_constant("LANGUAGES"), tuple(EXPECTED))
        self.assertEqual(app_constant("LANGUAGE_NAMES"), EXPECTED)


if __name__ == "__main__":
    unittest.main()
