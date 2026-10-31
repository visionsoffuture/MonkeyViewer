"""Security helpers shared by every viewer (see SECURITY.md for the threat model).

* one private temp folder per session, removed on exit; stale folders from crashed sessions are swept
* safe file names for anything written from untrusted metadata (decrypted names, embedded names)
* sidecar references inside documents (glTF buffers, ...) may only point *next to* the document:
  no URLs, no absolute or UNC paths (\\\\server\\share would leak Windows credentials), no ../ escapes
* XML from files is parsed with defusedxml (no entity expansion bombs, no external entities)
* programs and scripts are never launched from Monkey Viewer
"""

import atexit
import os
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import unquote

IS_WIN = sys.platform == "win32"
PREFIX = "MonkeyViewer-"
LEGACY_PREFIXES = ("monkeyviewer_dec_", "monkeyviewer_gpg_", "monkeyviewer_djvu_", "monkeyviewer_ql_", "monkeyviewer_prev_",
                   "monkeyviewer_lo_", "monkeyviewer_evt_", "monkeyviewer_clip_", "monkeyviewer_play_", "monkeyviewer_")

# ─────────────────────────────── temp files ───────────────────────────────
_SESSION = None


def session_dir():
    """Private per-process temp folder (0700 on POSIX; %TEMP% is per-user on Windows)."""
    global _SESSION
    if _SESSION is None or not os.path.isdir(_SESSION):
        _SESSION = tempfile.mkdtemp(prefix=f"{PREFIX}{os.getpid()}-")
        atexit.register(cleanup_session)
    return _SESSION


def temp_dir(tag="tmp"):
    return tempfile.mkdtemp(prefix=f"{tag}_", dir=session_dir())


def cleanup_session():
    global _SESSION
    if _SESSION:
        shutil.rmtree(_SESSION, ignore_errors=True)
        _SESSION = None


def _pid_alive(pid):
    if pid <= 0:
        return False
    if IS_WIN:
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259                                          # STILL_ACTIVE
        except Exception:  # noqa: BLE001
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def cleanup_stale(min_age_seconds=3600):
    """Remove temp folders left behind by sessions that crashed (and by older test builds)."""
    base = tempfile.gettempdir()
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    removed = 0
    now = time.time()
    for name in names:
        path = os.path.join(base, name)
        try:
            if not os.path.isdir(path) or now - os.path.getmtime(path) < min_age_seconds:
                continue
        except OSError:
            continue
        if name.startswith(PREFIX):
            m = re.match(rf"{re.escape(PREFIX)}(\d+)-", name)
            if m and _pid_alive(int(m.group(1))):
                continue
        elif not name.startswith(LEGACY_PREFIXES):
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


# ─────────────────────────────── names & paths ───────────────────────────────
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def unique_path(folder, name):
    """*name* in *folder*, or "name (1).ext", "name (2).ext"... when that file already exists."""
    import re
    stem, ext = os.path.splitext(name)
    stem = re.sub(r" \(\d+\)$", "", stem) or stem
    candidate, n = name, 0
    while os.path.exists(os.path.join(folder, candidate)):
        n += 1
        candidate = f"{stem} ({n}){ext}"
    return os.path.join(folder, candidate)


def safe_filename(name, default="file"):
    """A plain file name that is valid everywhere and cannot point outside its folder."""
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = _BAD_CHARS.sub("_", name).strip().rstrip(". ")
    if not name or name in (".", ".."):
        name = default
    stem, ext = os.path.splitext(name)
    if stem.lower() in _RESERVED:
        name = f"_{stem}{ext}"
    if len(name) > 150:
        name = stem[:150 - len(ext)] + ext
    return name


def is_within(base, path):
    base = os.path.realpath(base)
    path = os.path.realpath(path)
    try:
        return os.path.commonpath([base, path]) == base
    except ValueError:              # different drives on Windows
        return False


def resolve_sidecar(document, ref):
    """Path of a file a document refers to (e.g. a glTF .bin buffer), or None if the reference points
    anywhere but the document's own folder."""
    if not isinstance(ref, str) or not ref:
        return None
    ref = unquote(ref).replace("\\", "/")          # Windows-made files use backslashes
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", ref) or ref.startswith("/"):
        return None                 # URL, drive letter, UNC or absolute path
    folder = os.path.dirname(os.path.abspath(document))
    target = os.path.normpath(os.path.join(folder, ref))
    return target if is_within(folder, target) else None


# ─────────────────────────────── never run code ───────────────────────────────
DANGEROUS_EXTS = {
    ".exe", ".com", ".scr", ".pif", ".cpl", ".msi", ".msp", ".mst", ".msc", ".dll", ".sys", ".ocx", ".drv",
    ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".ps1xml", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta",
    ".lnk", ".url", ".scf", ".inf", ".reg", ".jar", ".application", ".appref-ms", ".gadget", ".settingcontent-ms",
    ".py", ".pyw", ".pyz", ".pyc", ".rb", ".pl", ".php", ".sh", ".bash", ".zsh", ".command", ".tool", ".app",
    ".workflow", ".terminal", ".action", ".scpt", ".applescript", ".lua", ".luau", ".wlua", ".iso", ".img",
    ".vhd", ".vhdx", ".appx", ".appxbundle", ".msix", ".msixbundle", ".library-ms", ".search-ms",
}


def is_dangerous(path):
    """True for programs, scripts and other files that would *execute* when handed to the system."""
    return os.path.splitext(str(path).lower())[1] in DANGEROUS_EXTS


# ─────────────────────────────── XML ───────────────────────────────
from defusedxml import ElementTree as _XML  # noqa: E402 - hard dependency: no entity expansion, no external DTDs


def xml_fromstring(data):
    return _XML.fromstring(data)


def xml_parse(path):
    return _XML.parse(path)


def xml_iterparse(path, events=("end",)):
    return _XML.iterparse(path, events=events)


# ─────────────────────────────── databases ───────────────────────────────
def quote_ident(name):
    """SQL identifier quoting; callers additionally only use names read from the database's own schema."""
    return '"' + str(name).replace('"', '""') + '"'


def sqlite_readonly(path):
    """Read-only SQLite connection. immutable=1 also prevents creating -wal/-shm files next to the file."""
    import sqlite3
    from urllib.parse import quote
    uri = "file:" + quote(os.path.abspath(path).replace("\\", "/")) + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)
