"""File-association logic against an in-memory registry (never touches the real registry)."""
import os

import ntpath
import sys
import types

import pytest


class FakeRegistry:
    def __init__(self):
        self.keys = {}

    def module(self):
        reg = self.keys
        w = types.ModuleType("winreg")
        w.HKEY_CURRENT_USER, w.HKEY_LOCAL_MACHINE, w.HKEY_CLASSES_ROOT = "HKCU", "HKLM", "HKCR"
        w.KEY_WRITE, w.KEY_ALL_ACCESS, w.KEY_SET_VALUE, w.KEY_READ = 1, 2, 3, 4
        w.REG_SZ, w.REG_NONE, w.REG_DWORD, w.REG_EXPAND_SZ = 1, 0, 4, 2

        class Key:
            def __init__(self, path):
                self.p = path

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def norm(path):
            return path.lower()

        def CreateKeyEx(root, path, res=0, access=0):
            parts = path.split("\\")
            for i in range(1, len(parts) + 1):
                reg.setdefault(norm("\\".join(parts[:i])), {"__name__": "\\".join(parts[:i])})
            return Key(norm(path))

        def OpenKey(root, path, res=0, access=0):
            if root != "HKCU" or norm(path) not in reg:
                raise FileNotFoundError(path)
            return Key(norm(path))

        def SetValueEx(key, name, res, kind, value):
            reg[key.p][name] = (kind, value)

        def QueryValueEx(key, name):
            if name not in reg[key.p]:
                raise FileNotFoundError(name)
            return reg[key.p][name][1], reg[key.p][name][0]

        def EnumKey(key, i):
            kids = sorted({reg[p]["__name__"].split("\\")[-1] for p in reg
                           if p.startswith(key.p + "\\") and p.count("\\") == key.p.count("\\") + 1})
            if i >= len(kids):
                raise OSError
            return kids[i]

        def EnumValue(key, i):
            names = [n for n in reg[key.p] if n != "__name__"]
            if i >= len(names):
                raise OSError
            return names[i], reg[key.p][names[i]][1], reg[key.p][names[i]][0]

        def DeleteKey(root, path):
            reg.pop(norm(path))

        def DeleteValue(key, name):
            if name not in reg[key.p]:
                raise FileNotFoundError(name)
            reg[key.p].pop(name)

        def CloseKey(key):
            pass

        for fn in (CreateKeyEx, OpenKey, SetValueEx, QueryValueEx, EnumKey, EnumValue, DeleteKey, DeleteValue,
                   CloseKey):
            setattr(w, fn.__name__, fn)
        return w

    def value(self, path, name=""):
        entry = self.keys.get(path.lower(), {})
        return entry.get(name, (None, None))[1]


@pytest.fixture
def registry(monkeypatch):
    fake = FakeRegistry()
    monkeypatch.setitem(sys.modules, "winreg", fake.module())
    from viewer import winutil
    monkeypatch.setattr(winutil, "IS_WIN", True)
    monkeypatch.setattr(winutil, "IS_MAC", False)
    monkeypatch.setattr(winutil, "FROZEN", True)
    monkeypatch.setattr(winutil.os, "path", ntpath)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Monkey Viewer\MonkeyViewer.exe")
    monkeypatch.setattr(winutil, "_notify_shell", lambda: None)
    monkeypatch.setattr(winutil, "_user_choice", lambda ext: None)
    return fake


def test_only_chosen_types_are_associated(registry):
    from viewer import winutil
    backup, overridden = winutil.apply_associations({".pdf", ".dwg"}, {".dwg"}, False)
    classes = r"Software\Classes"
    assert registry.value(rf"{classes}\.pdf\OpenWithProgids", "MonkeyViewer.pdf") is not None or \
        "monkeyviewer.pdf" in registry.keys[rf"{classes}\.pdf\openwithprogids".lower()]
    assert registry.value(rf"{classes}\.dwg") == "MonkeyViewer.cad"
    assert rf"{classes}\.lua\openwithprogids".lower() not in registry.keys
    assert registry.value(r"Software\Classes\*\shell\MonkeyViewer\command") is None
    assert overridden == []


def test_previous_default_is_restored(registry):
    from viewer import winutil
    w = sys.modules["winreg"]
    with w.CreateKeyEx(w.HKEY_CURRENT_USER, r"Software\Classes\.dwg") as k:
        w.SetValueEx(k, "", 0, w.REG_SZ, "AutoCAD.Drawing")
    backup, _ = winutil.apply_associations({".dwg"}, {".dwg"}, False)
    assert registry.value(r"Software\Classes\.dwg") == "MonkeyViewer.cad"
    winutil.apply_associations(set(), set(), False, backup)
    assert registry.value(r"Software\Classes\.dwg") == "AutoCAD.Drawing"


def test_legacy_office_and_archive_associations_are_removed(registry):
    from viewer import winutil
    w = sys.modules["winreg"]
    for ext, progid in ((".docx", "MonkeyViewer.office"), (".zip", "MonkeyViewer.archive")):
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids") as k:
            w.SetValueEx(k, progid, 0, w.REG_NONE, b"")
            w.SetValueEx(k, "Word.Document.12", 0, w.REG_NONE, b"")
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, rf"Software\Classes\{ext}") as k:
            w.SetValueEx(k, "", 0, w.REG_SZ, progid)
    with w.CreateKeyEx(w.HKEY_CURRENT_USER, r"Software\Classes\MonkeyViewer.office\shell\open\command") as k:
        w.SetValueEx(k, "", 0, w.REG_SZ, "x")
    winutil.apply_associations({".pdf"}, set(), False, {".docx": "Word.Document.12"})
    owp = registry.keys[r"software\classes\.docx\openwithprogids"]
    assert "MonkeyViewer.office" not in owp and "Word.Document.12" in owp
    assert registry.value(r"Software\Classes\.docx") == "Word.Document.12"        # restored from backup
    assert registry.value(r"Software\Classes\.zip") is None                       # no backup: cleared
    assert not any(k.startswith(r"software\classes\monkeyviewer.office") for k in registry.keys)


def test_group_policy_is_read_from_registry(registry, monkeypatch):
    """HKCU and HKLM policy keys; the machine policy wins."""
    from viewer import policy
    w = sys.modules["winreg"]
    store = registry.keys

    class K:
        def __init__(self, p):
            self.p = p

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(root, path, res=0, access=0):
        key = f"{root}\\{path}".lower()
        if key not in store:
            raise FileNotFoundError(path)
        return K(key)

    store["hkcu\\software\\policies\\monkeyviewer"] = {"ReadOnly": (4, 0), "AuditLogPath": (2, "%TEMP%\\a.log"),
                                                    "Bogus": (4, 1)}
    store["hklm\\software\\policies\\monkeyviewer"] = {"ReadOnly": (4, 1), "EventLog": (4, 1)}
    monkeypatch.setattr(w, "OpenKey", OpenKey)
    monkeypatch.setattr(policy, "IS_WIN", True)
    policy.override(None)
    try:
        values = policy.load(refresh=True)
        assert values == {"ReadOnly": 1, "AuditLogPath": "%TEMP%\\a.log", "EventLog": 1}
        assert policy.get_bool("ReadOnly") and policy.get_bool("EventLog")
    finally:
        policy._CACHE = None


def test_every_file_type_has_its_own_icon():
    from PIL import Image
    from viewer.winutil import PROGIDS, _progid_for, type_icon
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging", "icons")
    for suffix in PROGIDS:
        ico = os.path.join(root, f"{suffix}.ico")
        assert {(16, 16), (32, 32), (256, 256)} <= Image.open(ico).info["sizes"], suffix
        assert os.path.isfile(os.path.join(root, f"doc-{suffix}.icns")), suffix
        assert type_icon(suffix) and f"{suffix}.ico" in type_icon(suffix)
    assert _progid_for(".djvu", "pdf") == "MonkeyViewer.djvu"
    assert _progid_for(".pdf", "pdf") == "MonkeyViewer.pdf"


def test_registrations_of_deleted_copies_are_removed(monkeypatch, tmp_path):
    from viewer import winutil
    reg = {}
    monkeypatch.setattr(winutil, "IS_WIN", True)
    monkeypatch.setattr(winutil, "_reg_get", lambda path, name="": reg.get((path, name)))
    monkeypatch.setattr(winutil, "_reg_delete_tree",
                        lambda path: [reg.pop(k) for k in list(reg) if k[0] == path or k[0].startswith(path + "\\")])
    monkeypatch.setattr(winutil, "_reg_delete_value", lambda path, name: reg.pop((path, name), None))
    monkeypatch.setattr(winutil, "_notify_shell", lambda: None)
    live = tmp_path / "MonkeyViewer.exe"
    live.write_text("")
    old = r"C:\Users\x\Desktop\MonkeyViewer-3.0\dist\MonkeyViewer\MonkeyViewer.exe"
    C = winutil.CLASSES
    reg[(rf"{C}\MonkeyViewer.gis\shell\open\command", "")] = f'"{old}" "%1"'
    reg[(rf"{C}\MonkeyViewer.pdf\shell\open\command", "")] = f'"{live}" "%1"'
    reg[(rf"{C}\Applications\MonkeyViewer.exe\shell\open\command", "")] = f'"{old}" "%1"'
    reg[(rf"{C}\.geojson", "")] = "MonkeyViewer.gis"
    reg[(rf"{C}\.pdf", "")] = "MonkeyViewer.pdf"

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    names = ["MonkeyViewer.gis", "MonkeyViewer.pdf", ".geojson", ".pdf"]
    fake = types.SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=lambda *a: FakeKey(),
                                 EnumKey=lambda key, i: names[i] if i < len(names) else (_ for _ in ()).throw(OSError()))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert sorted(winutil.stale_registrations()) == ["Applications\\MonkeyViewer.exe", "MonkeyViewer.gis"]
    winutil.remove_stale_registrations()
    assert (rf"{C}\.geojson", "") not in reg                      # pointed at the removed ProgID
    assert reg[(rf"{C}\.pdf", "")] == "MonkeyViewer.pdf"             # the working copy is untouched
    assert (rf"{C}\MonkeyViewer.pdf\shell\open\command", "") in reg
