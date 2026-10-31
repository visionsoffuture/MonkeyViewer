"""Operating-system helpers: Windows chrome, registry, single instance, shell previews.
macOS equivalents live in macutil and are dispatched from here, so callers stay platform-neutral."""

import glob
import hashlib
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time

from . import macutil

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
FROZEN = getattr(sys, "frozen", False)
from .app_info import APP_ID, NAME as APP_NAME  # noqa: E402
from .i18n import T
CREATE_NO_WINDOW = 0x08000000


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, name)


def relaunch(files=()):
    """Start a fresh copy of Monkey Viewer (after a language / theme change), reopening *files*."""
    files = [f for f in files if f]
    if FROZEN and IS_MAC:
        bundle = sys.executable
        while bundle and not bundle.endswith(".app"):
            bundle = os.path.dirname(bundle) if os.path.dirname(bundle) != bundle else ""
        cmd = ["/usr/bin/open", "-n", bundle, "--args", *files] if bundle else [sys.executable, *files]
    elif FROZEN:
        cmd = [sys.executable, *files]
    else:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        cmd = [pyw if os.path.exists(pyw) else sys.executable, entry_script(), *files]
    kwargs = {"close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL}
    if IS_WIN:
        kwargs["creationflags"] = 0x00000008 | 0x00000200        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)  # nosec B603 - our own program, list arguments, no shell


def entry_script():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "monkey_viewer.py")


# ─────────────────────────────── Window chrome ───────────────────────────────
def enable_dpi_awareness():
    if not IS_WIN:
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _colorref(hex_color):
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return r | (g << 8) | (b << 16)


def apply_dark_titlebar(window, caption=None, border=None):
    """Title bar in the app's theme (dark or light) on Windows 10/11 and macOS; caption colour on Windows 11."""
    from . import theme
    dark = theme.IS_DARK
    if IS_MAC:
        macutil.window_appearance(window, dark)
        return
    if not IS_WIN:
        return
    try:
        import ctypes
        window.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id())
        build = sys.getwindowsversion().build
        if dark and 17763 <= build < 19041:            # Windows 10 1809-1909: dark frames must be allowed first
            try:
                uxtheme = ctypes.windll.uxtheme
                uxtheme[135](1)                         # SetPreferredAppMode(AllowDark)
                uxtheme[133](hwnd, True)                # AllowDarkModeForWindow
            except (AttributeError, OSError):
                pass
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
        for attr, color in ((35, caption), (34, border)):
            if color:
                ref = ctypes.c_uint(_colorref(color))
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ref), ctypes.sizeof(ref))
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)    # SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER
        # Windows 10 keeps painting the old (white) caption until the frame is activated again
        active = user32.GetForegroundWindow() == hwnd
        user32.SendMessageW(hwnd, 0x0086, 0 if active else 1, 0)    # WM_NCACTIVATE
        user32.SendMessageW(hwnd, 0x0086, 1 if active else 0, 0)
    except Exception:
        pass


def set_app_user_model_id():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


# ─────────────────────────────── Processes ───────────────────────────────
def run_hidden(args, timeout=None, **kw):
    flags = CREATE_NO_WINDOW if IS_WIN else 0
    if "input" not in kw:
        kw.setdefault("stdin", subprocess.DEVNULL)   # windowed exe has no valid stdin handle
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags, **kw)


class BlockedFile(PermissionError):
    """Raised instead of handing a program or script to the system."""


def open_external(path):
    """Open a document in the system's default app. Programs and scripts are never started."""
    from . import safeio
    if safeio.is_dangerous(path):
        raise BlockedFile(T("{0} is a program or script — Monkey Viewer never runs those. "
                            "Use Show in Folder if you really need it.", os.path.basename(path)))
    from . import audit
    audit.event("open_external", path=path)
    if IS_WIN:
        # documents only: programs and scripts were refused by is_dangerous() above
        os.startfile(path, "open")  # nosec B606
    elif IS_MAC:
        subprocess.Popen(["/usr/bin/open", "--", path])
    else:
        subprocess.Popen([_xdg_open(), path])


SAFE_URL_SCHEMES = ("https://", "http://", "mailto:", "ms-settings:")


def open_url(url):
    """Only web links and the Windows Settings app — never file:// or other handlers."""
    if not isinstance(url, str) or not url.lower().startswith(SAFE_URL_SCHEMES):
        raise BlockedFile(T("Only web links can be opened"))
    import webbrowser
    webbrowser.open(url)


def reveal(path):
    if IS_WIN:
        explorer = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe")
        subprocess.Popen([explorer, "/select,", os.path.normpath(path)])
    elif IS_MAC:
        subprocess.Popen(["/usr/bin/open", "-R", "--", path])
    else:
        subprocess.Popen([_xdg_open(), os.path.dirname(path)])


def _xdg_open():
    for folder in ("/usr/bin", "/usr/local/bin", "/bin"):
        cand = os.path.join(folder, "xdg-open")
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError("xdg-open is not installed")


# ─────────────────────────────── Settings ───────────────────────────────
def config_dir():
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_ID)
    elif IS_MAC:
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_ID)
    else:
        path = os.path.join(os.path.expanduser("~"), ".config", "monkeyviewer")
    os.makedirs(path, exist_ok=True)
    return path


class Settings(dict):
    def __init__(self):
        super().__init__()
        self.path = os.path.join(config_dir(), "settings.json")
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self.update(data)
        except Exception:
            pass

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass


def error_log_path():
    return os.path.join(config_dir(), "error.log")


def log_error(text):
    """Append a timestamped entry to %APPDATA%\\MonkeyViewer\\error.log (kept under ~1 MB)."""
    try:
        path = error_log_path()
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + text.rstrip() + "\n\n")
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────────── External tools ───────────────────────────────
# Optional helper programs are looked up in the protected program folders first, then in absolute PATH
# entries only (never the current directory), so a planted gpg.exe next to a document can't be run.
# Administrators can switch all of them off with the DisableExternalTools policy.
def _program_dirs():
    if not IS_WIN:
        return []
    out = []
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base and base not in out:
            out.append(base)
    return out


def bundled_tool(folder, name):
    """A helper program shipped inside Monkey Viewer (tools/<folder>/<name>), if this build has it."""
    exe = resource_path(os.path.join("tools", folder, name + (".exe" if IS_WIN else "")))
    return exe if os.path.isfile(exe) and (IS_WIN or os.access(exe, os.X_OK)) else None


def _find_tool(names, folders):
    from . import policy
    if policy.get_bool("DisableExternalTools"):
        return None
    if IS_MAC:
        return macutil.find(*names)
    for base in _program_dirs():
        for folder in folders:
            for name in names:
                hits = sorted(glob.glob(os.path.join(base, folder, name + ".exe")))
                if hits:
                    return hits[-1]
    exe_suffix = ".exe" if IS_WIN else ""
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or not os.path.isabs(entry):
            continue
        for name in names:
            cand = os.path.join(entry, name + exe_suffix)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


def find_oda_converter():
    if IS_MAC:
        from . import policy
        return None if policy.get_bool("DisableExternalTools") else macutil.find("ODAFileConverter")
    return _find_tool(["ODAFileConverter"], [os.path.join("ODA", "ODAFileConverter*")])


def find_gpg():
    """GnuPG: the copy shipped with Monkey Viewer first, else an installed one (Gpg4win, GnuPG, Homebrew)."""
    from . import policy
    if policy.get_bool("DisableExternalTools"):
        return None
    bundled = bundled_tool("gnupg", os.path.join("bin", "gpg"))
    if bundled:
        return bundled
    if IS_MAC:
        return macutil.find("gpg", "gpg2")
    return _find_tool(["gpg", "gpg2"], [os.path.join("GnuPG", "bin"), os.path.join("Gpg4win", "bin"),
                                        os.path.join("Git", "usr", "bin")])


def find_ddjvu():
    from . import policy
    if policy.get_bool("DisableExternalTools"):
        return None
    if bundled_tool("djvulibre", "ddjvu"):
        return bundled_tool("djvulibre", "ddjvu")
    if IS_MAC:
        return macutil.find("ddjvu")
    return _find_tool(["ddjvu"], ["DjVuLibre", os.path.join("DjVuZone", "DjVuLibre"), "WinDjView"])


def find_dwg2dxf():
    """LibreDWG's DWG -> DXF converter: shipped with Monkey Viewer, or installed separately."""
    from . import policy
    if policy.get_bool("DisableExternalTools"):
        return None
    if bundled_tool("libredwg", "dwg2dxf"):
        return bundled_tool("libredwg", "dwg2dxf")
    if IS_MAC:
        return macutil.find("dwg2dxf")
    return _find_tool(["dwg2dxf"], ["LibreDWG", "libredwg"])


# ─────────────────────── Windows shell: thumbnails, type names, clipboard ───────────────────────
def shell_thumbnail(path, size=512, allow_icon=False):
    """Explorer's own thumbnail for any file (uses whatever preview handlers are installed:
    3ds Max, ArchiCAD, AutoCAD, Office, video codecs...). On a Mac: the Quick Look thumbnail.
    Returns a PIL image or None."""
    if IS_MAC:
        return macutil.quicklook_thumbnail(path, size)
    if not IS_WIN:
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes
        from PIL import Image

        ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
        gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        ole32.CoInitializeEx(None, 2)

        class GUID(ctypes.Structure):
            _fields_ = [("data", ctypes.c_ubyte * 16)]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        iid = GUID()
        ctypes.memmove(ctypes.byref(iid), uuid.UUID("bcc18b79-ba16-442f-80c4-8a59c30c463b").bytes_le, 16)
        create = shell32.SHCreateItemFromParsingName
        create.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        factory = ctypes.c_void_p()
        if create(os.path.abspath(path), None, ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory:
            return None
        vtable = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0],
                             ctypes.POINTER(ctypes.c_void_p))
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int,
                                       ctypes.POINTER(wintypes.HANDLE))(vtable[3])
        hbmp = wintypes.HANDLE()
        flags = 0 if allow_icon else 0x8 | 0x1  # SIIGBF_THUMBNAILONLY | SIIGBF_BIGGERSIZEOK
        try:
            hr = get_image(factory, SIZE(size, size), flags, ctypes.byref(hbmp))
        finally:
            release(factory)
        if hr != 0 or not hbmp.value:
            return None

        class BITMAP(ctypes.Structure):
            _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                        ("bmWidthBytes", ctypes.c_long), ("bmPlanes", ctypes.c_ushort),
                        ("bmBitsPixel", ctypes.c_ushort), ("bmBits", ctypes.c_void_p)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
                        ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32),
                        ("bmiColors", ctypes.c_uint32 * 3)]

        gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
        gdi32.GetDIBits.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.c_uint, ctypes.c_uint,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        user32.GetDC.argtypes = [wintypes.HANDLE]
        user32.GetDC.restype = wintypes.HANDLE
        user32.ReleaseDC.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        try:
            bm = BITMAP()
            gdi32.GetObjectW(hbmp, ctypes.sizeof(bm), ctypes.byref(bm))
            w, h = bm.bmWidth, abs(bm.bmHeight)
            if w <= 0 or h <= 0:
                return None
            bi = BITMAPINFOHEADER()
            bi.biSize = 40
            bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -h, 1, 32
            buf = ctypes.create_string_buffer(w * h * 4)
            hdc = user32.GetDC(None)
            gdi32.GetDIBits(hdc, hbmp, 0, h, buf, ctypes.byref(bi), 0)
            user32.ReleaseDC(None, hdc)
            img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1)
            if img.getextrema()[3][1] == 0:  # no alpha channel in the bitmap
                img = img.convert("RGB")
            return img.copy()
        finally:
            gdi32.DeleteObject(hbmp)
    except Exception:
        return None


def shell_type_name(path):
    """Windows' friendly name for a file type, e.g. 'ARCHICAD Project File' (Finder's "Kind" on a Mac)."""
    if IS_MAC:
        return macutil.kind_name(path)
    if not IS_WIN:
        return None
    try:
        import ctypes

        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int), ("dwAttributes", ctypes.c_uint32),
                        ("szDisplayName", ctypes.c_wchar * 260), ("szTypeName", ctypes.c_wchar * 80)]

        fn = ctypes.windll.shell32.SHGetFileInfoW
        fn.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        fn.restype = ctypes.c_size_t
        info = SHFILEINFOW()
        if fn(path, 0x80, ctypes.byref(info), ctypes.sizeof(info), 0x400 | 0x10):
            return info.szTypeName or None
    except Exception:
        pass
    return None


def copy_image_to_clipboard(img):
    """Put a PIL image on the clipboard (CF_DIB on Windows, PNG on macOS). Returns True on success."""
    if IS_MAC:
        return macutil.copy_image_to_clipboard(img)
    if not IS_WIN:
        return False
    import ctypes
    import io
    from ctypes import wintypes
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.restype = wintypes.HANDLE
    k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wintypes.HANDLE]
    k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    u32.SetClipboardData.argtypes = [ctypes.c_uint, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        handle = k32.GlobalAlloc(0x0002, len(data))
        ptr = k32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(handle)
        return bool(u32.SetClipboardData(8, handle))
    finally:
        u32.CloseClipboard()


# ─────────────────── "Open with" registration (per user, no admin rights) ───────────────────
PROGIDS = {
    # progid suffix: (friendly type name, categories)
    "lua": ("Lua Script", ()),
    "code": ("Text / Code File", ("code", "text")),
    "pdf": ("PDF Document", ("pdf",)),
    "djvu": ("DjVu Document", ()),
    "image": ("Image", ("image",)),
    "cad": ("CAD Drawing", ("cad",)),
    "gis": ("GIS Data", ("gis",)),
    "data": ("Database", ("table",)),
    "secure": ("Signed / Encrypted File", ("secure",)),
    "file": ("File", ()),
}


def _launch_command():
    if FROZEN:
        exe = sys.executable
        return f'"{exe}" "%1"', exe
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    pyw = pyw if os.path.exists(pyw) else sys.executable
    return f'"{pyw}" "{entry_script()}" "%1"', pyw


def _reg_set(path, values):
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
        for name, (kind, value) in values.items():
            winreg.SetValueEx(key, name, 0, kind, value)


def _reg_get(path, name=""):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _reg_delete_tree(path):
    import winreg
    try:
        children = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    children.append(winreg.EnumKey(key, len(children)))
                except OSError:
                    break
        for child in children:
            _reg_delete_tree(path + "\\" + child)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def _reg_delete_value(path, name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except OSError:
        pass


def _notify_shell():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass


def _progid_for(ext, category):
    if ext in (".lua", ".luau"):
        return "MonkeyViewer.lua"
    if ext in (".djvu", ".djv"):
        return "MonkeyViewer.djvu"
    for suffix, (_name, cats) in PROGIDS.items():
        if category in cats:
            return f"MonkeyViewer.{suffix}"
    return "MonkeyViewer.file"


ICON_SCHEME = 4        # bump when the file-type icons / ProgIDs change: existing associations are refreshed


def type_icon(suffix):
    """DefaultIcon value for a MonkeyViewer.<suffix> ProgID: its own .ico next to the program, if present."""
    for path in (resource_path(os.path.join("icons", f"{suffix}.ico")),
                 resource_path(os.path.join("packaging", "icons", f"{suffix}.ico"))):
        if os.path.isfile(path):
            return f"{path},0"          # DefaultIcon form "path,index" - not quoted, spaces are allowed
    return None


def _command_exe(command):
    """Program path of a registry open command: '"C:\\x\\a.exe" "%1"' -> 'C:\\x\\a.exe'."""
    command = (command or "").strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    return command.split(" ", 1)[0]


def stale_registrations():
    """Per-user MonkeyViewer.* ProgIDs (and the Applications entry) whose program no longer exists - left by an
    old or deleted copy (3.x, portable folder). They hide the machine-wide ones the MSI installs."""
    if not IS_WIN:
        return []
    import winreg
    stale = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLASSES)
    except OSError:
        return []
    names, i = [], 0
    with root:
        while True:
            try:
                names.append(winreg.EnumKey(root, i))
            except OSError:
                break
            i += 1
    for name in names + [r"Applications\MonkeyViewer.exe"]:
        if name.lower().startswith("monkeyviewer.") or name.startswith("Applications"):
            exe = _command_exe(_reg_get(rf"{CLASSES}\{name}\shell\open\command"))
            if exe and not os.path.isfile(exe):
                stale.append(name)
    return stale


def remove_stale_registrations():
    """Delete what stale_registrations() found, plus extension links that point at removed ProgIDs."""
    stale = stale_registrations()
    if not stale:
        return []
    gone = {n for n in stale if n.lower().startswith("monkeyviewer.")}
    for name in stale:
        _reg_delete_tree(rf"{CLASSES}\{name}")
    from . import formats
    for ext in set(formats.association_extensions()) | {".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z"}:
        if _reg_get(rf"{CLASSES}\{ext}") in gone:
            _reg_delete_value(rf"{CLASSES}\{ext}", "")
        for progid in gone:
            _reg_delete_value(rf"{CLASSES}\{ext}\OpenWithProgids", progid)
    stale_verb = _command_exe(_reg_get(rf"{CONTEXT_VERB}\command"))
    if stale_verb and not os.path.isfile(stale_verb):
        _reg_delete_tree(CONTEXT_VERB)
    _notify_shell()
    return stale


CONTEXT_VERB = r"Software\Classes\*\shell\MonkeyViewer"
CLASSES = r"Software\Classes"


def _user_choice(ext):
    return _reg_get(rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice", "ProgId")


def current_associations():
    """What is registered right now: (open_with set, default set, context menu bool)."""
    if IS_MAC:
        from . import formats
        exts = set(formats.association_extensions())
        return exts, macutil.current_defaults(exts), False
    if not IS_WIN:
        return set(), set(), False
    from . import formats
    import winreg
    open_with, defaults = set(), set()
    for ext, category in formats.association_extensions().items():
        progid = _progid_for(ext, category)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{CLASSES}\{ext}\OpenWithProgids") as key:
                winreg.QueryValueEx(key, progid)
                open_with.add(ext)
        except OSError:
            pass
        if _reg_get(rf"{CLASSES}\{ext}") == progid:
            defaults.add(ext)
    return open_with, defaults, _reg_get(rf"{CONTEXT_VERB}\command") is not None


def recommended_associations():
    from . import formats
    open_with = {ext for ext, (kind, _cat, _label) in formats.FORMATS.items() if kind != "info"}
    return open_with, {".lua", ".luau"}, True


def apply_associations(open_with, defaults, context_menu, backup=None):
    """Associate exactly the chosen extensions (per user, no admin rights). Everything else is left
    as Windows had it. Returns (backup, overridden): backup remembers the previous default of each
    extension we took over; overridden lists extensions where the user's own "Always use" choice wins."""
    backup = dict(backup or {})
    if IS_MAC:     # "Open With" comes from the app bundle's Info.plist; only defaults are per user
        from . import formats
        return macutil.apply_defaults(set(formats.association_extensions()), set(defaults), backup)
    if not IS_WIN:
        return backup, []
    import winreg
    from . import formats
    sz = winreg.REG_SZ
    defaults = set(defaults)
    open_with = set(open_with) | defaults
    command, exe = _launch_command()
    icon = f'"{exe}",0'
    all_exts = formats.association_extensions()

    # 1. our ProgIDs (only used by the extensions that point at them)
    for suffix, (name, _cats) in PROGIDS.items():
        key = rf"{CLASSES}\MonkeyViewer.{suffix}"
        _reg_set(key, {"": (sz, name), "FriendlyTypeName": (sz, name)})
        _reg_set(rf"{key}\DefaultIcon", {"": (sz, type_icon(suffix) or icon)})
        _reg_set(rf"{key}\shell\open", {"FriendlyAppName": (sz, APP_NAME)})
        _reg_set(rf"{key}\shell\open\command", {"": (sz, command)})

    # 2. "Open with" entries: exactly the chosen extensions
    for ext, category in all_exts.items():
        progid = _progid_for(ext, category)
        if ext in open_with:
            try:
                _reg_set(rf"{CLASSES}\{ext}\OpenWithProgids", {progid: (winreg.REG_NONE, b"")})
            except OSError:
                pass
        else:
            _reg_delete_value(rf"{CLASSES}\{ext}\OpenWithProgids", progid)
            _reg_delete_value(rf"{CLASSES}\{ext}\OpenWithProgids", "MonkeyViewer.file")

    # 3. defaults: take over only chosen extensions, give back the others
    overridden = []
    for ext, category in all_exts.items():
        progid = _progid_for(ext, category)
        current = _reg_get(rf"{CLASSES}\{ext}")
        if ext in defaults:
            if current != progid:
                if not (current or "").startswith("MonkeyViewer."):    # never "restore" our own older ProgID
                    backup[ext] = current
                _reg_set(rf"{CLASSES}\{ext}", {"": (sz, progid)})
            choice = _user_choice(ext)
            if choice and choice != progid:
                overridden.append(ext)
        elif current == progid or (current or "").startswith("MonkeyViewer."):
            old = backup.pop(ext, None)
            if old:
                _reg_set(rf"{CLASSES}\{ext}", {"": (sz, old)})
            else:
                _reg_delete_value(rf"{CLASSES}\{ext}", "")

    # 4. app entry for the "Choose another app" list
    if FROZEN:
        app_key = rf"{CLASSES}\Applications\{os.path.basename(exe)}"
        _reg_delete_tree(rf"{app_key}\SupportedTypes")
        _reg_set(app_key, {"FriendlyAppName": (sz, APP_NAME)})
        _reg_set(rf"{app_key}\DefaultIcon", {"": (sz, icon)})
        _reg_set(rf"{app_key}\shell\open\command", {"": (sz, command)})
        if open_with:
            _reg_set(rf"{app_key}\SupportedTypes", {ext: (sz, "") for ext in sorted(open_with)})

    # 5. right-click "Open in Monkey Viewer" for every file
    if context_menu:
        _reg_set(CONTEXT_VERB, {"": (sz, f"Open in {APP_NAME}"), "Icon": (sz, icon)})
        _reg_set(rf"{CONTEXT_VERB}\command", {"": (sz, command)})
    else:
        _reg_delete_tree(CONTEXT_VERB)
    _cleanup_legacy(set(all_exts), open_with, defaults, backup)
    _notify_shell()
    return backup, sorted(overridden)


def _cleanup_legacy(current_exts, open_with, defaults, backup):
    """Remove what older versions registered for types Monkey Viewer no longer handles (Office, archives, mail,
    media...): OpenWithProgids entries, defaults pointing at a MonkeyViewer ProgID, and obsolete ProgID keys."""
    import winreg
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLASSES)
    except OSError:
        return
    names, i = [], 0
    with root:
        while True:
            try:
                names.append(winreg.EnumKey(root, i))
            except OSError:
                break
            i += 1
    for name in names:
        low = name.lower()
        if low.startswith("monkeyviewer.") and low[len("monkeyviewer."):] not in PROGIDS:
            _reg_delete_tree(rf"{CLASSES}\{name}")
            continue
        if not name.startswith(".") or low in current_exts:
            continue
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{CLASSES}\{name}\OpenWithProgids") as key:
                values, j = [], 0
                while True:
                    try:
                        values.append(winreg.EnumValue(key, j)[0])
                    except OSError:
                        break
                    j += 1
        except OSError:
            values = []
        for v in values:
            if v.lower().startswith("monkeyviewer."):
                _reg_delete_value(rf"{CLASSES}\{name}\OpenWithProgids", v)
        current = _reg_get(rf"{CLASSES}\{name}")
        if isinstance(current, str) and current.lower().startswith("monkeyviewer."):
            old = backup.pop(low, None)
            if old:
                _reg_set(rf"{CLASSES}\{name}", {"": (winreg.REG_SZ, old)})
            else:
                _reg_delete_value(rf"{CLASSES}\{name}", "")


def register_file_types():
    """Command-line --register: the recommended set (Open with for supported formats, default for .lua)."""
    ow, de, ctx = recommended_associations()
    return apply_associations(ow, de, ctx, Settings().get("assoc_backup"))


def unregister_file_types(backup=None):
    if IS_MAC:
        settings = Settings()
        apply_associations(set(), set(), False, backup or settings.get("assoc_backup"))
        settings.pop("assoc_backup", None)
        settings["assoc"] = {"open_with": [], "default": [], "context": False}
        settings.save()
        return True
    if not IS_WIN:
        return False
    settings = Settings()
    apply_associations(set(), set(), False, backup or settings.get("assoc_backup"))
    for suffix in PROGIDS:
        _reg_delete_tree(rf"{CLASSES}\MonkeyViewer.{suffix}")
    if FROZEN:
        _reg_delete_tree(rf"{CLASSES}\Applications\{os.path.basename(sys.executable)}")
    settings.pop("assoc_backup", None)
    settings["assoc"] = {"open_with": [], "default": [], "context": False}
    settings.save()
    _notify_shell()
    return True


def native_message(text, error=False):
    if IS_MAC and macutil.alert(text, error):
        return
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x10 if error else 0x40)
            return
        except Exception:
            pass
    print(text)


# ─────────────── Single instance: every file opens as a tab in ONE window ───────────────
def _instance_port():
    user = (os.environ.get("USERNAME") or os.environ.get("USER") or "user").lower()
    return 41000 + int(hashlib.sha256(f"{APP_ID}:{user}".encode()).hexdigest(), 16) % 20000


def _instance_token():
    """Per-user secret in the user's own settings folder: only this user's processes can hand files to the
    running window (matters on shared Remote Desktop servers where everyone shares 127.0.0.1)."""
    import secrets
    path = os.path.join(config_dir(), "instance.key")
    try:
        with open(path, "r", encoding="ascii") as fh:
            token = fh.read().strip()
        if len(token) == 64:
            return token
    except OSError:
        pass
    token = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(token)
    except OSError:
        pass
    return token


class SingleInstance:
    def __init__(self):
        self.queue = queue.Queue()
        self.sock = None
        self.token = _instance_token()

    def acquire(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if IS_WIN and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", _instance_port()))
            sock.listen(16)
        except OSError:
            sock.close()
            return False
        self.sock = sock
        threading.Thread(target=self._serve, daemon=True).start()
        return True

    def release(self):
        """Let a new instance take over (restart)."""
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _serve(self):
        while True:
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            try:
                conn.settimeout(3)
                data = b""
                while len(data) < 2_000_000:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                msg = json.loads(data.decode("utf-8"))
                import hmac
                if msg.get("app") == APP_ID and hmac.compare_digest(str(msg.get("token", "")), self.token):
                    files = [f for f in msg.get("files", []) if isinstance(f, str)]
                    conn.sendall(b"OK")
                    self.queue.put(files)
            except Exception:
                pass
            finally:
                conn.close()

    @staticmethod
    def send(files):
        if IS_WIN:
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
        payload = json.dumps({"app": APP_ID, "token": _instance_token(), "files": files}).encode("utf-8")
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", _instance_port()), timeout=2) as conn:
                    conn.sendall(payload)
                    conn.shutdown(socket.SHUT_WR)
                    return conn.recv(16) == b"OK"
            except OSError:
                time.sleep(0.15)
        return False
