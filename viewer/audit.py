"""Audit trail: who opened, saved, exported, decrypted or verified which file, and when.

Each event is one JSON object per line (JSON Lines) in
    Windows: %APPDATA%\\MonkeyViewer\\audit.log      macOS: ~/Library/Application Support/MonkeyViewer/audit.log
Optionally also a central file (AuditLogPath policy) and the Windows Application event log (EventLog policy,
source "MonkeyViewer", registered by the MSI). Passwords, keys and file contents are never logged.
"""

import datetime
import getpass
import hashlib
import json
import os
import socket
import sys
import threading

from . import app_info, policy

MAX_BYTES = 5_000_000
KEEP = 5
_LOCK = threading.Lock()
_SECRET_KEYS = ("password", "passphrase", "secret", "pin", "key_data", "token")

EVENT_IDS = {"app_start": 1000, "file_open": 1001, "file_save": 1002, "export": 1003, "decrypt": 1004,
             "signature": 1005, "associations": 1006, "open_external": 1007, "app_exit": 1009,
             "blocked": 1010, "settings": 1011, "hang": 1012, "print": 1013}


def log_path():
    from . import winutil
    return os.path.join(winutil.config_dir(), "audit.log")


def _user():
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "?"
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain and sys.platform == "win32" else user


def file_hash(path, limit=2 << 30):
    """SHA-256 of a file (only when the AuditFileHashes policy is on)."""
    if not policy.get_bool("AuditFileHashes"):
        return None
    try:
        if os.path.getsize(path) > limit:
            return None
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _rotate(path):
    try:
        if os.path.getsize(path) < MAX_BYTES:
            return
    except OSError:
        return
    for i in range(KEEP - 1, 0, -1):
        src, dst = f"{path}.{i}", f"{path}.{i + 1}"
        if os.path.exists(src):
            os.replace(src, dst)
    os.replace(path, f"{path}.1")


def _append(path, line):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    _rotate(path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _event_log(action, message, warning=False):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        adv = ctypes.windll.advapi32
        adv.RegisterEventSourceW.restype = ctypes.c_void_p
        adv.RegisterEventSourceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        adv.ReportEventW.argtypes = [ctypes.c_void_p, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_ulong,
                                     ctypes.c_void_p, ctypes.c_ushort, ctypes.c_ulong,
                                     ctypes.POINTER(ctypes.c_wchar_p), ctypes.c_void_p]
        adv.DeregisterEventSource.argtypes = [ctypes.c_void_p]
        handle = adv.RegisterEventSourceW(None, app_info.APP_ID)
        if not handle:
            return
        strings = (ctypes.c_wchar_p * 1)(message[:31000])
        adv.ReportEventW(handle, 0x0002 if warning else 0x0004, 0, EVENT_IDS.get(action, 1099), None, 1, 0,
                         strings, None)
        adv.DeregisterEventSource(handle)
    except Exception:  # noqa: BLE001
        pass


def event(action, warning=False, **fields):
    """Record an audit event. Never raises."""
    try:
        local = not policy.get_bool("DisableAuditLog")
        central = policy.get_str("AuditLogPath")
        to_eventlog = policy.get_bool("EventLog")
        if not (local or central or to_eventlog):
            return
        record = {
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "user": _user(),
            "computer": socket.gethostname(),
            "app": f"{app_info.NAME} {app_info.VERSION}",
            "pid": os.getpid(),
            "action": action,
        }
        for key, value in fields.items():
            if any(s in key.lower() for s in _SECRET_KEYS) or value is None:
                continue
            record[key] = value if isinstance(value, (bool, int, float)) else str(value)
        line = json.dumps(record, ensure_ascii=False)
        with _LOCK:
            if local:
                try:
                    _append(log_path(), line)
                except OSError:
                    pass
            if central:
                try:
                    _append(central, line)
                except OSError:
                    pass
        if to_eventlog:
            _event_log(action, line, warning)
    except Exception:  # noqa: BLE001 - auditing must never break the viewer
        pass
