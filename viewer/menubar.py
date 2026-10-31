"""Menu bar (File, Edit, View, <document>, Window, Help) and the app menu behind the ☰ button.

The menus are filled when they open, from the active tab: every document type adds its own items
(BaseTab.fill_menu) and its own menu (BaseTab.menu_title: Document, Drawing, Map, Table, Text...).
Windows / Linux get a themed bar inside the window; a Mac gets the same menus in its native menu bar.
"""

import os
import time
import tkinter as tk

from . import policy, theme
from .winutil import APP_NAME
from .i18n import T
from .theme import C, FONTS, px

# Alt + key opens a menu; Windows virtual-key codes work on every keyboard layout (Georgian too)
ALT_KEYS = {"file": ("f", 70), "edit": ("e", 69), "view": ("v", 86), "tools": ("d", 68), "window": ("w", 87),
            "help": ("h", 72)}


class MenuModel:
    def __init__(self, app):
        self.app = app

    # ── helpers ──
    def acc(self, text):
        """Shortcut text: 'Ctrl+S' on Windows, 'Command-S' for the native Mac menu (shown as ⌘S)."""
        if not text:
            return None
        if theme.IS_MAC:
            return text.replace("Ctrl+", "Command-").replace("Shift+", "Shift-").replace("Alt+", "Option-")
        return text

    def run(self, fn):
        """On a Mac a menu accelerator and the key binding can both fire: run once."""
        if not theme.IS_MAC:
            return fn

        def guarded():
            if time.monotonic() - self.app._last_shortcut > 0.35:
                fn()
        return guarded

    def cmd(self, m, label, fn, accel=None, enabled=True):
        m.add_command(label=label, command=self.run(fn), accelerator=self.acc(accel) or "",
                      state="normal" if enabled else "disabled")

    @property
    def tab(self):
        return self.app.active

    def titles(self):
        out = [("file", T("File")), ("edit", T("Edit")), ("view", T("View"))]
        own = self.tab.menu_title() if self.tab is not None else None
        if own:
            out.append(("tools", own))
        out += [("window", T("Window")), ("help", T("Help"))]
        return out

    def fill(self, key, m):
        m.delete(0, "end")
        for child in m.winfo_children():               # submenus of the previous opening
            child.destroy()
        m.__dict__["_lv_vars"] = []
        getattr(self, "fill_" + key)(m)

    # ── File ──
    def fill_file(self, m):
        app, tab = self.app, self.tab
        has_path = tab is not None and bool(tab.path) and os.path.exists(tab.path)
        self.cmd(m, T("New"), app.new_file, "Ctrl+N")
        self.cmd(m, T("Open…"), app.open_dialog, "Ctrl+O")
        recent = theme.popup_menu(m) if not theme.IS_MAC else tk.Menu(m, tearoff=0)
        self.fill_recent(recent)
        m.add_cascade(label=T("Open recent"), menu=recent)
        if tab is not None and tab.path:
            self.cmd(m, T("Reload from disk"), lambda: app._reload_open_tab(tab))
        m.add_separator()
        savable = tab is not None and getattr(tab, "savable", False)
        self.cmd(m, T("Save"), app.save_active, "Ctrl+S", savable)
        self.cmd(m, T("Save As…"), lambda: app.save_active(True), "Ctrl+Shift+S", savable)
        if tab is not None:
            tab.fill_menu("file", m)
        m.add_separator()
        self.cmd(m, T("Print…"), app.print_active, "Ctrl+P",
                 tab is not None and not policy.get_bool("DisablePrinting"))
        m.add_separator()
        self.cmd(m, T("Show in Finder") if theme.IS_MAC else T("Open file location"),
                 lambda: app.reveal(tab), enabled=has_path)
        self.cmd(m, T("Copy Path"), lambda: app.copy_path(tab), enabled=has_path)
        self.cmd(m, T("Open with Default App"), lambda: app.open_external(tab.path), enabled=has_path)
        m.add_separator()
        self.cmd(m, T("Close"), app.close_active, "Ctrl+W", tab is not None)
        self.cmd(m, T("Close All"), app.close_all, enabled=bool(app.tabs))
        if not theme.IS_MAC:                    # a Mac has Quit in the application menu
            m.add_separator()
            self.cmd(m, T("Exit"), app.on_close, "Alt+F4")

    def fill_recent(self, m):
        recent = [p for p in self.app.settings.get("recent", []) if isinstance(p, str) and os.path.exists(p)][:12]
        for path in recent:
            m.add_command(label=os.path.basename(path) + "   —   " + os.path.dirname(path),
                          command=lambda p=path: self.app.open_paths([p]))
        if recent:
            m.add_separator()
            m.add_command(label=T("Clear recent files"), command=self.app.clear_recent)
        else:
            m.add_command(label=T("No recent files"), state="disabled")

    # ── Edit ──
    def fill_edit(self, m):
        app, tab = self.app, self.tab
        on = tab is not None
        redo = "Ctrl+Shift+Z" if theme.IS_MAC else "Ctrl+Y"
        for item in ((T("Undo"), "undo", "Ctrl+Z"), (T("Redo"), "redo", redo), None,
                     (T("Cut"), "cut", "Ctrl+X"), (T("Copy"), "copy", "Ctrl+C"), (T("Paste"), "paste", "Ctrl+V"),
                     None, (T("Select All"), "selectall", "Ctrl+A")):
            if item is None:
                m.add_separator()
                continue
            label, action, accel = item
            self.cmd(m, label, lambda a=action: app.edit_action(a), accel, on)
        m.add_separator()
        self.cmd(m, T("Find…"), app.find_show, "Ctrl+F", on and tab.searchable)
        if on:
            before = m.index("end")
            tab.fill_menu("edit", m)
            if m.index("end") != before:
                m.insert_separator(before + 1)

    # ── View ──
    def fill_view(self, m):
        app, tab = self.app, self.tab
        m.add_checkbutton(label=T("Sidebar"), command=self.run(app.toggle_sidebar),
                          accelerator=self.acc("Ctrl+B"), variable=theme.menu_var(m, "bool", app.sidebar_visible))
        self.cmd(m, T("Home"), app.show_home)
        if not theme.IS_MAC:
            m.add_checkbutton(label=T("Full screen"), command=app.toggle_fullscreen, accelerator="F11",
                              variable=theme.menu_var(m, "bool", app.is_fullscreen()))
        if tab is not None:
            before = m.index("end")
            tab.fill_menu("view", m)
            if m.index("end") != before:
                m.insert_separator(before + 1)
        m.add_separator()
        look = theme.popup_menu(m) if not theme.IS_MAC else tk.Menu(m, tearoff=0)
        var = theme.menu_var(look, "str", app.settings.get("theme", "auto"))
        for value, text in (("auto", T("Same as the computer")), ("light", T("Light")), ("dark", T("Dark"))):
            look.add_radiobutton(label=text, value=value, variable=var, command=lambda v=value: app.set_theme(v))
        m.add_cascade(label=T("Theme"), menu=look)
        lang = theme.popup_menu(m) if not theme.IS_MAC else tk.Menu(m, tearoff=0)
        forced = "Language" in policy.active()
        lvar = theme.menu_var(lang, "str", app.settings.get("language", "auto"))
        for value, text in (("auto", T("Same as the computer")), ("ka", "ქართული"), ("en", "English")):
            lang.add_radiobutton(label=text, value=value, variable=lvar, state="disabled" if forced else "normal",
                                 command=lambda v=value: app.set_language(v))
        m.add_cascade(label=T("Language"), menu=lang)
        weather_menu = theme.popup_menu(m) if not theme.IS_MAC else tk.Menu(m, tearoff=0)
        app.weather.fill_menu(weather_menu)
        m.add_cascade(label=T("Weather"), menu=weather_menu)

    # ── the document's own menu ──
    def fill_tools(self, m):
        if self.tab is not None:
            self.tab.fill_menu("tools", m)
        if m.index("end") is None:
            m.add_command(label=T("Nothing here for this file"), state="disabled")

    # ── Window ──
    def fill_window(self, m):
        app = self.app
        many = len(app.tabs) > 1
        self.cmd(m, T("Next Tab"), lambda: app.cycle_tab(1), "Ctrl+Tab", many)
        self.cmd(m, T("Previous Tab"), lambda: app.cycle_tab(-1), "Ctrl+Shift+Tab", many)
        self.cmd(m, T("Close Others"), lambda: app.close_others(app.active), enabled=many and app.active is not None)
        m.add_separator()
        self.cmd(m, T("Calculator"), app.show_calculator, "Ctrl+Shift+K")
        if app.tabs:
            m.add_separator()
            var = theme.menu_var(m, "str", str(app.active.id) if app.active is not None else "")
            for n, t in enumerate(app.tabs, 1):
                label = ("● " if t.dirty else "") + t.title
                m.add_radiobutton(label=label, value=str(t.id), variable=var,
                                  accelerator=self.acc(f"Alt+{n}") if n <= 9 and not theme.IS_MAC else "",
                                  command=lambda x=t: app.select_tab(x))

    # ── Help ──
    def fill_help(self, m):
        app = self.app
        self.cmd(m, T("User guide"), app.open_user_guide, "F1")
        self.cmd(m, T("Keyboard shortcuts"), lambda: show_shortcuts(app))
        m.add_separator()
        if not policy.get_bool("DisableAssociationChanges"):
            self.cmd(m, T("File associations…"), app.show_associations)
        self.cmd(m, T("Components & diagnostics…"), app.show_diagnostics)
        if not theme.IS_MAC:
            m.add_separator()
            self.cmd(m, T("About {0}", APP_NAME), app.about)

    # ── ☰ app menu ──
    def fill_app_menu(self, m):
        app, tab = self.app, self.tab
        self.cmd(m, T("Home"), app.show_home)
        self.cmd(m, T("New"), app.new_file, "Ctrl+N")
        self.cmd(m, T("Open…"), app.open_dialog, "Ctrl+O")
        recent = theme.popup_menu(m)
        self.fill_recent(recent)
        m.add_cascade(label=T("Open recent"), menu=recent)
        m.add_separator()
        savable = tab is not None and getattr(tab, "savable", False)
        self.cmd(m, T("Save"), app.save_active, "Ctrl+S", savable)
        self.cmd(m, T("Save As…"), lambda: app.save_active(True), "Ctrl+Shift+S", savable)
        self.cmd(m, T("Print…"), app.print_active, "Ctrl+P",
                 tab is not None and not policy.get_bool("DisablePrinting"))
        m.add_separator()
        self.cmd(m, T("Calculator"), app.show_calculator, "Ctrl+Shift+K")
        m.add_separator()
        m.add_checkbutton(label=T("Sidebar"), command=app.toggle_sidebar, accelerator=theme.keys("Ctrl+B"),
                          variable=theme.menu_var(m, "bool", app.sidebar_visible))
        m.add_checkbutton(label=T("Menu bar"), command=app.toggle_menubar,
                          variable=theme.menu_var(m, "bool", app.settings.get("menubar", True)))
        self.cmd(m, T("Close All"), app.close_all, enabled=bool(app.tabs))
        m.add_separator()
        for key, label in self.titles()[1:]:
            if key in ("edit",):
                continue
            sub = theme.popup_menu(m)
            self.fill(key, sub)
            m.add_cascade(label=label, menu=sub)
        m.add_separator()
        self.cmd(m, T("Exit"), app.on_close)


class MenuBar(tk.Frame):
    """Themed in-window menu bar for Windows and Linux (the native one cannot follow the dark theme)."""

    def __init__(self, app, parent):
        super().__init__(parent, bg=C["chrome"], height=px(28))
        self.app = app
        self.model = MenuModel(app)
        self.pack_propagate(False)
        self.labels = {}
        self.open_key = None
        self.refresh()

    def refresh(self):
        titles = self.model.titles()
        if [k for k, _ in titles] == list(self.labels) and all(
                self.labels[k].cget("text") == t for k, t in titles):
            return
        for w in self.winfo_children():
            w.destroy()
        self.labels = {}
        for key, title in titles:
            lab = tk.Label(self, text=title, bg=C["chrome"], fg=C["fg_dim"], font=FONTS["ui"], padx=px(10))
            lab.pack(side="left", fill="y", padx=(px(4) if not self.labels else 0, 0))
            lab.bind("<Button-1>", lambda e, k=key: self.post(k))
            lab.bind("<Enter>", lambda e, w=lab: w.configure(bg=C["hover"], fg=C["fg_bright"]))
            lab.bind("<Leave>", lambda e, w=lab, k=key: None if self.open_key == k else
                     w.configure(bg=C["chrome"], fg=C["fg_dim"]))
            self.labels[key] = lab

    def post(self, key):
        self.refresh()
        lab = self.labels.get(key)
        if lab is None:
            return
        m = theme.popup_menu(self.app.root)
        self.model.fill(key, m)
        self.open_key = key
        lab.configure(bg=C["row_sel"], fg=C["fg_bright"])
        try:
            theme.show_menu(m, lab.winfo_rootx(), lab.winfo_rooty() + lab.winfo_height(), anchor=lab)
        finally:
            self.open_key = None
            self.repaint()

    def repaint(self):
        """Hover look only where the pointer really is (an open menu swallows <Enter>/<Leave>)."""
        try:
            x, y = self.winfo_pointerxy()
        except tk.TclError:
            return
        for key, lab in self.labels.items():
            if not lab.winfo_exists() or key == self.open_key:
                continue
            over = lab.winfo_rootx() <= x < lab.winfo_rootx() + lab.winfo_width() and \
                lab.winfo_rooty() <= y < lab.winfo_rooty() + lab.winfo_height()
            lab.configure(bg=C["hover"] if over else C["chrome"], fg=C["fg_bright"] if over else C["fg_dim"])

    def on_alt(self, event):
        for key, (letter, vk) in ALT_KEYS.items():
            if key in self.labels and (event.keysym.lower() == letter or (theme.IS_WIN and event.keycode == vk)):
                self.post(key)
                return "break"
        return None


def build_mac_menubar(app):
    """The same menus in the native macOS menu bar (refilled each time a menu opens)."""
    model = MenuModel(app)
    r = app.root
    bar = tk.Menu(r, tearoff=0)
    app_menu = tk.Menu(bar, name="apple", tearoff=0)
    app_menu.add_command(label=T("About {0}", APP_NAME), command=app.about)
    app_menu.add_separator()
    bar.add_cascade(menu=app_menu)
    titles = dict(model.titles())
    for key, label in (("file", titles["file"]), ("edit", titles["edit"]), ("view", titles["view"]),
                       ("tools", T("Document")), ("window", titles["window"]), ("help", titles["help"])):
        name = {"window": "window", "help": "help"}.get(key)
        menu = tk.Menu(bar, tearoff=0, **({"name": name} if name else {}))
        menu.configure(postcommand=lambda k=key, mm=menu: model.fill(k, mm))
        model.fill(key, menu)
        bar.add_cascade(label=label, menu=menu)
        if key == "tools":
            tools_index = bar.index("end")
    r.configure(menu=bar)
    app._mac_bar = bar

    def retitle():
        own = app.active.menu_title() if app.active is not None else None
        try:
            bar.entryconfigure(tools_index, label=own or T("Document"), state="normal" if own else "disabled")
        except tk.TclError:
            pass
    app._mac_retitle = retitle
    retitle()
    return bar


SHORTCUTS = [
    ("Ctrl+O", "Open files"), ("Ctrl+N", "New text file"), ("Ctrl+S", "Save"), ("Ctrl+Shift+S", "Save as"),
    ("Ctrl+P", "Print"), ("Ctrl+W", "Close the tab"), ("Ctrl+Tab", "Next tab"), ("Ctrl+F", "Find"),
    ("Ctrl+B", "Show or hide the sidebar"), ("Ctrl++ / Ctrl+-", "Zoom in / out"), ("Ctrl+0", "Actual size"),
    ("Ctrl+Z / Ctrl+Y", "Undo / redo"), ("Ctrl+Shift+K", "Calculator"), ("F1", "User guide"),
    ("F11", "Full screen"),
    ("Alt+F, E, V, D, W, H", "Open a menu"),
    ("V T E H P R W I C", "PDF tools: select, text, edit, mark, pen, box, erase, image, crop"),
    ("Enter / Esc", "Apply / cancel a crop"), ("← ↑ → ↓", "Move the crop frame (Shift: 10 pt)"),
]


def show_shortcuts(app):
    dlg = theme.Dialog(app.root, T("Keyboard shortcuts"), min_width=480)
    grid = tk.Frame(dlg.body, bg=C["panel"])
    grid.pack(fill="both", expand=True)
    for r, (keys, text) in enumerate(SHORTCUTS):
        if theme.IS_MAC and keys.startswith(("F11", "Alt+F")):
            continue
        tk.Label(grid, text=theme.keys(keys) if "/" not in keys else keys.replace("Ctrl", "⌘" if theme.IS_MAC
                                                                              else "Ctrl"),
                 font=FONTS["kbd"], bg=C["kbd"], fg=C["fg"], padx=px(6), pady=px(1)).grid(
            row=r, column=0, sticky="w", padx=(0, px(14)), pady=px(2))
        tk.Label(grid, text=T(text), font=FONTS["ui"], bg=C["panel"], fg=C["fg"], anchor="w").grid(
            row=r, column=1, sticky="w", pady=px(2))
    dlg.add_buttons("Close", cancel_text="")
    dlg.run()
