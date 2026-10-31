"""Interface language: Georgian translation table, language choice and policy."""

import ast
import glob
import os
import string

import pytest

from viewer import i18n, policy
from viewer.locale_ka import TEXTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# texts that are the same in every language (names, units)
SAME = {"Aa", "12 pt", "{0} px", "{0} pt", "Hex", "CAD", "GIS", "SHA-256", "CRL", "JSON Web Token", "Ansible Vault",
        "Vault ID", "Shapefile", "GeoPackage", "Google Earth KML"}


def _fields(text):
    return {f for _lit, f, _spec, _conv in string.Formatter().parse(text) if f is not None}


def _ui_literals():
    found = {}
    for path in glob.glob(os.path.join(ROOT, "viewer", "*.py")):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "T" \
                    and node.args and isinstance(node.args[0], ast.Constant):
                found.setdefault(node.args[0].value, f"{os.path.basename(path)}:{node.lineno}")
    return found


def test_every_interface_text_has_a_georgian_translation():
    missing = {k: w for k, w in _ui_literals().items() if k not in TEXTS and k not in SAME}
    assert not missing, missing


def test_translations_keep_the_placeholders():
    for english, georgian in TEXTS.items():
        assert _fields(georgian) <= _fields(english), english
        assert georgian.strip(), english
        georgian.format(*[1] * 6)          # every placeholder can be filled


def test_english_is_the_source_and_georgian_is_used_when_chosen():
    assert i18n.setup("en") == "en"
    assert i18n.T("Saved {0}", "a.pdf") == "Saved a.pdf"
    assert i18n.setup("ka") == "ka"
    assert i18n.T("Saved {0}", "a.pdf") == "შენახულია: a.pdf"
    assert i18n.T("Page {0} of {1}", 2, 9) == "გვერდი 2 / 9"
    assert i18n.T("not in the table {0}", 1) == "not in the table 1"      # falls back to English
    assert i18n.T(None) is None


def test_auto_follows_the_operating_system(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "ka")
    assert i18n.setup("auto") == "ka"
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.setup("auto") == "en"


@pytest.mark.parametrize("forced", ["ka", "en"])
def test_language_policy_wins_over_the_user_setting(forced):
    policy.override({"Language": forced})
    assert i18n.setup("ka" if forced == "en" else "en") == forced
    assert policy.active()["Language"] == forced


def test_invalid_language_policy_is_ignored():
    policy.override({"Language": "fr"})
    assert i18n.setup("en") == "en"
    assert "Language" not in policy.active()


def test_file_type_labels_are_translated():
    from viewer import formats
    i18n.setup("ka")
    assert formats.label_for("plan.dwg") == "AutoCAD DWG ნახაზი"
    assert formats.dialog_filetypes()[0][0] == "ყველა ფაილი"
