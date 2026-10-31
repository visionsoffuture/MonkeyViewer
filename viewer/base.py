"""Base class shared by every viewer tab."""

import os
import tkinter as tk

from . import formats, theme
from .i18n import T
from .theme import C, ContextBar, Spinner


class Notice(Exception):
    """Raised by a viewer to fall back to the info card with a friendly (non-error) message."""


class BaseTab:
    kind = "file"
    savable = False       # supports Save (Ctrl+S) / Save As
    searchable = False    # supports the find bar (Ctrl+F)
    zoomable = False      # supports Ctrl + / - / 0
    show_bar = True

    def __init__(self, app, path=None, title=None):
        self.app = app
        self.path = os.path.abspath(path) if path else None
        self.id = app.next_tab_id()
        self.title = title or (os.path.basename(path) if path else T("Untitled"))
        self.dirty = False
        self.alive = True
        self.spinner = None
        self.frame = tk.Frame(app.editor_area, bg=C["bg"])
        self.bar = ContextBar(self.frame)
        if self.show_bar:
            self.bar.pack(side="top", fill="x")
        self.body = tk.Frame(self.frame, bg=C["bg"])
        self.body.pack(side="top", fill="both", expand=True)

    # ── identity ──
    @property
    def badge_path(self):
        return self.path or self.title

    @property
    def category(self):
        return formats.category_of(self.badge_path)

    def badge(self):
        return theme.badge_image(formats.badge_label(self.badge_path),
                                 theme.KIND_COLORS.get(self.category, theme.KIND_COLORS["binary"]))

    def type_label(self):
        return formats.label_for(self.badge_path) or T("File")

    # ── lifecycle (override) ──
    def load(self):
        """Read the file. May raise; may start background work with self.run_async."""

    def on_show(self):
        pass

    def on_hide(self):
        pass

    def focus(self):
        try:
            self.frame.focus_set()
        except tk.TclError:
            pass

    def status(self):
        """Segments for the right side of the status bar."""
        return [self.type_label()]

    def edit_action(self, action):
        """Handle copy/cut/paste/undo/redo/selectall when focus is not in a text widget."""
        return False

    def zoom(self, step):
        pass

    # ── printing (File -> Print, Ctrl+P) ──
    def print_document(self):
        """A page-based document (PyMuPDF) to print, or None when this view has nothing to print.
        Default: the text of the tab's text widget, laid out on A4 pages."""
        widget = getattr(self, "text", None)
        if isinstance(widget, tk.Text):
            from . import printing
            return printing.text_document(widget.get("1.0", "end-1c"), self.title)
        return None

    # ── menu bar: per-document items (File / Edit / View and the document's own menu) ──
    def menu_title(self):
        """Name of this document type's own menu in the menu bar (None: no such menu)."""
        return None

    def fill_menu(self, name, menu):
        """Add this document's items to the menu *name* ('file', 'edit', 'view' or 'tools')."""

    # ── saving ──
    def save_filetypes(self):
        return [(T("All files"), "*")]

    def default_extension(self):
        return os.path.splitext(self.title)[1] or ""

    def save_to(self, path):
        """Write to *path*; raise on failure. Return an optional warning message."""
        raise NotImplementedError

    # ── find bar API (when searchable) ──
    def find_initial(self):
        return ""

    def find_update(self, needle, case, mode="jump"):
        return -1, 0

    def find_step(self, direction):
        return -1, 0

    def find_clear(self, commit=False):
        pass

    # ── helpers ──
    def set_dirty(self, dirty):
        dirty = bool(dirty)
        if dirty != self.dirty:
            self.dirty = dirty
            self.app.on_dirty_changed(self)

    def set_title(self, title):
        self.title = title
        self.app.on_title_changed(self)

    def busy(self, text="Loading…"):
        if self.spinner is None:
            self.spinner = Spinner(self.body, text)
        else:
            self.spinner.set_text(text)
            self.spinner.lift()

    def idle(self):
        if self.spinner is not None:
            self.spinner.close()
            self.spinner = None

    def run_async(self, work, done, error=None, text="Loading…"):
        """Run *work()* in a thread; call done(result) / error(exc) back on the UI thread."""
        self.busy(text)

        def finish(ok, value):
            if not self.alive:
                return
            self.idle()
            if ok:
                done(value)
            elif error:
                error(value)
            else:
                self.app.toast.show(f"{self.title}: {value}", "error", 4500)

        self.app.run_in_thread(work, finish)

    def toast(self, message, kind="success", duration=2400):
        self.app.toast.show(message, kind, duration)

    def destroy(self):
        self.alive = False
        self.idle()
        try:
            self.frame.destroy()
        except tk.TclError:
            pass
        self._release()

    def _release(self):
        """Free Tk variables and images now, on the UI thread (not later in a worker's garbage collection)."""
        for key, value in list(self.__dict__.items()):
            if isinstance(value, tk.Variable):
                try:
                    value._tk.globalunsetvar(value._name)
                except Exception:  # noqa: BLE001
                    pass
                value._tk = None
            elif isinstance(value, dict) and key not in ("info",):
                value.clear()
            elif type(value).__name__ == "PhotoImage":
                setattr(self, key, None)


class MessagePanel(tk.Frame):
    """Centered icon + title + text + optional buttons, used for empty/error states."""

    def __init__(self, master, title, text="", icon_name="info", color=None, buttons=()):
        super().__init__(master, bg=C["bg"])
        box = tk.Frame(self, bg=C["bg"])
        box.place(relx=0.5, rely=0.45, anchor="center")
        color = color or C["accent"]
        glyph, _f = theme.icon(icon_name)
        tile = theme.tile_image(color, 64)
        tk.Label(box, image=tile, text=glyph or "", compound="center", font=theme.FONTS["icon_xl"],
                 fg=color, bg=C["bg"]).pack()
        tk.Label(box, text=title, font=theme.FONTS["h2"], bg=C["bg"], fg=C["fg_bright"]).pack(
            pady=(theme.px(14), theme.px(4)))
        if text:
            tk.Label(box, text=text, font=theme.FONTS["ui"], bg=C["bg"], fg=C["fg_dim"], justify="center",
                     wraplength=theme.px(520)).pack()
        if buttons:
            row = tk.Frame(box, bg=C["bg"])
            row.pack(pady=(theme.px(18), 0))
            for i, (label, icon_n, cmd) in enumerate(buttons):
                theme.ToolButton(row, label, icon_n, cmd, variant="primary" if i == 0 else "ghost",
                                 bg=C["bg"] if i else None, hover=C["hover"] if i else None,
                                 pad=(14, 6)).pack(side="left", padx=theme.px(5))
