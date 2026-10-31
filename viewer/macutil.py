"""macOS helpers: tool lookup outside the bare Finder PATH, Quick Look thumbnails, Finder type names,
image clipboard, dark window chrome and LaunchServices default-app control (per user, no admin rights).

Everything here is a no-op / returns None on other systems.
"""

import ctypes
import glob
import os
import shutil
import subprocess
import sys
import tempfile

IS_MAC = sys.platform == "darwin"
from .app_info import BUNDLE_ID  # noqa: E402

# Apps started from Finder get PATH=/usr/bin:/bin:/usr/sbin:/sbin — add the usual package-manager folders.
EXTRA_BIN = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/local/MacGPG2/bin",
             os.path.expanduser("~/.local/bin"), "/Applications/MacPorts")

APP_BINARIES = {
    "soffice": ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
                "~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    "ODAFileConverter": ("/Applications/ODAFileConverter*.app/Contents/MacOS/ODAFileConverter",
                         "/Applications/ODA/ODAFileConverter*.app/Contents/MacOS/ODAFileConverter"),
    "ddjvu": ("/Applications/DjView.app/Contents/bin/ddjvu", "/Applications/DjVuLibre*/bin/ddjvu"),
    "gpg": ("/usr/local/MacGPG2/bin/gpg", "/usr/local/MacGPG2/bin/gpg2"),
    "7zz": ("/Applications/Keka.app/Contents/Resources/keka7z",),
}


def search_path():
    parts = os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(parts + [p for p in EXTRA_BIN if p not in parts])


def find(*names):
    """First executable among *names* on PATH, Homebrew/MacPorts folders or inside known app bundles."""
    if not IS_MAC:
        return None
    path = search_path()
    for name in names:
        hit = shutil.which(name, path=path)
        if hit:
            return hit
    for name in names:
        for pattern in APP_BINARIES.get(name, ()):
            hits = sorted(glob.glob(os.path.expanduser(pattern)))
            if hits and os.access(hits[-1], os.X_OK):
                return hits[-1]
    return None


def _run(args, timeout=30):
    return subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


# ─────────────────────────────── Finder / Quick Look ───────────────────────────────
def quicklook_thumbnail(path, size=512):
    """The Quick Look thumbnail Finder shows (works for Pages, Keynote, Numbers, many CAD/3D apps' files,
    video...). Returns a PIL image or None."""
    if not IS_MAC:
        return None
    tmp = tempfile.mkdtemp(prefix="monkeyviewer_ql_")
    try:
        _run(["/usr/bin/qlmanage", "-t", "-s", str(int(size)), "-o", tmp, path], timeout=25)
        hits = glob.glob(os.path.join(tmp, "*.png"))
        if not hits:
            return None
        from PIL import Image
        with Image.open(hits[0]) as im:
            im.load()
            return im.copy()
    except Exception:  # noqa: BLE001
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def kind_name(path):
    """Finder's "Kind", e.g. 'Pages Document'."""
    if not IS_MAC:
        return None
    try:
        out = _run(["/usr/bin/mdls", "-raw", "-name", "kMDItemKind", path], timeout=8).stdout
        text = out.decode("utf-8", "replace").strip()
        return None if not text or text == "(null)" else text
    except Exception:  # noqa: BLE001
        return None


def copy_image_to_clipboard(img):
    if not IS_MAC:
        return False
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="monkeyviewer_clip_")
    os.close(fd)
    try:
        img.save(tmp, "PNG")
        script = f'set the clipboard to (read (POSIX file "{tmp}") as «class PNGf»)'
        return _run(["/usr/bin/osascript", "-e", script], timeout=15).returncode == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def window_appearance(window, dark=True):
    """Dark or light title bar / window chrome (Tk 8.6.10+)."""
    if not IS_MAC:
        return
    try:
        window.tk.call("::tk::unsupported::MacWindowStyle", "appearance", window._w, "darkaqua" if dark else "aqua")
    except Exception:  # noqa: BLE001
        pass


def dark_window(window):
    window_appearance(window, True)


def alert(text, error=False):
    if not IS_MAC:
        return False
    icon = "critical" if error else "informational"
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    try:
        _run(["/usr/bin/osascript", "-e", f'display alert "Monkey Viewer" message "{safe}" as {icon}'], timeout=600)
        return True
    except Exception:  # noqa: BLE001
        return False


# ─────────────────────────────── LaunchServices (default apps) ───────────────────────────────
_LIBS = None
UTF8 = 0x08000100
ROLES_ALL = 0xFFFFFFFF


def _libs():
    global _LIBS
    if _LIBS is None:
        cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cs = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreServices.framework/CoreServices")
        vp, u32 = ctypes.c_void_p, ctypes.c_uint32
        cf.CFStringCreateWithCString.restype = vp
        cf.CFStringCreateWithCString.argtypes = [vp, ctypes.c_char_p, u32]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, u32]
        cf.CFRelease.argtypes = [vp]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [vp]
        cf.CFArrayGetValueAtIndex.restype = vp
        cf.CFArrayGetValueAtIndex.argtypes = [vp, ctypes.c_long]
        cs.UTTypeCreatePreferredIdentifierForTag.restype = vp
        cs.UTTypeCreatePreferredIdentifierForTag.argtypes = [vp, vp, vp]
        cs.LSCopyDefaultRoleHandlerForContentType.restype = vp
        cs.LSCopyDefaultRoleHandlerForContentType.argtypes = [vp, u32]
        cs.LSCopyAllRoleHandlersForContentType.restype = vp
        cs.LSCopyAllRoleHandlersForContentType.argtypes = [vp, u32]
        cs.LSSetDefaultRoleHandlerForContentType.restype = ctypes.c_int32
        cs.LSSetDefaultRoleHandlerForContentType.argtypes = [vp, u32, vp]
        _LIBS = (cf, cs)
    return _LIBS


class _CF:
    """CFString holder that releases itself."""

    def __init__(self, text=None, ref=None):
        cf, _cs = _libs()
        if text is not None:
            self.ref = cf.CFStringCreateWithCString(None, text.encode("utf-8"), UTF8)
        else:
            self.ref = ref or None            # may be NULL when the call found nothing

    def text(self):
        if not self.ref:
            return None
        cf, _cs = _libs()
        buf = ctypes.create_string_buffer(2048)
        return buf.value.decode("utf-8") if cf.CFStringGetCString(self.ref, buf, 2048, UTF8) else None

    def __del__(self):
        try:
            if self.ref:
                _libs()[0].CFRelease(self.ref)
        except Exception:  # noqa: BLE001
            pass


_UTI_CACHE = {}


def uti_for(ext):
    ext = ext.lower().lstrip(".")
    if ext not in _UTI_CACHE:
        _cf, cs = _libs()
        tag_class, tag = _CF("public.filename-extension"), _CF(ext)
        _UTI_CACHE[ext] = _CF(ref=cs.UTTypeCreatePreferredIdentifierForTag(tag_class.ref, tag.ref, None)).text()
    return _UTI_CACHE[ext]


def default_handler(ext):
    """Bundle id of the app that opens *ext* on double-click (or None)."""
    _cf, cs = _libs()
    uti = uti_for(ext)
    if not uti:
        return None
    u = _CF(uti)
    return _CF(ref=cs.LSCopyDefaultRoleHandlerForContentType(u.ref, ROLES_ALL)).text()


def all_handlers(ext):
    cf, cs = _libs()
    uti = uti_for(ext)
    if not uti:
        return []
    u = _CF(uti)
    arr = cs.LSCopyAllRoleHandlersForContentType(u.ref, ROLES_ALL)
    if not arr:
        return []
    try:
        return [_string_at(cf.CFArrayGetValueAtIndex(arr, i)) for i in range(cf.CFArrayGetCount(arr))]
    finally:
        cf.CFRelease(arr)


def _string_at(ref):
    """Read a CFString we do not own (no release)."""
    cf, _cs = _libs()
    buf = ctypes.create_string_buffer(2048)
    return buf.value.decode("utf-8") if ref and cf.CFStringGetCString(ref, buf, 2048, UTF8) else None


def set_default_handler(ext, bundle_id):
    _cf, cs = _libs()
    uti = uti_for(ext)
    if not uti:
        return False
    u, b = _CF(uti), _CF(bundle_id)
    return cs.LSSetDefaultRoleHandlerForContentType(u.ref, ROLES_ALL, b.ref) == 0


def current_defaults(exts):
    out = set()
    for ext in exts:
        try:
            if (default_handler(ext) or "").lower() == BUNDLE_ID:
                out.add(ext)
        except Exception:  # noqa: BLE001
            pass
    return out


def apply_defaults(exts_all, defaults, backup=None):
    """Make Monkey Viewer the default app for exactly *defaults*; give every other type that currently opens in
    Monkey Viewer back to its previous app. Returns (backup, failed)."""
    backup = dict(backup or {})
    failed = []
    if not IS_MAC:
        return backup, failed
    for ext in sorted(exts_all):
        try:
            current = (default_handler(ext) or "")
        except Exception:  # noqa: BLE001
            continue
        mine = current.lower() == BUNDLE_ID
        if ext in defaults:
            if not mine:
                if current:
                    backup[ext] = current
                if not set_default_handler(ext, BUNDLE_ID):
                    failed.append(ext)
        elif mine:
            previous = backup.pop(ext, None)
            if not previous:
                previous = next((h for h in all_handlers(ext) if h and h.lower() != BUNDLE_ID), None)
            if previous:
                set_default_handler(ext, previous)
    return backup, failed
