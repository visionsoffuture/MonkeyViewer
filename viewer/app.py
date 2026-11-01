"""Main window: toolbar, sidebar, tabs, welcome screen, status bar, file dispatch."""

import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from itertools import count
from tkinter import filedialog, messagebox

from . import app_info, audit, formats, policy, safeio, theme, winutil
from .theme import C, FONTS, ToolButton, Tooltip, px
from . import i18n
from .i18n import T

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = TkinterDnD = None

APP_NAME = winutil.APP_NAME
# after a language change the question is asked in the new language: (title, question, "later" note)
RESTART_TEXTS = {
    "ka": ("ენა", "ახალი ენა ჩაირთვება Monkey Viewer-ის გადატვირთვის შემდეგ.\n\nგადავტვირთოთ ახლა?",
           "ენა შეიცვლება Monkey Viewer-ის შემდეგ გახსნაზე."),
    "en": ("Language", "The new language is used after Monkey Viewer restarts.\n\nRestart Monkey Viewer now?",
           "The language changes the next time you open Monkey Viewer."),
}
SHIFT_MASK, CONTROL_MASK = 0x0001, 0x0004
if theme.IS_MAC:
    PRIMARY_MASK, ALT_MASK = 0x0008, 0x0010          # Command, Option
else:
    PRIMARY_MASK = CONTROL_MASK
    ALT_MASK = 0x20000 if theme.IS_WIN else 0x0008

if theme.IS_WIN:
    _KEYCODES = {code: chr(code + 32) for code in range(65, 91)}
    _KEYCODES.update({9: "tab", 48: "0", 96: "0", 187: "plus", 107: "plus", 189: "minus", 109: "minus"})
elif theme.IS_MAC:
    # macOS virtual key codes (kVK_ANSI_*): the physical key, whatever input source is active
    _KEYCODES = {0: "a", 11: "b", 8: "c", 2: "d", 14: "e", 3: "f", 5: "g", 4: "h", 40: "k", 45: "n", 31: "o",
                 35: "p", 1: "s", 17: "t", 9: "v", 13: "w", 7: "x", 16: "y", 6: "z", 48: "tab", 29: "0",
                 24: "plus", 27: "minus"}
else:
    _KEYCODES = {38: "a", 56: "b", 54: "c", 40: "d", 26: "e", 41: "f", 42: "g", 43: "h", 45: "k", 57: "n",
                 32: "o", 33: "p", 39: "s", 28: "t", 55: "v", 25: "w", 53: "x", 29: "y", 52: "z",
                 23: "tab", 19: "0", 21: "plus", 20: "minus"}


# Georgian (QWERTY) letters -> the Latin key they share, so Ctrl/Cmd shortcuts work in Georgian too
GEORGIAN_KEYS = dict(zip("\u10d0\u10d1\u10ea\u10d3\u10d4\u10e4\u10d2\u10f0\u10d8\u10ef\u10d9\u10da\u10db"
                         "\u10dc\u10dd\u10de\u10e5\u10e0\u10e1\u10e2\u10e3\u10d5\u10ec\u10ee\u10e7\u10d6",
                         "abcdefghijklmnopqrstuvwxyz"))
GEORGIAN_KEYS.update(dict(zip("\u10ed\u10e6\u10d7\u10e8\u10df\u10eb\u10e9", "wrtsjzc")))


def _mac_virtual_key(keycode):
    """Tk 8.6.11+ packs the virtual key code into the top byte; older builds into bits 16-23."""
    if keycode >= 1 << 24:
        return (keycode >> 24) & 0xFF
    if keycode >= 1 << 16:
        return (keycode >> 16) & 0xFF
    return None


def shortcut_key(event):
    """Latin key name for a Ctrl (Cmd on a Mac) shortcut, independent of the active keyboard layout."""
    keysym = event.keysym
    if keysym in ("Tab", "ISO_Left_Tab"):
        return "tab"
    if keysym in ("equal", "plus", "KP_Add"):
        return "plus"
    if keysym in ("minus", "underscore", "KP_Subtract"):
        return "minus"
    if keysym in ("0", "KP_0", "parenright"):
        return "0"
    if len(keysym) == 1 and keysym.isascii() and keysym.isalpha():
        return keysym.lower()
    char = getattr(event, "char", "") or ""
    if char in GEORGIAN_KEYS:
        return GEORGIAN_KEYS[char]
    if theme.IS_MAC:
        return _KEYCODES.get(_mac_virtual_key(event.keycode or 0))
    return _KEYCODES.get(event.keycode)


def tab_class(kind):
    if kind == "text":
        from .text_view import TextTab
        return TextTab
    if kind == "image":
        from .image_view import ImageTab
        return ImageTab
    if kind == "svg":
        from .svg_view import SvgTab
        return SvgTab
    if kind == "pdf":
        from .pdf_edit import PdfTab
        return PdfTab
    if kind == "document":
        from .pdf_view import DocumentTab
        return DocumentTab
    if kind == "dxf":
        from .cad_view import DxfTab
        return DxfTab
    if kind == "dwg":
        from .cad_view import DwgTab
        return DwgTab
    if kind == "map":
        from .map_view import MapTab
        return MapTab
    if kind == "table":
        from .table_view import TableTab
        return TableTab
    if kind == "hex":
        from .hex_view import HexTab
        return HexTab
    if kind == "crypto":
        from .crypto_view import CryptoTab
        return CryptoTab
    if kind == "cert":
        from .crypto_view import CertTab
        return CertTab
    if kind == "djvu":
        from .pdf_view import DjvuTab
        return DjvuTab
    from .info_view import InfoTab
    return InfoTab


# ─────────────────────────────── Tab strip ───────────────────────────────
class TabChip(tk.Frame):
    def __init__(self, bar, tab):
        super().__init__(bar.inner, bg=C["chrome"])
        self.bar, self.tab, self.app = bar, tab, bar.app
        self.hover = self.close_hover = False
        tk.Frame(self, bg=C["border"], width=1).pack(side="right", fill="y")
        self.topline = tk.Frame(self, bg=C["chrome"], height=px(2))
        self.topline.pack(side="top", fill="x")
        self.body = tk.Frame(self, bg=C["chrome"])
        self.body.pack(side="top", fill="both", expand=True)
        self.icon = tk.Label(self.body, bg=C["chrome"])
        self.icon.pack(side="left", padx=(px(12), px(7)))
        self.name = tk.Label(self.body, font=FONTS["ui"], bg=C["chrome"])
        self.name.pack(side="left")
        self.close_box = tk.Frame(self.body, width=px(22), height=px(22), bg=C["chrome"])
        self.close_box.pack_propagate(False)
        self.close_box.pack(side="left", padx=(px(10), px(8)))
        self.close = tk.Label(self.close_box, bg=C["chrome"], cursor="hand2")
        self.close.pack(fill="both", expand=True)
        parts = (self, self.topline, self.body, self.icon, self.name, self.close_box)
        for w in parts:
            w.bind("<ButtonPress-1>", lambda e: self.app.select_tab(self.tab))
            theme.bind_middle_release(w, lambda e: self.app.close_tab(self.tab))
            theme.bind_right(w, lambda e: self.app.show_tab_menu(e, self.tab))
        for w in parts + (self.close,):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<MouseWheel>", bar.on_wheel)
        self.close.bind("<Enter>", lambda e: self._set_close_hover(True), add="+")
        self.close.bind("<Leave>", lambda e: self._set_close_hover(False), add="+")
        self.close.bind("<ButtonRelease-1>", self._on_close_click)
        Tooltip(list(parts), lambda: self.tab.path or T("Unsaved file"))
        self.render()

    def _on_enter(self, _event):
        if not self.hover:
            self.hover = True
            self.render()

    def _on_leave(self, event):
        if theme.pointer_inside(self, event):
            return
        self.hover = self.close_hover = False
        self.render()

    def _set_close_hover(self, on):
        self.close_hover = on
        self.render()

    def _on_close_click(self, event):
        if theme.pointer_inside(self.close, event):
            self.app.close_tab(self.tab)
        return "break"

    def render(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        active = self.app.active is self.tab
        if active:
            bg, fg, line = C["bg"], C["fg_bright"], C["accent"]
        elif self.hover:
            bg, fg, line = C["tab_hover"], C["fg"], C["tab_hover"]
        else:
            bg, fg, line = C["chrome"], C["fg_dim"], C["chrome"]
        for w in (self, self.body, self.icon, self.name, self.close_box):
            w.configure(bg=bg)
        self.topline.configure(bg=line)
        self.icon.configure(image=self.tab.badge())
        self.name.configure(text=self.tab.title, fg=fg)
        close_bg = C["hover_strong"] if self.close_hover else bg
        if self.tab.dirty and not self.close_hover:
            self.close.configure(text="●", font=FONTS["dot"], bg=close_bg,
                                 fg=C["fg"] if active else C["fg_dim"])
        elif active or self.hover:
            glyph, gfont = (theme.GLYPHS["close"], FONTS["icon_xs"]) if theme.HAS_ICONS else ("✕", FONTS["small"])
            self.close.configure(text=glyph, font=gfont, bg=close_bg,
                                 fg=C["fg_bright"] if self.close_hover else C["fg_dim"])
        else:
            self.close.configure(text="", bg=bg)


class TabBar(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=C["chrome"])
        self.app = app
        self.chips = {}
        self.height = px(40)
        self.canvas = tk.Canvas(self, bg=C["chrome"], height=self.height, highlightthickness=0, bd=0,
                                xscrollincrement=px(48))
        self.canvas.pack(fill="x")
        self.inner = tk.Frame(self.canvas, bg=C["chrome"])
        self.canvas.create_window(0, 0, window=self.inner, anchor="nw", height=self.height)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=(0, 0, e.width, self.height)))
        for w in (self.canvas, self.inner):
            w.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Double-Button-1>", lambda e: app.new_file())

    def on_wheel(self, event):
        if self.inner.winfo_width() > self.canvas.winfo_width():
            self.canvas.xview_scroll(theme.wheel_units(event, 1), "units")
        return "break"

    def add(self, tab):
        chip = TabChip(self, tab)
        chip.pack(side="left", fill="y")
        self.chips[tab.id] = chip

    def remove(self, tab):
        chip = self.chips.pop(tab.id, None)
        if chip:
            chip.destroy()

    def reorder(self, tabs):
        for chip in self.chips.values():
            chip.pack_forget()
        for tab in tabs:
            chip = self.chips.get(tab.id)
            if chip:
                chip.pack(side="left", fill="y")

    def refresh(self, tab=None):
        chips = [self.chips.get(tab.id)] if tab else list(self.chips.values())
        for chip in chips:
            if chip:
                chip.render()

    def ensure_visible(self, tab):
        chip = self.chips.get(tab.id)
        if not chip:
            return
        self.update_idletasks()
        total, view = self.inner.winfo_width(), self.canvas.winfo_width()
        if total <= view:
            self.canvas.xview_moveto(0)
            return
        x0 = chip.winfo_x()
        x1 = x0 + chip.winfo_width()
        left = self.canvas.canvasx(0)
        if x0 < left:
            self.canvas.xview_moveto(x0 / total)
        elif x1 > left + view:
            self.canvas.xview_moveto((x1 - view) / total)


# ─────────────────────────────── Find bar ───────────────────────────────
class FindBar(tk.Frame):
    def __init__(self, app):
        super().__init__(app.editor_area, bg=C["border_strong"])
        self.app = app
        self.visible = self.case = self._suppress = False
        self.tab = None
        body = tk.Frame(self, bg=C["panel"])
        body.pack(padx=1, pady=1)
        glyph, gfont = theme.icon("find")
        if glyph:
            tk.Label(body, text=glyph, font=gfont, bg=C["panel"], fg=C["fg_muted"]).pack(side="left", padx=(px(12), 0))
        self.var = tk.StringVar()
        box, self.entry = theme.styled_entry(body, self.var, width=28)
        box.pack(side="left", padx=(px(8), px(6)), pady=px(7))
        self.case_btn = ToolButton(body, T("Aa"), command=self.toggle_case, tooltip=T("Match case"), bg=C["panel"],
                                   hover=C["hover_strong"], pad=(8, 4))
        self.case_btn.pack(side="left")
        self.count_lbl = tk.Label(body, text="", width=11, anchor="w", font=FONTS["small"], bg=C["panel"],
                                  fg=C["fg_muted"])
        self.count_lbl.pack(side="left", padx=(px(8), px(4)))
        for name, tip, cmd in (("up", T("Previous  (Shift+Enter)"), lambda: self.step(-1)),
                               ("down", T("Next  (Enter)"), lambda: self.step(1)),
                               ("close", T("Close  (Esc)"), self.hide)):
            ToolButton(body, "", name, cmd, tip, bg=C["panel"], hover=C["hover_strong"], pad=(7, 4)).pack(
                side="left", padx=(0, px(6) if name == "close" else px(2)))
        self.var.trace_add("write", lambda *_: None if self._suppress else self.search("jump"))
        e = self.entry
        e.bind("<Return>", lambda ev: (self.step(1), "break")[1])
        e.bind("<KP_Enter>", lambda ev: (self.step(1), "break")[1])
        e.bind("<Shift-Return>", lambda ev: (self.step(-1), "break")[1])
        e.bind("<Escape>", lambda ev: (self.hide(), "break")[1])

    def show(self):
        tab = self.app.active
        if tab is None or not tab.searchable:
            return
        if self.tab is not tab and self.tab is not None and self.tab.alive:
            self.tab.find_clear()
        self.tab = tab
        initial = tab.find_initial()
        if initial:
            self._suppress = True
            self.var.set(initial)
            self._suppress = False
        self.place(relx=1.0, x=-px(26), y=px(52), anchor="ne")
        self.lift()
        self.visible = True
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self.entry.icursor("end")
        self.search("jump" if initial else "none")

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.place_forget()
        if self.tab is not None and self.tab.alive:
            self.tab.find_clear(commit=True)
            if self.tab is self.app.active:
                self.tab.focus()
        self.tab = None

    def switch_to(self, tab):
        if not self.visible:
            return
        if self.tab is not None and self.tab.alive:
            self.tab.find_clear()
        if tab is None or not tab.searchable:
            self.visible = False
            self.place_forget()
            self.tab = None
            return
        self.tab = tab
        self.lift()
        self.search("none")

    def toggle_case(self):
        self.case = not self.case
        self.case_btn.set_toggled(self.case)
        self.search("jump")

    def search(self, mode="jump"):
        if self.tab is None or not self.tab.alive:
            return
        cur, total = self.tab.find_update(self.var.get(), self.case, mode)
        self._update_count(cur, total)

    def refresh(self):
        if self.visible:
            self.search("keep")

    def step(self, direction):
        if self.tab is None:
            return
        cur, total = self.tab.find_step(direction)
        if total == 0 and self.var.get():
            cur, total = self.tab.find_update(self.var.get(), self.case, "jump")
        self._update_count(cur, total)

    def _update_count(self, cur, total):
        if not self.var.get():
            text, color = "", C["fg_muted"]
        elif total == 0:
            text, color = T("No results"), C["danger"]
        elif cur >= 0:
            text, color = f"{cur + 1} of {total}", C["fg_dim"]
        else:
            text, color = f"{total} found", C["fg_dim"]
        self.count_lbl.configure(text=text, fg=color)


# ─────────────────────────────── Application ───────────────────────────────
class App:
    def __init__(self, root, files=(), instance=None):
        self.root = root
        self.instance = instance
        self.settings = winutil.Settings()
        i18n.setup(self.settings.get("language", "auto"))      # before any text is built
        theme.set_mode(self.settings.get("theme", "auto"))     # before any colour is used
        theme.init(root)
        self._install_write_guards()
        size = int(self.settings.get("code_size", theme.CODE_SIZE))
        theme.CODE_FONT.configure(size=size)
        theme.CODE_FONT_ITALIC.configure(size=size)
        self.tabs, self.active = [], None
        self._ids, self._untitled = count(1), count(1)
        self.page_clipboard = None
        self.last_dir = self.settings.get("last_dir") or os.path.expanduser("~")
        self.sidebar_visible = bool(self.settings.get("sidebar", True))
        self.dnd = bool(TkinterDnD) and hasattr(root, "drop_target_register")
        self._results = queue.Queue()
        self._pending = 0
        self._poll_job = None
        self._incoming = list(files)
        self._incoming_at = time.monotonic()
        self._incoming_wake = bool(files)
        self._incoming_raise = False
        self._batch, self._batch_at = [], 0.0
        self._welcome_shown = False
        self.overlay = None

        self._build_window()
        self.menubar = None
        if not theme.IS_MAC:
            from .menubar import MenuBar
            self.menubar = MenuBar(self, root)
            if self.settings.get("menubar", True):
                self.menubar.pack(side="top", fill="x")
        self._build_toolbar()
        self._build_statusbar()
        self._build_body()
        self.toast = theme.Toast(root)
        self.find = FindBar(self)
        self._native = None
        self._last_shortcut = 0.0
        root.bind_all(f"<{theme.PRIMARY}-KeyPress>", self.on_ctrl_key)
        root.bind_all("<F1>", lambda e: (self.open_user_guide(), "break")[1])
        if not theme.IS_MAC:
            root.bind_all("<F11>", lambda e: (self.toggle_fullscreen(), "break")[1])
            root.bind_all("<Alt-KeyPress>", self.on_alt_key)
            root.bind_all("<F10>", lambda e: (self.menubar.post("file"), "break")[1])
        if theme.IS_MAC:     # Control-Tab switches tabs on a Mac as well
            root.bind_all("<Control-Tab>", lambda e: (self.cycle_tab(1), "break")[1])
            root.bind_all("<Control-Shift-Tab>", lambda e: (self.cycle_tab(-1), "break")[1])
            self._build_mac_menubar()
            root.createcommand("::tk::mac::OpenDocument", self.receive_files)
            root.createcommand("::tk::mac::ReopenApplication", self.bring_to_front)
            root.createcommand("tk::mac::Quit", self.on_close)
        root.report_callback_exception = self._on_tk_error
        for w in (root, self.editor_area, self.welcome):
            self.register_drop(w)
        self._show_welcome()
        self.refresh_sidebar()
        self.update_status()
        self.update_title()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.update_idletasks()
        winutil.apply_dark_titlebar(root, C["chrome"], C["border"])
        root.after(500, lambda: winutil.apply_dark_titlebar(root, C["chrome"], C["border"]))   # once really shown
        root.after(60, self._poll_incoming)

    # ── window chrome ──
    def _build_window(self):
        r = self.root
        r.title(APP_NAME)
        r.configure(bg=C["chrome"])
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w, h = min(px(1280), sw - px(40)), min(px(820), sh - px(80))
        geo = self.settings.get("geometry")
        if isinstance(geo, list) and len(geo) == 4 and geo[2] > 300 and geo[3] > 200 \
                and -50 < geo[0] < sw - 100 and -20 < geo[1] < sh - 100:
            r.geometry("%dx%d+%d+%d" % (geo[2], geo[3], geo[0], geo[1]))
        else:
            r.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - px(20))}")
        r.minsize(px(640), px(420))
        if self.settings.get("maximized") and theme.IS_WIN:
            r.state("zoomed")
        ico = winutil.resource_path("monkeyviewer.ico")
        try:
            if theme.IS_WIN and os.path.exists(ico):
                r.iconbitmap(default=ico)
            elif theme.IS_MAC and winutil.FROZEN:
                pass                      # the .app bundle's own icon is used in the Dock
            else:
                r.iconphoto(True, theme.logo_image(64, plate=True), theme.logo_image(32, plate=True))
        except tk.TclError:
            pass

    @staticmethod
    def _divider(parent):
        tk.Frame(parent, bg=C["border"], width=1, height=px(22)).pack(side="left", padx=px(8))

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=C["chrome"], height=px(52))
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.toolbar = bar
        tk.Frame(self.root, bg=C["border"], height=1).pack(side="top", fill="x")
        right = tk.Frame(bar, bg=C["chrome"])        # packed first: stays visible in a narrow window
        right.pack(side="right", fill="y", padx=(0, px(8)))
        left = tk.Frame(bar, bg=C["chrome"])
        left.pack(side="left", fill="y", padx=(px(6), 0))
        from .menubar import MenuModel
        self.menu_model = MenuModel(self)
        ToolButton(left, "", "menu", tooltip=T("Menu"), menu=self.menu_model.fill_app_menu, pad=(10, 6)).pack(
            side="left")
        brand = tk.Frame(left, bg=C["chrome"], cursor="hand2")
        brand.pack(side="left", padx=(px(6), px(10)))
        tk.Label(brand, image=theme.logo_image(px(24), plate=True), bg=C["chrome"]).pack(side="left")
        self.brand_name = tk.Label(brand, text=APP_NAME, font=FONTS["brand"], bg=C["chrome"], fg=C["fg_bright"])
        self.brand_name.pack(side="left", padx=(px(9), 0))
        for w in (brand, *brand.winfo_children()):
            w.bind("<Button-1>", lambda e: self.show_home())
        self._divider(left)
        self.open_btn = ToolButton(left, T("Open"), "open", self.open_dialog, T("Open files  (Ctrl+O)"),
                                   variant="primary")
        self.open_btn.pack(side="left", padx=px(2))
        self.new_btn = ToolButton(left, T("New"), "new", self.new_file, T("New text file  (Ctrl+N)"))
        self.new_btn.pack(side="left", padx=px(2))
        self._divider(left)
        self.save_btn = ToolButton(left, T("Save"), "save", self.save_active, T("Save  (Ctrl+S)"))
        self.save_btn.pack(side="left", padx=px(2))
        self.saveas_btn = ToolButton(left, T("Save As"), "saveas", lambda: self.save_active(True),
                                     T("Save as  (Ctrl+Shift+S)"))
        self.saveas_btn.pack(side="left", padx=px(2))
        self.calc_btn = ToolButton(right, "", "calc", self.show_calculator, T("Calculator  (Ctrl+Shift+K)"),
                                   pad=(8, 6))
        self.calc_btn.pack(side="left", padx=(0, px(2)))
        self.find_btn = ToolButton(right, T("Find"), "find", self.find_show, T("Find  (Ctrl+F)"))
        self.find_btn.pack(side="left")
        ToolButton(right, "", "more", tooltip=T("More"), menu=self._more_menu, pad=(8, 6)).pack(side="left", padx=px(2))
        self._toolbar_parts = (left, right)
        self._toolbar_level = 0
        self._fit_job = None
        bar.bind("<Configure>", lambda e: self._schedule_fit())

    # ── narrow windows: everything stays reachable ──
    def _schedule_fit(self):
        if self._fit_job is None:
            self._fit_job = self.root.after(40, self._fit_window)

    def _set_toolbar_level(self, level):
        """0: full; 1: Save / Save As / New / Find as icons; 2: Open as an icon, no app name."""
        self._toolbar_level = level
        for btn in (self.new_btn, self.save_btn, self.saveas_btn, self.find_btn):
            btn.set_compact(level >= 1)
        self.open_btn.set_compact(level >= 2)
        if level >= 2:
            self.brand_name.pack_forget()
        elif not self.brand_name.winfo_ismapped():
            self.brand_name.pack(side="left", padx=(px(9), 0))

    def _fit_window(self):
        self._fit_job = None
        try:
            width = self.toolbar.winfo_width()
        except tk.TclError:
            return
        if width <= 1:
            return
        left, right = self._toolbar_parts
        level = 0
        self._set_toolbar_level(0)
        self.toolbar.update_idletasks()
        while level < 2 and left.winfo_reqwidth() + right.winfo_reqwidth() + px(24) > width:
            level += 1
            self._set_toolbar_level(level)
            self.toolbar.update_idletasks()
        # the file list gives way to the document in a narrow window and comes back when there is room
        root_w = self.root.winfo_width()
        if self.sidebar_visible and root_w < px(820):
            self._sidebar_auto_hidden = True
            self._show_sidebar(False)
        elif getattr(self, "_sidebar_auto_hidden", False) and root_w >= px(900):
            self._sidebar_auto_hidden = False
            self._show_sidebar(True)

    def _more_menu(self, m):
        has_path = self.active is not None and bool(self.active.path) and os.path.exists(self.active.path)
        m.add_command(label=T("Open file location") if not theme.IS_MAC else T("Show in Finder"),
                      state="normal" if has_path else "disabled", command=lambda: self.reveal(self.active))
        m.add_separator()
        if not policy.get_bool("DisableAssociationChanges"):
            m.add_command(label=T("File associations\u2026"), command=self.show_associations)
            m.add_command(label=T('Remove all associations'), command=self.unregister_types)
            m.add_separator()
        m.add_command(label=T("Components & diagnostics\u2026"), command=self.show_diagnostics)
        m.add_separator()
        lang = theme.popup_menu(m)
        self._lang_var = tk.StringVar(master=lang, value=self.settings.get("language", "auto"))
        forced = "Language" in policy.active()
        for value, text in (("auto", T("Same as the computer")), ("ka", "ქართული"), ("en", "English")):
            lang.add_radiobutton(label=text, value=value, variable=self._lang_var,
                                 state="disabled" if forced else "normal",
                                 command=lambda v=value: self.set_language(v))
        m.add_cascade(label=T("Language") + ("  \u00b7  " + T("set by your administrator") if forced else ""),
                      menu=lang)
        look = theme.popup_menu(m)
        self._theme_var = tk.StringVar(master=look, value=self.settings.get("theme", "auto"))
        for value, text in (("auto", T("Same as the computer")), ("light", T("Light")), ("dark", T("Dark"))):
            look.add_radiobutton(label=text, value=value, variable=self._theme_var,
                                 command=lambda v=value: self.set_theme(v))
        m.add_cascade(label=T("Theme"), menu=look)
        m.add_command(label=T("User guide"), command=self.open_user_guide)
        m.add_command(label=T("Clear recent files"), command=self.clear_recent)
        m.add_command(label=T("About {0}", APP_NAME), command=self.about)

    def open_user_guide(self):
        # bundled next to the program; docs/ when running from the source tree
        for path in (winutil.resource_path("USER_GUIDE.md"), winutil.resource_path(os.path.join("docs", "USER_GUIDE.md"))):
            if os.path.isfile(path):
                existing = next((t for t in self.tabs if getattr(t, "is_guide", False)), None)
                if existing is not None:
                    self.select_tab(existing)
                    return
                try:
                    from . import guide
                    pdf = guide.write_guide(path, f"{APP_NAME} \u2014 " + T("User guide"))
                except Exception as exc:  # noqa: BLE001 - the Markdown source is still readable
                    winutil.log_error(f"user guide layout failed: {exc!r}")
                    self.open_paths([path])
                    return
                tab = self.create_tab(pdf, "document", title=T("User guide"))
                if tab:
                    tab.is_guide = True
                    tab.display_path = f"{APP_NAME} \u2014 " + T("User guide")      # not the temp file
                    self.refresh_sidebar()
                    self.select_tab(tab)
                return
        self.toast.show(T("{0} is not included in this build", "USER_GUIDE.md"), "info")

    def check_registrations(self, may_change):
        """Windows start-up: drop file associations of deleted / old copies (they hide the MSI's icons) and
        rewrite the user's own choices after an update."""
        def work():
            try:
                stale = winutil.remove_stale_registrations()
            except Exception as exc:  # noqa: BLE001
                winutil.log_error(f"remove_stale_registrations failed: {exc!r}")
                stale = []
            self.root.after(0, lambda: done(stale))

        def done(stale):
            if stale:
                audit.event("associations", cleanup=",".join(stale)[:500])
            if may_change and self.settings.get("assoc") and \
                    (stale or self.settings.get("assoc_scheme") != winutil.ICON_SCHEME):
                self.refresh_associations()
        threading.Thread(target=work, daemon=True).start()

    def refresh_associations(self):
        """After an update: rewrite the user's own choices so new type icons / ProgIDs take effect."""
        chosen = self.settings.get("assoc") or {}

        def work():
            try:
                backup, _over = winutil.apply_associations(chosen.get("open_with", []), chosen.get("default", []),
                                                           chosen.get("context", True),
                                                           self.settings.get("assoc_backup"))
            except Exception as exc:  # noqa: BLE001
                winutil.log_error(f"refresh_associations failed: {exc!r}")
                return

            def store():
                self.settings["assoc_backup"] = backup
                self.settings["assoc_scheme"] = winutil.ICON_SCHEME
                self.settings.save()
            self.root.after(0, store)
        threading.Thread(target=work, daemon=True).start()

    def set_language(self, value):
        if "Language" in policy.active() or self.settings.get("language", "auto") == value:
            return
        self.settings["language"] = value
        self.settings.save()
        audit.event("settings", language=value)
        chosen = value if value in i18n.LANGUAGES else i18n.system_language()
        if chosen == i18n.current():
            return
        # asked in the language being switched to
        title, question, later = RESTART_TEXTS[chosen]
        self._ask_restart(title, question, later)

    def set_theme(self, value):
        if self.settings.get("theme", "auto") == value:
            return
        self.settings["theme"] = value
        self.settings.save()
        audit.event("settings", theme=value)
        mode = value if value in ("light", "dark") else theme.system_theme()
        if (mode == "dark") == theme.IS_DARK:
            return
        self._ask_restart(T("Theme"), T("The new theme is used after Monkey Viewer restarts.\n\nRestart Monkey Viewer now?"),
                          T("The theme changes the next time you open Monkey Viewer."))

    def _ask_restart(self, title, question, later):
        if messagebox.askyesno(title, question, parent=self.root):
            self.on_close(relaunch=True)
        else:
            self.toast.show(later, "info", 5000)

    # ── errors & diagnostics ──
    def _on_tk_error(self, exc_type, exc, tb):
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        winutil.log_error(detail)
        try:
            self.hide_overlay()
            self.toast.show(T("Something went wrong: {0}", exc), "error", 6000)
        except Exception:  # noqa: BLE001
            pass

    def show_associations(self):
        if policy.get_bool("DisableAssociationChanges"):
            self.toast.show(T("File types are managed by your administrator."), "info", 3500)
            return
        from . import assoc_view
        assoc_view.show(self)

    def _install_write_guards(self):
        """Every save / export dialog goes through here: the ReadOnly policy blocks it and the audit log
        records where files were written."""
        orig_save, orig_dir = filedialog.asksaveasfilename, filedialog.askdirectory
        app = self

        def free_name(kw):
            """Suggest "name (1).ext" when the suggested file already exists - never an overwrite by default."""
            name, folder = kw.get("initialfile"), kw.get("initialdir") or app.last_dir
            if name and folder and os.path.isdir(folder):
                ext = kw.get("defaultextension") or ""
                full = name if os.path.splitext(name)[1] or not ext else name + ext
                kw = dict(kw, initialfile=os.path.basename(safeio.unique_path(folder, full)), initialdir=folder)
            return kw

        self._orig_save_dialog = lambda *a, **kw: orig_save(*a, **free_name(kw))

        def blocked():
            if policy.get_bool("ReadOnly"):
                try:
                    app.toast.show(T("Saving and exporting are turned off by your administrator."), "warning", 4000)
                except Exception:  # noqa: BLE001
                    pass
                return True
            return False

        def save_dialog(*args, **kw):
            if blocked():
                return ""
            path = orig_save(*args, **free_name(kw))
            if path:
                audit.event("export", path=path, dialog=kw.get("title", ""))
            return path

        def dir_dialog(*args, **kw):
            if blocked():
                return ""
            path = orig_dir(*args, **kw)
            if path:
                audit.event("export", path=path, dialog=kw.get("title", ""))
            return path

        if not getattr(filedialog.asksaveasfilename, "_lv_guard", False):
            save_dialog._lv_guard = dir_dialog._lv_guard = True
            filedialog.asksaveasfilename, filedialog.askdirectory = save_dialog, dir_dialog

    def show_diagnostics(self):
        from . import diagnostics
        diagnostics.show(self)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C["chrome"], height=px(26))
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        tk.Frame(self.root, bg=C["border"], height=1).pack(side="bottom", fill="x")
        from .weather_view import WeatherCorner
        self.weather = WeatherCorner(self, bar)           # the right-hand corner of the status bar
        self.st_items = []
        for _ in range(7):
            lbl = tk.Label(bar, bg=C["chrome"], fg=C["fg_muted"], font=FONTS["small"], padx=px(9))
            self.st_items.append(lbl)
        for lbl in reversed(self.st_items):       # packed before the path: the path is the part that gets cut
            lbl.pack(side="right", fill="y")
        self.st_path = tk.Label(bar, bg=C["chrome"], fg=C["fg_muted"], font=FONTS["small"], padx=px(10), anchor="w",
                                width=1)
        self.st_path.pack(side="left", fill="both", expand=True)

    def _build_body(self):
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(side="top", fill="both", expand=True)
        self.sidebar = self._build_sidebar(body)
        self.sidebar_sep = tk.Frame(body, bg=C["border"], width=1)
        self.workspace = tk.Frame(body, bg=C["bg"])
        if self.sidebar_visible:
            self.sidebar.pack(side="left", fill="y")
            self.sidebar_sep.pack(side="left", fill="y")
        self.workspace.pack(side="left", fill="both", expand=True)
        self.tabbar = TabBar(self.workspace, self)
        self.tabbar.pack(side="top", fill="x")
        self.editor_area = tk.Frame(self.workspace, bg=C["bg"])
        self.editor_area.pack(side="top", fill="both", expand=True)
        self.welcome = self._build_welcome(self.editor_area)

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=C["sidebar"], width=px(250))
        side.pack_propagate(False)
        head = tk.Frame(side, bg=C["sidebar"])
        head.pack(side="top", fill="x", padx=(px(16), px(8)), pady=(px(12), px(6)))
        tk.Label(head, text=T("OPEN FILES"), font=FONTS["caption"], bg=C["sidebar"], fg=C["fg_muted"]).pack(side="left")
        self.count_badge = tk.Label(head, text="0", font=FONTS["caption"], bg=C["kbd"], fg=C["fg_dim"],
                                    padx=px(7), pady=px(1))
        self.count_badge.pack(side="left", padx=px(8))
        ToolButton(head, "", "copy", self.copy_all_files, T("Copy all open text files, in order"),
                   bg=C["sidebar"], pad=(7, 4)).pack(side="right")
        holder = tk.Frame(side, bg=C["sidebar"])
        holder.pack(side="top", fill="both", expand=True)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        from tkinter import ttk
        self.tree = ttk.Treeview(holder, style="Side.Treeview", show="tree", selectmode="browse")
        sb = ttk.Scrollbar(holder, orient="vertical", style="Side.Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=lambda f, l: self._autohide(sb, f, l))
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        sb.grid_remove()
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        theme.bind_right(self.tree, self._on_tree_menu)
        theme.bind_middle_release(self.tree, self._on_tree_middle)
        self.side_empty = tk.Label(holder, text=T("No files open"), font=FONTS["small"], bg=C["sidebar"],
                                   fg=C["fg_muted"])
        return side

    @staticmethod
    def _autohide(scrollbar, first, last):
        scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            scrollbar.grid_remove()
        else:
            scrollbar.grid()

    # ── welcome screen ──
    def _build_welcome(self, parent):
        frame = tk.Frame(parent, bg=C["bg"])
        # the home page scrolls when the window is too short and reflows its tiles when it is narrow
        from tkinter import ttk
        self._welcome_canvas = canvas = tk.Canvas(frame, bg=C["bg"], highlightthickness=0, bd=0)
        self._welcome_sb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=self._welcome_sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        box = tk.Frame(canvas, bg=C["bg"])
        self._welcome_item = canvas.create_window(0, 0, window=box, anchor="n")
        self._welcome_box = box
        self._tiles = []
        tk.Label(box, image=theme.logo_image(px(72), plate=True), bg=C["bg"]).pack()
        tk.Label(box, text=APP_NAME, font=FONTS["h1"], bg=C["bg"], fg=C["fg_bright"]).pack(pady=(px(10), px(2)))
        self._welcome_sub = tk.Label(box, text=T("For the files Office can't open \u2014 PDF editing, DjVu, CAD "
                                                 "drawings, GIS layers, signed & encrypted documents and Lua code."),
                                     font=FONTS["subtitle"], bg=C["bg"], fg=C["fg_dim"], wraplength=px(640),
                                     justify="center")
        self._welcome_sub.pack()
        btns = tk.Frame(box, bg=C["bg"])
        btns.pack(pady=(px(20), px(22)))
        ToolButton(btns, T("Open Files"), "open", self.open_dialog, variant="primary", pad=(18, 8)).pack(
            side="left", padx=px(6))
        outline = tk.Frame(btns, bg=C["border_strong"])
        outline.pack(side="left", padx=px(6))
        ToolButton(outline, T("New File"), "new", self.new_file, bg=C["bg"], hover=C["hover"], pad=(18, 7)).pack(
            padx=1, pady=1)
        grid = tk.Frame(box, bg=C["bg"])
        grid.pack(fill="x")
        self._tile_grid, self._tile_cols = grid, 0
        for i, (cat, (title, desc, icon_name)) in enumerate(formats.CATEGORIES.items()):
            self._tiles.append(self._make_tile(grid, i, cat, title, desc, icon_name))
        self._grid_tiles(4)
        self.recent_wrap = tk.Frame(box, bg=C["bg"])
        head = tk.Frame(self.recent_wrap, bg=C["bg"])
        head.pack(fill="x", pady=(px(18), px(6)))
        tk.Label(head, text=T("RECENT"), font=FONTS["caption"], bg=C["bg"], fg=C["fg_muted"]).pack(side="left", padx=px(8))
        self.recent_rows = tk.Frame(self.recent_wrap, bg=C["bg"])
        self.recent_rows.pack(fill="x")
        hint = theme.keys(T("Ctrl+O open  ·  Ctrl+F find  ·  Ctrl+S save  ·  Ctrl+Tab next tab  ·  "
                            "shortcuts work with any keyboard layout"))
        if self.dnd:
            hint = T("Drop files here") + "  ·  " + hint
        self.welcome_hint = tk.Label(box, text=hint, font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"])
        self.welcome_hint.pack(side="bottom", pady=(px(20), 0))
        canvas.bind("<Configure>", lambda e: self._place_welcome())
        box.bind("<Configure>", lambda e: self._place_welcome(reflow=False))
        return frame

    def _grid_tiles(self, cols):
        if cols == self._tile_cols:
            return
        self._tile_cols = cols
        for c in range(4):
            self._tile_grid.grid_columnconfigure(c, weight=1 if c < cols else 0, uniform="tiles" if c < cols else "")
        for i, tile in enumerate(self._tiles):
            r, c = divmod(i, cols)
            tile.grid(row=r, column=c, sticky="ew", padx=px(4), pady=px(3))

    def _make_tile(self, grid, i, cat, title, desc, icon_name):
        color = theme.KIND_COLORS.get(cat, C["accent"])
        tile = tk.Frame(grid, bg=C["bg"], cursor="hand2")
        glyph, _f = theme.icon(icon_name, allow_fallback=False)
        file_icon = theme.file_icon_image(cat, px(44))
        if file_icon is not None:
            ico = tk.Label(tile, image=file_icon, bg=C["bg"])
        else:
            ico = tk.Label(tile, image=theme.tile_image(color, 38), text=glyph or title[0], compound="center",
                           font=FONTS["icon_lg"] if glyph else FONTS["h3"], fg=color, bg=C["bg"])
        ico.pack(side="left", padx=(px(10), px(12)), pady=px(9))
        txt = tk.Frame(tile, bg=C["bg"])
        txt.pack(side="left", fill="x", expand=True)
        t1 = tk.Label(txt, text=T(title), font=FONTS["ui_bold"], fg=C["fg_bright"], bg=C["bg"], anchor="w")
        t1.pack(fill="x")
        t2 = tk.Label(txt, text=T(desc), font=FONTS["small"], fg=C["fg_muted"], bg=C["bg"], anchor="w")
        t2.pack(fill="x")
        parts = (tile, ico, txt, t1, t2)

        def paint(bg):
            for w in parts:
                w.configure(bg=bg)

        for w in parts:
            w.bind("<Enter>", lambda e: paint(C["hover"]))
            w.bind("<Leave>", lambda e: None if theme.pointer_inside(tile, e) else paint(C["bg"]))
            w.bind("<ButtonRelease-1>", lambda e, k=cat: self.open_dialog(k))
        return tile

    def _refresh_recent(self):
        for w in self.recent_rows.winfo_children():
            w.destroy()
        recent = [p for p in self.settings.get("recent", []) if isinstance(p, str) and os.path.exists(p)][:6]
        if not recent:
            self.recent_wrap.pack_forget()
            return
        self.recent_wrap.pack(fill="x", before=self.welcome_hint)
        for path in recent:
            row = tk.Frame(self.recent_rows, bg=C["bg"], cursor="hand2")
            row.pack(fill="x")
            badge = tk.Label(row, image=theme.badge_image(formats.badge_label(path), theme.KIND_COLORS.get(
                formats.category_of(path), theme.KIND_COLORS["binary"])), bg=C["bg"])
            badge.pack(side="left", padx=(px(10), px(10)), pady=px(5))
            name = tk.Label(row, text=os.path.basename(path), font=FONTS["ui"], bg=C["bg"], fg=C["fg"], anchor="w")
            name.pack(side="left")
            folder = tk.Label(row, text=os.path.dirname(path), font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"],
                              anchor="w")
            folder.pack(side="left", padx=px(12), fill="x", expand=True)
            parts = (row, badge, name, folder)

            def paint(bg, parts=parts):
                for w in parts:
                    w.configure(bg=bg)

            for w in parts:
                w.bind("<Enter>", lambda e, p=paint: p(C["hover"]))
                w.bind("<Leave>", lambda e, p=paint, r=row: None if theme.pointer_inside(r, e) else p(C["bg"]))
                w.bind("<ButtonRelease-1>", lambda e, p=path: self.open_paths([p]))

    def _place_welcome(self, reflow=True):
        canvas, box = self._welcome_canvas, self._welcome_box
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw <= 1:
            return
        width = max(px(280), min(px(1000), cw - px(48)))
        if reflow:
            self._grid_tiles(4 if width >= px(860) else 2 if width >= px(470) else 1)
            self._welcome_sub.configure(wraplength=max(px(240), min(px(640), width - px(20))))
            box.update_idletasks()
        req_h = box.winfo_reqheight()
        pad = px(18)
        fits = req_h + 2 * pad <= ch
        y = max(pad, (ch - req_h) // 2 - px(10)) if fits else pad
        canvas.coords(self._welcome_item, cw // 2, y)
        canvas.itemconfigure(self._welcome_item, width=width)
        canvas.configure(scrollregion=(0, 0, cw, ch if fits else req_h + 2 * pad))
        if fits:
            canvas.yview_moveto(0)
            self._welcome_sb.pack_forget()
        elif not self._welcome_sb.winfo_ismapped():
            self._welcome_sb.pack(side="right", fill="y", before=canvas)
        self._bind_welcome_wheel(box)

    def _bind_welcome_wheel(self, widget):
        def wheel(event):
            if self._welcome_sb.winfo_ismapped():
                self._welcome_canvas.yview_scroll(theme.wheel_units(event, 3), "units")
        for w in (widget, *widget.winfo_children()):
            w.bind("<MouseWheel>", wheel)
            if not theme.IS_WIN and not theme.IS_MAC:
                w.bind("<Button-4>", lambda e: wheel(type("E", (), {"delta": 120, "num": 4})()))
                w.bind("<Button-5>", lambda e: wheel(type("E", (), {"delta": -120, "num": 5})()))
            if w is not widget:
                self._bind_welcome_wheel(w)

    def _show_welcome(self):
        if self._welcome_shown:
            return
        self._welcome_shown = True
        self.find.hide()
        self.tabbar.pack_forget()
        self._refresh_recent()
        self.welcome.pack(fill="both", expand=True)
        self.welcome.lift()
        self.root.after_idle(self._place_welcome)
        self._bind_welcome_wheel(self._welcome_canvas)

    def _hide_welcome(self):
        if not self._welcome_shown:
            return
        self._welcome_shown = False
        self.welcome.pack_forget()
        self.tabbar.pack(side="top", fill="x", before=self.editor_area)

    def show_home(self):
        if self.active is not None:
            self.active.on_hide()
            self.active.frame.pack_forget()
            self.active = None
            self.tabbar.refresh()
            self.tree.selection_remove(self.tree.selection())
        self._show_welcome()
        if self.tabs:
            self.tabbar.pack(side="top", fill="x", before=self.editor_area)
        self.update_status()
        self.update_title()

    def _show_sidebar(self, show):
        if show and not self.sidebar_visible:
            self.sidebar.pack(side="left", fill="y", before=self.workspace)
            self.sidebar_sep.pack(side="left", fill="y", before=self.workspace)
        elif not show and self.sidebar_visible:
            self.sidebar.pack_forget()
            self.sidebar_sep.pack_forget()
        self.sidebar_visible = bool(show)

    def toggle_sidebar(self):
        self._sidebar_auto_hidden = False         # the user's own choice wins over the automatic one
        self._show_sidebar(not self.sidebar_visible)
        self.settings["sidebar"] = self.sidebar_visible

    # ── threads, drops, incoming files ──
    def next_tab_id(self):
        return f"tab{next(self._ids)}"

    def register_drop(self, widget):
        if not self.dnd:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event):
        self.open_paths(self.root.tk.splitlist(event.data))
        return getattr(event, "action", None)

    def run_in_thread(self, work, finish):
        def runner():
            try:
                result = (True, work())
            except Exception as exc:  # noqa: BLE001
                from .base import Notice
                if not isinstance(exc, Notice) and not getattr(exc, "quiet", False):
                    winutil.log_error("Background task failed:\n" + traceback.format_exc())
                result = (False, exc)

            def deliver():
                self._pending = max(0, self._pending - 1)
                finish(*result)

            self._results.put(deliver)

        self._pending += 1
        threading.Thread(target=runner, daemon=True).start()
        self._ensure_polling()

    def post(self, fn):
        """Thread-safe: run fn() on the UI thread soon."""
        self._results.put(fn)

    def _ensure_polling(self):
        if self._poll_job is None:
            self._poll_job = self.root.after(30, self._poll_results)

    def _poll_results(self):
        self._poll_job = None
        while True:
            try:
                fn = self._results.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                self.toast.show(T("Error: {0}", exc), "error", 4000)
        self._poll_job = self.root.after(40 if self._pending else 120, self._poll_results)

    def _poll_incoming(self):
        if self.instance is not None:
            while True:
                try:
                    files = self.instance.queue.get_nowait()
                except queue.Empty:
                    break
                self._incoming.extend(files)
                self._incoming_at = time.monotonic()
                self._incoming_wake = self._incoming_raise = True
        if self._incoming_wake and time.monotonic() - self._incoming_at >= 0.3:
            files, self._incoming = self._incoming, []
            raise_window = self._incoming_raise
            self._incoming_wake = self._incoming_raise = False
            if files:
                self.open_paths(files, merge_recent=True)
            if raise_window:
                self.bring_to_front()
        self._ensure_polling()
        self.root.after(100, self._poll_incoming)

    def receive_files(self, *paths):
        """Files handed over by the OS while running (Finder "Open With" / double-click on a Mac)."""
        files = [p for p in paths if isinstance(p, str) and p]
        if files:
            self._incoming.extend(files)
            self._incoming_at = time.monotonic()
            self._incoming_wake = self._incoming_raise = True

    def _build_mac_menubar(self):
        """Native macOS menu bar with the same menus as the in-window bar on Windows."""
        from . import menubar
        menubar.build_mac_menubar(self)

    def bring_to_front(self):
        r = self.root
        try:
            if r.state() == "iconic":
                r.deiconify()
            r.lift()
            r.attributes("-topmost", True)
            r.after(200, lambda: r.attributes("-topmost", False))
            r.focus_force()
        except tk.TclError:
            pass

    def show_overlay(self, text):
        if self.overlay is None:
            self.overlay = theme.Spinner(self.workspace, text)
        else:
            self.overlay.set_text(text)
        self.overlay.lift()

    def hide_overlay(self):
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None

    # ── opening files ──
    def open_dialog(self, category=None):
        types = formats.category_filetypes(category) if category else formats.dialog_filetypes()
        initial = self.last_dir if self.last_dir and os.path.isdir(self.last_dir) else os.path.expanduser("~")
        try:
            result = filedialog.askopenfilenames(parent=self.root, title=T("Open files"), initialdir=initial,
                                                 filetypes=types)
        except tk.TclError as exc:          # an over-long or odd filter must never block opening files
            winutil.log_error(f"open dialog: {exc}")
            result = filedialog.askopenfilenames(parent=self.root, title=T("Open files"), initialdir=initial)
        if result:
            self.open_paths(self.root.tk.splitlist(result))

    def find_tab(self, path):
        key = os.path.normcase(os.path.abspath(path))
        return next((t for t in self.tabs if t.path and os.path.normcase(t.path) == key), None)

    def tab_by_id(self, tab_id):
        return next((t for t in self.tabs if t.id == tab_id), None)

    def open_paths(self, paths, merge_recent=False):
        files = sorted({os.path.abspath(p) for p in paths if p and os.path.isfile(p)}, key=formats.natural_key)
        missing = [p for p in paths if p and not os.path.exists(p)]
        first, new_tabs = None, []
        for path in files:
            tab = self.find_tab(path)
            if tab is not None:            # opening it again reads the file from disk again
                tab = self._reload_open_tab(tab) or tab
                first = first or tab
                continue
            if tab is None:
                tab = self.create_tab(path)
                if tab is None:
                    continue
                new_tabs.append(tab)
                self.add_recent(path)
            first = first or tab
        if files:
            self.last_dir = os.path.dirname(files[0])
            self.settings["last_dir"] = self.last_dir
        if new_tabs:
            now = time.monotonic()
            group = new_tabs
            if merge_recent and now - self._batch_at < 4.0:
                recent = [t for t in self._batch if t in self.tabs and t not in new_tabs]
                combined = recent + new_tabs
                if recent and self.tabs[-len(combined):] == combined:
                    group = sorted(combined, key=lambda t: formats.natural_key(t.path or t.title))
                    self.tabs[-len(combined):] = group
                    self.tabbar.reorder(self.tabs)
                    first = group[0]
            self._batch, self._batch_at = group, now
        self.refresh_sidebar()
        if first:
            self.select_tab(first)
        if missing:
            self.toast.show(T("File not found: {0}", os.path.basename(missing[0])), "error", 3500)
        elif len(self._batch) > 1 and new_tabs:
            self.toast.show(T("Opened {0} files", len(self._batch)), "success")

    def create_tab(self, path=None, kind=None, title=None, index=None, **kw):
        kind = kind or (formats.viewer_kind(path) if path else "text")
        try:
            cls = tab_class(kind)
            tab = cls(self, path, title=title, **kw)
        except Exception as exc:  # noqa: BLE001
            winutil.log_error(f"Viewer '{kind}' failed for {path}:\n" + traceback.format_exc())
            from .info_view import InfoTab
            name = getattr(exc, "name", None)
            msg = f"A component needed for this file type is missing ({name})." if isinstance(exc, ImportError) \
                else f"{exc.__class__.__name__}: {exc}"
            if path is None:
                self.toast.show(T("Couldn't create the viewer: {0}", msg), "error", 5000)
                return None
            tab = InfoTab(self, path, error=msg)
            kind = "info"
        try:
            tab.load()
        except Exception as exc:  # noqa: BLE001
            from .base import Notice
            if not isinstance(exc, Notice):
                winutil.log_error(f"Loading {path} as '{kind}' failed:\n" + traceback.format_exc())
            tab.destroy()
            if kind in ("info",) or path is None:
                self.toast.show(T("Couldn't open {0}: {1}", title or os.path.basename(path or ''), exc), "error", 4500)
                return None
            from .base import Notice
            from .info_view import InfoTab
            if isinstance(exc, Notice):
                tab = InfoTab(self, path, notice=str(exc))
            else:
                tab = InfoTab(self, path, error=str(exc) or exc.__class__.__name__)
            tab.load()
        self.add_tab(tab, index)
        if path:
            self._audit_open(path, kind if tab.kind == kind else tab.kind)
        return tab

    @staticmethod
    def _audit_open(path, kind):
        def work():
            try:
                size = os.path.getsize(path)
            except OSError:
                size = None
            audit.event("file_open", path=path, viewer=kind, size=size, sha256=audit.file_hash(path))
        threading.Thread(target=work, daemon=True).start()

    def add_tab(self, tab, index=None):
        if index is None or index >= len(self.tabs):
            self.tabs.append(tab)
        else:
            self.tabs.insert(index, tab)
        self.tabbar.add(tab)
        if index is not None:
            self.tabbar.reorder(self.tabs)

    def replace_with(self, old, kind, **kw):
        """Swap a tab for another viewer of the same file (e.g. after a failed background load)."""
        if old not in self.tabs:
            return None
        index = self.tabs.index(old)
        was_active = old is self.active
        self._remove_tab(old)
        tab = self.create_tab(old.path, kind=kind, title=None if old.path else old.title, index=index, **kw)
        self.refresh_sidebar()
        if tab and (was_active or self.active is None):
            self.select_tab(tab)
        elif not self.tabs:
            self._show_welcome()
        return tab

    def _reload_open_tab(self, tab):
        if tab.dirty and not messagebox.askyesno(
                T("Reopen"), T("{0} is already open and has unsaved changes.\n\nReload it from the disk? "
                               "The changes are lost.", tab.title), parent=self.root):
            return tab
        kind = None if tab.kind in ("info", "hex") else tab.kind
        new = self.replace_with(tab, kind)
        if new is not None:
            self.toast.show(T("Reloaded {0}", new.title), "info", 1800)
        return new

    def reopen_as(self, tab, kind):
        if tab.dirty and not messagebox.askyesno(T("Reopen"), T("Discard unsaved changes and reopen?"), parent=self.root):
            return
        self.replace_with(tab, kind)

    def open_pdf_bytes(self, data, title):
        from .pdf_edit import PdfTab
        tab = PdfTab(self, None, title=title, data=data)
        tab.load()
        self.add_tab(tab)
        tab.set_dirty(True)
        self.refresh_sidebar()
        self.select_tab(tab)
        return tab

    def new_file(self):
        tab = self.create_tab(None, "text", title=f"Untitled-{next(self._untitled)}.lua")
        self.refresh_sidebar()
        self.select_tab(tab)

    def add_recent(self, path):
        recent = [p for p in self.settings.get("recent", []) if isinstance(p, str)
                  and os.path.normcase(p) != os.path.normcase(path)]
        self.settings["recent"] = ([path] + recent)[:15]

    def clear_recent(self):
        self.settings["recent"] = []
        self._refresh_recent()

    # ── tabs ──
    def select_tab(self, tab, focus=True):
        if tab not in self.tabs:
            return
        if tab is not self.active:
            old = self.active
            if old is not None:
                old.on_hide()
                old.frame.pack_forget()
            self._hide_welcome()
            self.active = tab
            tab.frame.pack(fill="both", expand=True)
            self.find.switch_to(tab)
            self.tabbar.refresh()
            self.root.after_idle(lambda: self.tabbar.ensure_visible(tab))
            if self.tree.exists(tab.id):
                self.tree.selection_set(tab.id)
                self.tree.see(tab.id)
            tab.on_show()
            self.update_title()
            self.update_status()
        if focus and not self.find.visible:
            tab.focus()

    def cycle_tab(self, step):
        if not self.tabs:
            return
        if self.active is None:
            self.select_tab(self.tabs[0])
        elif len(self.tabs) > 1:
            self.select_tab(self.tabs[(self.tabs.index(self.active) + step) % len(self.tabs)])

    def _remove_tab(self, tab):
        was_active = tab is self.active
        if self.find.tab is tab:
            self.find.hide()
        self.tabs.remove(tab)
        self.tabbar.remove(tab)
        if was_active:
            self.active = None
        tab.destroy()

    def close_tab(self, tab):
        if tab not in self.tabs:
            return True
        if tab.dirty:
            self.select_tab(tab)
            answer = messagebox.askyesnocancel(T("Unsaved changes"), T("Save the changes you made to {0}?", tab.title),
                                               parent=self.root, icon=messagebox.WARNING)
            if answer is None or (answer and not self.save_tab(tab)):
                return False
        i = self.tabs.index(tab)
        was_active = tab is self.active
        self._remove_tab(tab)
        if self.tabs:
            if was_active:
                self.select_tab(self.tabs[min(i, len(self.tabs) - 1)])
        else:
            self._show_welcome()
        self.refresh_sidebar()
        self.update_title()
        self.update_status()
        return True

    def close_active(self):
        if self.active:
            self.close_tab(self.active)

    def close_others(self, keep):
        for tab in [t for t in self.tabs if t is not keep]:
            if not self.close_tab(tab):
                return
        self.select_tab(keep)

    def close_all(self):
        for tab in list(self.tabs):
            if not self.close_tab(tab):
                return

    # ── saving & clipboard ──
    def save_active(self, save_as=False):
        if self.active:
            self.save_tab(self.active, save_as)

    def save_tab(self, tab, save_as=False):
        if policy.get_bool("ReadOnly"):
            self.toast.show(T("Saving is turned off by your administrator (view-only mode)."), "warning", 4000)
            return False
        if not tab.savable:
            if hasattr(tab, "pdf_bytes"):
                return self.export_active_pdf(tab)
            self.toast.show(T("This file type is view-only here — use Convert or Export instead."), "info", 3500)
            return False
        path = tab.path
        if save_as or not path or getattr(tab, "save_needs_new_path", False):
            initial = tab.title
            ext = tab.default_extension()
            if ext and not initial.lower().endswith(ext.lower()):
                initial = os.path.splitext(initial)[0] + ext
            path = self._orig_save_dialog(
                parent=self.root, title=T("Save as"), initialfile=initial, defaultextension=ext,
                initialdir=os.path.dirname(tab.path) if tab.path else self.last_dir, filetypes=tab.save_filetypes())
            if not path:
                return False
        if hasattr(tab, "confirm_save") and not tab.confirm_save(path):
            return False
        try:
            warning = tab.save_to(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(T("Save failed"), T("Could not save the file:\n{0}", exc), parent=self.root)
            return False
        exported = getattr(tab, "exported", None)       # e.g. a PDF saved as page images: the tab stays the PDF
        if exported:
            tab.exported = None
            audit.event("export", path=os.path.abspath(path), source=tab.path, viewer=tab.kind, files=len(exported))
            self.last_dir = os.path.dirname(os.path.abspath(path))
            self.toast.show(T("Saved {0} page image{1}", len(exported), "s" if len(exported) != 1 else ""), "success")
            return True
        audit.event("file_save", path=os.path.abspath(path), source=tab.path, viewer=tab.kind)
        tab.path = os.path.abspath(path)
        tab.title = os.path.basename(path)
        if hasattr(tab, "save_needs_new_path"):
            tab.save_needs_new_path = False
        tab.set_dirty(False)
        self.last_dir = os.path.dirname(tab.path)
        self.add_recent(tab.path)
        self.on_title_changed(tab)
        self.toast.show(warning or T("Saved {0}", tab.title), "warning" if warning else "success", 4500 if warning else 2200)
        return True

    def export_active_pdf(self, tab=None):
        tab = tab or self.active
        if tab is None or not hasattr(tab, "pdf_bytes"):
            return False
        name = os.path.splitext(tab.title)[0] + ".pdf"
        if policy.get_bool("ReadOnly"):
            self.toast.show(T("Saving and exporting are turned off by your administrator."), "warning", 4000)
            return False
        path = self._orig_save_dialog(parent=self.root, title=T("Export as PDF"), initialfile=name,
                                            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                            initialdir=os.path.dirname(tab.path) if tab.path else self.last_dir)
        if not path:
            return False
        try:
            data = tab.pdf_bytes()
            with open(path, "wb") as fh:
                fh.write(data)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(T("Export failed"), str(exc), parent=self.root)
            return False
        audit.event("export", path=path, source=tab.path, what="pdf")
        self.toast.show(T("Exported {0}", os.path.basename(path)), "success")
        return True

    def set_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def copy_all_files(self):
        texts = [t for t in self.tabs if t.kind == "text"]
        if not texts:
            self.toast.show(T("No text files are open."), "warning")
            return
        bar = "=" * 18
        parts = [f"-- {bar} {t.title} {bar}\n{t.get_content().rstrip()}\n" for t in texts]
        self.set_clipboard("\n".join(parts))
        self.toast.show(T("Copied {0} file{1} in order", len(texts), 's' if len(texts) != 1 else ''), "success")

    def copy_path(self, tab):
        if tab.path:
            self.set_clipboard(tab.path)
            self.toast.show(T("Path copied"), "success")

    def reveal(self, tab):
        if tab.path:
            try:
                winutil.reveal(tab.path)
            except Exception as exc:  # noqa: BLE001
                self.toast.show(T("Couldn't open the folder: {0}", exc), "error")

    def open_external(self, path):
        try:
            winutil.open_external(path)
        except winutil.BlockedFile as exc:
            self.toast.show(str(exc), "warning", 5000)
        except Exception as exc:  # noqa: BLE001
            self.toast.show(T("No app is set to open this file: {0}", exc), "error", 4000)

    # ── shortcuts ──
    def edit_action(self, action, widget=None):
        if widget is None:
            focus = self.root.focus_get()
            widget = focus if isinstance(focus, (tk.Text, tk.Entry)) else None
        if widget is None:
            if self.active is not None:
                self.active.edit_action(action)
            return
        if isinstance(widget, tk.Text):
            if action == "selectall":
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "end-1c")
            elif action in ("copy", "cut", "paste"):
                widget.event_generate(f"<<{action.capitalize()}>>")
            elif action in ("undo", "redo"):
                try:
                    widget.edit_undo() if action == "undo" else widget.edit_redo()
                except tk.TclError:
                    pass
                widget.see("insert")
        elif isinstance(widget, tk.Entry):
            if action == "selectall":
                widget.select_range(0, "end")
                widget.icursor("end")
            elif action in ("copy", "cut", "paste"):
                widget.event_generate(f"<<{action.capitalize()}>>")

    EDIT_KEYS = {("a", False): "selectall", ("c", False): "copy", ("x", False): "cut", ("v", False): "paste",
                 ("z", False): "undo", ("z", True): "redo", ("y", False): "redo"}

    def _native_shortcuts(self):
        """Keys Tk's own Text/Entry bindings already handle (e.g. Ctrl+V -> <<Paste>> on a Latin layout)."""
        if self._native is None:
            import re
            table = {}
            for action, virtual in (("copy", "<<Copy>>"), ("cut", "<<Cut>>"), ("paste", "<<Paste>>"),
                                    ("undo", "<<Undo>>"), ("redo", "<<Redo>>"), ("selectall", "<<SelectAll>>")):
                try:
                    seqs = self.root.event_info(virtual)
                except tk.TclError:
                    seqs = ()
                # Tk spells the Mac Command key "Command", "Mod1" or "M1" depending on the version
                mods = "Command|Mod1|M1|Meta" if theme.IS_MAC else "Control"
                for seq in seqs:
                    m = re.fullmatch(rf"<(?:{mods})-((?:Shift-)?)(?:Key-)?([A-Za-z])>", seq)   # Caps-Lock variants skipped
                    if m:
                        table[(m.group(2).lower(), bool(m.group(1)) or m.group(2).isupper())] = action
            self._native = table
        return self._native

    def on_ctrl_key(self, event):
        """Ctrl (Cmd on a Mac) shortcuts resolved by physical key, so they work on every keyboard layout."""
        if not event.state & PRIMARY_MASK or event.state & ALT_MASK:
            return None
        self._last_shortcut = time.monotonic()
        key = shortcut_key(event)
        if key is None:
            return None
        shift = bool(event.state & SHIFT_MASK)
        widget = event.widget if isinstance(event.widget, (tk.Text, tk.Entry)) else None
        edit = self.EDIT_KEYS.get((key, shift))
        if widget is not None and edit and len(event.keysym) == 1 and event.keysym.isascii() \
                and self._native_shortcuts().get((event.keysym.lower(), shift)) == edit:
            return None           # the widget's own binding already did it — doing it again would paste twice
        return self.run_shortcut(key, shift, widget)

    def run_shortcut(self, key, shift=False, widget=None):
        tab = self.active

        def tab_or_widget(action):
            return lambda: self.edit_action(action, widget)

        actions = {
            "a": tab_or_widget("selectall"),
            "c": (lambda: tab and hasattr(tab, "copy_all") and tab.copy_all()) if shift else tab_or_widget("copy"),
            "x": tab_or_widget("cut"),
            "v": tab_or_widget("paste"),
            "z": tab_or_widget("redo" if shift else "undo"),
            "y": tab_or_widget("redo"),
            "s": lambda: self.save_active(shift),
            "o": self.open_dialog,
            "n": self.new_file,
            "w": self.close_active,
            "f": self.find_show,
            "b": self.toggle_sidebar,
            "p": self.print_active,
            "tab": lambda: self.cycle_tab(-1 if shift else 1),
            "plus": lambda: tab and tab.zoomable and tab.zoom(1),
            "minus": lambda: tab and tab.zoomable and tab.zoom(-1),
            "0": lambda: tab and tab.zoomable and tab.zoom(0),
        }
        if key == "k" and shift:
            self.show_calculator()
            return "break"
        action = actions.get(key)
        if action:
            action()
            return "break"
        if key in ("d", "e", "k", "t", "h"):
            return "break"
        return None

    def zoom_code(self, step):
        size = theme.CODE_SIZE if step == 0 else max(7, min(40, theme.CODE_FONT.cget("size") + step))
        theme.CODE_FONT.configure(size=size)
        theme.CODE_FONT_ITALIC.configure(size=size)
        self.settings["code_size"] = size
        for tab in self.tabs:
            if tab.kind == "text":
                tab.update_tabstops()

    def find_show(self):
        if self.active and self.active.searchable:
            self.find.show()
        elif self.active:
            self.toast.show(T("Search isn't available for this file type."), "info", 2000)

    # ── menus ──
    def show_tab_menu(self, event, tab):
        m = theme.popup_menu(self.root)
        has_path = "normal" if tab.path else "disabled"
        m.add_command(label=T("Close"), accelerator="Ctrl+W", command=lambda: self.close_tab(tab))
        m.add_command(label=T("Close Others"), command=lambda: self.close_others(tab))
        m.add_command(label=T("Close All"), command=self.close_all)
        m.add_separator()
        m.add_command(label=T("Copy Path"), state=has_path, command=lambda: self.copy_path(tab))
        m.add_command(label=T("Open file location") if theme.IS_WIN else T("Show in Finder") if theme.IS_MAC
                      else T("Show in Folder"), state=has_path,
                      command=lambda: self.reveal(tab))
        m.add_command(label=T("Open with Default App"), state=has_path, command=lambda: self.open_external(tab.path))
        if tab.path:
            sub = theme.popup_menu(m)
            sub.add_command(label=T("Default viewer"), command=lambda: self.reopen_as(tab, None))
            sub.add_command(label=T("Hex"), command=lambda: self.reopen_as(tab, "hex"))
            sub.add_command(label=T("File info"), command=lambda: self.reopen_as(tab, "info"))
            m.add_cascade(label=T("Reopen As"), menu=sub)
        theme.show_menu(m, event.x_root, event.y_root)

    # ── sidebar ──
    @staticmethod
    def _sidebar_text(tab):
        return f" {tab.title}" + ("   ●" if tab.dirty else "")

    def refresh_sidebar(self):
        self.tree.delete(*self.tree.get_children())
        for tab in self.tabs:
            self.tree.insert("", "end", iid=tab.id, text=self._sidebar_text(tab), image=tab.badge())
        if self.active and self.tree.exists(self.active.id):
            self.tree.selection_set(self.active.id)
            self.tree.see(self.active.id)
        self.count_badge.configure(text=str(len(self.tabs)))
        if self.tabs:
            self.side_empty.place_forget()
        else:
            self.side_empty.place(relx=0.5, rely=0.12, anchor="n")

    def _on_tree_select(self, _event):
        sel = self.tree.selection()
        tab = self.tab_by_id(sel[0]) if sel else None
        if tab and tab is not self.active:
            self.select_tab(tab)

    def _on_tree_menu(self, event):
        tab = self.tab_by_id(self.tree.identify_row(event.y))
        if tab:
            self.show_tab_menu(event, tab)

    def _on_tree_middle(self, event):
        tab = self.tab_by_id(self.tree.identify_row(event.y))
        if tab:
            self.close_tab(tab)

    # ── status ──
    def on_dirty_changed(self, tab):
        if tab not in self.tabs:
            return
        self.tabbar.refresh(tab)
        if self.tree.exists(tab.id):
            self.tree.item(tab.id, text=self._sidebar_text(tab))
        if tab is self.active:
            self.update_title()

    def on_title_changed(self, tab):
        if tab not in self.tabs:
            return
        self.tabbar.refresh(tab)
        if self.tree.exists(tab.id):
            self.tree.item(tab.id, text=self._sidebar_text(tab), image=tab.badge())
        if tab is self.active:
            self.update_title()
            self.update_status()

    def update_title(self):
        self._menus_changed()
        tab = self.active
        if tab is None:
            self.root.title(APP_NAME)
        else:
            mark = "● " if tab.dirty else ""
            self.root.title(f"{mark}{tab.title} — {APP_NAME}")

    def _menus_changed(self):
        """The document's own menu follows the active tab."""
        if getattr(self, "menubar", None) is not None:
            self.menubar.refresh()
        retitle = getattr(self, "_mac_retitle", None)
        if retitle:
            retitle()

    def on_alt_key(self, event):
        """Alt+F/E/V/D/W/H open the menus, Alt+1..9 switch tabs (by key position, any keyboard layout)."""
        if event.state & PRIMARY_MASK:
            return None
        digit = event.keycode - 48 if 49 <= event.keycode <= 57 and theme.IS_WIN else (
            int(event.keysym) if event.keysym.isdigit() and event.keysym != "0" else None)
        if digit and digit <= len(self.tabs):
            self.select_tab(self.tabs[digit - 1])
            return "break"
        if self.menubar is not None:
            return self.menubar.on_alt(event)
        return None

    def toggle_menubar(self):
        if self.menubar is None:
            return
        show = not self.settings.get("menubar", True)
        self.settings["menubar"] = show
        if show:
            self.menubar.pack(side="top", fill="x", before=self.toolbar)
        else:
            self.menubar.pack_forget()
            self.toast.show(T("Menu bar hidden \u2014 Alt shows a menu, \u2630 has everything."), "info", 3000)

    def is_fullscreen(self):
        try:
            return bool(self.root.attributes("-fullscreen"))
        except tk.TclError:
            return False

    def toggle_fullscreen(self):
        try:
            self.root.attributes("-fullscreen", not self.is_fullscreen())
        except tk.TclError:
            pass

    def show_calculator(self):
        from . import calc_view
        return calc_view.show(self)

    def print_active(self):
        if self.active is None:
            return
        from . import printing
        printing.print_tab(self, self.active)

    def update_status(self):
        tab = self.active
        segments = []
        if tab is None:
            self.st_path.configure(text=T("{0} file open", 1) if len(self.tabs) == 1 else
                                   T("{0} files open", len(self.tabs)) if self.tabs else T("Ready"))
        else:
            self.st_path.configure(text=getattr(tab, "display_path", None) or tab.path or T("Unsaved"))
            try:
                segments = [s for s in tab.status() if s]
            except Exception:  # noqa: BLE001
                segments = []
        segments = segments[-len(self.st_items):]
        pad = [""] * (len(self.st_items) - len(segments))
        for lbl, text in zip(self.st_items, pad + segments):
            lbl.configure(text=text)
        savable = tab is not None and (tab.savable or hasattr(tab, "pdf_bytes"))
        self.save_btn.set_enabled(savable)
        self.saveas_btn.set_enabled(savable)
        self.find_btn.set_enabled(tab is not None and tab.searchable)

    # ── registration / about ──
    def unregister_types(self):
        if policy.get_bool("DisableAssociationChanges"):
            self.toast.show(T("File types are managed by your administrator."), "info", 3500)
            return
        if not (theme.IS_WIN or theme.IS_MAC):
            self.toast.show(T("File associations are only used on Windows and macOS."), "info")
            return
        question = (T("Give every file type that opens in Monkey Viewer back to the app it used before?") if theme.IS_MAC
                    else T("Remove Monkey Viewer from \"Open with\", the right-click menu and every default it was given?"))
        if not messagebox.askyesno(T("Remove associations"), question, parent=self.root):
            return
        try:
            backup, _over = winutil.apply_associations(set(), set(), False, self.settings.get("assoc_backup"))
            audit.event("associations", open_with=0, default=0, context_menu=False, removed=True)
            self.settings["assoc_backup"] = backup
            self.settings["assoc"] = {"open_with": [], "default": [], "context": False}
            self.settings.save()
            self.toast.show(T("All associations removed"), "success")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(T("Remove associations"), str(exc), parent=self.root)

    def about(self):
        dlg = theme.Dialog(self.root, T("About {0}", APP_NAME), min_width=460)
        b = dlg.body
        tk.Label(b, image=theme.logo_image(px(56), plate=True), bg=C["panel"]).pack(anchor="w")
        tk.Label(b, text=APP_NAME, font=FONTS["h2"], bg=C["panel"], fg=C["fg_bright"], anchor="w").pack(
            fill="x", pady=(px(8), 0))
        build = "  \u00b7  " + T("build {0}", app_info.BUILD_COMMIT) + (f" ({app_info.BUILD_DATE})" if app_info.BUILD_DATE else "")
        rows = [(T("Version"), app_info.VERSION + build), (T("Publisher"), app_info.PUBLISHER),
                (T("License"), T(app_info.LICENSE)), ("", app_info.COPYRIGHT)]
        active = policy.active()
        if active:
            rows.append((T("Policies"), ", ".join(active)))
        grid = tk.Frame(b, bg=C["panel"])
        grid.pack(fill="x", pady=(px(8), px(4)))
        for i, (k, v) in enumerate(rows):
            tk.Label(grid, text=k, font=FONTS["small"], bg=C["panel"], fg=C["fg_muted"], anchor="w").grid(
                row=i, column=0, sticky="w", padx=(0, px(14)))
            tk.Label(grid, text=v, font=FONTS["small"], bg=C["panel"], fg=C["fg"], anchor="w", justify="left",
                     wraplength=px(360)).grid(row=i, column=1, sticky="w")
        tk.Label(b, text=T(app_info.DESCRIPTION) + ". " + T("No telemetry, no update checks, no accounts; the internet is used only for the weather."),
                 font=FONTS["small"], bg=C["panel"], fg=C["fg_dim"], anchor="w", justify="left",
                 wraplength=px(420)).pack(fill="x", pady=(px(6), 0))

        def show_doc(name):
            path = winutil.resource_path(name)
            if os.path.exists(path):
                dlg.cancel()
                self.open_paths([path])
            else:
                self.toast.show(T("{0} is not included in this build", name), "info")

        for label, name in (("Licenses", "THIRD_PARTY_NOTICES.txt"), ("Security", "SECURITY.md"),
                            ("Privacy", "PRIVACY.md")):
            ToolButton(dlg.footer, T(label), None, lambda n=name: show_doc(n), bg=C["chrome"], pad=(12, 5)).pack(
                side="left", padx=(0, px(6)))
        dlg.add_buttons(T("Close"), None)
        dlg.run()

    # ── exit ──
    def on_close(self, relaunch=False):
        """Close the window (asking about unsaved changes). relaunch=True starts a fresh copy afterwards."""
        dirty = [t for t in self.tabs if t.dirty]
        if dirty and policy.get_bool("ReadOnly"):
            if not messagebox.askokcancel(T("Close"), T("Changes can't be saved in view-only mode. Close anyway?"),
                                          parent=self.root, icon=messagebox.WARNING):
                return False
            dirty = []
        if dirty:
            names = "\n".join(f"• {t.title}" for t in dirty[:8]) + ("\n…" if len(dirty) > 8 else "")
            answer = messagebox.askyesnocancel(T("Unsaved changes"),
                                               T("Save changes to {0} file(s) before closing?\n\n{1}", len(dirty), names),
                                               parent=self.root, icon=messagebox.WARNING)
            if answer is None:
                return False
            if answer:
                for tab in dirty:
                    self.select_tab(tab)
                    if not self.save_tab(tab):
                        return False
        session = safeio._SESSION            # decrypted temp copies are deleted on exit - never reopened
        reopen = [t.path for t in self.tabs if t.path and os.path.isfile(t.path)
                  and not (session and safeio.is_within(session, t.path))]
        try:
            maximized = self.root.state() == "zoomed"
            self.settings["maximized"] = maximized
            if not maximized and self.root.state() == "normal":
                self.settings["geometry"] = [self.root.winfo_x(), self.root.winfo_y(),
                                             self.root.winfo_width(), self.root.winfo_height()]
        except tk.TclError:
            pass
        self.settings.save()
        for tab in list(self.tabs):
            tab.destroy()
        audit.event("app_exit", restart=bool(relaunch))
        safeio.cleanup_session()
        if relaunch:
            if self.instance is not None:
                self.instance.release()
            try:
                winutil.relaunch(reopen)
            except OSError as exc:
                winutil.log_error(f"relaunch failed: {exc!r}")
        try:
            self.weather.destroy()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()
        return True


def main():
    args = sys.argv[1:]
    test = next((a for a in args if a == "--self-test" or a.startswith("--self-test=")), None)
    if test is not None:
        from . import selftest
        sys.exit(selftest.main(test.partition("=")[2] or None))
    if "--register" in args and policy.get_bool("DisableAssociationChanges"):
        return
    i18n.setup(winutil.Settings().get("language", "auto"))
    if "--register" in args or "--unregister" in args:
        quiet = "--quiet" in args
        try:
            if "--unregister" in args:
                winutil.unregister_file_types()
                msg = T('{0} was removed from "Open with".', APP_NAME)
            else:
                winutil.register_file_types()
                msg = T("Done! Right-click any file → Open in {0}, or use Open with.\n\n"
                        "Tip: in Open with → Choose another app, tick \"Always\" to make it the default.", APP_NAME)
            if not quiet:
                winutil.native_message(msg)
        except Exception as exc:  # noqa: BLE001
            winutil.native_message(T("Registration failed:\n{0}", exc), error=True)
        return

    files = [os.path.abspath(a) for a in args if not a.startswith("-")]   # also skips macOS "-psn_…"
    instance = winutil.SingleInstance()
    if not instance.acquire():
        if winutil.SingleInstance.send(files):
            return
        instance = None
    winutil.enable_dpi_awareness()
    winutil.set_app_user_model_id()
    from . import watchdog
    watchdog.wrap_dialogs()                          # dialog time is not a freeze; must precede App()
    root = None
    if TkinterDnD is not None and "--no-dnd" not in args and not winutil.Settings().get("no_drag_drop"):
        try:
            root = TkinterDnD.Tk()
        except Exception:  # noqa: BLE001
            root = None
    if root is None:
        root = tk.Tk(className="MonkeyViewer")
    app = App(root, files, instance)
    watchdog.start(root)
    active = policy.active()
    audit.event("app_start", frozen=winutil.FROZEN, build=app_info.BUILD_COMMIT, language=i18n.current(),
                policies=",".join(f"{k}={v}" for k, v in active.items()) or "none")
    threading.Thread(target=safeio.cleanup_stale, daemon=True).start()
    may_ask = (theme.IS_WIN or theme.IS_MAC) and not policy.get_bool("DisableAssociationChanges")
    if theme.IS_WIN:
        app.check_registrations(may_ask)
    if "--associations" in args and may_ask:
        root.after(400, app.show_associations)
    elif may_ask and not policy.get_bool("DisableAssociationPrompt") and not app.settings.get("assoc_prompted") \
            and app.settings.get("assoc") is None:
        app.settings["assoc_prompted"] = True          # first start after installation: ask once
        app.settings.save()
        root.after(900, app.show_associations)
    root.mainloop()

