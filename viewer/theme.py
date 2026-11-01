"""Colours, fonts, icons and the small shared widgets every view uses."""

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import winutil
from .i18n import T

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
PRIMARY = "Command" if IS_MAC else "Control"      # shortcut modifier in Tk event patterns
FONT_SCALE = 1.3 if IS_MAC else 1.0               # Tk on macOS measures fonts at 72 dpi
CODE_SIZE = 13 if IS_MAC else 11
SCALE = 1.0
FONTS = {}
HAS_ICONS = False
CODE_FONT = None
CODE_FONT_ITALIC = None
_IMAGES = {}

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except Exception:  # Pillow is optional for the bare text editor
    Image = ImageDraw = ImageFont = ImageTk = None


def px(value):
    return int(round(value * SCALE))


# ─────────────────────────────── platform input helpers ───────────────────────────────
_MAC_SYMBOLS = {"Ctrl": "\u2318", "Shift": "\u21e7", "Alt": "\u2325"}
_KEY_COMBO = None


def keys(text):
    """Shortcut hints for display: 'Ctrl+Shift+S' stays on Windows, becomes '\u21e7\u2318S' on a Mac."""
    if not IS_MAC or not text or "+" not in text:
        return text
    global _KEY_COMBO
    if _KEY_COMBO is None:
        import re
        _KEY_COMBO = re.compile(r"\b((?:(?:Ctrl|Shift|Alt)\+)+)(Tab|Del|Enter|[A-Za-z0-9=+\-/]|F\d+)(?![A-Za-z])")

    def repl(m):
        mods = m.group(1).rstrip("+").split("+")
        key = m.group(2)
        if key == "Tab":                       # tab switching keeps the Control key on a Mac
            return "".join(s for k, s in (("Ctrl", "\u2303"), ("Shift", "\u21e7")) if k in mods) + "Tab"
        order = [k for k in ("Alt", "Shift", "Ctrl") if k in mods]
        return "".join(_MAC_SYMBOLS[k] for k in order) + (key.upper() if len(key) == 1 else key)
    return _KEY_COMBO.sub(repl, text)


def menu_accel(text):
    """Menu accelerator label in the form Tk renders natively on each platform."""
    if not IS_MAC or not text:
        return text
    return text.replace("Ctrl+", "Command-").replace("Shift+", "Shift-").replace("Alt+", "Option-")


def has_modifier(event):
    """True when Ctrl / Alt (or Command / Option on a Mac) is held."""
    if IS_MAC:
        return bool(event.state & (0x0004 | 0x0008 | 0x0010))
    return bool(event.state & (0x0004 | 0x20000 | 0x0008))


def wheel_units(event, notch=3):
    """Scroll amount for a <MouseWheel> event: whole notches on Windows, the trackpad's fine steps on a Mac."""
    d = event.delta
    if not d:
        return 0
    if IS_MAC:
        return -d
    return int(round(-d / 120.0 * notch)) or (-1 if d > 0 else 1)


_BUTTONS = None


def mouse_buttons(widget):
    """(right, middle) button numbers: Tk 8.6 on macOS reports the right button as 2."""
    global _BUTTONS
    if _BUTTONS is None:
        right, middle = 3, 2
        if IS_MAC:
            try:
                level = str(widget.tk.call("info", "patchlevel"))
            except tk.TclError:
                level = "8.6"
            if level.startswith(("8.5", "8.6")):
                right, middle = 2, 3
        _BUTTONS = (right, middle)
    return _BUTTONS


def bind_right(widget, func, add=None):
    """Context-menu click: right button everywhere, also Control-click on a Mac."""
    right, _middle = mouse_buttons(widget)
    widget.bind(f"<Button-{right}>", func, add)
    if IS_MAC:
        widget.bind("<Control-Button-1>", func, add)


def bind_middle_release(widget, func, add=None):
    _right, middle = mouse_buttons(widget)
    widget.bind(f"<ButtonRelease-{middle}>", func, add)


DARK = {
    "bg": "#1a1b26",
    "bg_deep": "#15161f",
    "chrome": "#16161e",
    "sidebar": "#16161e",
    "panel": "#1f2335",
    "panel_hi": "#252a40",
    "input": "#13131a",
    "border": "#24283b",
    "border_strong": "#343a52",
    "hover": "#222433",
    "hover_strong": "#2c3148",
    "tab_hover": "#1c1d29",
    "row_sel": "#262c45",
    "row_alt": "#1d1e2b",
    "curline": "#1f2133",
    "fg": "#c0caf5",
    "fg_bright": "#eef0ff",
    "fg_dim": "#9aa5ce",
    "fg_muted": "#5c6488",
    "gutter": "#3b4261",
    "gutter_active": "#a9b1d6",
    "accent": "#7aa2f7",
    "accent_hover": "#93b4ff",
    "on_accent": "#10121b",
    "selection": "#2b3a63",
    "selection_inactive": "#232a40",
    "caret": "#c0caf5",
    "thumb": "#262a3d",
    "thumb_hover": "#363c58",
    "thumb_active": "#454d70",
    "find": "#33406a",
    "find_cur_bg": "#e0af68",
    "find_cur_fg": "#16161e",
    "kbd": "#222538",
    "success": "#9ece6a",
    "warning": "#e0af68",
    "danger": "#f7768e",
    "canvas": "#0f1017",
    "page_shadow": "#090a10",
    "syn_keyword": "#bb9af7",
    "syn_const": "#ff9e64",
    "syn_number": "#ff9e64",
    "syn_string": "#9ece6a",
    "syn_comment": "#636da6",
    "syn_builtin": "#2ac3de",
    "syn_func": "#7aa2f7",
    "syn_tag": "#f7768e",
}

LIGHT = {
    "bg": "#f7f8fb",
    "bg_deep": "#eceef3",
    "chrome": "#eef0f4",
    "sidebar": "#f0f2f6",
    "panel": "#ffffff",
    "panel_hi": "#f3f5fa",
    "input": "#ffffff",
    "border": "#d9dce5",
    "border_strong": "#c3c8d4",
    "hover": "#e6e9f0",
    "hover_strong": "#dde1ea",
    "tab_hover": "#e9ecf2",
    "row_sel": "#dbe6fd",
    "row_alt": "#f2f4f8",
    "curline": "#eef2fb",
    "fg": "#343b58",
    "fg_bright": "#151a30",
    "fg_dim": "#4c5577",
    "fg_muted": "#7a819c",
    "gutter": "#a8aec3",
    "gutter_active": "#343b58",
    "accent": "#2f6fe0",
    "accent_hover": "#4a82ea",
    "on_accent": "#ffffff",
    "selection": "#cddcfb",
    "selection_inactive": "#e2e8f5",
    "caret": "#151a30",
    "thumb": "#c9cdd8",
    "thumb_hover": "#b4b9c7",
    "thumb_active": "#9da3b5",
    "find": "#fde68a",
    "find_cur_bg": "#f59e0b",
    "find_cur_fg": "#151a30",
    "kbd": "#e6e9f0",
    "success": "#2e7d32",
    "warning": "#a3620a",
    "danger": "#d32f45",
    "canvas": "#e2e5eb",
    "page_shadow": "#c5c9d3",
    "syn_keyword": "#7c3aed",
    "syn_const": "#c2410c",
    "syn_number": "#c2410c",
    "syn_string": "#2e7d32",
    "syn_comment": "#8a90a6",
    "syn_builtin": "#0e7490",
    "syn_func": "#1d4ed8",
    "syn_tag": "#be123c",
}
C = dict(DARK)            # the active palette; set_mode() switches it before any widget is built

KIND_COLORS_LIGHT = {
    "code": "#2f6fe0", "text": "#5a6382", "pdf": "#d6334f", "image": "#8e44c8",
    "cad": "#b7791f", "gis": "#4f8a1f", "model": "#d9640f", "office": "#0e7490",
    "table": "#13877a", "archive": "#a0602a", "media": "#c2185b", "font": "#4c5577",
    "binary": "#6b7290", "secure": "#a8810a", "mail": "#167c88",
}
KIND_COLORS = {
    "code": "#7aa2f7", "text": "#a9b1d6", "pdf": "#f7768e", "image": "#bb9af7",
    "cad": "#e0af68", "gis": "#9ece6a", "model": "#ff9e64", "office": "#7dcfff",
    "table": "#73daca", "archive": "#d19a66", "media": "#f472b6", "font": "#c0caf5",
    "binary": "#737aa2", "secure": "#e5c07b", "mail": "#56b6c2",
}
KIND_COLORS_DARK = dict(KIND_COLORS)
THEMES = ("auto", "light", "dark")
IS_DARK = True


def system_theme():
    """'light' or 'dark' as set in Windows (Personalize > Colors > app mode) or macOS (Appearance)."""
    try:
        if IS_WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
        if IS_MAC:
            import subprocess                  # fixed absolute command, no shell, no user input
            out = subprocess.run(["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True,
                                 text=True, timeout=5, stdin=subprocess.DEVNULL).stdout
            return "dark" if "dark" in out.lower() else "light"
    except Exception:  # noqa: BLE001 - no setting means the system default (light)
        return "light"
    return "dark"


def set_mode(preference="auto"):
    """Choose the palette once, before any widget is built: 'auto' follows the operating system."""
    global IS_DARK
    mode = preference if preference in ("light", "dark") else system_theme()
    IS_DARK = mode == "dark"
    C.clear()
    C.update(DARK if IS_DARK else LIGHT)
    KIND_COLORS.clear()
    KIND_COLORS.update(KIND_COLORS_DARK if IS_DARK else KIND_COLORS_LIGHT)
    _IMAGES.clear()
    return mode

# Segoe Fluent Icons / Segoe MDL2 Assets code points (Windows 10/11)
GLYPHS = {
    "menu": "", "open": "", "folder": "", "new": "", "add": "",
    "save": "", "saveas": "", "copy": "", "cut": "", "paste": "",
    "selectall": "", "find": "", "close": "", "up": "", "down": "",
    "left": "", "right": "", "check": "", "warning": "", "info": "",
    "error": "", "undo": "", "redo": "", "rotate": "", "delete": "",
    "crop": "", "edit": "", "text": "", "highlight": "", "erase": "",
    "rect": "", "picture": "", "pointer": "", "zoomin": "", "zoomout": "",
    "fit": "", "print": "", "export": "", "download": "", "document": "",
    "page": "", "convert": "", "more": "", "settings": "", "openwith": "",
    "external": "", "reveal": "", "play": "", "pause": "", "map": "",
    "globe": "", "code": "", "layers": "", "list": "", "table": "",
    "pane": "", "wrap": "", "contrast": "", "cube": "", "zip": "",
    "pen": "", "split": "", "refresh": "", "flip": "", "split_pages": "",
    "media": "", "font": "", "chevron": "", "history": "", "link": "",
    "key": "\uE8D7", "pipette": "\uE790", "lock": "\uE72E", "mail": "\uE715", "attach": "\uE723", "stop": "\uE71A",
    "volume": "\uE767", "music": "\uEC4F", "calc": "\uE8EF", "weather": "\uE9CA", "pin": "\uE718",
    "unpin": "\uE77A",
}
FALLBACK_GLYPHS = {
    "menu": "☰", "close": "✕", "up": "▲", "down": "▼", "left": "◀",
    "right": "▶", "check": "✓", "warning": "!", "info": "i", "error": "✕",
    "add": "+", "new": "+", "zoomin": "+", "zoomout": "−", "chevron": "▾",
    "play": "▶", "pause": "❚❚", "more": "⋯", "undo": "↶", "redo": "↷",
    "calc": "÷", "pin": "⊙", "unpin": "⊙", "history": "⟲", "copy": "⧉", "refresh": "⟳",
}


# ─────────────────────────────── setup ───────────────────────────────
def init(root):
    """Compute DPI scale, pick fonts and configure ttk styles. Call once after Tk()."""
    global SCALE, HAS_ICONS, CODE_FONT, CODE_FONT_ITALIC
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    families = set(tkfont.families(root))

    def pick(candidates, default):
        return next((f for f in candidates if f in families), default)

    system_ui = None
    if IS_MAC:
        try:
            system_ui = tkfont.nametofont("TkDefaultFont", root).actual("family")   # San Francisco
        except tk.TclError:
            system_ui = None
    ui = system_ui or pick(("Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Inter", "Helvetica Neue",
                            "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial"), "TkDefaultFont")
    ui_display = ui if IS_MAC else pick(("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI"), ui)
    code = pick(("Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas", "SF Mono",
                 "Menlo", "DejaVu Sans Mono", "Courier New"), "TkFixedFont")
    icons = pick(("Segoe Fluent Icons", "Segoe MDL2 Assets"), None)
    HAS_ICONS = icons is not None

    def f(size):
        return int(round(size * FONT_SCALE))

    FONTS.update(
        ui=(ui, f(10)), ui_bold=(ui, f(10), "bold"), small=(ui, f(9)), small_bold=(ui, f(9), "bold"),
        tiny=(ui, f(8)), caption=(ui, f(8), "bold"), brand=(ui, f(11), "bold"), h1=(ui_display, f(26), "bold"),
        h2=(ui_display, f(15), "bold"), h3=(ui, f(11), "bold"), subtitle=(ui, f(11)), dot=(ui, f(9)),
        kbd=(code, f(9)), mono=(code, f(10)), icon=(icons or ui, f(11)), icon_sm=(icons or ui, f(10)),
        icon_xs=(icons or ui, f(8)), icon_lg=(icons or ui, f(16)), icon_xl=(icons or ui, f(34)),
    )
    CODE_FONT = tkfont.Font(root, family=code, size=CODE_SIZE)
    CODE_FONT_ITALIC = tkfont.Font(root, family=code, size=CODE_SIZE, slant="italic")
    _setup_styles(root)


def _setup_styles(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass

    def scrollbar(name, vertical, trough):
        elem = "Vertical" if vertical else "Horizontal"
        st.layout(name, [(f"{elem}.Scrollbar.trough", {
            "sticky": "ns" if vertical else "ew",
            "children": [(f"{elem}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        st.configure(name, troughcolor=trough, background=C["thumb"], bordercolor=trough,
                     lightcolor=C["thumb"], darkcolor=C["thumb"], arrowcolor=C["thumb"],
                     gripcount=0, borderwidth=0, relief="flat", arrowsize=px(10), width=px(10))
        states = [("pressed", C["thumb_active"]), ("active", C["thumb_hover"])]
        st.map(name, background=states, lightcolor=states, darkcolor=states)

    for prefix, trough in (("", C["bg"]), ("Side.", C["sidebar"]), ("Canvas.", C["canvas"]),
                           ("Panel.", C["panel"])):
        scrollbar(f"{prefix}Vertical.TScrollbar", True, trough)
        scrollbar(f"{prefix}Horizontal.TScrollbar", False, trough)

    st.configure("Side.Treeview", background=C["sidebar"], fieldbackground=C["sidebar"],
                 foreground=C["fg_dim"], borderwidth=0, relief="flat", rowheight=px(32),
                 font=FONTS["ui"], indent=0)
    st.map("Side.Treeview", background=[("selected", C["row_sel"])],
           foreground=[("selected", C["fg_bright"])])
    st.layout("Side.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    st.layout("Side.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
        ("Treeitem.image", {"side": "left", "sticky": ""}),
        ("Treeitem.text", {"side": "left", "sticky": ""})]})])
    st.configure("Side.Treeview.Item", padding=(px(14), 0, 0, 0))

    # data grids (tables, attribute tables, archives, layer lists)
    st.configure("Grid.Treeview", background=C["bg"], fieldbackground=C["bg"], foreground=C["fg"],
                 borderwidth=0, relief="flat", rowheight=px(26), font=FONTS["small"])
    st.map("Grid.Treeview", background=[("selected", C["selection"])],
           foreground=[("selected", C["fg_bright"])])
    st.layout("Grid.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    st.configure("Grid.Treeview.Heading", background=C["chrome"], foreground=C["fg_dim"],
                 bordercolor=C["border"], lightcolor=C["chrome"], darkcolor=C["chrome"],
                 relief="flat", font=FONTS["small_bold"], padding=(px(8), px(5)))
    st.map("Grid.Treeview.Heading", background=[("active", C["hover"])],
           foreground=[("active", C["fg_bright"])])
    st.configure("Grid.Treeview.Item", padding=(px(4), 0))


# ─────────────────────────────── helpers ───────────────────────────────
def icon(name, allow_fallback=True):
    """Returns (glyph, font) for a named icon, or (None, None)."""
    if HAS_ICONS and name in GLYPHS:
        return GLYPHS[name], FONTS["icon"]
    if allow_fallback and name in FALLBACK_GLYPHS:
        return FALLBACK_GLYPHS[name], FONTS["ui"]
    return None, None


def hex_to_rgb(color):
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def mix(c1, c2, t):
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def is_descendant(widget, ancestor):
    a, w = str(ancestor), str(widget)
    return w == a or w.startswith(a + ".")


def pointer_inside(widget, event):
    try:
        target = widget.winfo_containing(event.x_root, event.y_root)
    except (KeyError, tk.TclError):
        return False
    return target is not None and is_descendant(target, widget)


def _badge_font(size):
    for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                 "Arial Bold.ttf", "/System/Library/Fonts/HelveticaNeue.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def badge_image(label, color, width=32, height=17):
    """The file-type label in tabs and lists: the type name on a band in the category colour plus the monkey
    tile (Monkey Viewer's file icon in small). A tinted pill when resvg is not available."""
    key = ("badge", label, color, width, height)
    if key in _IMAGES:
        return _IMAGES[key]
    w, h = px(width), px(height)
    from . import monkey
    if Image is not None and monkey.available():
        try:
            img = ImageTk.PhotoImage(monkey.type_chip(label, color, w, h, _badge_font))
        except Exception:
            img = None
        if img is not None:
            _IMAGES[key] = img
            return img
    if Image is None:
        img = tk.PhotoImage(width=w, height=h)
        img.put(mix(color, C["bg"], 0.65), to=(0, 0, w, h))
    else:
        ss = 4
        big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        rgb = hex_to_rgb(color)
        d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=int(h * ss * 0.32), fill=rgb + (52,))
        font = _badge_font(int(h * ss * 0.56))
        d.text((w * ss / 2, h * ss / 2 + ss * 0.5), label, font=font, fill=rgb + (255,), anchor="mm")
        img = ImageTk.PhotoImage(big.resize((w, h), Image.LANCZOS))
    _IMAGES[key] = img
    return img


def swatch_image(color, size=14):
    return tile_image(color, size, alpha=255, radius=0.3)


def tile_image(color, size=40, alpha=46, radius=0.28):
    key = ("tile", color, size, alpha)
    if key in _IMAGES:
        return _IMAGES[key]
    s = px(size)
    if Image is None:
        img = tk.PhotoImage(width=s, height=s)
        img.put(mix(color, C["bg"], 0.8), to=(0, 0, s, s))
    else:
        ss = 4
        big = Image.new("RGBA", (s * ss, s * ss), (0, 0, 0, 0))
        ImageDraw.Draw(big).rounded_rectangle((0, 0, s * ss - 1, s * ss - 1), radius=int(s * ss * radius),
                                              fill=hex_to_rgb(color) + (alpha,))
        img = ImageTk.PhotoImage(big.resize((s, s), Image.LANCZOS))
    _IMAGES[key] = img
    return img


def moon_image(size, color=None, plate=False):
    """Crescent moon ("Lua" = moon). With plate=True it sits on a rounded dark tile."""
    color = color or C["accent"]
    key = ("moon", size, color, plate)
    if key in _IMAGES:
        return _IMAGES[key]
    if Image is None:
        img = _moon_photo(size, color)
    else:
        ss = 4
        n = size * ss
        big = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        if plate:
            d.rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.24), fill=hex_to_rgb(C["panel"]) + (255,))
            inset = 0.17
        else:
            inset = 0.0
        mask = Image.new("L", (n, n), 0)
        md = ImageDraw.Draw(mask)
        r = n * (0.5 - inset) * 0.86
        cx = cy = n / 2
        md.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        bx, by, br = cx + r * 0.42, cy - r * 0.38, r * 0.80
        md.ellipse((bx - br, by - br, bx + br, by + br), fill=0)
        big.paste(hex_to_rgb(color) + (255,), (0, 0), mask)
        img = ImageTk.PhotoImage(big.resize((size, size), Image.LANCZOS))
    _IMAGES[key] = img
    return img


def file_icon_image(category, size):
    """The file icon (as in Explorer / Finder) for a program category, or None without resvg."""
    key = ("fileicon", category, size)
    if key in _IMAGES:
        return _IMAGES[key]
    from . import monkey
    if Image is None or not monkey.available():
        return None
    try:
        img = ImageTk.PhotoImage(monkey.file_icon(monkey.CATEGORY_TYPE.get(category, "file"), size, _badge_font))
    except Exception:
        return None
    _IMAGES[key] = img
    return img


def logo_image(size, plate=False):
    """Monkey Viewer's mark (the monkey with the magnifier); plate=True puts it on its yellow tile."""
    key = ("logo", size, plate)
    if key in _IMAGES:
        return _IMAGES[key]
    from . import monkey
    if Image is None or not monkey.available():
        return moon_image(size, plate=plate)
    try:
        img = ImageTk.PhotoImage(monkey.render(monkey.logo_svg(plate, tiny=size <= 24), size))
    except Exception:                               # never let the logo stop the window from opening
        return moon_image(size, plate=plate)
    _IMAGES[key] = img
    return img


def _moon_photo(size, color):
    img = tk.PhotoImage(width=size, height=size)
    s = size / 32.0
    cx, cy, r = 16 * s, 16 * s, 13.5 * s
    bx, by, br = 22.5 * s, 10.5 * s, 10.5 * s
    for y in range(size):
        x0 = None
        for x in range(size + 1):
            inside = (x < size and (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 <= r * r
                      and (x + .5 - bx) ** 2 + (y + .5 - by) ** 2 > br * br)
            if inside and x0 is None:
                x0 = x
            elif not inside and x0 is not None:
                img.put(color, to=(x0, y, x, y + 1))
                x0 = None
    return img


class _Menu(tk.Menu):
    """tk.Menu that shows accelerators the way each platform expects."""

    def add_command(self, cnf=None, **kw):
        if "accelerator" in kw:
            kw["accelerator"] = menu_accel(kw["accelerator"])
        return super().add_command(cnf or {}, **kw)


def popup_menu(root):
    return _Menu(root, tearoff=0, bg=C["panel"], fg=C["fg"], activebackground=C["row_sel"],
                   activeforeground=C["fg_bright"], disabledforeground=C["fg_muted"], bd=0,
                   relief="flat", activeborderwidth=0, font=FONTS["ui"])


def menu_var(menu, kind, value):
    """A Tk variable for a check/radio item that lives as long as the menu (a dropped Python variable would
    unset the Tk one and the item would lose its tick)."""
    var = {"bool": tk.BooleanVar, "str": tk.StringVar}[kind](master=menu, value=value)
    menu.__dict__.setdefault("_lv_vars", []).append(var)
    return var


_POPUP = {"open": 0}


MENU_CLOSE_DELAY = 0.45     # seconds the pointer may stay away from an open menu before it closes
MENU_MARGIN = 16            # px of slack around the menu and its button


def _win_menu_rects(thread_id):
    """Screen rectangles of the open menus of the UI thread (Windows draws them as '#32768' windows)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    rects = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def check(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowThreadProcessId(hwnd, None) == thread_id:
            buf = ctypes.create_unicode_buffer(16)
            user32.GetClassNameW(hwnd, buf, 16)
            if buf.value == "#32768":
                r = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                rects.append((r.left, r.top, r.right, r.bottom))
        return True
    user32.EnumWindows(proc_type(check), 0)
    return rects


def _win_cancel_menu(thread_id):
    """Close the UI thread's open menu from another thread: WM_CANCELMODE to the menu's owner window."""
    import ctypes
    from ctypes import wintypes

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    user32 = ctypes.windll.user32
    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndMenuOwner:
        user32.PostMessageW(info.hwndMenuOwner, 0x001F, 0, 0)        # WM_CANCELMODE


class _WinMenuWatcher:
    """Windows: the menu runs its own modal loop, so the pointer is watched from a small thread that only
    reads the cursor / window rectangles and posts WM_CANCELMODE (no Tk calls off the UI thread)."""

    def __init__(self, anchor):
        import ctypes
        import threading
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self.anchor_rect = None
        if anchor is not None:
            try:
                self.anchor_rect = (anchor.winfo_rootx(), anchor.winfo_rooty(),
                                    anchor.winfo_rootx() + anchor.winfo_width(),
                                    anchor.winfo_rooty() + anchor.winfo_height())
            except tk.TclError:
                pass
        self.margin = px(MENU_MARGIN)
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, name="menu-watch", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.done.set()

    def run(self):
        import ctypes
        import time
        from ctypes import wintypes
        away_since = None
        point = wintypes.POINT()
        while not self.done.wait(0.08):
            try:
                rects = _win_menu_rects(self.thread_id)
                if not rects:
                    continue
                if self.anchor_rect:
                    rects.append(self.anchor_rect)
                ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
                m = self.margin
                inside = any(x0 - m <= point.x <= x1 + m and y0 - m <= point.y <= y1 + m
                             for x0, y0, x1, y1 in rects)
                now = time.monotonic()
                if inside:
                    away_since = None
                elif away_since is None:
                    away_since = now
                elif now - away_since >= MENU_CLOSE_DELAY:
                    _win_cancel_menu(self.thread_id)
                    if self.done.wait(0.3):
                        return
                    for _ in range(len(_win_menu_rects(self.thread_id))):   # still open: Esc per level
                        ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)
                        ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
                    return
            except Exception:  # noqa: BLE001 - a watcher problem must never affect the menu
                return


def _tk_menu_rects(menu):
    """Rectangles of a posted Tk menu and the cascades opened from it (Linux)."""
    out = []
    try:
        if not menu.winfo_ismapped():
            return out
        out.append((menu.winfo_rootx(), menu.winfo_rooty(), menu.winfo_rootx() + menu.winfo_width(),
                    menu.winfo_rooty() + menu.winfo_height()))
        end = menu.index("end")
        for i in range(0 if end is None else end + 1):
            if menu.type(i) == "cascade":
                sub = menu.entrycget(i, "menu")
                if sub:
                    out.extend(_tk_menu_rects(menu.nametowidget(sub)))
    except (tk.TclError, KeyError):
        pass
    return out


class _MenuWatcher:
    """Closes an open drop-down once the pointer has left it (and the button that opened it) for a moment.
    Menus never open by themselves on hover - only a click opens them."""

    def __init__(self, menu, anchor=None):
        self.menu, self.anchor = menu, anchor
        self.away_since = None
        self.job = None
        self.active = not (IS_MAC or IS_WIN)     # Linux / X11 (Windows: _WinMenuWatcher; Mac: native)

    def start(self):
        if self.active:
            self.job = self.menu.after(150, self.tick)

    def stop(self):
        self.active = False
        if self.job is not None:
            try:
                self.menu.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None

    def rects(self):
        menus = _tk_menu_rects(self.menu)
        if not menus:
            return None                   # not on screen (yet / any more)
        if self.anchor is not None:
            try:
                a = self.anchor
                menus.append((a.winfo_rootx(), a.winfo_rooty(), a.winfo_rootx() + a.winfo_width(),
                              a.winfo_rooty() + a.winfo_height()))
            except tk.TclError:
                pass
        return menus

    def tick(self):
        import time
        self.job = None
        if not self.active:
            return
        try:
            rects = self.rects()
            if rects is None:             # a Tk menu that is no longer mapped was closed by the user
                return
            x, y = self.menu.winfo_pointerxy()
            m = px(MENU_MARGIN)
            inside = any(x0 - m <= x <= x1 + m and y0 - m <= y <= y1 + m for x0, y0, x1, y1 in rects)
            now = time.monotonic()
            if inside:
                self.away_since = None
            elif self.away_since is None:
                self.away_since = now
            elif now - self.away_since >= MENU_CLOSE_DELAY:
                self.close()
                return
            self.job = self.menu.after(80, self.tick)
        except tk.TclError:
            self.active = False

    def close(self):
        self.active = False
        try:
            self.menu.unpost()
            self.menu.grab_release()
        except tk.TclError:
            pass


def show_menu(menu, x, y, anchor=None):
    """Open a drop-down / context menu. It closes on a click outside, Esc, or when the pointer moves away."""
    _POPUP["open"] += 1                 # no tooltips on top of an open menu
    watcher = _WinMenuWatcher(anchor) if IS_WIN else _MenuWatcher(menu, anchor)
    watcher.start()
    try:
        menu.tk_popup(x, y)
    finally:
        _POPUP["open"] -= 1
        if IS_WIN or IS_MAC:            # tk_popup returned because the menu is closed
            watcher.stop()
        menu.grab_release()


# ─────────────────────────────── widgets ───────────────────────────────
class Tooltip:
    def __init__(self, widgets, text, delay=550):
        self.widgets = list(widgets) if isinstance(widgets, (list, tuple)) else [widgets]
        self.text, self.delay = text, delay
        self.job = self.tip = None
        for w in self.widgets:
            w.bind("<Enter>", self._schedule, add="+")
            w.bind("<Leave>", self._cancel, add="+")
            w.bind("<ButtonPress>", self._cancel, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self.job = self.widgets[0].after(self.delay, self._show)
        except tk.TclError:
            pass

    def _cancel(self, _event=None):
        if self.job:
            try:
                self.widgets[0].after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None

    def _show(self):
        self.job = None
        anchor = self.widgets[0]
        if _POPUP["open"]:
            return
        text = keys(self.text() if callable(self.text) else self.text)
        if not text or not anchor.winfo_exists():
            return
        tip = tk.Toplevel(anchor)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        border = tk.Frame(tip, bg=C["border_strong"])
        border.pack()
        tk.Label(border, text=text, bg=C["panel"], fg=C["fg"], font=FONTS["small"],
                 padx=px(9), pady=px(4), justify="left").pack(padx=1, pady=1)
        tip.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + px(6)
        if y + tip.winfo_reqheight() > anchor.winfo_screenheight() - px(40):     # no room below: above
            y = anchor.winfo_rooty() - tip.winfo_reqheight() - px(6)
        x = max(0, min(x, tip.winfo_screenwidth() - tip.winfo_reqwidth() - 4))
        tip.geometry(f"+{x}+{y}")
        self.tip = tip


class ToolButton(tk.Frame):
    """Flat button: optional icon glyph, label, hover/toggle/disabled states, tooltip, dropdown."""

    def __init__(self, master, text="", icon_name=None, command=None, tooltip=None,
                 variant="ghost", bg=None, hover=None, pad=(10, 5), menu=None, compact=False):
        primary = variant == "primary"
        self.c_bg = C["accent"] if primary else (bg or master.cget("bg"))
        self.c_hover = C["accent_hover"] if primary else (hover or C["hover"])
        self.c_fg = C["on_accent"] if primary else (C["danger"] if variant == "danger" else C["fg_dim"])
        self.c_fg_hover = C["on_accent"] if primary else C["fg_bright"]
        super().__init__(master, bg=self.c_bg, cursor="hand2")
        self.command, self.menu_builder = command, menu
        self.hovered = self.toggled = False
        self.enabled = True
        self.labels = []
        padx, pady = px(pad[0]), px(pad[1])
        glyph, gfont = icon(icon_name, allow_fallback=not text or compact) if icon_name else (None, None)
        if compact and glyph:
            text = ""
        if glyph:
            lbl = tk.Label(self, text=glyph, font=gfont)
            lbl.pack(side="left", padx=(padx, px(7) if text else padx), pady=pady)
            self.labels.append(lbl)
        self.text_label = None
        if text or not glyph:
            lbl = tk.Label(self, text=text, font=FONTS["ui_bold"] if primary else FONTS["ui"])
            lbl.pack(side="left", padx=(0 if glyph else padx, padx if not menu else px(4)), pady=pady)
            self.labels.append(lbl)
            self.text_label = lbl
        if menu:
            g, f = icon("chevron")
            lbl = tk.Label(self, text=g, font=FONTS["icon_xs"] if HAS_ICONS else f)
            lbl.pack(side="left", padx=(0, padx), pady=pady)
            self.labels.append(lbl)
        for w in (self, *self.labels):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<ButtonRelease-1>", self._on_click)
        self.tooltip_text = tooltip or ""
        if tooltip:
            Tooltip([self, *self.labels], tooltip)
        self._paint()

    def _paint(self):
        if not self.enabled:
            bg, fg = self.c_bg, C["fg_muted"] if self.c_bg != C["accent"] else C["thumb_active"]
        else:
            bg = self.c_hover if self.hovered else (C["row_sel"] if self.toggled else self.c_bg)
            fg = C["accent"] if self.toggled and not self.hovered else (
                self.c_fg_hover if self.hovered else self.c_fg)
        self.configure(bg=bg)
        for lbl in self.labels:
            lbl.configure(bg=bg, fg=fg)

    def _on_enter(self, _event):
        if not self.hovered and self.enabled:
            self.hovered = True
            self._paint()

    def _on_leave(self, event):
        if pointer_inside(self, event):
            return
        self.hovered = False
        self._paint()

    def _on_click(self, event):
        if not self.enabled or not pointer_inside(self, event):
            return
        if self.menu_builder:
            m = popup_menu(self)
            self.menu_builder(m)
            show_menu(m, self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + px(2), anchor=self)
            self._unhover_if_away()
        elif self.command:
            self.command()

    def _unhover_if_away(self):
        """While a menu is open the button misses its <Leave>: clear the hover look if the pointer is gone."""
        try:
            x, y = self.winfo_pointerxy()
            inside = self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width() and \
                self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height()
        except tk.TclError:
            return
        if not inside and self.hovered:
            self.hovered = False
            self._paint()

    def set_toggled(self, on):
        self.toggled = bool(on)
        self._paint()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.configure(cursor="hand2" if on else "")
        if not on:
            self.hovered = False
        self._paint()

    def set_text(self, text):
        if self.text_label is not None:
            self.text_label.configure(text=text)

    def set_compact(self, on):
        """Icon only (narrow windows); the tooltip still names the button."""
        if self.text_label is None or len(self.labels) < 2 or bool(on) == getattr(self, "_compact", False):
            return
        self._compact = bool(on)
        icon_lbl = self.labels[0]
        if on:
            self._text_pack = self.text_label.pack_info()
            self.text_label.pack_forget()
            self._icon_padx = icon_lbl.pack_info().get("padx")
            pad = icon_lbl.pack_info().get("padx")
            left = pad[0] if isinstance(pad, (tuple, list)) else pad
            icon_lbl.pack_configure(padx=(left, left))
        else:
            if self._icon_padx is not None:
                icon_lbl.pack_configure(padx=self._icon_padx)
            info = {k: v for k, v in self._text_pack.items() if k != "in"}
            self.text_label.pack(after=icon_lbl, **info)


class Check(tk.Label):
    """Checkbox drawn with an icon glyph so it matches the dark theme on every platform."""

    def __init__(self, master, value=False, command=None, bg=None, text=""):
        bg = bg or master.cget("bg")
        super().__init__(master, bg=bg, cursor="hand2", compound="left", font=FONTS["ui"], text=text, anchor="w")
        self.value, self.command, self.mixed = bool(value), command, False
        self.bind("<Button-1>", self._click)
        self._paint()

    def _paint(self):
        if HAS_ICONS:
            glyph = "\uE73A" if self.value else ("\uE73C" if self.mixed else "\uE739")
            font = FONTS["icon"]
        else:
            glyph = "\u2611" if self.value else ("\u25A3" if self.mixed else "\u2610")
            font = FONTS["ui"]
        color = C["accent"] if (self.value or self.mixed) else C["fg_muted"]
        if self.cget("text"):
            self.configure(text=f"{glyph}  {self._label}", fg=color)
        else:
            self.configure(text=glyph, font=font, fg=color)

    @property
    def _label(self):
        return getattr(self, "_text", "")

    def configure_label(self, text):
        self._text = text
        self._paint()

    def _click(self, _event=None):
        self.set(not self.value)
        if self.command:
            self.command(self.value)

    def set(self, value, mixed=False):
        self.value, self.mixed = bool(value), bool(mixed) and not value
        self._paint()


class ContextBar(tk.Frame):
    """Per-view toolbar shown under the tab strip.

    When the window is too narrow (or the labels are long, e.g. in Georgian) the buttons that don't fit are
    offered in a » menu at the end of the left side, so every command stays reachable.
    """

    def __init__(self, master, height=42):
        super().__init__(master, bg=C["bg"], height=px(height))
        self.pack_propagate(False)
        tk.Frame(self, bg=C["border"], height=1).pack(side="bottom", fill="x")
        self.right = tk.Frame(self, bg=C["bg"])                  # packed first: the right side never gets cut
        self.right.pack(side="right", fill="y", padx=(0, px(8)))
        self.left = tk.Frame(self, bg=C["bg"])
        self.left.pack(side="left", fill="y", padx=(px(8), 0))
        # a cover from the first button that does not fit to the end, with the » button on it: no half-cut
        # buttons are left peeking out
        self.cover = tk.Frame(self, bg=C["bg"])
        self.overflow = ToolButton(self.cover, "»", None, tooltip=None, bg=C["bg"], pad=(8, 4),
                                   menu=self._overflow_menu)
        self.overflow.pack(side="left", padx=(px(2), 0), pady=px(6))
        self._overflow_job = None
        self.left.bind("<Configure>", self._schedule_overflow, add="+")
        self.bind("<Configure>", self._schedule_overflow, add="+")

    def _schedule_overflow(self, _event=None):
        if self._overflow_job is None:
            self._overflow_job = self.after_idle(self._check_overflow)

    def _cut(self):
        """(x where the cover starts, buttons behind it), from the packed sizes - not the current mapping."""
        limit = self.left.winfo_width() - self.overflow.winfo_reqwidth() - px(4)
        hidden, x, start = [], 0, None
        for w in self.left.pack_slaves():
            try:
                pad = w.pack_info().get("padx", 0)
                left, right = (int(pad), int(pad)) if isinstance(pad, (int, str)) else (int(pad[0]), int(pad[1]))
            except (tk.TclError, ValueError, TypeError, IndexError):
                left = right = 0
            x0 = x + left
            x = x0 + w.winfo_reqwidth()
            if x > limit:
                if start is None:
                    start = min(x0, limit)
                if isinstance(w, ToolButton):
                    hidden.append(w)
            x += right
        return (limit if start is None else max(0, start)), hidden

    def _hidden_buttons(self):
        return self._cut()[1]

    def _clipped(self):
        return self.left.winfo_reqwidth() > self.left.winfo_width() + 1

    def _check_overflow(self):
        self._overflow_job = None
        try:
            if self.left.winfo_width() > 1 and self._clipped():
                start, _hidden = self._cut()
                self.cover.place(in_=self.left, x=start, y=0, relheight=1.0,
                                 width=max(self.overflow.winfo_reqwidth(), self.left.winfo_width() - start))
                self.cover.lift()
            else:
                self.cover.place_forget()
        except tk.TclError:
            pass

    def _overflow_menu(self, menu):
        for b in self._hidden_buttons():
            text = b.text_label.cget("text") if b.text_label is not None else ""
            text = text or getattr(b, "tooltip_text", "") or "…"
            if b.toggled:
                text = "✓ " + text
            state = "normal" if b.enabled else "disabled"
            if b.menu_builder:
                sub = popup_menu(menu)
                b.menu_builder(sub)
                menu.add_cascade(label=text, menu=sub, state=state)
            elif b.command:
                menu.add_command(label=text, command=b.command, state=state)

    def button(self, text="", icon_name=None, command=None, tooltip=None, side="left", **kw):
        parent = self.left if side == "left" else self.right
        kw.setdefault("pad", (8, 4))
        b = ToolButton(parent, text, icon_name, command, tooltip, bg=C["bg"], **kw)
        b.pack(side="left", padx=px(1), pady=px(6))
        return b

    def divider(self, side="left"):
        parent = self.left if side == "left" else self.right
        tk.Frame(parent, bg=C["border"], width=1, height=px(20)).pack(side="left", padx=px(6), pady=px(11))

    def label(self, text="", side="left", muted=True, **kw):
        parent = self.left if side == "left" else self.right
        lbl = tk.Label(parent, text=text, bg=C["bg"], fg=C["fg_muted"] if muted else C["fg_dim"],
                       font=kw.pop("font", FONTS["small"]), **kw)
        lbl.pack(side="left", padx=px(6))
        return lbl


class Toast:
    KINDS = {"success": ("check", "success"), "warning": ("warning", "warning"),
             "error": ("error", "danger"), "info": ("info", "accent")}

    def __init__(self, root):
        self.root = root
        self.frame = tk.Frame(root, bg=C["border_strong"])
        body = tk.Frame(self.frame, bg=C["panel"])
        body.pack(padx=1, pady=1)
        self.stripe = tk.Frame(body, width=px(3), bg=C["accent"])
        self.stripe.pack(side="left", fill="y")
        self.icon = tk.Label(body, bg=C["panel"])
        self.icon.pack(side="left", padx=(px(12), px(8)), pady=px(10))
        self.label = tk.Label(body, bg=C["panel"], fg=C["fg"], font=FONTS["ui"],
                              justify="left", wraplength=px(420))
        self.label.pack(side="left", padx=(0, px(16)), pady=px(10))
        self.job = None
        for w in (self.frame, body, self.icon, self.label):
            w.bind("<Button-1>", lambda e: self.hide())

    def show(self, message, kind="success", duration=2400):
        icon_name, color_key = self.KINDS.get(kind, self.KINDS["info"])
        glyph, gfont = icon(icon_name)
        color = C[color_key]
        self.stripe.configure(bg=color)
        self.icon.configure(text=glyph or "", font=gfont or FONTS["ui"], fg=color)
        self.label.configure(text=keys(message))
        self.frame.place(relx=1.0, rely=1.0, x=-px(20), y=-px(40), anchor="se")
        self.frame.lift()
        if self.job:
            self.root.after_cancel(self.job)
        self.job = self.root.after(duration, self.hide)

    def hide(self):
        self.job = None
        self.frame.place_forget()


class Spinner(tk.Frame):
    """Full-size loading overlay: the monkey looks around while a dashed ring turns (a plain ring without resvg)."""

    def __init__(self, parent, text="Loading…", bg=None):
        bg = bg or C["bg"]
        super().__init__(parent, bg=bg)
        from . import monkey
        self.monkey = monkey if (Image is not None and monkey.available()) else None
        size = px(76) if self.monkey else px(42)
        self.canvas = tk.Canvas(self, width=size, height=size, bg=bg, highlightthickness=0)
        self.canvas.place(relx=0.5, rely=0.44, anchor="center")
        self.label = tk.Label(self, text=T(text), bg=bg, fg=C["fg_dim"], font=FONTS["ui"])
        self.label.place(relx=0.5, rely=0.44, y=size // 2 + px(14), anchor="n")
        self.angle, self.job, self.size, self.frame = 90, None, size, 0
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        self._tick()

    def _monkey_frame(self):
        i = self.frame % self.monkey.FRAMES
        key = ("spinner", self.size, IS_DARK, i)     # shared image cache: rendered once per session
        if key not in _IMAGES:
            _IMAGES[key] = ImageTk.PhotoImage(self.monkey.render(self.monkey.spinner_svg(i, dark=IS_DARK), self.size))
        return _IMAGES[key]

    def _tick(self):
        c, s = self.canvas, self.size
        if self.monkey is not None:
            try:
                img = self._monkey_frame()
            except Exception:                       # resvg failed: fall back to the plain ring
                self.monkey = None
            else:
                c.delete("all")
                c.create_image(s // 2, s // 2, image=img)
                self.frame += 1
                self.job = self.after(45, self._tick)
                return
        w = px(4)
        c.delete("all")
        c.create_oval(w, w, s - w, s - w, outline=C["border_strong"], width=w)
        c.create_arc(w, w, s - w, s - w, start=self.angle, extent=110, style="arc",
                     outline=C["accent"], width=w)
        self.angle = (self.angle - 14) % 360
        self.job = self.after(28, self._tick)

    def set_text(self, text):
        self.label.configure(text=text)

    def close(self):
        if self.job:
            self.after_cancel(self.job)
            self.job = None
        self.destroy()


def styled_entry(parent, var=None, width=24, bg=None, font=None):
    """Entry inside a 1px border frame that lights up on focus. Returns (frame, entry)."""
    box = tk.Frame(parent, bg=C["input"], highlightthickness=1, highlightbackground=C["border_strong"],
                   highlightcolor=C["accent"])
    entry = tk.Entry(box, textvariable=var, width=width, font=font or FONTS["ui"], bg=bg or C["input"],
                     fg=C["fg"], insertbackground=C["fg"], relief="flat", bd=0, highlightthickness=0,
                     selectbackground=C["selection"], selectforeground=C["fg_bright"])
    entry.pack(fill="x", padx=px(8), pady=px(5))
    entry.bind("<FocusIn>", lambda e: box.configure(highlightbackground=C["accent"]), add="+")
    entry.bind("<FocusOut>", lambda e: box.configure(highlightbackground=C["border_strong"]), add="+")
    return box, entry


class Dialog(tk.Toplevel):
    """Small themed modal dialog."""

    def __init__(self, parent, title, min_width=380):
        top = parent.winfo_toplevel()
        super().__init__(top)
        self.withdraw()
        self.title(title)
        self.configure(bg=C["panel"])
        self.transient(top)
        self.resizable(False, False)
        self.result = None
        self.parent_top = top
        self.min_width = px(min_width)
        self.body = tk.Frame(self, bg=C["panel"], padx=px(20), pady=px(16))
        self.body.pack(side="top", fill="both", expand=True)
        tk.Frame(self, bg=C["border"], height=1).pack(side="top", fill="x")
        self.footer = tk.Frame(self, bg=C["chrome"], padx=px(14), pady=px(10))
        self.footer.pack(side="top", fill="x")
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def add_buttons(self, ok_text="OK", cancel_text="Cancel"):
        ok_text, cancel_text = T(ok_text), T(cancel_text)
        if cancel_text:
            ToolButton(self.footer, cancel_text, command=self.cancel, bg=C["chrome"],
                       pad=(14, 5)).pack(side="right", padx=(px(6), 0))
        ToolButton(self.footer, ok_text, command=self.ok, variant="primary", pad=(16, 5)).pack(side="right")

    def ok(self):
        self.result = self.collect()
        self.destroy()

    def collect(self):
        return True

    def cancel(self):
        self.result = None
        self.destroy()

    def run(self, focus=None):
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), self.min_width)
        h = self.winfo_reqheight()
        top = self.parent_top
        x = top.winfo_rootx() + (top.winfo_width() - w) // 2
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        winutil.apply_dark_titlebar(self, C["panel"], C["border"])
        try:
            self.grab_set()
        except tk.TclError:
            pass
        (focus or self).focus_set()
        self.wait_window()
        return self.result


def ask_string(parent, title, label, initial="", hint=None, multiline=False, ok_text="OK", width=44,
               secret=False):
    dlg = Dialog(parent, title)
    tk.Label(dlg.body, text=label, bg=C["panel"], fg=C["fg"], font=FONTS["ui"], anchor="w",
             justify="left").pack(fill="x", pady=(0, px(8)))
    if multiline:
        box = tk.Frame(dlg.body, bg=C["input"], highlightthickness=1, highlightbackground=C["accent"])
        box.pack(fill="both", expand=True)
        widget = tk.Text(box, width=width, height=6, font=FONTS["ui"], bg=C["input"], fg=C["fg"],
                         insertbackground=C["fg"], relief="flat", bd=0, wrap="word", padx=px(8),
                         pady=px(6), selectbackground=C["selection"], undo=True)
        widget.pack(fill="both", expand=True)
        widget.insert("1.0", initial)
        dlg.collect = lambda: widget.get("1.0", "end-1c")
        widget.bind(f"<{PRIMARY}-Return>", lambda e: (dlg.ok(), "break")[1])
    else:
        var = tk.StringVar(value=initial)
        box, widget = styled_entry(dlg.body, var, width=width)
        if secret:
            widget.configure(show="\u2022")
        box.pack(fill="x")
        widget.select_range(0, "end")
        dlg.collect = var.get
        widget.bind("<Return>", lambda e: dlg.ok())
    if hint:
        tk.Label(dlg.body, text=hint, bg=C["panel"], fg=C["fg_muted"], font=FONTS["small"], anchor="w",
                 justify="left").pack(fill="x", pady=(px(8), 0))
    dlg.add_buttons(ok_text)
    return dlg.run(widget)


def ask_choice(parent, title, label, options, initial=None, ok_text="OK"):
    """options: list of (value, text). Returns the chosen value or None."""
    dlg = Dialog(parent, title)
    tk.Label(dlg.body, text=label, bg=C["panel"], fg=C["fg"], font=FONTS["ui"], anchor="w",
             justify="left").pack(fill="x", pady=(0, px(8)))
    var = tk.StringVar(value=str(initial if initial is not None else options[0][0]))
    values = {str(v): v for v, _t in options}
    for value, text in options:
        tk.Radiobutton(dlg.body, text=text, value=str(value), variable=var, bg=C["panel"], fg=C["fg"],
                       selectcolor=C["input"], activebackground=C["panel"], activeforeground=C["fg_bright"],
                       font=FONTS["ui"], anchor="w", highlightthickness=0, bd=0).pack(fill="x", pady=px(2))
    dlg.collect = lambda: values.get(var.get())
    dlg.bind("<Return>", lambda e: dlg.ok())
    dlg.add_buttons(ok_text)
    return dlg.run()


# ─────────────────────────────── colour picker ───────────────────────────────
PALETTE = [
    # neutrals, then hues from light to dark (modern UI palette)
    ["#000000", "#374151", "#6b7280", "#9ca3af", "#d1d5db", "#e5e7eb", "#f3f4f6", "#ffffff"],
    ["#fecaca", "#fed7aa", "#fef08a", "#bbf7d0", "#a5f3fc", "#bfdbfe", "#ddd6fe", "#fbcfe8"],
    ["#f87171", "#fb923c", "#facc15", "#4ade80", "#22d3ee", "#60a5fa", "#a78bfa", "#f472b6"],
    ["#dc2626", "#ea580c", "#ca8a04", "#16a34a", "#0891b2", "#2563eb", "#7c3aed", "#db2777"],
    ["#991b1b", "#9a3412", "#854d0e", "#166534", "#155e75", "#1e40af", "#5b21b6", "#9d174d"],
]


def pick_color(settings, anchor, current, on_pick, x=None, y=None, eyedropper=None):
    """The one colour chooser used everywhere: opens ColorPicker and remembers the colour among the recent ones."""
    def picked(color):
        recent = [color] + [c for c in settings.get("recent_colors", []) if c != color]
        settings["recent_colors"] = recent[:8]
        try:
            settings.save()
        except OSError:
            pass
        on_pick(color)
    return ColorPicker(anchor, current, picked, recent=settings.get("recent_colors", []), x=x, y=y,
                       eyedropper=eyedropper)


class ColorPicker(tk.Toplevel):
    """Pop-up colour chooser: a saturation/brightness field with a hue strip, a palette, recently used colours,
    hex entry, the system colour dialog and an eyedropper that takes a colour from the document."""

    SV_W, SV_H, HUE_W = 216, 132, 16

    def __init__(self, anchor, current, on_pick, recent=(), x=None, y=None, eyedropper=None):
        super().__init__(anchor)
        self.withdraw()
        self.overrideredirect(True)
        import colorsys
        self._colorsys = colorsys
        self.on_pick, self.eyedropper = on_pick, eyedropper
        self.current = (current or "#000000").lower()
        r, g, b = (int(self.current[i:i + 2], 16) / 255 for i in (1, 3, 5))
        self.h, self.s, self.v = colorsys.rgb_to_hsv(r, g, b)
        outer = tk.Frame(self, bg=C["border_strong"], padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        body = tk.Frame(outer, bg=C["panel"], padx=px(10), pady=px(10))
        body.pack(fill="both", expand=True)

        top = tk.Frame(body, bg=C["panel"])
        top.pack(fill="x")
        self.sv = tk.Canvas(top, width=px(self.SV_W), height=px(self.SV_H), highlightthickness=1,
                            highlightbackground=C["border"], cursor="crosshair", bd=0)
        self.sv.pack(side="left")
        self.hue = tk.Canvas(top, width=px(self.HUE_W), height=px(self.SV_H), highlightthickness=1,
                             highlightbackground=C["border"], cursor="sb_v_double_arrow", bd=0)
        self.hue.pack(side="left", padx=(px(8), 0))
        for ev in ("<Button-1>", "<B1-Motion>"):
            self.sv.bind(ev, self._on_sv)
            self.hue.bind(ev, self._on_hue)
        self.sv.bind("<Double-Button-1>", lambda e: self._pick(self.current))
        self._draw_hue()
        self._draw_sv()

        grid = tk.Frame(body, bg=C["panel"])
        grid.pack(fill="x", pady=(px(10), 0))
        size = px(18)
        for r_, row in enumerate(PALETTE):
            for c_, color in enumerate(row):
                self._swatch(grid, color, size).grid(row=r_, column=c_, padx=px(2), pady=px(2))
        recent = [c for c in recent if c][:8]
        if recent:
            tk.Label(body, text=T("Recent"), font=FONTS["caption"], bg=C["panel"], fg=C["fg_muted"],
                     anchor="w").pack(fill="x", pady=(px(6), px(2)))
            rec = tk.Frame(body, bg=C["panel"])
            rec.pack(fill="x")
            for c_, color in enumerate(recent):
                self._swatch(rec, color, size).grid(row=0, column=c_, padx=px(2), pady=px(2))

        bottom = tk.Frame(body, bg=C["panel"])
        bottom.pack(fill="x", pady=(px(10), 0))
        self.preview = tk.Frame(bottom, width=px(26), height=px(26), bg=self.current, highlightthickness=1,
                                highlightbackground=C["border_strong"])
        self.preview.pack(side="left")
        self.hex_var = tk.StringVar(value=self.current)
        box, entry = styled_entry(bottom, self.hex_var, width=8, font=FONTS["mono"])
        box.pack(side="left", padx=px(6))
        entry.bind("<Return>", lambda e: self._from_hex())
        self._typing = True
        self.hex_var.trace_add("write", lambda *_: self._preview_hex())
        ToolButton(bottom, T("OK"), None, self._from_hex, variant="primary", pad=(10, 3)).pack(side="right")
        tools = tk.Frame(body, bg=C["panel"])
        tools.pack(fill="x", pady=(px(6), 0))
        if eyedropper is not None:
            ToolButton(tools, T("Pick from document"), "pipette" if "pipette" in GLYPHS else None,
                       self._eyedropper, T("Click this, then click anywhere on the page to take its colour"),
                       bg=C["panel"], hover=C["hover_strong"], pad=(8, 3)).pack(side="left")
        ToolButton(tools, T("More colours\u2026"), None, self._system_dialog, bg=C["panel"],
                   hover=C["hover_strong"], pad=(8, 3)).pack(side="right")

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<FocusOut>", self._focus_out)
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = anchor.winfo_rootx() if x is None else x
        y = anchor.winfo_rooty() + anchor.winfo_height() + px(4) if y is None else y
        x = max(0, min(x, self.winfo_screenwidth() - w - 4))
        y = max(0, min(y, self.winfo_screenheight() - h - 4))
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()
        entry.focus_set()
        entry.select_range(0, "end")

    # ── drawing ──
    def _image(self, img):
        from PIL import ImageTk
        return ImageTk.PhotoImage(img)

    def _draw_hue(self):
        from PIL import Image
        w, h = px(self.HUE_W), px(self.SV_H)
        img = Image.new("RGB", (1, h))
        for y in range(h):
            r, g, b = self._colorsys.hsv_to_rgb(y / max(1, h - 1), 1, 1)
            img.putpixel((0, y), (int(r * 255), int(g * 255), int(b * 255)))
        self._hue_img = self._image(img.resize((w, h)))
        self.hue.delete("all")
        self.hue.create_image(0, 0, image=self._hue_img, anchor="nw")
        y = self.h * (h - 1)
        self.hue.create_rectangle(0, y - 2, w, y + 2, outline="#ffffff", width=2, tags="mark")

    def _draw_sv(self):
        from PIL import Image
        w, h = px(self.SV_W), px(self.SV_H)
        if getattr(self, "_sv_hue", None) != self.h:
            small = Image.new("RGB", (64, 40))
            for yy in range(40):
                for xx in range(64):
                    r, g, b = self._colorsys.hsv_to_rgb(self.h, xx / 63, 1 - yy / 39)
                    small.putpixel((xx, yy), (int(r * 255), int(g * 255), int(b * 255)))
            self._sv_img = self._image(small.resize((w, h), Image.BILINEAR))
            self._sv_hue = self.h
        self.sv.delete("all")
        self.sv.create_image(0, 0, image=self._sv_img, anchor="nw")
        x, y = self.s * (w - 1), (1 - self.v) * (h - 1)
        ring = "#000000" if self.v > 0.6 and self.s < 0.5 else "#ffffff"
        self.sv.create_oval(x - 6, y - 6, x + 6, y + 6, outline=ring, width=2)

    # ── interaction ──
    def _set_from_hsv(self):
        r, g, b = self._colorsys.hsv_to_rgb(self.h, self.s, self.v)
        color = "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
        self.current = color
        self._typing = False
        self.hex_var.set(color)
        self._typing = True
        self.preview.configure(bg=color)

    def _on_sv(self, event):
        w, h = px(self.SV_W), px(self.SV_H)
        self.s = min(1, max(0, event.x / max(1, w - 1)))
        self.v = 1 - min(1, max(0, event.y / max(1, h - 1)))
        self._set_from_hsv()
        self._draw_sv()

    def _on_hue(self, event):
        h = px(self.SV_H)
        self.h = min(1, max(0, event.y / max(1, h - 1)))
        self._set_from_hsv()
        self._draw_hue()
        self._draw_sv()

    def _swatch(self, parent, color, size):
        selected = color.lower() == self.current
        f = tk.Frame(parent, width=size, height=size, bg=color, cursor="hand2", highlightthickness=2,
                     highlightbackground=C["accent"] if selected else C["border"],
                     highlightcolor=C["accent"] if selected else C["border"])
        f.bind("<Button-1>", lambda e, c=color: self._pick(c))
        f.bind("<Enter>", lambda e: f.configure(highlightbackground=C["fg_bright"]))
        f.bind("<Leave>", lambda e: f.configure(highlightbackground=C["accent"] if selected else C["border"]))
        Tooltip([f], color.upper())
        return f

    def _valid(self, text):
        text = text.strip().lower()
        if not text.startswith("#"):
            text = "#" + text
        if len(text) == 4 and all(ch in "0123456789abcdef" for ch in text[1:]):
            text = "#" + "".join(ch * 2 for ch in text[1:])
        if len(text) == 7 and all(ch in "0123456789abcdef" for ch in text[1:]):
            return text
        return None

    def _preview_hex(self):
        if not self._typing:
            return
        color = self._valid(self.hex_var.get())
        if color:
            self.current = color
            self.preview.configure(bg=color)
            r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
            self.h, self.s, self.v = self._colorsys.rgb_to_hsv(r, g, b)
            self._draw_hue()
            self._draw_sv()

    def _from_hex(self):
        color = self._valid(self.hex_var.get())
        if color:
            self._pick(color)
        else:
            self.bell()

    def _eyedropper(self):
        callback = self.eyedropper
        self.destroy()
        callback()

    def _system_dialog(self):
        from tkinter import colorchooser
        self.unbind("<FocusOut>")
        result = colorchooser.askcolor(color=self.current, parent=self.master, title=T("Colour"))
        if result and result[1]:
            self._pick(result[1].lower())
        else:
            self.destroy()

    def _focus_out(self, _event):
        def check():
            if not self.winfo_exists():
                return
            focus = self.focus_get()
            if focus is None or not str(focus).startswith(str(self)):
                self.destroy()
        self.after(150, check)

    def _pick(self, color):
        self.destroy()
        self.on_pick(color.lower())
