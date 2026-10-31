"""BuddyRemote – UI languages: lang/*.json strings, language choice, Qt's own translations."""

import json

from PyQt6.QtCore import QTranslator, QLibraryInfo

from paths import LANG_DIR


def load_lang(code="en") -> dict:
    path = LANG_DIR / f"{code}.json"
    if not path.exists():
        path = LANG_DIR / "en.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

LANGUAGES = ("de", "en", "es", "fr", "it", "cs", "ja", "ko")
# shown in Settings in their own language (never translated)
LANGUAGE_NAMES = {"de": "Deutsch", "en": "English", "es": "Español", "fr": "Français",
                  "it": "Italiano", "cs": "Čeština", "ja": "日本語", "ko": "한국어"}

def system_language() -> str:
    """The system locale's language if BuddyRemote has it, otherwise 'en'."""
    try:
        from PyQt6.QtCore import QLocale
        code = QLocale.system().name().lower()[:2]
        return code if code in LANGUAGES else "en"
    except Exception:
        return "en"

def language_choice(settings: dict) -> str:
    """The chosen language: one of LANGUAGES or 'auto' (system locale).
    Before 1.2 the setting had no UI and every config said "en" without being used,
    so an "en" that was never chosen in Options counts as 'auto'."""
    code = (settings or {}).get("language", "auto")
    if code == "en" and not (settings or {}).get("language_set"):
        code = "auto"
    return code if code in LANGUAGES else "auto"

def resolve_language(settings: dict) -> str:
    code = language_choice(settings)
    return code if code in LANGUAGES else system_language()

def set_language(code: str):
    global L
    L = load_lang(code)

_qt_translator = None

def install_qt_translations(qapp, code: str):
    """Qt's own strings (Yes/No/Cancel in message boxes, context menus) in the UI
    language; qtbase_*.qm ships with the PyQt6 wheel / bundle. English needs none."""
    global _qt_translator
    if code == "en" or _qt_translator is not None:
        return
    tr = QTranslator(qapp)
    if tr.load(f"qtbase_{code}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        qapp.installTranslator(tr)
        _qt_translator = tr

L = load_lang()
def t(key, **kw):
    s = L.get(key, key)
    try:
        return s.format(**kw) if kw else s
    except Exception:
        return s
