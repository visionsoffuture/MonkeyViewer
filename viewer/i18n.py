"""Interface language: English (source) and Georgian.

    T("Saved {0}", name)  ->  "შენახულია: report.pdf"  (Georgian)  /  "Saved report.pdf"  (English)

The language is chosen in More -> Language (auto / ქართული / English) or forced by the Language policy.
"auto" follows the operating system's display language.
"""

import locale
import os
import sys

LANGUAGES = {"ka": "ქართული", "en": "English"}
_LANG = "en"
_TABLE = {}


def system_language():
    """'ka' when the operating system's display language is Georgian, else 'en'."""
    try:
        if sys.platform == "win32":
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "ka" if (lang_id & 0x3FF) == 0x37 else "en"           # LANG_GEORGIAN
        if sys.platform == "darwin":
            import subprocess                  # fixed absolute command, no shell, no user input
            out = subprocess.run(["/usr/bin/defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                                 text=True, timeout=5, stdin=subprocess.DEVNULL).stdout
            first = next((part.strip(' "(),\n') for part in out.split(",") if part.strip(' "(),\n')), "")
            return "ka" if first.lower().startswith("ka") else "en"
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            if os.environ.get(var):
                return "ka" if os.environ[var].lower().startswith("ka") else "en"
        return "ka" if (locale.getlocale()[0] or "").lower().startswith("ka") else "en"
    except Exception:  # noqa: BLE001
        return "en"


def setup(preference="auto"):
    """Pick the language once, before any window is built."""
    global _LANG, _TABLE
    from . import policy
    forced = str(policy.get("Language") or "").strip().lower()[:2]
    choice = forced if forced in LANGUAGES else (preference if preference in LANGUAGES else system_language())
    _LANG = choice
    if choice == "ka":
        from .locale_ka import TEXTS
        _TABLE = TEXTS
    else:
        _TABLE = {}
    return _LANG


def current():
    return _LANG


def T(text, *args, **kwargs):
    """Translate an English UI text; {0} / {name} placeholders are filled after translation."""
    if not isinstance(text, str):
        return text
    out = _TABLE.get(text, text)
    if args or kwargs:
        try:
            return out.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return text.format(*args, **kwargs)
    return out
