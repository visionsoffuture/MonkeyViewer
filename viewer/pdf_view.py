"""PDF / document viewer core: continuous pages, thumbnails, zoom, search, text selection."""

import os
import time
import tkinter as tk
from tkinter import ttk

from . import formats, theme
from .base import BaseTab
from .theme import C, FONTS, px
from .i18n import T

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF
    import fitz  # noqa: F401

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

GAP = 18
MAX_FULL_PIXELS = 9_000_000
ZOOM_STEPS = (0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)


def open_pdf_bytes(data):
    return fitz.open(stream=data, filetype="pdf")


class PdfView(BaseTab):
    kind = "pdf"
    searchable = zoomable = True
    editable = False
    THUMB_W = 116

    def __init__(self, app, path=None, title=None, data=None):
        super().__init__(app, path, title)
        self.data = data
        self.doc = None
        self.zoom_mode = "width"
        self.ppp = self.base_ppp = theme.SCALE * 96 / 72
        self.boxes, self.sizes, self.page_rev = [], [], []
        self.photos = {}
        self.thumb_boxes, self.thumb_photos = [], {}
        self.cur = 0
        self.selected = {0}
        self.matches, self.match_i = [], -1
        self.words_cache = {}
        self.text_sel = None
        self._render_job = self._thumb_job = None
        self._drag = None
        self._thumb_anchor = 0
        self.focus_area = "pages"
        self.dark_pages = False
        self.build_ui()

    # ─────────────────────────── UI ───────────────────────────
    def build_ui(self):
        self.build_tools()
        self.build_nav()
        body = self.body
        self.thumb_frame = tk.Frame(body, bg=C["sidebar"], width=px(self.THUMB_W + 56))
        self.thumb_frame.pack_propagate(False)
        self.thumb_canvas = tk.Canvas(self.thumb_frame, bg=C["sidebar"], highlightthickness=0, takefocus=1)
        tsb = ttk.Scrollbar(self.thumb_frame, orient="vertical", style="Side.Vertical.TScrollbar",
                            command=self._thumb_yview)
        self.thumb_canvas.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.thumb_canvas.pack(fill="both", expand=True)
        self.thumb_frame.pack(side="left", fill="y")
        self.thumb_sep = tk.Frame(body, bg=C["border"], width=1)
        self.thumb_sep.pack(side="left", fill="y")
        self._thumbs_auto_hidden = False
        body.bind("<Configure>", self._fit_thumbs, add="+")
        main = tk.Frame(body, bg=C["canvas"])
        main.pack(side="left", fill="both", expand=True)
        self.main = main
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(main, bg=C["canvas"], highlightthickness=0, takefocus=1)
        self.vsb = ttk.Scrollbar(main, orient="vertical", style="Canvas.Vertical.TScrollbar", command=self._yview)
        self.hsb = ttk.Scrollbar(main, orient="horizontal", style="Canvas.Horizontal.TScrollbar",
                                 command=self._xview)
        self.canvas.configure(yscrollcommand=self._on_ys, xscrollcommand=self._on_xs)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.hsb.grid_remove()
        self.app.register_drop(self.canvas)
        c = self.canvas
        c.bind("<Configure>", self._on_configure)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: (c.xview_scroll(theme.wheel_units(e, 1), "units"),
                                                self.schedule_render(), "break")[2])
        c.bind(f"<{theme.PRIMARY}-MouseWheel>", self._on_ctrl_wheel)
        c.bind("<Button-4>", lambda e: self._scroll(-3))
        c.bind("<Button-5>", lambda e: self._scroll(3))
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Double-Button-1>", self._on_double)
        _right, middle = theme.mouse_buttons(c)
        c.bind(f"<ButtonPress-{middle}>", lambda e: c.scan_mark(e.x, e.y))
        c.bind(f"<B{middle}-Motion>", lambda e: (c.scan_dragto(e.x, e.y, gain=1), self.schedule_render()))
        theme.bind_right(c, self._on_context)
        c.bind("<Motion>", self._on_hover)
        for key, fn in (("<Prior>", lambda: self._scroll_pages(-1)), ("<Next>", lambda: self._scroll_pages(1)),
                        ("<Up>", lambda: self._scroll(-2)), ("<Down>", lambda: self._scroll(2)),
                        ("<Home>", lambda: self.goto_page(0)), ("<End>", lambda: self.goto_page(self.page_count - 1)),
                        ("<Delete>", self.on_delete_key), ("<Escape>", self.on_escape)):
            c.bind(key, lambda e, f=fn: (f(), "break")[1])
        t = self.thumb_canvas
        t.bind("<Button-1>", self._on_thumb_click)
        t.bind(f"<{theme.PRIMARY}-Button-1>", lambda e: self._on_thumb_click(e, "toggle"))
        t.bind("<Shift-Button-1>", lambda e: self._on_thumb_click(e, "range"))
        theme.bind_right(t, self._on_thumb_menu)
        t.bind("<MouseWheel>", lambda e: (t.yview_scroll(theme.wheel_units(e, 2), "units"), self.schedule_thumbs(),
                                          "break")[2])
        t.bind("<Button-4>", lambda e: (t.yview_scroll(-2, "units"), self.schedule_thumbs()))
        t.bind("<Button-5>", lambda e: (t.yview_scroll(2, "units"), self.schedule_thumbs()))
        t.bind("<Configure>", lambda e: self.layout_thumbs())
        t.bind("<Delete>", lambda e: (self.on_delete_key(), "break")[1])
        t.bind("<Up>", lambda e: (self.goto_page(self.cur - 1, select=True), "break")[1])
        t.bind("<Down>", lambda e: (self.goto_page(self.cur + 1, select=True), "break")[1])

    def build_tools(self):
        """Subclasses add their tools to the left side of the context bar."""

    def build_nav(self):
        bar = self.bar
        self.zoom_btn = bar.button("100%", None, tooltip=T("Zoom"), side="right", menu=self._zoom_menu)
        bar.button("", "zoomin", lambda: self.zoom(1), T("Zoom in  (Ctrl +)"), side="right", compact=True)
        bar.button("", "zoomout", lambda: self.zoom(-1), T("Zoom out  (Ctrl −)"), side="right", compact=True)
        # re-order so it reads  [-] 100% [+]
        kids = self.bar.right.pack_slaves()[-3:]
        for w in kids:
            w.pack_forget()
        for w in (kids[2], kids[0], kids[1]):
            w.pack(side="left", padx=px(1), pady=px(6))
        bar.divider(side="right")
        box = tk.Frame(bar.right, bg=C["bg"])
        box.pack(side="left", padx=px(4))
        self.page_var = tk.StringVar(value="1")
        ebox, self.page_entry = theme.styled_entry(box, self.page_var, width=3, font=FONTS["small"])
        self.page_entry.configure(justify="center")
        self.page_entry.pack_configure(padx=px(4), pady=px(2))
        ebox.pack(side="left", pady=px(9))
        self.page_total = tk.Label(box, text="/ 0", bg=C["bg"], fg=C["fg_muted"], font=FONTS["small"])
        self.page_total.pack(side="left", padx=(px(6), 0))
        self.page_entry.bind("<Return>", self._on_page_entry)
        bar.button("", "pane", self.toggle_thumbs, T("Show / hide page thumbnails"), side="right", compact=True)

    def _zoom_menu(self, m):
        for label, value in (("Fit width", "width"), ("Fit page", "page"), (None, None), ("50%", 0.5),
                             ("75%", 0.75), ("100%", 1.0), ("125%", 1.25), ("150%", 1.5), ("200%", 2.0),
                             ("300%", 3.0), ("400%", 4.0)):
            if label is None:
                m.add_separator()
            elif isinstance(value, str):
                m.add_command(label=T(label), command=lambda v=value: self.set_zoom(mode=v))
            else:
                m.add_command(label=label, command=lambda v=value: self.set_zoom(value=v))

    def _thumbs_shown(self):
        return bool(self.thumb_frame.winfo_manager())

    def _show_thumbs(self, show):
        if show and not self._thumbs_shown():
            self.thumb_frame.pack(side="left", fill="y", before=self.main)
            self.thumb_sep.pack(side="left", fill="y", before=self.main)
        elif not show and self._thumbs_shown():
            self.thumb_frame.pack_forget()
            self.thumb_sep.pack_forget()

    def toggle_thumbs(self):
        self._thumbs_auto_hidden = False
        self._show_thumbs(not self._thumbs_shown())

    def _fit_thumbs(self, event):
        """Narrow window: the page gets the room and the thumbnails come back when it is wide enough."""
        if event.widget is not self.body:
            return
        if self._thumbs_shown() and event.width < px(560) and self.page_count > 1:
            self._thumbs_auto_hidden = True
            self._show_thumbs(False)
        elif self._thumbs_auto_hidden and event.width >= px(680):
            self._thumbs_auto_hidden = False
            self._show_thumbs(True)

    # ─────────────────────────── document ───────────────────────────
    @property
    def page_count(self):
        return len(self.doc) if self.doc is not None else 0

    def open_document(self):
        with open(self.path, "rb") as fh:
            raw = fh.read()
        ext = formats.ext_of(self.path)[1:] or "pdf"
        return fitz.open(stream=raw, filetype="pdf" if ext == "ai" else ext)

    def load(self):
        doc = open_pdf_bytes(self.data) if self.data is not None else self.open_document()
        self.data = None
        if doc.needs_pass:
            for _ in range(3):
                pw = theme.ask_string(self.app.root, T("Password required"),
                                      T("{0} is protected. Enter the password:", self.title), secret=True)
                if pw is None:
                    raise ValueError(T("password required"))
                if doc.authenticate(pw):
                    break
            else:
                raise ValueError(T("wrong password"))
        self.set_document(doc)
        if self.path and doc.is_pdf and not doc.needs_pass:
            self.check_signatures()

    # ─────────────────────────── digital signatures ───────────────────────────
    def check_signatures(self):
        """Look for PDF signatures in the background; signed documents get a banner with the result."""
        from . import pdfsig
        path = self.path

        def finish(ok, sigs):
            if ok and sigs and self.path == path:
                self.signatures = sigs
                self._signature_banner(sigs)
                from . import audit
                audit.event("signature", warning=not all(s["intact"] for s in sigs), path=path, check="pdf",
                            result=",".join(pdfsig.summary(s)[0] for s in sigs),
                            signer=";".join(s["signer"] or s["name"] or "?" for s in sigs)[:300])
        self.app.run_in_thread(lambda: pdfsig.signatures(path), finish)

    def _signature_banner(self, sigs):
        from . import pdfsig
        if getattr(self, "sig_banner", None) is not None:
            self.sig_banner.destroy()
        levels = [pdfsig.summary(s)[0] for s in sigs]
        worst = "bad" if "bad" in levels else "warning" if "warning" in levels else "ok"
        colour = {"ok": C["success"], "warning": C["warning"], "bad": C["danger"]}
        box = tk.Frame(self.body, bg=C["panel"], padx=px(14), pady=px(6))
        first = next(iter(self.body.pack_slaves()), None)
        box.pack(side="top", fill="x", before=first) if first is not None else box.pack(side="top", fill="x")
        self.sig_banner = box
        text = tk.Frame(box, bg=C["panel"])
        text.pack(side="left", fill="x", expand=True)
        for s in sigs[:3]:
            level, line = pdfsig.summary(s)
            mark = {"ok": "\u2713 ", "warning": "! ", "bad": "\u2717 "}[level]
            when = f"  \u00b7  {s['time']:%Y-%m-%d %H:%M}" if s.get("time") else ""
            tk.Label(text, text=mark + line + when, bg=C["panel"], anchor="w", font=FONTS["small_bold"],
                     fg=colour[level], justify="left", wraplength=px(760)).pack(fill="x")
        if len(sigs) > 3:
            tk.Label(text, text=T("+{0} more signatures", len(sigs) - 3), bg=C["panel"], fg=C["fg_muted"],
                     font=FONTS["small"], anchor="w").pack(fill="x")
        theme.ToolButton(box, T("Details"), "info", self.signature_details, bg=C["panel"], hover=C["hover_strong"],
                         pad=(10, 4)).pack(side="right", padx=(px(6), 0))
        if any(s["cert"] is not None for s in sigs):
            theme.ToolButton(box, T("Check signer trust"), "check", self.check_signer_trust, bg=C["panel"],
                             hover=C["hover_strong"], pad=(10, 4)).pack(side="right")
        if worst != "ok":
            box.configure(highlightthickness=1, highlightbackground=colour[worst])

    def menu_title(self):
        return T("Document")

    def fill_menu(self, name, m):
        if name == "view":
            m.add_command(label=T("Zoom in"), accelerator=theme.keys("Ctrl++"), command=lambda: self.zoom(1))
            m.add_command(label=T("Zoom out"), accelerator=theme.keys("Ctrl+-"), command=lambda: self.zoom(-1))
            m.add_command(label=T("Actual size"), accelerator=theme.keys("Ctrl+0"),
                          command=lambda: self.set_zoom(value=1.0))
            m.add_command(label=T("Fit width"), command=lambda: self.set_zoom(mode="width"))
            m.add_command(label=T("Fit page"), command=lambda: self.set_zoom(mode="page"))
            m.add_separator()
            m.add_checkbutton(label=T("Page thumbnails"), command=self.toggle_thumbs,
                              variable=theme.menu_var(m, "bool", self._thumbs_shown()))
            m.add_separator()
            last = max(0, self.page_count - 1)
            m.add_command(label=T("First page"), accelerator="Home", command=lambda: self.goto_page(0))
            m.add_command(label=T("Previous page"), accelerator="PgUp",
                          command=lambda: self.goto_page(self.cur - 1))
            m.add_command(label=T("Next page"), accelerator="PgDn", command=lambda: self.goto_page(self.cur + 1))
            m.add_command(label=T("Last page"), accelerator="End", command=lambda: self.goto_page(last))
        elif name == "tools":
            self.fill_page_menu(m)
            if getattr(self, "signatures", None):
                m.add_separator()
                m.add_command(label=T("Digital signatures\u2026"), command=self.signature_details)
                m.add_command(label=T("Check signer trust"), command=self.check_signer_trust)

    def print_document(self):
        return self.doc

    def signature_details(self):
        """The signature panel: one card per signature with its checks and certificate."""
        from . import sig_view
        return sig_view.show(self)

    def check_signer_trust(self):
        from . import crypto
        sigs = getattr(self, "signatures", [])

        def work():
            out = {}
            for n, s in enumerate(sigs, 1):
                if s["cert"] is not None:
                    ok, summary, _text = crypto.verify_trust(s["cert"])
                    text = (T("Trusted: the operating system accepts this certificate.") if ok else
                            T("Not trusted or not valid according to the operating system.") if ok is False else
                            summary)
                    out[n] = (ok, text if ok or not summary or summary == text else f"{text} ({summary})")
            return out

        def done(trust):
            panel = self.signature_details()
            panel.set_trust(trust)

        self.run_async(work, done, text=T("Checking the certificate chain…"))

    def set_document(self, doc, keep_view=False):
        view = (self.canvas.yview()[0], self.canvas.xview()[0]) if keep_view else None
        old = self.doc
        self.doc = doc
        if old is not None and old is not doc:
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        self.sizes = [(p.rect.width, p.rect.height) for p in doc]
        self.page_rev = [0] * len(self.sizes)
        self.words_cache.clear()
        self.photos.clear()
        self.thumb_photos.clear()
        self.matches, self.match_i, self.text_sel = [], -1, None
        self.cur = min(self.cur, max(0, len(self.sizes) - 1))
        self.selected = {i for i in self.selected if i < len(self.sizes)} or {self.cur}
        self.page_total.configure(text=f"/ {len(self.sizes)}")
        if old is None and len(self.sizes) == 1 and self._thumbs_shown():
            self.toggle_thumbs()
        if self.canvas.winfo_width() > 1:
            self.layout()
            if view:
                self.canvas.yview_moveto(view[0])
                self.canvas.xview_moveto(view[1])
            self.layout_thumbs()
        self.schedule_render()

    def refresh_pages(self, pages=None, structure=False):
        """Re-render after an edit. structure=True when pages were added/removed/rotated."""
        if structure:
            self.set_document(self.doc, keep_view=True)
            return
        for i in pages if pages is not None else range(self.page_count):
            if 0 <= i < self.page_count:
                self.page_rev[i] += 1
                self.words_cache.pop(i, None)
                self.thumb_photos.pop(i, None)
        self.schedule_render()
        self.schedule_thumbs()

    # ─────────────────────────── layout & zoom ───────────────────────────
    def _fit_ppp(self, mode):
        cw = max(100, self.canvas.winfo_width() - 2 * px(GAP))
        ch = max(100, self.canvas.winfo_height() - 2 * px(GAP))
        if not self.sizes:
            return self.base_ppp
        if mode == "width":
            return cw / max(w for w, _h in self.sizes)
        w, h = self.sizes[self.cur]
        return min(cw / w, ch / h)

    def layout(self):
        c = self.canvas
        if mode := self.zoom_mode:
            self.ppp = self._fit_ppp(mode)
        gap = px(GAP)
        y, maxw = gap, 0
        self.boxes = []
        for w, h in self.sizes:
            pw, ph = w * self.ppp, h * self.ppp
            self.boxes.append([0, y, pw, ph])
            y += ph + gap
            maxw = max(maxw, pw)
        total_w = max(maxw + 2 * gap, c.winfo_width())
        for b in self.boxes:
            b[0] = (total_w - b[2]) / 2
        c.delete("all")
        self.photos.clear()
        for i, (x, yy, w, h) in enumerate(self.boxes):
            c.create_rectangle(x + 2, yy + 3, x + w + 2, yy + h + 3, fill=C["page_shadow"], outline="")
            c.create_rectangle(x, yy, x + w, yy + h, fill="#ffffff" if not self.dark_pages else "#000000",
                               outline="", tags=(f"bg{i}",))
        c.configure(scrollregion=(0, 0, total_w, y))
        self.zoom_btn.set_text(f"{round(self.ppp / self.base_ppp * 100)}%")
        self.draw_overlays()

    def set_zoom(self, mode=None, value=None, anchor=None):
        c = self.canvas
        if not self.boxes:
            return
        if anchor is None:
            anchor = (c.winfo_width() / 2, c.winfo_height() / 2)
        ax, ay = c.canvasx(anchor[0]), c.canvasy(anchor[1])
        page = self.page_at(ax, ay, nearest=True)
        bx, by, _bw, _bh = self.boxes[page]
        px_, py_ = (ax - bx) / self.ppp, (ay - by) / self.ppp
        if mode:
            self.zoom_mode = mode
        else:
            self.zoom_mode = None
            self.ppp = max(0.1, min(12.0, value)) * self.base_ppp
        self.layout()
        bx, by, _bw, _bh = self.boxes[page]
        nx, ny = bx + px_ * self.ppp, by + py_ * self.ppp
        x0, y0, x1, y1 = (float(v) for v in c.cget("scrollregion").split())
        if x1 > c.winfo_width():
            c.xview_moveto(max(0, (nx - anchor[0]) / x1))
        c.yview_moveto(max(0, (ny - anchor[1]) / y1))
        self.schedule_render()
        self.app.update_status()

    def zoom(self, step):
        if step == 0:
            self.set_zoom(value=1.0)
            return
        current = self.ppp / self.base_ppp
        if step > 0:
            nxt = next((z for z in ZOOM_STEPS if z > current * 1.01), ZOOM_STEPS[-1])
        else:
            nxt = next((z for z in reversed(ZOOM_STEPS) if z < current * 0.99), ZOOM_STEPS[0])
        self.set_zoom(value=nxt, anchor=getattr(self, "_zoom_anchor", None))
        self._zoom_anchor = None

    def _on_ctrl_wheel(self, event):
        self._zoom_anchor = (event.x, event.y)
        self.zoom(1 if event.delta > 0 else -1)
        return "break"

    def _on_configure(self, _event):
        if not self.sizes:
            return
        if self.zoom_mode or not self.boxes:
            frac = self.canvas.yview()[0]
            self.layout()
            self.canvas.yview_moveto(frac)
        self.schedule_render()

    # ─────────────────────────── scrolling ───────────────────────────
    def _yview(self, *args):
        self.canvas.yview(*args)
        self.schedule_render()

    def _xview(self, *args):
        self.canvas.xview(*args)
        self.schedule_render()

    def _on_ys(self, first, last):
        self.vsb.set(first, last)
        self.schedule_render()

    def _on_xs(self, first, last):
        self.hsb.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.hsb.grid_remove()
        else:
            self.hsb.grid()

    def _scroll(self, units):
        self.canvas.yview_scroll(units, "units")
        self.schedule_render()
        return "break"

    def _on_wheel(self, event):
        return self._scroll(theme.wheel_units(event, 3))

    def _scroll_pages(self, n):
        self.canvas.yview_scroll(n, "pages")
        self.schedule_render()

    def goto_page(self, i, select=False, top=True):
        if not self.boxes:
            return
        i = max(0, min(self.page_count - 1, i))
        _x, y, _w, _h = self.boxes[i]
        total = float(self.canvas.cget("scrollregion").split()[3])
        self.canvas.yview_moveto(max(0, (y - px(GAP) / 2) / total))
        self.cur = i
        if select:
            self.selected = {i}
            self._thumb_anchor = i
        self.schedule_render()
        self.draw_thumbs_state()
        self.ensure_thumb_visible(i)

    def _on_page_entry(self, _event):
        try:
            self.goto_page(int(self.page_var.get()) - 1, select=True)
        except ValueError:
            pass
        self.canvas.focus_set()

    # ─────────────────────────── rendering ───────────────────────────
    def schedule_render(self, delay=12):
        if self._render_job is None and self.alive:
            self._render_job = self.app.root.after(delay, self._render_visible)

    def _render_visible(self):
        self._render_job = None
        if not self.alive or self.doc is None or not self.boxes:
            return
        c = self.canvas
        vx0, vy0 = c.canvasx(0), c.canvasy(0)
        vw, vh = c.winfo_width(), c.winfo_height()
        vx1, vy1 = vx0 + vw, vy0 + vh
        margin = vh * 0.6
        visible = [i for i, (x, y, w, h) in enumerate(self.boxes) if y + h >= vy0 - margin and y <= vy1 + margin]
        for i in list(self.photos):
            if i not in visible:
                c.delete(self.photos[i][2])
                del self.photos[i]
        deadline = time.perf_counter() + 0.10
        for i in sorted(visible, key=lambda k: abs(self.boxes[k][1] - vy0)):
            x, y, w, h = self.boxes[i]
            clip = None
            if w * h > MAX_FULL_PIXELS:
                cx0, cy0 = max(x, vx0 - 64), max(y, vy0 - 64)
                cx1, cy1 = min(x + w, vx1 + 64), min(y + h, vy1 + 64)
                if cx1 <= cx0 or cy1 <= cy0:
                    continue
                q = 256
                cx0, cy0 = x + (cx0 - x) // q * q, y + (cy0 - y) // q * q
                cx1, cy1 = min(x + w, x + ((cx1 - x) // q + 1) * q), min(y + h, y + ((cy1 - y) // q + 1) * q)
                clip = (round(cx0 - x), round(cy0 - y), round(cx1 - x), round(cy1 - y))
            key = (round(self.ppp, 5), self.page_rev[i], clip, self.dark_pages)
            if i in self.photos and self.photos[i][0] == key:
                continue
            if time.perf_counter() > deadline:
                self.schedule_render(1)
                break
            try:
                photo = self.render_page(i, clip)
            except Exception:  # noqa: BLE001
                continue
            if i in self.photos:
                c.delete(self.photos[i][2])
            ox, oy = (x + clip[0], y + clip[1]) if clip else (x, y)
            item = c.create_image(ox, oy, image=photo, anchor="nw", tags=("page",))
            self.photos[i] = (key, photo, item)
        c.tag_raise("overlay")
        c.tag_raise("editor")
        self.update_current_page()

    def render_page(self, i, clip=None):
        page = self.doc[i]
        mat = fitz.Matrix(self.ppp, self.ppp)
        rect = None
        if clip:
            rect = fitz.Rect(clip[0] / self.ppp, clip[1] / self.ppp, clip[2] / self.ppp, clip[3] / self.ppp)
        pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False, annots=True)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if self.dark_pages:
            from PIL import ImageOps
            img = ImageOps.invert(img)
        return ImageTk.PhotoImage(img)

    def page_at(self, cx, cy, nearest=False):
        for i, (x, y, w, h) in enumerate(self.boxes):
            if y <= cy <= y + h and (nearest or x <= cx <= x + w):
                return i
        if nearest and self.boxes:
            return min(range(len(self.boxes)), key=lambda k: min(abs(self.boxes[k][1] - cy),
                                                                abs(self.boxes[k][1] + self.boxes[k][3] - cy)))
        return None

    def update_current_page(self):
        c = self.canvas
        mid = c.canvasy(c.winfo_height() * 0.35)
        page = self.page_at(c.canvasx(c.winfo_width() / 2), mid, nearest=True)
        if page is not None and page != self.cur:
            self.cur = page
            self.draw_thumbs_state()
            self.ensure_thumb_visible(page)
        if self.app.root.focus_get() is not self.page_entry:
            self.page_var.set(str(self.cur + 1))
        if self.app.active is self:
            self.app.update_status()

    # ── coordinate helpers ──
    def to_page(self, i, cx, cy):
        """Canvas -> unrotated page coordinates (what PyMuPDF expects for editing)."""
        x, y, _w, _h = self.boxes[i]
        p = fitz.Point((cx - x) / self.ppp, (cy - y) / self.ppp)
        return p * self.doc[i].derotation_matrix

    def to_display(self, i, cx, cy):
        x, y, _w, _h = self.boxes[i]
        return fitz.Point((cx - x) / self.ppp, (cy - y) / self.ppp)

    def page_rect_to_canvas(self, i, rect):
        r = fitz.Rect(rect) * self.doc[i].rotation_matrix
        x, y, _w, _h = self.boxes[i]
        return (x + r.x0 * self.ppp, y + r.y0 * self.ppp, x + r.x1 * self.ppp, y + r.y1 * self.ppp)

    def canvas_rect_to_page(self, i, x0, y0, x1, y1):
        a, b = self.to_page(i, x0, y0), self.to_page(i, x1, y1)
        return fitz.Rect(a, b).normalize()

    # ─────────────────────────── overlays ───────────────────────────
    def draw_overlays(self):
        c = self.canvas
        c.delete("overlay")
        if not self.boxes:
            return
        for k, (i, r) in enumerate(self.matches):
            x0, y0, x1, y1 = self.page_rect_to_canvas(i, r)
            cur = k == self.match_i
            c.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline=C["find_cur_bg"] if cur else C["accent"],
                               width=2 if cur else 1, tags=("overlay",),
                               fill=C["find_cur_bg"] if cur else "", stipple="gray25" if cur else "")
        if self.text_sel:
            i, rects, _text = self.text_sel
            for r in rects:
                x0, y0, x1, y1 = self.page_rect_to_canvas(i, r)
                c.create_rectangle(x0, y0, x1, y1, fill=C["accent"], stipple="gray50", outline="",
                                   tags=("overlay",))
        self.draw_extra_overlays()

    def draw_extra_overlays(self):
        pass

    # ─────────────────────────── thumbnails ───────────────────────────
    def _thumb_yview(self, *args):
        self.thumb_canvas.yview(*args)
        self.schedule_thumbs()

    def layout_thumbs(self):
        t = self.thumb_canvas
        t.delete("all")
        self.thumb_photos.clear()
        tw = px(self.THUMB_W)
        pw = max(t.winfo_width(), tw + px(20))
        y = px(14)
        self.thumb_boxes = []
        for w, h in self.sizes:
            s = tw / w
            if h * s > tw * 1.42:
                s = tw * 1.42 / h
            bw, bh = w * s, h * s
            x = (pw - bw) / 2
            self.thumb_boxes.append((x, y, bw, bh, s))
            t.create_rectangle(x - 3, y - 3, x + bw + 3, y + bh + 3, outline="", width=2, tags=("frame",))
            t.create_rectangle(x, y, x + bw, y + bh, fill="#ffffff", outline=C["border_strong"])
            y += bh + px(30)
        t.configure(scrollregion=(0, 0, pw, y))
        self.draw_thumbs_state()
        self.schedule_thumbs()

    def draw_thumbs_state(self):
        t = self.thumb_canvas
        t.delete("state")
        for i, (x, y, bw, bh, _s) in enumerate(self.thumb_boxes):
            sel = i in self.selected
            cur = i == self.cur
            if sel or cur:
                t.create_rectangle(x - 4, y - 4, x + bw + 4, y + bh + 4, outline=C["accent"] if sel else
                                   C["border_strong"], width=2, tags=("state",))
            t.create_text(x + bw / 2, y + bh + px(13), text=str(i + 1), fill=C["fg_bright"] if sel else C["fg_muted"],
                          font=FONTS["small_bold"] if sel else FONTS["small"], tags=("state",))

    def ensure_thumb_visible(self, i):
        if not self.thumb_boxes or not self.thumb_frame.winfo_ismapped():
            return
        t = self.thumb_canvas
        _x, y, _w, h, _s = self.thumb_boxes[i]
        top, bottom = t.canvasy(0), t.canvasy(t.winfo_height())
        total = float(t.cget("scrollregion").split()[3])
        if y < top or y + h > bottom:
            t.yview_moveto(max(0, (y - px(30)) / total))
            self.schedule_thumbs()

    def schedule_thumbs(self):
        if self._thumb_job is None and self.alive:
            self._thumb_job = self.app.root.after(30, self._render_thumbs)

    def _render_thumbs(self):
        self._thumb_job = None
        if not self.alive or self.doc is None:
            return
        t = self.thumb_canvas
        top, bottom = t.canvasy(0) - 200, t.canvasy(t.winfo_height()) + 400
        done = 0
        for i, (x, y, bw, bh, s) in enumerate(self.thumb_boxes):
            if y + bh < top or y > bottom:
                continue
            key = self.page_rev[i]
            if i in self.thumb_photos and self.thumb_photos[i][0] == key:
                continue
            if done >= 4:
                self.schedule_thumbs()
                return
            try:
                pix = self.doc[i].get_pixmap(matrix=fitz.Matrix(s, s), alpha=False, annots=True)
                photo = ImageTk.PhotoImage(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            except Exception:  # noqa: BLE001
                continue
            if i in self.thumb_photos:
                t.delete(self.thumb_photos[i][2])
            item = t.create_image(x, y, image=photo, anchor="nw")
            self.thumb_photos[i] = (key, photo, item)
            done += 1

    def _thumb_index(self, event):
        y = self.thumb_canvas.canvasy(event.y)
        for i, (_x, ty, _w, h, _s) in enumerate(self.thumb_boxes):
            if ty - px(6) <= y <= ty + h + px(24):
                return i
        return None

    def _on_thumb_click(self, event, mode="single"):
        self.thumb_canvas.focus_set()
        self.focus_area = "thumbs"
        i = self._thumb_index(event)
        if i is None:
            return "break"
        if mode == "toggle":
            self.selected ^= {i}
            self.selected = self.selected or {i}
            self._thumb_anchor = i
        elif mode == "range":
            a, b = sorted((self._thumb_anchor, i))
            self.selected = set(range(a, b + 1))
        else:
            self.selected = {i}
            self._thumb_anchor = i
        self.goto_page(i)
        self.draw_thumbs_state()
        return "break"

    def _on_thumb_menu(self, event):
        i = self._thumb_index(event)
        if i is None:
            return
        if i not in self.selected:
            self.selected = {i}
            self.draw_thumbs_state()
        self.focus_area = "thumbs"
        m = theme.popup_menu(self.app.root)
        self.fill_page_menu(m)
        theme.show_menu(m, event.x_root, event.y_root)

    def fill_page_menu(self, m):
        m.add_command(label=T("Export page images…"), command=self.export_images)

    # ─────────────────────────── mouse (text selection) ───────────────────────────
    def _on_press(self, event):
        self.canvas.focus_set()
        self.focus_area = "pages"
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        i = self.page_at(cx, cy)
        self.on_tool_press(event, cx, cy, i)

    def _on_motion(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.on_tool_drag(event, cx, cy)

    def _on_release(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.on_tool_release(event, cx, cy)

    def _on_double(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        i = self.page_at(cx, cy)
        if i is None:
            return
        p = self.to_page(i, cx, cy)
        for w in self.words(i):
            if fitz.Rect(w[:4]).contains(p):
                line = [x for x in self.words(i) if x[5] == w[5] and x[6] == w[6]]
                self.set_text_selection(i, line)
                break

    def _on_hover(self, event):
        cursor = self.cursor_for(event)
        if self.canvas.cget("cursor") != cursor:
            self.canvas.configure(cursor=cursor)

    def cursor_for(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        return "xterm" if self.page_at(cx, cy) is not None else ""

    def on_tool_press(self, event, cx, cy, i):
        self.text_sel = None
        self.draw_overlays()
        if i is None:
            self._drag = ("pan", event.x, event.y)
            self.canvas.scan_mark(event.x, event.y)
            return
        self._drag = ("select", i, cx, cy)

    def on_tool_drag(self, event, cx, cy):
        d = self._drag
        if not d:
            return
        if d[0] == "pan":
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            self.schedule_render()
        elif d[0] == "select":
            _k, i, x0, y0 = d
            self.canvas.delete("rubber")
            self.canvas.create_rectangle(x0, y0, cx, cy, outline=C["accent"], dash=(3, 2), tags=("rubber", "overlay"))
            r = self.canvas_rect_to_page(i, x0, y0, cx, cy)
            hits = [w for w in self.words(i) if fitz.Rect(w[:4]).intersects(r)]
            self.set_text_selection(i, hits, redraw=False)
            self.canvas.delete("selrect")
            for w in hits:
                a = self.page_rect_to_canvas(i, w[:4])
                self.canvas.create_rectangle(*a, fill=C["accent"], stipple="gray50", outline="", tags=("selrect", "overlay"))

    def on_tool_release(self, event, cx, cy):
        d, self._drag = self._drag, None
        self.canvas.delete("rubber")
        if d and d[0] == "select":
            self.draw_overlays()

    def words(self, i):
        if i not in self.words_cache:
            try:
                self.words_cache[i] = self.doc[i].get_text("words", sort=True)
            except Exception:  # noqa: BLE001
                self.words_cache[i] = []
        return self.words_cache[i]

    def set_text_selection(self, i, words, redraw=True):
        if not words:
            self.text_sel = None
        else:
            lines, last = [], None
            for w in words:
                key = (w[5], w[6])
                if key != last:
                    lines.append([])
                    last = key
                lines[-1].append(w[4])
            self.text_sel = (i, [w[:4] for w in words], "\n".join(" ".join(ln) for ln in lines))
        if redraw:
            self.draw_overlays()
        if self.app.active is self:
            self.app.update_status()

    def _on_context(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        i = self.page_at(cx, cy)
        m = theme.popup_menu(self.app.root)
        m.add_command(label=T("Copy"), accelerator="Ctrl+C", state="normal" if self.text_sel else "disabled",
                      command=lambda: self.edit_action("copy"))
        if i is not None:
            m.add_command(label=T("Select all text on this page"),
                          command=lambda: self.set_text_selection(i, self.words(i)))
            m.add_command(label=T("Copy all text of this page"),
                          command=lambda: self._copy_text(self.doc[i].get_text()))
        m.add_separator()
        if i is not None:
            self.selected = {i} if i not in self.selected else self.selected
            self.cur = i
            self.draw_thumbs_state()
            self.fill_page_menu(m)
            m.add_separator()
        m.add_command(label=T("Fit width"), command=lambda: self.set_zoom(mode="width"))
        m.add_command(label=T("Fit page"), command=lambda: self.set_zoom(mode="page"))
        theme.show_menu(m, event.x_root, event.y_root)

    def _copy_text(self, text):
        self.app.set_clipboard(text)
        self.toast(T("Copied {0:,} characters", len(text)))

    def edit_action(self, action):
        if action == "copy" and self.text_sel:
            self._copy_text(self.text_sel[2])
            return True
        if action == "selectall" and self.focus_area == "pages" and self.doc is not None:
            self.set_text_selection(self.cur, self.words(self.cur))
            return True
        return False

    def on_delete_key(self):
        pass

    def on_escape(self):
        self.text_sel = None
        self.draw_overlays()

    # ─────────────────────────── search ───────────────────────────
    def find_initial(self):
        if self.text_sel and len(self.text_sel[2]) < 100 and "\n" not in self.text_sel[2]:
            return self.text_sel[2]
        return ""

    def find_update(self, needle, case, mode="jump"):
        keep = self.match_i
        self.matches, self.match_i = [], -1
        if needle and self.doc is not None:
            for i in range(self.page_count):
                try:
                    hits = self.doc[i].search_for(needle)
                except Exception:  # noqa: BLE001
                    hits = []
                if case and hits:
                    hits = [r for r in hits if needle in self.doc[i].get_textbox(r + (-1, -1, 1, 1))]
                self.matches += [(i, r) for r in hits]
                if len(self.matches) > 5000:
                    break
        if self.matches:
            if mode == "jump":
                first = next((k for k, (i, _r) in enumerate(self.matches) if i >= self.cur), 0)
                self._goto_match(first)
            elif mode == "keep" and keep >= 0:
                self._goto_match(min(keep, len(self.matches) - 1), scroll=False)
        self.draw_overlays()
        return self.match_i, len(self.matches)

    def find_step(self, direction):
        if not self.matches:
            return -1, 0
        self._goto_match((self.match_i + direction) % len(self.matches))
        return self.match_i, len(self.matches)

    def _goto_match(self, k, scroll=True):
        self.match_i = k
        i, r = self.matches[k]
        if scroll:
            x0, y0, x1, y1 = self.page_rect_to_canvas(i, r)
            c = self.canvas
            total_h = float(c.cget("scrollregion").split()[3])
            total_w = float(c.cget("scrollregion").split()[2])
            top, bottom = c.canvasy(0), c.canvasy(c.winfo_height())
            if y0 < top + 40 or y1 > bottom - 40:
                c.yview_moveto(max(0, (y0 - c.winfo_height() / 3) / total_h))
            left, right = c.canvasx(0), c.canvasx(c.winfo_width())
            if x0 < left or x1 > right:
                c.xview_moveto(max(0, (x0 - c.winfo_width() / 3) / total_w))
            self.schedule_render()
        self.draw_overlays()

    def find_clear(self, commit=False):
        self.matches, self.match_i = [], -1
        self.draw_overlays()

    # ─────────────────────────── misc ───────────────────────────
    def on_show(self):
        if self.boxes:
            self.schedule_render()
        else:
            self.app.root.after_idle(self._first_layout)

    def _first_layout(self):
        if self.doc is not None and self.alive:
            self.layout()
            self.layout_thumbs()
            self.schedule_render()

    def focus(self):
        self.canvas.focus_set()

    def status(self):
        segs = []
        if self.text_sel:
            segs.append(T("{0:,} chars selected", len(self.text_sel[2])))
        if self.doc is not None:
            segs.append(T("Page {0} of {1}", self.cur + 1, self.page_count))
            w, h = self.sizes[self.cur] if self.sizes else (0, 0)
            segs.append(T("{0:.0f} × {1:.0f} mm", w * 25.4 / 72, h * 25.4 / 72))
        segs.append(f"{round(self.ppp / self.base_ppp * 100)}%")
        segs.append(self.type_label())
        return segs

    def pdf_bytes(self):
        if self.doc.is_pdf:
            return self.doc.tobytes(garbage=3, deflate=True)
        return self.doc.convert_to_pdf()

    def export_images(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(parent=self.app.root, title=T("Save page images to…"),
                                         initialdir=os.path.dirname(self.path) if self.path else self.app.last_dir)
        if not folder:
            return
        pages = sorted(self.selected) if len(self.selected) > 1 else list(range(self.page_count))
        stem = os.path.splitext(self.title)[0]
        data = self.doc.tobytes() if self.doc.is_pdf else self.doc.convert_to_pdf()

        def work():
            doc = open_pdf_bytes(data)
            out = []
            for i in pages:
                pix = doc[i].get_pixmap(dpi=150, alpha=False)
                path = os.path.join(folder, f"{stem}_page{i + 1:03d}.png")
                pix.save(path)
                out.append(path)
            return out

        def done(paths):
            self.toast(T("Saved {0} page image{1}", len(paths), 's' if len(paths) != 1 else ''))

        self.run_async(work, done, text=T("Rendering page images…"))

    def destroy(self):
        panel = getattr(self, "sig_panel", None)
        if panel is not None:
            try:
                panel.destroy()
            except tk.TclError:
                pass
        for job in (self._render_job, self._thumb_job):
            if job:
                try:
                    self.app.root.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:  # noqa: BLE001
                pass


class DocumentTab(PdfView):
    """XPS, EPUB, MOBI, FB2, CBZ, DWFx — read-only, exportable to PDF."""
    kind = "document"

    def build_tools(self):
        self.bar.button(T("Save as PDF"), "export", self.app.export_active_pdf, T("Convert this document to PDF"))
        self.bar.button(T("Page images…"), "picture", self.export_images, T("Export pages as PNG images"))

    def type_label(self):
        return formats.label_for(self.path or self.title) or T("Document")


def djvu_info(path):
    """(pages, first page width, height, dpi) from the DjVu IFF structure."""
    import struct
    with open(path, "rb") as fh:
        data = fh.read(1 << 20)
    if not data.startswith(b"AT&TFORM"):
        return None
    form = data[12:16]
    pages = 1
    if form == b"DJVM":
        i = data.find(b"DIRM")
        if i > 0:
            pages = struct.unpack(">H", data[i + 9:i + 11])[0]
    i = data.find(b"INFO")
    if i > 0:
        w, h = struct.unpack(">HH", data[i + 8:i + 12])
        dpi = struct.unpack("<H", data[i + 14:i + 16])[0]
        return pages, w, h, dpi
    return pages, 0, 0, 0


def djvu_to_pdf(path):
    """Convert DjVu to PDF bytes with DjVuLibre's ddjvu (PDF output, or TIFF as a fallback)."""
    import shutil
    from . import safeio, winutil
    exe = winutil.find_ddjvu()
    if not exe:
        raise RuntimeError(T("DjVuLibre is not installed"))
    tmp = safeio.temp_dir("djvu")
    try:
        out = os.path.join(tmp, "out.pdf")
        winutil.run_hidden([exe, "-format=pdf", "-quality=80", "-scale=200", path, out], timeout=900)   # 200 dpi: sharp, fast
        if os.path.exists(out) and os.path.getsize(out) > 0:
            with open(out, "rb") as fh:
                return fh.read()
        tif = os.path.join(tmp, "out.tif")
        winutil.run_hidden([exe, "-format=tiff", "-scale=200", path, tif], timeout=900)
        if not os.path.exists(tif):
            raise RuntimeError(T("ddjvu could not convert this file"))
        with fitz.open(tif) as doc:
            return doc.convert_to_pdf()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class DjvuTab(DocumentTab):
    """DjVu documents, rendered through DjVuLibre (free) and shown with the normal page viewer."""
    kind = "djvu"

    def open_document(self):
        return None

    def load(self):
        from . import winutil
        from .base import Notice
        if not winutil.find_ddjvu():
            raise Notice(T("DjVu documents need the free DjVuLibre (ddjvu) — install it, then reopen this file."))
        self.run_async(lambda: djvu_to_pdf(self.path), self._converted,
                       error=lambda exc: self.app.replace_with(self, "info", error=str(exc)),
                       text=T("Converting DjVu pages…"))

    def _converted(self, data):
        self.set_document(open_pdf_bytes(data))
        if self.app.active is self:
            self.on_show()
            self.app.update_status()

    def type_label(self):
        return T("DjVu document")
