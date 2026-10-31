"""Image viewer: fast zoom/pan on huge images, transparency, animation, multi-page TIFF, EXIF/GeoTIFF info,
rotate/flip, save/convert, copy, export to PDF. SVG is rasterised with PyMuPDF."""

import io
import os
import tkinter as tk

from . import formats, theme, winutil
from .base import BaseTab
from .theme import C, FONTS, px
from .i18n import T

try:
    from PIL import ExifTags, Image, ImageOps, ImageTk
except ImportError:
    Image = ImageOps = ImageTk = ExifTags = None

try:
    import pi_heif as _heif  # HEIC / HEIF / AVIF decoding (decode-only build, LGPL libheif)
except ImportError:
    try:
        import pillow_heif as _heif
    except ImportError:
        _heif = None
if _heif is not None:
    try:
        _heif.register_heif_opener()
    except Exception:  # noqa: BLE001
        pass

SAVE_TYPES = [("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg"), ("WebP", "*.webp"), ("TIFF", "*.tif *.tiff"),
              ("BMP", "*.bmp"), ("GIF", "*.gif"), ("Icon", "*.ico"), ("PDF", "*.pdf"), ("All files", "*")]
MAX_FRAMES = 600


def normalize_mode(img):
    """Make any Pillow image displayable (handles 16-bit / float rasters such as GeoTIFF DEMs)."""
    mode = img.mode
    if mode in ("RGB", "RGBA", "L", "LA"):
        return img.convert("RGBA") if mode == "LA" else img
    if mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        try:
            import numpy as np
            arr = np.asarray(img.convert("F") if mode != "F" else img, dtype="float64")
            finite = arr[np.isfinite(arr)]
            if finite.size:
                lo, hi = np.percentile(finite, (1, 99))
                if hi <= lo:
                    hi = lo + 1
                arr = np.clip((arr - lo) / (hi - lo) * 255, 0, 255)
                arr[~np.isfinite(arr)] = 0
            return Image.fromarray(arr.astype("uint8"), "L")
        except Exception:  # noqa: BLE001
            return img.convert("L")
    if mode in ("P", "PA"):
        return img.convert("RGBA")
    if mode in ("1",):
        return img.convert("L")
    return img.convert("RGB") if "A" not in mode else img.convert("RGBA")


class ImageTab(BaseTab):
    kind = "image"
    zoomable = True

    def menu_title(self):
        return T("Image")

    def fill_menu(self, name, m):
        if name == "view":
            m.add_command(label=T("Zoom in"), accelerator=theme.keys("Ctrl++"), command=lambda: self.zoom(1))
            m.add_command(label=T("Zoom out"), accelerator=theme.keys("Ctrl+-"), command=lambda: self.zoom(-1))
            m.add_command(label=T("Fit to window"), accelerator=theme.keys("Ctrl+0"), command=self.set_fit)
            m.add_command(label=T("Image information"), command=self.toggle_info)
        elif name == "tools":
            for op, label in (("rotl", "Rotate left"), ("rotr", "Rotate right"), ("fliph", "Flip horizontally"),
                              ("flipv", "Flip vertically")):
                m.add_command(label=T(label), command=lambda o=op: self.transform(o))
            m.add_separator()
            m.add_command(label=T("Copy image"), command=self.copy_image)

    def print_document(self):
        if self.src is None:
            return None
        from . import printing
        return printing.image_document(self.src)

    def __init__(self, app, path=None, title=None):
        super().__init__(app, path, title)
        self.src = None           # current (possibly rotated) image, display-ready
        self.frames = []          # [(image, duration_ms)]
        self.frame_i = 0
        self.playing = False
        self.info = {}
        self.ops = []             # transforms applied since load
        self.scale = 1.0
        self.fit = True
        self.cx = self.cy = 0.0
        self.photo = None
        self._job = self._anim_job = None
        self._drag = None
        self._checker = {}
        self.savable = True
        self._build()

    # ─────────────────────────── UI ───────────────────────────
    def _build(self):
        bar = self.bar
        bar.button(T("Fit"), "fit", lambda: self.set_fit(), T("Fit to window  (Ctrl+0)"))
        bar.button("1:1", None, lambda: self.set_zoom(1.0), T("Actual pixels"))
        bar.divider()
        self.edit_btns = [
            bar.button("", "undo", lambda: self.transform("rotl"), T("Rotate left"), compact=True),
            bar.button("", "redo", lambda: self.transform("rotr"), T("Rotate right"), compact=True),
            bar.button(T("Flip H"), None, lambda: self.transform("fliph"), T("Flip horizontally")),
            bar.button(T("Flip V"), None, lambda: self.transform("flipv"), T("Flip vertically")),
        ]
        bar.divider()
        bar.button(T("Copy"), "copy", self.copy_image, T("Copy image  (Ctrl+C)"))
        bar.button(T("Save as PDF"), "export", lambda: self.app.export_active_pdf(self), T("Save the image as a PDF"))
        self.info_btn = bar.button(T("Info"), "info", self.toggle_info, T("Image details, EXIF and GeoTIFF tags"))
        self.frame_box = tk.Frame(bar.left, bg=C["bg"])
        theme.ToolButton(self.frame_box, "", "left", lambda: self.step_frame(-1), T("Previous frame / page"),
                         bg=C["bg"], pad=(6, 4)).pack(side="left")
        self.frame_lbl = tk.Label(self.frame_box, text="", bg=C["bg"], fg=C["fg_dim"], font=FONTS["small"])
        self.frame_lbl.pack(side="left", padx=px(4))
        theme.ToolButton(self.frame_box, "", "right", lambda: self.step_frame(1), T("Next frame / page"),
                         bg=C["bg"], pad=(6, 4)).pack(side="left")
        self.play_btn = theme.ToolButton(self.frame_box, T("Play"), "play", self.toggle_play, bg=C["bg"], pad=(6, 4))
        self.zoom_lbl = bar.label("", side="right")
        bar.button("", "zoomout", lambda: self.zoom(-1), T("Zoom out"), side="right", compact=True)
        bar.button("", "zoomin", lambda: self.zoom(1), T("Zoom in"), side="right", compact=True)
        kids = bar.right.pack_slaves()
        for w in kids:
            w.pack_forget()
        for w in (kids[1], kids[0], kids[2]):
            w.pack(side="left", padx=px(1), pady=px(6))

        self.info_panel = tk.Frame(self.body, bg=C["bg"], width=px(300))
        self.info_panel.pack_propagate(False)
        self.canvas = tk.Canvas(self.body, bg=C["canvas"], highlightthickness=0, takefocus=1)
        self.canvas.pack(side="left", fill="both", expand=True)
        c = self.canvas
        c.bind("<Configure>", lambda e: self.schedule())
        c.bind("<MouseWheel>", lambda e: self.zoom_at(e.x, e.y, 1.25 if e.delta > 0 else 0.8))
        c.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.25))
        c.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 0.8))
        c.bind("<ButtonPress-1>", lambda e: (c.focus_set(), setattr(self, "_drag", (e.x, e.y, self.cx, self.cy))))
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", lambda e: (setattr(self, "_drag", None), self.schedule()))
        c.bind("<Double-Button-1>", lambda e: self.set_fit() if not self.fit else self.set_zoom(1.0, (e.x, e.y)))
        c.bind("<Left>", lambda e: self.step_frame(-1))
        c.bind("<Right>", lambda e: self.step_frame(1))
        self.app.register_drop(c)

    # ─────────────────────────── loading ───────────────────────────
    def _special(self):
        """Formats Pillow can't open directly. Returns (frames, info, exif) or None."""
        import numpy as np
        ext = formats.ext_of(self.path)
        if ext == ".hgt":
            n = int(round((os.path.getsize(self.path) / 2) ** 0.5))
            arr = np.fromfile(self.path, ">i2", n * n).reshape(n, n).astype("float32")
            arr[arr <= -32768] = np.nan
            img = normalize_mode(Image.fromarray(np.nan_to_num(arr, nan=float(np.nanmin(arr))), "F"))
            return [(img, 0)], {"Format": "SRTM HGT", "Size": f"{n} \u00D7 {n} samples",
                                "Elevation": f"{np.nanmin(arr):.0f} \u2026 {np.nanmax(arr):.0f} m"}, {}
        if ext == ".asc":
            header, skip = {}, 0
            with open(self.path, "r", encoding="ascii", errors="replace") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) == 2 and parts[0].isalpha() or (parts and parts[0].lower() in
                                                                   ("ncols", "nrows", "xllcorner", "yllcorner",
                                                                    "xllcenter", "yllcenter", "cellsize",
                                                                    "nodata_value", "dx", "dy")):
                        header[parts[0].lower()] = float(parts[1])
                        skip += 1
                    else:
                        break
            arr = np.loadtxt(self.path, skiprows=skip, dtype="float32", ndmin=2)
            nodata = header.get("nodata_value")
            if nodata is not None:
                arr[arr == nodata] = np.nan
            img = normalize_mode(Image.fromarray(np.nan_to_num(arr, nan=float(np.nanmin(arr))), "F"))
            info = {"Format": "ESRI ASCII grid", "Size": f"{arr.shape[1]} \u00D7 {arr.shape[0]} cells",
                    "Values": f"{np.nanmin(arr):.4g} \u2026 {np.nanmax(arr):.4g}"}
            if "cellsize" in header:
                info["Cell size"] = f"{header['cellsize']:g}"
            return [(img, 0)], info, {}
        if ext in (".ora", ".kra"):
            import zipfile
            from io import BytesIO
            with zipfile.ZipFile(self.path) as z:
                name = next((n for n in ("mergedimage.png", "preview.png", "Thumbnails/thumbnail.png")
                             if n in z.namelist()), None)
                if not name:
                    raise ValueError(T("No merged image stored in this file"))
                img = Image.open(BytesIO(z.read(name)))
                img.load()
            return [(normalize_mode(img), 0)], {"Format": ext[1:].upper() + T(" (merged layers)"),
                                                "Size": f"{img.width} \u00D7 {img.height} px"}, {}
        if (formats.info(self.path) or ("", "", ""))[2] == "Camera RAW photo":
            from .info_view import find_embedded_preview
            img = find_embedded_preview(self.path, limit=200 * 1024 * 1024)
            if img is not None:
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:  # noqa: BLE001
                    pass
                return [(normalize_mode(img), 0)], {"Format": T("{0} camera RAW", ext[1:].upper()),
                                                    "Shown": T("embedded full-size JPEG preview"),
                                                    "Size": f"{img.width} \u00D7 {img.height} px"}, {}
        return None

    def read_image(self):
        special = self._special()
        if special is not None:
            return special
        img = Image.open(self.path)
        if img.format in ("WMF", "EMF"):
            try:
                img.load(dpi=144)
            except TypeError:
                img.load()
        info = {"Format": img.format or formats.ext_of(self.path)[1:].upper(), "Size": f"{img.width} \u00D7 {img.height} px",
                "Mode": img.mode}
        dpi = img.info.get("dpi")
        if dpi:
            info["Resolution"] = f"{round(float(dpi[0]))} dpi"
        exif = {}
        try:
            raw = img.getexif()
            for tag, value in raw.items():
                name = ExifTags.TAGS.get(tag, str(tag))
                if name in ("Make", "Model", "DateTime", "Software", "Artist", "Copyright"):
                    exif[name] = str(value).strip("\x00 ")
            sub = raw.get_ifd(0x8769)
            for tag, value in sub.items():
                name = ExifTags.TAGS.get(tag, str(tag))
                if name in ("ExposureTime", "FNumber", "ISOSpeedRatings", "FocalLength", "DateTimeOriginal",
                            "LensModel"):
                    exif[name] = str(value)
            gps = raw.get_ifd(0x8825)
            if gps and 2 in gps and 4 in gps:
                def dms(v, ref):
                    d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                    return -d if ref in ("S", "W") else d
                exif["GPS"] = f"{dms(gps[2], gps.get(1)):.6f}, {dms(gps[4], gps.get(3)):.6f}"
        except Exception:  # noqa: BLE001
            pass
        tags = getattr(img, "tag_v2", None)
        if tags:
            if 33922 in tags and 33550 in tags:
                tie, scale = tags[33922], tags[33550]
                info["GeoTIFF origin"] = f"{tie[3]:.4f}, {tie[4]:.4f}"
                info["Pixel size"] = f"{scale[0]:.6g} × {scale[1]:.6g}"
        frames = []
        n = getattr(img, "n_frames", 1)
        if n > 1:
            info["Frames"] = str(n)
            for k in range(min(n, MAX_FRAMES)):
                img.seek(k)
                frames.append((normalize_mode(img.copy()), int(img.info.get("duration", 0) or 0)))
            img.seek(0)
        else:
            try:
                im = ImageOps.exif_transpose(img)
            except Exception:  # noqa: BLE001
                im = img
            im.load()
            frames.append((normalize_mode(im), 0))
        return frames, info, exif

    def load(self):
        if Image is None:
            raise RuntimeError(T("Pillow is not installed"))
        self.run_async(self.read_image, self._loaded,
                       error=lambda exc: self.app.replace_with(self, "info", error=str(exc)),
                       text=T("Opening image…"))

    def _loaded(self, result):
        self.frames, self.info, self.exif = result
        self.frame_i = 0
        self.src = self.frames[0][0]
        if len(self.frames) > 1:
            self.frame_box.pack(side="left", padx=px(6))
            animated = any(d for _f, d in self.frames)
            if animated:
                self.play_btn.pack(side="left", padx=px(4))
                self.toggle_play()
            for b in self.edit_btns:
                b.set_enabled(False)
            self._frame_label()
        self.set_fit()
        self._fill_info()
        self.app.update_status()

    # ─────────────────────────── view ───────────────────────────
    def set_fit(self):
        self.fit = True
        if self.src is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        iw, ih = self.src.size
        self.scale = min(1.0 if iw < w and ih < h else 99, (w - px(32)) / iw, (h - px(32)) / ih)
        self.scale = max(self.scale, 0.001)
        self.cx, self.cy = iw / 2, ih / 2
        self.schedule()

    def set_zoom(self, scale, anchor=None):
        if self.src is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        ax, ay = anchor or (w / 2, h / 2)
        ix = self.cx + (ax - w / 2) / self.scale
        iy = self.cy + (ay - h / 2) / self.scale
        self.fit = False
        self.scale = max(0.005, min(64.0, scale))
        self.cx = ix - (ax - w / 2) / self.scale
        self.cy = iy - (ay - h / 2) / self.scale
        self.schedule()

    def zoom_at(self, x, y, factor):
        self.set_zoom(self.scale * factor, (x, y))

    def zoom(self, step):
        if step == 0:
            self.set_fit()
        else:
            self.set_zoom(self.scale * (1.25 if step > 0 else 0.8))

    def _on_drag(self, event):
        if not self._drag:
            return
        x0, y0, cx, cy = self._drag
        self.fit = False
        self.cx = cx - (event.x - x0) / self.scale
        self.cy = cy - (event.y - y0) / self.scale
        self.schedule(fast=True)

    def schedule(self, fast=False):
        if self._job:
            self.app.root.after_cancel(self._job)
        self._job = self.app.root.after(5 if fast else 20, lambda: self.render(fast))

    def _checkerboard(self, w, h):
        key = (w, h)
        if key not in self._checker:
            if len(self._checker) > 4:
                self._checker.clear()
            tile = Image.new("RGB", (16, 16), (46, 48, 62))
            tile.paste((36, 38, 50), (0, 0, 8, 8))
            tile.paste((36, 38, 50), (8, 8, 16, 16))
            board = Image.new("RGB", (w, h))
            for y in range(0, h, 16):
                for x in range(0, w, 16):
                    board.paste(tile, (x, y))
            self._checker[key] = board
        return self._checker[key]

    def render(self, fast=False):
        self._job = None
        if not self.alive or self.src is None:
            return
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if self.fit:
            iw, ih = self.src.size
            self.scale = max(0.001, min(1.0 if iw < w and ih < h else 99, (w - px(32)) / iw, (h - px(32)) / ih))
            self.cx, self.cy = iw / 2, ih / 2
        s = self.scale
        iw, ih = self.src.size
        x0, y0 = self.cx - w / 2 / s, self.cy - h / 2 / s
        ix0, iy0 = max(0.0, x0), max(0.0, y0)
        ix1, iy1 = min(float(iw), x0 + w / s), min(float(ih), y0 + h / s)
        c.delete("all")
        if ix1 <= ix0 or iy1 <= iy0:
            return
        out_w, out_h = max(1, round((ix1 - ix0) * s)), max(1, round((iy1 - iy0) * s))
        if s >= 3:
            resample = Image.NEAREST
        elif fast:
            resample = Image.BILINEAR
        else:
            resample = Image.LANCZOS if s < 1 else Image.BICUBIC
        kw = {"reducing_gap": 2.0} if s < 0.5 else {}
        region = self.src.resize((out_w, out_h), resample, box=(ix0, iy0, ix1, iy1), **kw)
        if region.mode in ("RGBA", "LA", "PA"):
            board = self._checkerboard(out_w, out_h).copy()
            board.paste(region, (0, 0), region)
            region = board
        self.photo = ImageTk.PhotoImage(region)
        c.create_image(round((ix0 - x0) * s), round((iy0 - y0) * s), image=self.photo, anchor="nw")
        self.zoom_lbl.configure(text=f"{round(s * 100)}%")
        if self.app.active is self:
            self.app.update_status()

    # ─────────────────────────── frames ───────────────────────────
    def _frame_label(self):
        self.frame_lbl.configure(text=f"{self.frame_i + 1} / {len(self.frames)}")

    def step_frame(self, d):
        if len(self.frames) < 2:
            return
        self.frame_i = (self.frame_i + d) % len(self.frames)
        self.src = self.frames[self.frame_i][0]
        self._frame_label()
        self.schedule()

    def toggle_play(self):
        self.playing = not self.playing
        self.play_btn.set_text(T("Pause") if self.playing else T("Play"))
        if self.playing:
            self._tick()
        elif self._anim_job:
            self.app.root.after_cancel(self._anim_job)
            self._anim_job = None

    def _tick(self):
        if not self.playing or not self.alive:
            return
        self.step_frame(1)
        delay = self.frames[self.frame_i][1] or 100
        self._anim_job = self.app.root.after(max(20, delay), self._tick)

    def on_hide(self):
        if self.playing:
            self.toggle_play()

    # ─────────────────────────── editing ───────────────────────────
    def transform(self, op):
        if self.src is None or len(self.frames) > 1:
            return
        fn = {"rotl": lambda im: im.transpose(Image.ROTATE_90), "rotr": lambda im: im.transpose(Image.ROTATE_270),
              "fliph": lambda im: im.transpose(Image.FLIP_LEFT_RIGHT),
              "flipv": lambda im: im.transpose(Image.FLIP_TOP_BOTTOM)}[op]
        self.src = fn(self.src)
        self.frames = [(self.src, 0)]
        self.ops.append(op)
        self.set_dirty(True)
        self.set_fit()

    def save_filetypes(self):
        ext = formats.ext_of(self.path or self.title)
        first = [(T("{0} image", ext[1:].upper()), f"*{ext}")] if ext else []
        rest = [(T(a), b) for a, b in SAVE_TYPES if not (first and f"*{ext}" in b.split())]
        return first + rest

    def default_extension(self):
        return formats.ext_of(self.path or self.title) or ".png"

    def save_to(self, path):
        ext = formats.ext_of(path)
        if ext == ".pdf":
            with open(path, "wb") as fh:
                fh.write(self.pdf_bytes())
            return None
        if len(self.frames) > 1 and not self.ops and os.path.abspath(path) != self.path:
            with Image.open(self.path) as orig:
                orig.save(path, save_all=ext in (".gif", ".webp", ".png", ".tif", ".tiff"))
            return None
        img = self.src
        if not self.ops and self.path and os.path.normcase(os.path.abspath(path)) == os.path.normcase(self.path):
            return None
        kw = {}
        if ext in (".jpg", ".jpeg", ".jfif"):
            img = img.convert("RGB")
            kw = {"quality": 95, "subsampling": 0}
            if self.path:
                try:
                    with Image.open(self.path) as orig:
                        exif = orig.getexif()
                        exif.pop(0x0112, None)
                        kw["exif"] = exif.tobytes()
                        if orig.info.get("icc_profile"):
                            kw["icc_profile"] = orig.info["icc_profile"]
                except Exception:  # noqa: BLE001
                    pass
        elif ext == ".bmp":
            img = img.convert("RGBA" if img.mode == "RGBA" else "RGB")
        elif ext == ".ico":
            kw = {"sizes": [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(img.size)]}
        elif ext == ".webp":
            kw = {"quality": 92}
        tmp = path + ".tmp~"
        fmt = Image.registered_extensions().get(ext)
        img.save(tmp, format=fmt, **kw)
        os.replace(tmp, path)
        self.ops = []
        return None

    def pdf_bytes(self):
        buf = io.BytesIO()
        img = self.src.convert("RGB")
        img.save(buf, "PDF", resolution=96.0)
        return buf.getvalue()

    def copy_image(self):
        if self.src is None:
            return
        if winutil.copy_image_to_clipboard(self.src):
            self.toast(T("Image copied to the clipboard"))
        else:
            self.toast(T("Copying images is only supported on Windows."), "info")

    def edit_action(self, action):
        if action == "copy":
            self.copy_image()
            return True
        return False

    # ─────────────────────────── info panel ───────────────────────────
    def toggle_info(self):
        if self.info_panel.winfo_ismapped():
            self.info_panel.pack_forget()
            self.info_btn.set_toggled(False)
        else:
            self.info_panel.pack(side="right", fill="y", before=self.canvas)
            self.info_btn.set_toggled(True)

    def _fill_info(self):
        p = self.info_panel
        for w in p.winfo_children():
            w.destroy()
        tk.Frame(p, bg=C["border"], width=1).pack(side="left", fill="y")
        inner = tk.Frame(p, bg=C["bg"], padx=px(16), pady=px(14))
        inner.pack(side="left", fill="both", expand=True)
        rows = list(self.info.items())
        try:
            rows.append(("File size", formats.human_size(os.path.getsize(self.path))))
        except (OSError, TypeError):
            pass
        sections = [("IMAGE", rows)]
        if self.exif:
            sections.append(("CAMERA / EXIF", list(self.exif.items())))
        for title, items in sections:
            tk.Label(inner, text=T(title), font=FONTS["caption"], bg=C["bg"], fg=C["fg_muted"], anchor="w").pack(
                fill="x", pady=(px(6), px(4)))
            grid = tk.Frame(inner, bg=C["bg"])
            grid.pack(fill="x")
            for i, (k, v) in enumerate(items):
                tk.Label(grid, text=T(k), font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"], anchor="nw").grid(
                    row=i, column=0, sticky="nw", padx=(0, px(10)), pady=px(2))
                tk.Label(grid, text=v, font=FONTS["small"], bg=C["bg"], fg=C["fg"], anchor="w", justify="left",
                         wraplength=px(170)).grid(row=i, column=1, sticky="w", pady=px(2))

    def focus(self):
        self.canvas.focus_set()

    def on_show(self):
        if self.src is not None:
            self.schedule()

    def status(self):
        if self.src is None:
            return [self.type_label()]
        segs = [f"{self.src.size[0]} × {self.src.size[1]} px", f"{round(self.scale * 100)}%"]
        if len(self.frames) > 1:
            segs.insert(0, T("Frame {0}/{1}", self.frame_i + 1, len(self.frames)))
        return segs + [self.info.get("Format", T("Image"))]

    def destroy(self):
        for job in (self._job, self._anim_job):
            if job:
                try:
                    self.app.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.playing = False
        super().destroy()
