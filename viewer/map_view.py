"""Map viewer for GIS layers: pan/zoom, layer list, feature info, attribute table, search, PNG export."""

import math
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

import numpy as np

from . import gis, theme
from .base import BaseTab
from .theme import C, FONTS, px
from .i18n import T

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = ImageDraw = ImageTk = None

HILITE = "#ffd166"


def nice_step(raw):
    if raw <= 0:
        return 1
    exp = math.floor(math.log10(raw))
    base = raw / 10 ** exp
    for n in (1, 2, 5, 10):
        if base <= n:
            return n * 10 ** exp
    return 10 * 10 ** exp


def pip(arr, x, y):
    xs, ys = arr[:, 0], arr[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cond = ((ys > y) != (yj > y)) & (x < (xj - xs) * (y - ys) / (yj - ys) + xs)
    return np.count_nonzero(cond) % 2 == 1


def seg_dist(pts, p):
    if len(pts) == 1:
        return float(np.hypot(*(pts[0] - p)))
    a, b = pts[:-1], pts[1:]
    ab = b - a
    denom = (ab * ab).sum(axis=1)
    denom[denom == 0] = 1e-12
    t = np.clip(((p - a) * ab).sum(axis=1) / denom, 0, 1)
    proj = a + ab * t[:, None]
    return float(np.hypot(*(proj - p).T).min())


class MapTab(BaseTab):
    kind = "map"
    zoomable = searchable = True

    def __init__(self, app, path=None, title=None):
        super().__init__(app, path, title)
        self.layers = []
        self.view = None
        self.aspect = 1.0
        self.geographic = False
        self.photo = None
        self.img_item = None
        self.sel = None
        self._render_job = self._hq_job = None
        self._drag = None
        self.matches, self.match_i = [], -1
        self.table_layer = 0
        self._table_job = None
        self.mouse = None
        self._build()

    # ─────────────────────────── UI ───────────────────────────
    def _build(self):
        bar = self.bar
        bar.button(T("Fit All"), "fit", self.fit_all, T("Zoom to all layers  (Ctrl+0)"))
        self.layers_btn = bar.button(T("Layers"), "layers", self.toggle_layers, T("Show / hide the layer list"))
        self.table_btn = bar.button(T("Attribute Table"), "table", self.toggle_table, T("Show / hide the attribute table"))
        bar.divider()
        bar.button(T("Export PNG"), "export", self.export_png, T("Save the current map view as an image"))
        self.coord_lbl = bar.label("", side="right")
        body = self.body
        self.layer_panel = tk.Frame(body, bg=C["sidebar"], width=px(240))
        self.layer_panel.pack_propagate(False)
        self.layer_panel.pack(side="left", fill="y")
        self.layer_sep = tk.Frame(body, bg=C["border"], width=1)
        self.layer_sep.pack(side="left", fill="y")
        self._layers_auto_hidden = False
        body.bind("<Configure>", self._fit_layers, add="+")
        self.layers_btn.set_toggled(True)
        self.center = tk.Frame(body, bg=C["canvas"])
        self.center.pack(side="left", fill="both", expand=True)
        self.table_frame = tk.Frame(self.center, bg=C["bg"], height=px(240))
        self.table_frame.pack_propagate(False)
        self.top = tk.Frame(self.center, bg=C["canvas"])
        self.top.pack(side="top", fill="both", expand=True)
        self.info_panel = tk.Frame(self.top, bg=C["bg"], width=px(300))
        self.info_panel.pack_propagate(False)
        self.canvas = tk.Canvas(self.top, bg=C["canvas"], highlightthickness=0, takefocus=1, cursor="fleur")
        self.canvas.pack(side="left", fill="both", expand=True)
        c = self.canvas
        c.bind("<Configure>", lambda e: self.schedule_render(hq=True))
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Double-Button-1>", lambda e: self.zoom_at(e.x, e.y, 2.0))
        c.bind("<MouseWheel>", lambda e: self.zoom_at(e.x, e.y, 1.25 if e.delta > 0 else 0.8))
        c.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.25))
        c.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 0.8))
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", lambda e: self.coord_lbl.configure(text=""))
        c.bind("<Escape>", lambda e: self.select(None))
        self._build_info()
        self._build_table()

    def _build_info(self):
        p = self.info_panel
        tk.Frame(p, bg=C["border"], width=1).pack(side="left", fill="y")
        inner = tk.Frame(p, bg=C["bg"])
        inner.pack(side="left", fill="both", expand=True)
        head = tk.Frame(inner, bg=C["bg"])
        head.pack(fill="x", padx=px(14), pady=(px(10), px(4)))
        self.info_title = tk.Label(head, text=T("Feature"), font=FONTS["h3"], bg=C["bg"], fg=C["fg_bright"], anchor="w")
        self.info_title.pack(side="left", fill="x", expand=True)
        theme.ToolButton(head, "", "close", lambda: self.select(None), T("Close"), bg=C["bg"], pad=(6, 3)).pack(side="right")
        self.info_sub = tk.Label(inner, text="", font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"], anchor="w")
        self.info_sub.pack(fill="x", padx=px(14))
        actions = tk.Frame(inner, bg=C["bg"])
        actions.pack(fill="x", padx=px(10), pady=px(6))
        theme.ToolButton(actions, T("Zoom to"), "zoomin", lambda: self.zoom_to_feature(self.sel), bg=C["bg"],
                         pad=(6, 3)).pack(side="left")
        theme.ToolButton(actions, T("Copy"), "copy", self.copy_feature, bg=C["bg"], pad=(6, 3)).pack(side="left")
        self.info_tree = ttk.Treeview(inner, style="Grid.Treeview", columns=("v",), show="tree", selectmode="browse")
        self.info_tree.column("#0", width=px(110), stretch=False)
        self.info_tree.column("v", width=px(170), stretch=True)
        self.info_tree.pack(fill="both", expand=True, padx=(px(6), 0))

    def _build_table(self):
        f = self.table_frame
        tk.Frame(f, bg=C["border"], height=1).pack(side="top", fill="x")
        head = tk.Frame(f, bg=C["bg"])
        head.pack(side="top", fill="x")
        self.table_layer_btn = theme.ToolButton(head, T("Layer"), "layers", menu=self._table_layer_menu, bg=C["bg"],
                                                pad=(8, 4))
        self.table_layer_btn.pack(side="left", padx=px(6), pady=px(3))
        self.table_count = tk.Label(head, text="", font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"])
        self.table_count.pack(side="left", padx=px(8))
        holder = tk.Frame(f, bg=C["bg"])
        holder.pack(fill="both", expand=True)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        self.table = ttk.Treeview(holder, style="Grid.Treeview", show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.table.yview)
        hsb = ttk.Scrollbar(holder, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.table.tag_configure("odd", background=C["row_alt"])
        self.table.bind("<<TreeviewSelect>>", self._on_table_select)

    # ─────────────────────────── loading ───────────────────────────
    def load(self):
        self.run_async(lambda: gis.read_any(self.path), self._loaded,
                       error=lambda exc: self.app.replace_with(self, "info", error=str(exc)),
                       text=T("Reading map data…"))

    def _loaded(self, layers):
        self.layers = layers
        boxes = [l.bbox for l in layers if l.bbox is not None]
        self.geographic = all(l.geographic for l in layers if l.features)
        if self.geographic and boxes:
            lat = (min(b[1] for b in boxes) + max(b[3] for b in boxes)) / 2
            self.aspect = max(0.2, math.cos(math.radians(max(-80.0, min(80.0, lat)))))
        self._fill_layer_panel()
        self.fit_all()
        self.app.update_status()

    # ─────────────────────────── layer panel ───────────────────────────
    def _fill_layer_panel(self):
        p = self.layer_panel
        for w in p.winfo_children():
            w.destroy()
        tk.Label(p, text=T("LAYERS"), font=FONTS["caption"], bg=C["sidebar"], fg=C["fg_muted"], anchor="w").pack(
            fill="x", padx=px(14), pady=(px(12), px(6)))
        for li, layer in enumerate(self.layers):
            row = tk.Frame(p, bg=C["sidebar"])
            row.pack(fill="x", padx=px(6), pady=px(1))
            check = tk.Label(row, text="☑" if layer.visible else "☐", font=FONTS["ui"], bg=C["sidebar"],
                             fg=C["fg_dim"], cursor="hand2")
            check.pack(side="left", padx=(px(6), px(4)))
            sw = tk.Label(row, image=theme.swatch_image(layer.color, 14), bg=C["sidebar"], cursor="hand2")
            sw.pack(side="left", padx=px(4))
            txt = tk.Frame(row, bg=C["sidebar"])
            txt.pack(side="left", fill="x", expand=True, padx=px(4), pady=px(4))
            tk.Label(txt, text=layer.name, font=FONTS["ui"], bg=C["sidebar"], fg=C["fg"], anchor="w").pack(fill="x")
            geom = {"point": "points", "line": "lines", "polygon": "polygons"}.get(layer.geom, "features")
            tk.Label(txt, text=f"{len(layer.features):,} {geom}", font=FONTS["tiny"], bg=C["sidebar"],
                     fg=C["fg_muted"], anchor="w").pack(fill="x")
            check.bind("<Button-1>", lambda e, k=li: self._toggle_layer(k))
            sw.bind("<Button-1>", lambda e, k=li: self._color_menu(e, k))
        crs = next((gis.crs_name(l.crs) for l in self.layers if l.crs), None)
        tk.Label(p, text=T("CRS: {0}", crs or 'unknown'), font=FONTS["tiny"], bg=C["sidebar"], fg=C["fg_muted"],
                 anchor="w", justify="left", wraplength=px(210)).pack(side="bottom", fill="x", padx=px(14),
                                                                      pady=px(10))

    def _toggle_layer(self, k):
        self.layers[k].visible = not self.layers[k].visible
        self._fill_layer_panel()
        self.schedule_render(hq=True)

    def _color_menu(self, event, k):
        theme.pick_color(self.app.settings, event.widget, self.layers[k].color, lambda c: self._set_color(k, c),
                         x=event.x_root, y=event.y_root)

    def _set_color(self, k, color):
        self.layers[k].color = color
        self._fill_layer_panel()
        self.schedule_render(hq=True)

    def _show_layers(self, show):
        if show and not self.layer_panel.winfo_manager():
            self.layer_panel.pack(side="left", fill="y", before=self.center)
            self.layer_sep.pack(side="left", fill="y", before=self.center)
        elif not show and self.layer_panel.winfo_manager():
            self.layer_panel.pack_forget()
            self.layer_sep.pack_forget()
        self.layers_btn.set_toggled(bool(show))

    def toggle_layers(self):
        self._layers_auto_hidden = False
        self._show_layers(not self.layer_panel.winfo_manager())

    def _fit_layers(self, event):
        """Narrow window: the map gets the room; the layer list comes back when it is wide enough."""
        if event.widget is not self.body:
            return
        if self.layer_panel.winfo_manager() and event.width < px(600):
            self._layers_auto_hidden = True
            self._show_layers(False)
        elif self._layers_auto_hidden and event.width >= px(720):
            self._layers_auto_hidden = False
            self._show_layers(True)

    # ─────────────────────────── view ───────────────────────────
    def fit_all(self):
        boxes = [l.bbox for l in self.layers if l.visible and l.bbox is not None] or \
                [l.bbox for l in self.layers if l.bbox is not None]
        if not boxes:
            return
        self.fit_bbox((min(b[0] for b in boxes), min(b[1] for b in boxes),
                       max(b[2] for b in boxes), max(b[3] for b in boxes)))

    def fit_bbox(self, bbox, max_scale=None):
        w, h = max(200, self.canvas.winfo_width()), max(200, self.canvas.winfo_height())
        x0, y0, x1, y1 = bbox
        dw, dh = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
        s = min(w * 0.9 / (dw * self.aspect), h * 0.9 / dh)
        if x1 - x0 < 1e-9 and y1 - y0 < 1e-9:
            s = max_scale or (self.view[2] * 4 if self.view else 1000)
        if max_scale:
            s = min(s, max_scale)
        self.view = ((x0 + x1) / 2, (y0 + y1) / 2, s)
        self.schedule_render(hq=True, delay=1)

    def zoom_at(self, mx, my, factor):
        if not self.view:
            return
        cx, cy, s = self.view
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        dx, dy = self.to_data(mx, my)
        s2 = max(1e-12, min(1e12, s * factor))
        self.view = (dx - (mx - w / 2) / (s2 * self.aspect), dy + (my - h / 2) / s2, s2)
        self.schedule_render()

    def zoom(self, step):
        if step == 0:
            self.fit_all()
            return
        self.zoom_at(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2, 1.5 if step > 0 else 1 / 1.5)

    def to_data(self, mx, my):
        cx, cy, s = self.view
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        return cx + (mx - w / 2) / (s * self.aspect), cy - (my - h / 2) / s

    # ─────────────────────────── rendering ───────────────────────────
    def schedule_render(self, hq=False, delay=15):
        if self._render_job:
            self.app.root.after_cancel(self._render_job)
        self._render_job = self.app.root.after(delay, lambda: self._render(hq))
        if self._hq_job:
            self.app.root.after_cancel(self._hq_job)
            self._hq_job = None
        if not hq:
            self._hq_job = self.app.root.after(280, lambda: self._render(True))

    def _render(self, hq=False):
        self._render_job = None
        if hq:
            self._hq_job = None
        if not self.alive or not self.view or Image is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 10 or h < 10:
            return
        img = self.render_image(w, h, ss=2 if hq and self._visible_count() < 40000 else 1)
        self.photo = ImageTk.PhotoImage(img)
        c = self.canvas
        c.delete("all")
        self.img_item = c.create_image(0, 0, image=self.photo, anchor="nw")
        self._draw_scalebar()

    def _visible_count(self):
        return sum(len(l.features) for l in self.layers if l.visible)

    def menu_title(self):
        return T("Map")

    def fill_menu(self, name, m):
        if name == "view":
            m.add_command(label=T("Zoom in"), accelerator=theme.keys("Ctrl++"), command=lambda: self.zoom(1))
            m.add_command(label=T("Zoom out"), accelerator=theme.keys("Ctrl+-"), command=lambda: self.zoom(-1))
            m.add_command(label=T("Show everything"), command=self.fit_all)
        elif name == "tools":
            m.add_command(label=T("Layers"), command=self.toggle_layers)
            m.add_command(label=T("Attribute table"), command=self.toggle_table)
            m.add_separator()
            m.add_command(label=T("Save map as image\u2026"), command=self.export_png)

    def print_document(self):
        """The map as shown (current view and layers), on a white background."""
        if self.view is None:
            return None
        from . import printing
        w, h = max(400, self.canvas.winfo_width()), max(300, self.canvas.winfo_height())
        saved = C["canvas"]
        C["canvas"] = "#ffffff"
        try:
            img = self.render_image(w, h, ss=3)
        finally:
            C["canvas"] = saved
        return printing.image_document(img)

    def render_image(self, w, h, ss=1, view=None):
        cx, cy, s = view or self.view
        ax = self.aspect
        W, H = w * ss, h * ss
        bg = theme.hex_to_rgb(C["canvas"])
        img = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img, "RGBA")
        sx, sy = s * ax * ss, s * ss
        ox, oy = W / 2, H / 2
        vx0, vx1 = cx - (w / 2) / (s * ax), cx + (w / 2) / (s * ax)
        vy0, vy1 = cy - (h / 2) / s, cy + (h / 2) / s
        self._draw_grid(draw, vx0, vx1, vy0, vy1, cx, cy, sx, sy, ox, oy, W, H)
        lw = max(1, round(1.4 * ss * theme.SCALE))
        pr = 3.2 * ss * theme.SCALE

        def screen(arr):
            out = np.empty_like(arr)
            out[:, 0] = (arr[:, 0] - cx) * sx + ox
            out[:, 1] = oy - (arr[:, 1] - cy) * sy
            return out

        def simplify(scr):
            if len(scr) <= 32:
                return scr
            q = np.round(scr).astype(np.int64)
            keep = np.empty(len(q), bool)
            keep[0] = True
            keep[1:] = np.any(q[1:] != q[:-1], axis=1)
            keep[-1] = True
            return scr[keep]

        for li, layer in enumerate(self.layers):
            if not layer.visible or not layer.features:
                continue
            rgb = theme.hex_to_rgb(layer.color)
            b = layer.bboxes
            idx = np.nonzero((b[:, 2] >= vx0) & (b[:, 0] <= vx1) & (b[:, 3] >= vy0) & (b[:, 1] <= vy1))[0]
            if not len(idx):
                continue
            feats = layer.features
            polys = [k for k in idx if feats[k].kind == "polygon"]
            if polys:
                mask = Image.new("L", (W, H), 0)
                md = ImageDraw.Draw(mask)
                outlines = []
                for k in polys:
                    f = feats[k]
                    fb = b[k]
                    if (fb[2] - fb[0]) * sx < 1.5 and (fb[3] - fb[1]) * sy < 1.5:
                        x, y = ((fb[0] + fb[2]) / 2 - cx) * sx + ox, oy - ((fb[1] + fb[3]) / 2 - cy) * sy
                        draw.point((x, y), fill=rgb + (255,))
                        continue
                    for ri, ring in enumerate(f.parts):
                        if len(ring) < 3 or ri in f.holes:
                            continue
                        pts = simplify(screen(ring))
                        flat = pts.ravel().tolist()
                        if len(flat) >= 6:
                            md.polygon(flat, fill=70)
                        outlines.append(flat)
                    for ri in f.holes:
                        ring = f.parts[ri]
                        if len(ring) >= 3:
                            flat = simplify(screen(ring)).ravel().tolist()
                            if len(flat) >= 6:
                                md.polygon(flat, fill=0)
                                outlines.append(flat)
                img.paste(Image.new("RGB", (W, H), rgb), (0, 0), mask)
                for flat in outlines:
                    if len(flat) >= 4:
                        draw.line(flat + flat[:2], fill=rgb + (235,), width=lw)
            for k in idx:
                f = feats[k]
                if f.kind == "line":
                    for part in f.parts:
                        if len(part) >= 2:
                            draw.line(simplify(screen(part)).ravel().tolist(), fill=rgb + (240,), width=lw + ss // 2,
                                      joint="curve" if ss > 1 else None)
                elif f.kind == "point":
                    for x, y in screen(f.parts[0]):
                        if -10 <= x <= W + 10 and -10 <= y <= H + 10:
                            draw.ellipse((x - pr, y - pr, x + pr, y + pr), fill=rgb + (235,),
                                         outline=(10, 10, 16, 200), width=max(1, ss))
        if self.sel:
            li, k = self.sel
            f = self.layers[li].features[k]
            for ri, part in enumerate(f.parts):
                scr = screen(part)
                if f.kind == "point":
                    for x, y in scr:
                        r = pr * 1.8
                        draw.ellipse((x - r, y - r, x + r, y + r), outline=theme.hex_to_rgb(HILITE) + (255,),
                                     width=max(2, 2 * ss))
                elif len(scr) >= 2:
                    flat = scr.ravel().tolist()
                    if f.kind == "polygon":
                        flat += flat[:2]
                        if len(scr) >= 3 and ri not in f.holes:
                            draw.polygon(scr.ravel().tolist(), fill=theme.hex_to_rgb(HILITE) + (60,))
                    draw.line(flat, fill=theme.hex_to_rgb(HILITE) + (255,), width=lw + 2 * ss)
        if ss > 1:
            img = img.resize((w, h), Image.LANCZOS)
        return img

    def _draw_grid(self, draw, vx0, vx1, vy0, vy1, cx, cy, sx, sy, ox, oy, W, H):
        span = max(vx1 - vx0, vy1 - vy0)
        if span <= 0 or not math.isfinite(span):
            return
        step = nice_step(span / 8)
        if self.geographic:
            for cand in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30):
                if span / cand <= 12:
                    step = cand
                    break
        color = theme.hex_to_rgb(C["border"]) + (255,)
        x = math.floor(vx0 / step) * step
        while x <= vx1:
            px_ = (x - cx) * sx + ox
            draw.line((px_, 0, px_, H), fill=color, width=1)
            x += step
        y = math.floor(vy0 / step) * step
        while y <= vy1:
            py_ = oy - (y - cy) * sy
            draw.line((0, py_, W, py_), fill=color, width=1)
            y += step

    def _meters_per_px(self):
        if not self.view:
            return None
        s = self.view[2]
        return 110574.0 / s if self.geographic else 1.0 / s

    def _draw_scalebar(self):
        mpp = self._meters_per_px()
        if not mpp or not math.isfinite(mpp):
            return
        target = px(110) * mpp
        length = nice_step(target)
        bar_px = length / mpp
        label = f"{length / 1000:g} km" if length >= 1000 else f"{length:g} m"
        if not self.geographic and self.layers and not any(l.crs for l in self.layers):
            label = f"{length:g} units"
        c = self.canvas
        x0, y0 = px(18), c.winfo_height() - px(22)
        c.create_rectangle(x0 - px(8), y0 - px(22), x0 + bar_px + px(8), y0 + px(9), fill=C["panel"], outline="",
                           tags=("scale",))
        c.create_line(x0, y0, x0 + bar_px, y0, fill=C["fg"], width=px(2), tags=("scale",))
        for xx in (x0, x0 + bar_px):
            c.create_line(xx, y0 - px(5), xx, y0 + px(1), fill=C["fg"], width=px(2), tags=("scale",))
        c.create_text(x0 + bar_px / 2, y0 - px(12), text=label, fill=C["fg"], font=FONTS["tiny"], tags=("scale",))

    # ─────────────────────────── mouse ───────────────────────────
    def _on_press(self, event):
        self.canvas.focus_set()
        self._drag = (event.x, event.y, False)

    def _on_drag(self, event):
        if not self._drag or self.img_item is None:
            return
        x0, y0, _moved = self._drag
        dx, dy = event.x - x0, event.y - y0
        if abs(dx) + abs(dy) > 3:
            self._drag = (x0, y0, True)
            self.canvas.coords(self.img_item, dx, dy)
            self.canvas.delete("scale")

    def _on_release(self, event):
        d, self._drag = self._drag, None
        if not d or not self.view:
            return
        x0, y0, moved = d
        if moved:
            cx, cy, s = self.view
            self.view = (cx - (event.x - x0) / (s * self.aspect), cy + (event.y - y0) / s, s)
            self.schedule_render(hq=True, delay=1)
        else:
            self.select(self.hit_test(event.x, event.y))

    def _on_motion(self, event):
        if not self.view:
            return
        x, y = self.to_data(event.x, event.y)
        if self.geographic:
            text = f"{abs(y):.5f}° {'N' if y >= 0 else 'S'}   {abs(x):.5f}° {'E' if x >= 0 else 'W'}"
        else:
            text = f"X {x:,.2f}   Y {y:,.2f}"
        self.coord_lbl.configure(text=text)

    def hit_test(self, mx, my):
        if not self.view:
            return None
        cx, cy, s = self.view
        x, y = self.to_data(mx, my)
        tol = px(7)
        tx, ty = tol / (s * self.aspect), tol / s
        p = np.array([mx, my], float)
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()

        def screen(arr):
            out = np.empty_like(arr)
            out[:, 0] = (arr[:, 0] - cx) * s * self.aspect + w / 2
            out[:, 1] = h / 2 - (arr[:, 1] - cy) * s
            return out

        poly_hits = []
        for li in reversed(range(len(self.layers))):
            layer = self.layers[li]
            if not layer.visible or not layer.features:
                continue
            b = layer.bboxes
            cand = np.nonzero((b[:, 0] - tx <= x) & (b[:, 2] + tx >= x) & (b[:, 1] - ty <= y) & (b[:, 3] + ty >= y))[0]
            for k in cand[::-1]:
                f = layer.features[k]
                if f.kind == "point":
                    if np.hypot(*(screen(f.parts[0]) - p).T).min() <= tol * 1.3:
                        return li, int(k)
                elif f.kind == "line":
                    if any(seg_dist(screen(part), p) <= tol for part in f.parts):
                        return li, int(k)
                else:
                    inside = any(pip(r, x, y) for i, r in enumerate(f.parts) if i not in f.holes) and \
                        not any(pip(f.parts[i], x, y) for i in f.holes)
                    if inside:
                        area = (b[k, 2] - b[k, 0]) * (b[k, 3] - b[k, 1])
                        poly_hits.append((area, li, int(k)))
        if poly_hits:
            _a, li, k = min(poly_hits)
            return li, k
        return None

    # ─────────────────────────── selection & info ───────────────────────────
    def select(self, sel, from_table=False):
        self.sel = sel
        if sel is None:
            self.info_panel.pack_forget()
        else:
            li, k = sel
            layer = self.layers[li]
            f = layer.features[k]
            t = self.info_tree
            t.delete(*t.get_children())
            for name, value in zip(layer.fields, f.props):
                t.insert("", "end", text=f"  {name}", values=(self._fmt(value),))
            title = next((self._fmt(v) for n, v in zip(layer.fields, f.props)
                          if str(n).lower() in ("name", "name_en", "title", "label", "id") and v not in (None, "")),
                         T("Feature {0}", k + 1))
            self.info_title.configure(text=title[:40])
            npts = sum(len(p) for p in f.parts)
            self.info_sub.configure(text=T("{0}  ·  {1}  ·  {2:,} vertices", layer.name, f.kind, npts))
            if not self.info_panel.winfo_ismapped():
                self.info_panel.pack(side="right", fill="y", before=self.canvas)
            if not from_table and self.table_frame.winfo_ismapped() and li == self.table_layer:
                iid = str(k)
                if self.table.exists(iid):
                    self.table.selection_set(iid)
                    self.table.see(iid)
        self.schedule_render(hq=True, delay=1)

    @staticmethod
    def _fmt(value):
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6g}" if not value.is_integer() else str(int(value))
        if isinstance(value, bytes):
            return f"<{len(value)} bytes>"
        return str(value)

    def copy_feature(self):
        if not self.sel:
            return
        li, k = self.sel
        layer = self.layers[li]
        lines = [f"{n}\t{self._fmt(v)}" for n, v in zip(layer.fields, layer.features[k].props)]
        self.app.set_clipboard("\n".join(lines))
        self.toast(T("Feature attributes copied"))

    def zoom_to_feature(self, sel):
        if not sel:
            return
        li, k = sel
        f = self.layers[li].features[k]
        x0, y0, x1, y1 = f.bbox
        if x1 - x0 < 1e-12 and y1 - y0 < 1e-12:
            cx, cy, s = self.view
            self.view = (x0, y0, max(s, 4 * s))
            self.schedule_render(hq=True, delay=1)
        else:
            pad_x, pad_y = (x1 - x0) * 0.6, (y1 - y0) * 0.6
            self.fit_bbox((x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y))

    # ─────────────────────────── attribute table ───────────────────────────
    def toggle_table(self):
        if self.table_frame.winfo_ismapped():
            self.table_frame.pack_forget()
            self.table_btn.set_toggled(False)
        else:
            self.table_frame.pack(side="bottom", fill="x", before=self.top)
            self.table_btn.set_toggled(True)
            self._fill_table()

    def _table_layer_menu(self, m):
        for li, layer in enumerate(self.layers):
            m.add_command(label=layer.name, command=lambda k=li: self._set_table_layer(k))

    def _set_table_layer(self, k):
        self.table_layer = k
        self._fill_table()

    def _fill_table(self):
        if not self.layers:
            return
        if self._table_job:
            self.app.root.after_cancel(self._table_job)
            self._table_job = None
        layer = self.layers[min(self.table_layer, len(self.layers) - 1)]
        self.table_layer_btn.set_text(layer.name)
        t = self.table
        t.delete(*t.get_children())
        cols = layer.fields[:80]
        t.configure(columns=[f"c{i}" for i in range(len(cols))])
        font = tkfont.Font(self.app.root, font=FONTS["small_bold"])
        small = tkfont.Font(self.app.root, font=FONTS["small"])
        sample = layer.features[:150]
        for i, name in enumerate(cols):
            t.heading(f"c{i}", text=name, anchor="w")
            width = font.measure(str(name)) + px(28)
            for f in sample:
                if i < len(f.props):
                    width = max(width, small.measure(self._fmt(f.props[i])[:40]) + px(18))
            t.column(f"c{i}", width=max(px(60), min(px(280), width)), stretch=False, anchor="w")
        self.table_count.configure(text=T("{0:,} rows  ·  {1} columns", len(layer.features), len(layer.fields)))
        self._insert_rows(layer, 0, len(cols))

    def _insert_rows(self, layer, start, ncols):
        t = self.table
        end = min(len(layer.features), start + 1500)
        for k in range(start, end):
            vals = [self._fmt(v)[:200] for v in layer.features[k].props[:ncols]]
            t.insert("", "end", iid=str(k), values=vals, tags=("odd",) if k % 2 else ())
        if end < len(layer.features):
            self._table_job = self.app.root.after(10, lambda: self._insert_rows(layer, end, ncols))
        else:
            self._table_job = None

    def _on_table_select(self, _event):
        sel = self.table.selection()
        if not sel:
            return
        target = (self.table_layer, int(sel[0]))
        if target != self.sel:
            self.select(target, from_table=True)
            self.zoom_to_feature(target)

    # ─────────────────────────── search ───────────────────────────
    def find_update(self, needle, case, mode="jump"):
        self.matches, self.match_i = [], -1
        if not needle:
            return -1, 0
        n = needle if case else needle.lower()
        for li, layer in enumerate(self.layers):
            for k, f in enumerate(layer.features):
                for v in f.props:
                    if v is None:
                        continue
                    sv = str(v) if case else str(v).lower()
                    if n in sv:
                        self.matches.append((li, k))
                        break
                if len(self.matches) >= 5000:
                    break
        if self.matches and mode == "jump":
            self._goto(0)
        return self.match_i, len(self.matches)

    def find_step(self, direction):
        if not self.matches:
            return -1, 0
        self._goto((self.match_i + direction) % len(self.matches))
        return self.match_i, len(self.matches)

    def _goto(self, i):
        self.match_i = i
        self.select(self.matches[i])
        self.zoom_to_feature(self.matches[i])

    def find_clear(self, commit=False):
        self.matches, self.match_i = [], -1

    # ─────────────────────────── misc ───────────────────────────
    def export_png(self):
        if not self.view:
            return
        path = filedialog.asksaveasfilename(parent=self.app.root, title=T("Export map"), defaultextension=".png",
                                            initialfile=(self.title.rsplit(".", 1)[0]) + ".png",
                                            filetypes=[(T("PNG image"), "*.png")])
        if not path:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        img = self.render_image(w * 2, h * 2, ss=1, view=(self.view[0], self.view[1], self.view[2] * 2))
        img.save(path)
        self.toast(T("Saved {0}", path.rsplit('/', 1)[-1]))

    def focus(self):
        self.canvas.focus_set()

    def on_show(self):
        if self.view:
            self.schedule_render(hq=True)

    def status(self):
        n = sum(len(l.features) for l in self.layers)
        crs = next((gis.crs_name(l.crs) for l in self.layers if l.crs), None)
        segs = [T("{0} layer", 1) if len(self.layers) == 1 else T("{0} layers", len(self.layers)), T("{0:,} features", n)]
        if crs:
            segs.append(crs[:40])
        return segs + [self.type_label()]

    def destroy(self):
        for job in (self._render_job, self._hq_job, self._table_job):
            if job:
                try:
                    self.app.root.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()
