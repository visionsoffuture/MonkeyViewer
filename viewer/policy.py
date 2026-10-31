"""Administrator policies.

Windows: Group Policy (ADMX template in deploy/admx) writes them to
    HKLM\\SOFTWARE\\Policies\\MonkeyViewer  (computer, wins)   and   HKCU\\SOFTWARE\\Policies\\MonkeyViewer  (user)
macOS: a configuration profile for the app's bundle id (managed preferences).

Unknown values are ignored; every policy is off unless an administrator sets it.
"""

import os
import plistlib
import sys

from .app_info import BUNDLE_ID, POLICY_KEY

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

DEFINITIONS = {
    # name: (type, description)
    "DisableAssociationPrompt": ("bool", "Don't ask users to choose file types on first start"),
    "DisableAssociationChanges": ("bool", "Users can't change which file types open in Monkey Viewer"),
    "DisableExternalTools": ("bool", "Never start helper programs (GnuPG, DjVuLibre, ODA File Converter)"),
    "DisableDecryption": ("bool", "Encrypted files are analysed but never decrypted"),
    "ReadOnly": ("bool", "View only: nothing can be saved or exported"),
    "DisablePrinting": ("bool", "Turn off printing"),
    "DisableWeather": ("bool", "Turn off the weather forecast (the only internet connection)"),
    "DisableAuditLog": ("bool", "Don't keep the local audit log"),
    "EventLog": ("bool", "Also write audit events to the Windows Application event log"),
    "AuditLogPath": ("str", "Additional audit log file, e.g. \\\\server\\audit$\\%USERNAME%.jsonl"),
    "AuditFileHashes": ("bool", "Record the SHA-256 of every opened file in the audit log"),
    "Language": ("enum", "Interface language for everyone: ka (Georgian) or en (English)"),
}
CHOICES = {"Language": ("ka", "en")}

_CACHE = None
_OVERRIDE = None


def _read_windows():
    import winreg
    out = {}
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):      # machine policy wins
        try:
            with winreg.OpenKey(hive, POLICY_KEY) as key:
                i = 0
                while True:
                    try:
                        name, value, _type = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    out[name] = value
                    i += 1
        except OSError:
            continue
    return out


def _read_mac():
    out = {}
    user = os.environ.get("USER", "")
    for path in (f"/Library/Managed Preferences/{user}/{BUNDLE_ID}.plist",
                 f"/Library/Managed Preferences/{BUNDLE_ID}.plist"):
        try:
            with open(path, "rb") as fh:
                data = plistlib.load(fh)
            if isinstance(data, dict):
                out.update(data)
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
    return out


def load(refresh=False):
    global _CACHE
    if _OVERRIDE is not None:
        return dict(_OVERRIDE)
    if _CACHE is None or refresh:
        raw = {}
        try:
            raw = _read_windows() if IS_WIN else _read_mac() if IS_MAC else {}
        except Exception:  # noqa: BLE001 - a broken policy store must never stop the app
            raw = {}
        _CACHE = {k: v for k, v in raw.items() if k in DEFINITIONS}
    return dict(_CACHE)


def override(values):
    """For tests: use *values* instead of the system policy store (None restores it)."""
    global _OVERRIDE
    _OVERRIDE = None if values is None else dict(values)


def get(name, default=None):
    return load().get(name, default)


def get_bool(name):
    value = get(name)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def get_str(name):
    value = get(name)
    return os.path.expandvars(str(value)) if value not in (None, "") else None


def active():
    """Policies that are switched on, for the About box, diagnostics and the audit log."""
    out = {}
    for name, (kind, _desc) in DEFINITIONS.items():
        if kind == "bool" and get_bool(name):
            out[name] = True
        elif kind == "str" and get_str(name):
            out[name] = get_str(name)
        elif kind == "enum" and str(get(name, "")).strip().lower() in CHOICES.get(name, ()):
            out[name] = str(get(name)).strip().lower()
    return out
