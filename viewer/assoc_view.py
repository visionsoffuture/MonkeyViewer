"""File-association chooser: the user decides, per file type, whether Monkey Viewer appears in
"Open with" and whether it becomes the default app. Nothing is associated automatically.
On a Mac, Finder's "Open With" list comes from the app bundle, so only the default-app column is shown."""

import tkinter as tk
from tkinter import messagebox, ttk

from . import audit, formats, theme, winutil
from .theme import C, FONTS, Check, ToolButton, px
from .i18n import T


class AssocDialog(tk.Toplevel):
    def __init__(self, app):
        top = app.root
        super().__init__(top)
        self.withdraw()
        self.app = app
        self.title(T("File associations"))
        self.configure(bg=C["panel"])
        self.transient(top)
        self.minsize(px(620), px(480))
        self.mac = theme.IS_MAC
        state = app.settings.get("assoc")
        if (state is None and theme.IS_WIN) or self.mac:      # a Mac is always asked for the live state
            ow, de, ctx = winutil.current_associations()
            state = {"open_with": sorted(ow), "default": sorted(de), "context": ctx}
        state = state or {"open_with": [], "default": [], "context": True}
        self.open_with = set(state.get("open_with", []))
        self.defaults = set(state.get("default", []))
        self.context = bool(state.get("context", True))
        self.collapsed = {cat: True for cat in formats.CATEGORIES}
        self.collapsed["other"] = True
        self.rows = {}
        self.groups = self._groups()
        self._build()
        self._render()
        w, h = px(820), px(640)
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        winutil.apply_dark_titlebar(self, C["panel"], C["border"])
        self.bind("<Escape>", lambda e: self.destroy())
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _groups(self):
        groups = {}
        for ext, (_kind, cat, label) in sorted(formats.FORMATS.items()):
            key = cat if cat in formats.CATEGORIES else "other"
            groups.setdefault(key, []).append((ext, T(label)))
        order = list(formats.CATEGORIES) + ["other"]
        return [(k, groups[k]) for k in order if k in groups]

    # ── layout ──
    def _build(self):
        head = tk.Frame(self, bg=C["panel"], padx=px(20), pady=px(14))
        head.pack(side="top", fill="x")
        tk.Label(head, text=T("Which files should open in Monkey Viewer?"), font=FONTS["h3"], bg=C["panel"],
                 fg=C["fg_bright"], anchor="w").pack(fill="x")
        if self.mac:
            text = T("Tick the types that should open in Monkey Viewer on double-click. Unticked types keep the app "
                     "they use now.\nMonkey Viewer is always available in Finder \u2192 Open With for the formats it "
                     "supports \u2014 that list does not change anything by itself.")
        else:
            text = T("Tick only the types you want. Everything you leave unticked stays exactly as it is "
                     "on this computer.\n• Open with — Monkey Viewer is listed in the right-click "
                     "\"Open with\" menu.\n• Default — double-click opens the file in Monkey Viewer.")
        tk.Label(head, text=text, font=FONTS["small"], bg=C["panel"], fg=C["fg_dim"], anchor="w",
                 justify="left").pack(fill="x", pady=(px(4), px(8)))
        tools = tk.Frame(head, bg=C["panel"])
        tools.pack(fill="x")
        self.search_var = tk.StringVar()
        box, entry = theme.styled_entry(tools, self.search_var, width=24, font=FONTS["small"])
        box.pack(side="left")
        self.search_hint = tk.Label(box, text=T("Search, e.g. pdf"), bg=C["input"], fg=C["fg_muted"],
                                    font=FONTS["small"])
        self.search_hint.place(x=px(8), rely=0.5, anchor="w")
        self.search_hint.bind("<Button-1>", lambda e: entry.focus_set())
        self.search_var.trace_add("write", lambda *_: self._render())
        for label, cmd in (("Recommended", self._recommended), ("Clear all", self._clear),
                           ("Expand all", lambda: self._expand(True)), ("Collapse all", lambda: self._expand(False))):
            ToolButton(tools, T(label), None, cmd, bg=C["panel"], hover=C["hover_strong"], pad=(10, 4)).pack(
                side="left", padx=(px(6), 0))

        cols = tk.Frame(self, bg=C["chrome"], padx=px(20), pady=px(6))
        cols.pack(side="top", fill="x")
        tk.Label(cols, text=T("FILE TYPE"), font=FONTS["caption"], bg=C["chrome"], fg=C["fg_muted"]).pack(side="left")
        tk.Label(cols, text=T("DEFAULT"), font=FONTS["caption"], bg=C["chrome"], fg=C["fg_muted"], width=10).pack(
            side="right", padx=(0, px(12)))
        if not self.mac:
            tk.Label(cols, text=T("OPEN WITH"), font=FONTS["caption"], bg=C["chrome"], fg=C["fg_muted"],
                     width=11).pack(side="right")

        foot = tk.Frame(self, bg=C["chrome"], padx=px(16), pady=px(10))
        foot.pack(side="bottom", fill="x")
        tk.Frame(self, bg=C["border"], height=1).pack(side="bottom", fill="x")
        self.ctx_check = Check(foot, self.context, lambda v: setattr(self, "context", v), bg=C["chrome"])
        if not self.mac:
            self.ctx_check.pack(side="left")
            tk.Label(foot, text=T('Add "Open in Monkey Viewer" to the right-click menu of every file'),
                     font=FONTS["small"], bg=C["chrome"], fg=C["fg"]).pack(side="left", padx=px(6))
        ToolButton(foot, T("Cancel"), None, self.destroy, bg=C["chrome"], pad=(14, 5)).pack(side="right", padx=(px(6), 0))
        ToolButton(foot, T("Apply"), "check", self.apply, variant="primary", pad=(16, 5)).pack(side="right")
        self.summary = tk.Label(foot, text="", font=FONTS["small"], bg=C["chrome"], fg=C["fg_muted"])
        self.summary.pack(side="right", padx=px(12))

        holder = tk.Frame(self, bg=C["bg"])
        holder.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(holder, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=C["bg"])
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.bind_all_wheel()

    def bind_all_wheel(self):
        def wheel(event):
            if str(event.widget).startswith(str(self)):
                self.canvas.yview_scroll(theme.wheel_units(event, 2), "units")
        self.bind("<MouseWheel>", wheel)
        self.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.bind("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

    # ── rendering ──
    def _render(self):
        for w in self.inner.winfo_children():
            w.destroy()
        query = self.search_var.get().strip().lower().lstrip(".")
        if query:
            self.search_hint.place_forget()
        else:
            self.search_hint.place(x=px(8), rely=0.5, anchor="w")
        for cat, items in self.groups:
            if query:
                items = [(e, l) for e, l in items if query in e or query in l.lower()]
                if not items:
                    continue
            self._section(cat, items, expanded=bool(query) or not self.collapsed.get(cat, True))
        self._update_summary()

    def _section(self, cat, items, expanded):
        title = T(formats.CATEGORIES.get(cat, ("Other formats",))[0])
        color = theme.KIND_COLORS.get(cat, C["fg_dim"])
        head = tk.Frame(self.inner, bg=C["panel"], cursor="hand2")
        head.pack(fill="x", pady=(px(6), 0), padx=px(10))
        arrow = tk.Label(head, text=("▾" if expanded else "▸"), bg=C["panel"], fg=C["fg_dim"],
                         font=FONTS["ui"], width=2)
        arrow.pack(side="left", padx=(px(6), 0), pady=px(6))
        tk.Label(head, image=theme.swatch_image(color, 10), bg=C["panel"]).pack(side="left", padx=px(4))
        name = tk.Label(head, text=title, font=FONTS["ui_bold"], bg=C["panel"], fg=C["fg_bright"])
        name.pack(side="left", padx=px(4))
        exts = [e for e, _l in items]
        n_ow = sum(1 for e in exts if (e in self.defaults if self.mac else (e in self.open_with or e in self.defaults)))
        count = tk.Label(head, text=T("{0} of {1} selected", n_ow, len(exts)), font=FONTS["small"], bg=C["panel"],
                         fg=C["fg_muted"])
        count.pack(side="left", padx=px(10))
        all_def = all(e in self.defaults for e in exts)
        any_def = any(e in self.defaults for e in exts)
        all_ow = all(e in self.open_with or e in self.defaults for e in exts)
        cd = Check(head, all_def, lambda v, x=exts: self._set_many(x, "default", v), bg=C["panel"])
        cd.set(all_def, mixed=any_def)
        cd.pack(side="right", padx=(px(38), px(36)))
        if not self.mac:
            co = Check(head, all_ow, lambda v, x=exts: self._set_many(x, "open", v), bg=C["panel"])
            co.set(all_ow, mixed=n_ow > 0)
            co.pack(side="right")
        for w in (head, arrow, name, count):
            w.bind("<Button-1>", lambda e, c=cat: self._toggle_section(c))
        if not expanded:
            return
        body = tk.Frame(self.inner, bg=C["bg"])
        body.pack(fill="x", padx=px(10))
        for ext, label in items:
            row = tk.Frame(body, bg=C["bg"])
            row.pack(fill="x")
            tk.Label(row, image=theme.badge_image(formats.badge_label("x" + ext), color), bg=C["bg"]).pack(
                side="left", padx=(px(34), px(8)), pady=px(3))
            tk.Label(row, text=ext, font=FONTS["mono"], bg=C["bg"], fg=C["fg"], width=10, anchor="w").pack(side="left")
            tk.Label(row, text=label, font=FONTS["small"], bg=C["bg"], fg=C["fg_dim"], anchor="w").pack(
                side="left", fill="x", expand=True)
            d = Check(row, ext in self.defaults, lambda v, e=ext: self._set_one(e, "default", v), bg=C["bg"])
            d.pack(side="right", padx=(px(38), px(36)))
            if not self.mac:
                o = Check(row, ext in self.open_with or ext in self.defaults,
                          lambda v, e=ext: self._set_one(e, "open", v), bg=C["bg"])
                o.pack(side="right")

    def _toggle_section(self, cat):
        self.collapsed[cat] = not self.collapsed.get(cat, True)
        self._render()

    def _expand(self, on):
        for k in self.collapsed:
            self.collapsed[k] = not on
        self._render()

    # ── state ──
    def _set_one(self, ext, what, value):
        if what == "default":
            (self.defaults.add if value else self.defaults.discard)(ext)
            if value:
                self.open_with.add(ext)
        else:
            (self.open_with.add if value else self.open_with.discard)(ext)
            if not value:
                self.defaults.discard(ext)
        self._render_keep_scroll()

    def _set_many(self, exts, what, value):
        for e in exts:
            if what == "default":
                (self.defaults.add if value else self.defaults.discard)(e)
                if value:
                    self.open_with.add(e)
            else:
                (self.open_with.add if value else self.open_with.discard)(e)
                if not value:
                    self.defaults.discard(e)
        self._render_keep_scroll()

    def _render_keep_scroll(self):
        pos = self.canvas.yview()[0]
        self._render()
        self.update_idletasks()
        self.canvas.yview_moveto(pos)

    def _recommended(self):
        ow, de, ctx = winutil.recommended_associations()
        self.open_with, self.defaults, self.context = set(ow), set(de), ctx
        self.ctx_check.set(ctx)
        self._render_keep_scroll()

    def _clear(self):
        self.open_with, self.defaults = set(), set()
        self._render_keep_scroll()

    def _update_summary(self):
        ow = len(self.open_with | self.defaults)
        self.summary.configure(text=T("Default: {0}", len(self.defaults)) if self.mac else
                               T("Open with: {0}   ·   Default: {1}", ow, len(self.defaults)))

    # ── apply ──
    def apply(self):
        settings = self.app.settings
        ow = sorted(self.open_with | self.defaults)
        de = sorted(self.defaults)
        settings["assoc"] = {"open_with": ow, "default": de, "context": self.context}
        overridden = []
        if theme.IS_WIN or self.mac:
            try:
                backup, overridden = winutil.apply_associations(ow, de, self.context, settings.get("assoc_backup"))
                settings["assoc_backup"] = backup
                settings["assoc_scheme"] = winutil.ICON_SCHEME
            except Exception as exc:  # noqa: BLE001
                winutil.log_error(f"apply_associations failed: {exc!r}")
                messagebox.showerror(T("File associations"), T("Couldn't change the file associations:\n{0}", exc),
                                     parent=self)
                return
        settings.save()
        audit.event("associations", open_with=len(ow), default=len(de), context_menu=bool(self.context),
                    defaults=",".join(de)[:2000])
        self.destroy()
        if self.mac:
            done = len(de) - len(overridden)
            self.app.toast.show(T("Monkey Viewer is now the default app for {0} type{1}", done, 's' if done != 1 else ''),
                                "success", 3500)
            if overridden:
                names = ", ".join(overridden[:12]) + (" \u2026" if len(overridden) > 12 else "")
                messagebox.showinfo(T("macOS kept the current app"),
                                    T("macOS didn't allow the change for: {0}\n\nIn Finder select such a file → File → Get Info → Open with: Monkey Viewer → Change All…", names),
                                    parent=self.app.root)
            return
        if not theme.IS_WIN:
            self.app.toast.show(T("Saved. File associations are applied on Windows and macOS only."), "info", 3500)
            return
        self.app.toast.show(T("Associations updated — Open with: {0}, default: {1}", len(ow), len(de)), "success", 3500)
        if overridden:
            names = ", ".join(overridden[:12]) + (" …" if len(overridden) > 12 else "")
            if messagebox.askyesno(
                    T("Windows keeps your earlier choice"),
                    T('For these types you once picked another app with "Always": {0}\n\nWindows protects that choice, so they still open in the other app. To switch, right-click a file → Open with → Choose another app → Monkey Viewer → Always.\n\nOpen Windows "Default apps" settings now?', names), parent=self.app.root):
                winutil.open_url("ms-settings:defaultapps")


def show(app):
    AssocDialog(app)
