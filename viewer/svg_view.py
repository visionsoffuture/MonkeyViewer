"""SVG preview: the drawing rendered with resvg, its SMIL / CSS animation played in real time.

Opened with Run SVG (F5) from the code view; Run again shows the code's current state, saved or not.
"""

import io
import os
import re
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from . import formats, theme
from .base import BaseTab
from .i18n import T
from .theme import C, px

MAX_PIXELS = 36_000_000
BACKGROUNDS = (("checker", "Checkerboard"), ("white", "White"), ("black", "Black"), ("theme", "Window colour"))


def is_svg(name, text=None):
    if formats.ext_of(name or "") in (".svg", ".svgz"):
        return True
    head = (text or "")[:4096].lower()
    return "<svg" in head and ("<?xml" in head[:200] or head.lstrip().startswith("<svg"))


# ─────────────────────────────── fonts ───────────────────────────────
# resvg reads every installed font on every render when it may use the system fonts; on Windows that can take
# many seconds (a "Not responding" window). Only the families the SVG names, plus a few defaults, are loaded.
_FONT_INDEX = None
DEFAULTS = {
    "win": {"serif": "Times New Roman", "sans-serif": "Arial", "monospace": "Courier New", "cursive": "Comic Sans MS",
            "fantasy": "Impact", "extra": ("Segoe UI", "Sylfaen", "Segoe UI Symbol", "Calibri")},
    "mac": {"serif": "Times New Roman", "sans-serif": "Helvetica", "monospace": "Courier New",
            "cursive": "Apple Chancery", "fantasy": "Papyrus", "extra": ("Arial", "Georgian", "Noto Sans Georgian")},
    "other": {"serif": "DejaVu Serif", "sans-serif": "DejaVu Sans", "monospace": "DejaVu Sans Mono",
              "cursive": "DejaVu Sans", "fantasy": "DejaVu Sans", "extra": ("Liberation Sans", "Noto Sans")},
}
STYLE_WORDS = ("bold", "italic", "oblique", "light", "medium", "semibold", "demibold", "black", "regular",
               "thin", "condensed", "narrow", "extra", "ultra", "heavy", "book", "roman")


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _platform():
    return "win" if theme.IS_WIN else "mac" if theme.IS_MAC else "other"


def font_index():
    """{normalised family name: [font files]} for this computer, built once (registry / font folders)."""
    global _FONT_INDEX
    if _FONT_INDEX is not None:
        return _FONT_INDEX
    index = {}

    def add(name, path):
        key = _norm(name)
        if key and os.path.isfile(path):
            index.setdefault(key, [])
            if path not in index[key]:
                index[key].append(path)
    if theme.IS_WIN:
        import winreg
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                          (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")):
            try:
                key = winreg.OpenKey(hive, sub)
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        name, value, _t = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    i += 1
                    path = value if os.path.isabs(str(value)) else os.path.join(fonts_dir, str(value))
                    name = re.sub(r"\s*\((TrueType|OpenType|All res)\)\s*$", "", name, flags=re.I)
                    for part in name.split(" & "):
                        add(part, path)
                        words = part.split()
                        while len(words) > 1 and words[-1].lower() in STYLE_WORDS:
                            words.pop()
                            add(" ".join(words), path)
    else:
        dirs = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
                os.path.expanduser("~/Library/Fonts")] if theme.IS_MAC else \
            ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
             os.path.expanduser("~/.local/share/fonts")]
        for base in dirs:
            for folder, _subdirs, files in os.walk(base):
                for f in files:
                    if not f.lower().endswith((".ttf", ".otf", ".ttc", ".otc")):
                        continue
                    stem = os.path.splitext(f)[0]
                    path = os.path.join(folder, f)
                    add(stem, path)
                    words = re.split(r"[-_ ]+", stem)
                    while len(words) > 1 and words[-1].lower() in STYLE_WORDS:
                        words.pop()
                        add(" ".join(words), path)
    _FONT_INDEX = index
    return index


def font_options(svg_text):
    """resvg options that load only the needed fonts: the SVG's own families and the generic defaults."""
    plat = DEFAULTS[_platform()]
    families = set()
    for value in re.findall(r"font-family\s*[:=]\s*([^;>{}]+)", svg_text, flags=re.I):
        for name in value.split(","):
            name = name.strip().strip("\"'").strip()
            if name and name.lower() not in ("inherit", "initial"):
                families.add(name)
    for m in re.findall(r"font\s*:\s*[^;>{}]*?(?:\d+(?:px|pt|em|%)?(?:/[\d.]+)?)\s+([^;>{}]+)", svg_text, flags=re.I):
        families.update(n.strip().strip("\"'") for n in m.split(","))
    wanted = {plat.get(f.lower(), f) for f in families}
    wanted.update(plat[g] for g in ("serif", "sans-serif", "monospace"))
    wanted.update(plat["extra"])
    index = font_index()
    files = []
    for fam in wanted:
        for path in index.get(_norm(fam), [])[:8]:
            if path not in files:
                files.append(path)
    if not files:                                  # nothing found: let resvg look itself
        return {}
    return {"skip_system_fonts": True, "font_files": files[:80], "font_family": plat["serif"],
            "serif_family": plat["serif"], "sans_serif_family": plat["sans-serif"],
            "monospace_family": plat["monospace"], "cursive_family": plat["cursive"],
            "fantasy_family": plat["fantasy"]}


def render(svg_text, zoom=1.0, resources_dir=None):
    """RGBA image of the SVG at *zoom* (resvg; MuPDF when resvg is not available)."""
    zoom = max(0.01, float(zoom))
    try:
        import resvg_py
    except ImportError:
        resvg_py = None
    if resvg_py is not None:
        kw = {"svg_string": svg_text, "zoom": zoom}
        low = svg_text.lower()
        if "<text" not in low and "<tspan" not in low and "<textpath" not in low:
            kw["skip_system_fonts"] = True          # no text: no fonts needed at all
        else:
            kw.update(font_options(svg_text))
        if resources_dir and os.path.isdir(resources_dir):
            kw["resources_dir"] = resources_dir
        data = resvg_py.svg_to_bytes(**kw)
        return Image.open(io.BytesIO(bytes(data))).convert("RGBA")
    import fitz
    doc = fitz.open(stream=svg_text.encode("utf-8"), filetype="svg")
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


UNITS = {"": 1.0, "px": 1.0, "pt": 4 / 3, "pc": 16.0, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0, "em": 16.0,
         "ex": 8.0}


def intrinsic_size(svg_text):
    """(width, height) in pixels from the root element's width / height / viewBox, as resvg sizes it."""
    m = re.search(r"<svg\b([^>]*)>", svg_text[:65536], flags=re.I | re.S)
    if not m:
        return None
    attrs = dict((k.lower(), v) for k, v in re.findall(r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']", m.group(1)))

    def length(v):
        mm = re.fullmatch(r"\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*([a-z]*)\s*", v or "")
        if not mm or mm.group(2) not in UNITS:
            return None
        return float(mm.group(1)) * UNITS[mm.group(2)]
    vb = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?", attrs.get("viewbox", ""))]
    w, h = length(attrs.get("width")), length(attrs.get("height"))
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        if w is None and h is None:
            w, h = vb[2], vb[3]
        elif w is None:
            w = h * vb[2] / vb[3]
        elif h is None:
            h = w * vb[3] / vb[2]
    if not w or not h or w <= 0 or h <= 0:
        return None
    return max(1, round(w)), max(1, round(h))


def read_svg(path):
    with open(path, "rb") as fh:
        data = fh.read(64 << 20)
    if data[:2] == b"\x1f\x8b":                      # .svgz
        import gzip
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


class SvgTab(BaseTab):
    kind = "svg"
    zoomable = True

    def __init__(self, app, path=None, title=None, content=None, source=None):
        super().__init__(app, path, title)
        self.source = source
        self.svg_text = content
        self.anim = None
        self.static_svg = None
        self.size = (1, 1)
        self.scale = 1.0
        self.fit = True
        self.playing = True
        self.ended = False
        self.t0 = time.monotonic()
        self.t_paused = 0.0
        self.background = app.settings.get("svg_background", "checker")
        self._job = None
        self._resize_job = None
        self.photo = None
        self.render_ms = 0.0
        self.error = None
        self._build()

    # ── interface ──
    def _build(self):
        bar = self.bar
        self.play_btn = bar.button(T("Pause"), "pause", self.toggle_play, T("Play / pause the animation  (Space)"))
        bar.button(T("Restart"), "refresh", self.restart, T("Play the animation from the start"))
        self.time_lbl = bar.label("")
        bar.divider()
        bar.button(T("Background"), "picture", tooltip=T("What is shown behind transparent parts"),
                   menu=self._background_menu)
        if self.source is not None:
            bar.button(T("Code"), "code", self.show_code, T("Back to the code (F5 there runs it again)"))
        bar.button(T("Save as PNG"), "export", self.save_png, T("Save the current frame as a picture"),
                   side="right")
        self.zoom_lbl = bar.label("", side="right")
        bar.button("", "zoomin", lambda: self.zoom(1), T("Zoom in  (Ctrl +)"), side="right", compact=True)
        bar.button("", "zoomout", lambda: self.zoom(-1), T("Zoom out  (Ctrl −)"), side="right", compact=True)
        bar.button(T("Fit"), "fit", lambda: self.zoom(0), T("Fit to the window  (Ctrl+0)"), side="right")

        body = self.body
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, bg=C["canvas"], highlightthickness=0, bd=0, takefocus=1)
        self.vsb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.vsb.grid_remove()
        self.hsb.grid_remove()
        c = self.canvas
        c.bind("<Configure>", self._on_resize)
        c.bind("<space>", lambda e: (self.toggle_play(), "break")[1])
        c.bind("<Button-1>", lambda e: c.focus_set())
        c.bind(f"<{theme.PRIMARY}-MouseWheel>", lambda e: (self.zoom(1 if e.delta > 0 else -1), "break")[1])
        c.bind("<MouseWheel>", lambda e: c.yview_scroll(theme.wheel_units(e, 3), "units"))
        c.bind("<Shift-MouseWheel>", lambda e: c.xview_scroll(theme.wheel_units(e, 3), "units"))
        _r, middle = theme.mouse_buttons(c)
        c.bind(f"<ButtonPress-{middle}>", lambda e: c.scan_mark(e.x, e.y))
        c.bind(f"<B{middle}-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))

    def _background_menu(self, m):
        var = theme.menu_var(m, "str", self.background)
        for key, label in BACKGROUNDS:
            m.add_radiobutton(label=T(label), value=key, variable=var, command=lambda k=key: self.set_background(k))

    def set_background(self, key):
        self.background = key
        self.app.settings["svg_background"] = key
        self.render_now()

    def show_code(self):
        if self.source is not None and self.source in self.app.tabs:
            self.app.select_tab(self.source)

    # ── document ──
    def load(self):
        if self.svg_text is None:
            self.svg_text = read_svg(self.path)
        self.set_svg(self.svg_text, initial=True)

    def resources_dir(self):
        base = self.path or (self.source.path if self.source is not None else None)
        return os.path.dirname(base) if base else None

    def set_svg(self, text, initial=False):
        """Show new SVG text (Run SVG again): parse its animation, measure it, start playing."""
        from .svg_anim import SvgAnimation
        self.svg_text = text
        try:
            anim = SvgAnimation(text)
            self.static_svg = anim.frame(0.0)
            self.anim = anim if anim.animated else None
        except Exception:  # noqa: BLE001 - unusual XML (entities, broken markup): drawn as it is, no animation
            self.anim = None
            self.static_svg = text
        size = intrinsic_size(self.static_svg)
        if size is None:                           # no width / height / viewBox: let resvg measure it
            try:
                size = render(self.static_svg, 1.0, self.resources_dir()).size
            except ValueError as exc:
                if initial:
                    raise ValueError(T("This SVG cannot be drawn: {0}", exc)) from exc
                self.app.toast.show(T("This SVG cannot be drawn: {0}", exc), "error", 5000)
                return
        self.size = size
        self.error = None
        self.ended = False
        self.restart()

    def current_time(self):
        return time.monotonic() - self.t0 if self.playing else self.t_paused

    # ── playback ──
    def toggle_play(self):
        if self.anim is None:
            return
        if self.playing:
            self.t_paused = self.current_time()
            self.playing = False
        else:
            if self.ended:
                self.t_paused = 0.0
                self.ended = False
            self.t0 = time.monotonic() - self.t_paused
            self.playing = True
        self._sync_buttons()
        self.render_now()

    def restart(self):
        self.t0 = time.monotonic()
        self.t_paused = 0.0
        self.ended = False
        self.playing = self.anim is not None
        self._sync_buttons()
        self.render_now()

    def _sync_buttons(self):
        animated = self.anim is not None
        self.play_btn.set_enabled(animated)
        self.play_btn.set_text(T("Pause") if self.playing else T("Play"))

    def _cancel(self):
        if self._job is not None:
            try:
                self.app.root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    # ── drawing ──
    def effective_scale(self):
        w, h = self.size
        if self.fit:
            cw, ch = max(50, self.canvas.winfo_width() - px(32)), max(50, self.canvas.winfo_height() - px(32))
            self.scale = max(0.02, min(cw / max(w, 1), ch / max(h, 1), 16.0))
        limit = (MAX_PIXELS / max(1, w * h)) ** 0.5
        return min(self.scale, limit)

    def frame_svg(self, t):
        if self.anim is None:
            return self.static_svg
        return self.anim.frame(t)

    def _backdrop(self, size):
        w, h = size
        if self.background == "white":
            return Image.new("RGBA", size, (255, 255, 255, 255))
        if self.background == "black":
            return Image.new("RGBA", size, (0, 0, 0, 255))
        if self.background == "theme":
            return Image.new("RGBA", size, theme.hex_to_rgb(C["bg"]) + (255,))
        tile = px(8)
        light, dark = (236, 238, 243, 255), (214, 218, 226, 255)
        base = Image.new("RGBA", (tile * 2, tile * 2), light)
        base.paste(dark, (tile, 0, tile * 2, tile))
        base.paste(dark, (0, tile, tile, tile * 2))
        out = Image.new("RGBA", size)
        for y in range(0, h, tile * 2):
            for x in range(0, w, tile * 2):
                out.paste(base, (x, y))
        return out

    def render_now(self):
        self._cancel()
        if not self.alive or self.static_svg is None:
            return
        t = self.current_time()
        if self.anim is not None and self.playing and self.anim.end != float("inf") and t >= self.anim.end:
            t = self.anim.end                      # finite animation: stop on its last frame
            self.t_paused, self.playing, self.ended = t, False, True
            self._sync_buttons()
        scale = self.effective_scale()
        started = time.perf_counter()
        try:
            img = render(self.frame_svg(t), scale, self.resources_dir())
        except Exception as exc:  # noqa: BLE001 - keep the last good frame
            if self.error != str(exc):
                self.error = str(exc)
                self.app.toast.show(T("This SVG cannot be drawn: {0}", exc), "error", 4000)
            return
        self.render_ms = (time.perf_counter() - started) * 1000
        if self.playing and self.anim is not None and self.render_ms > 1500:
            self.t_paused, self.playing = t, False      # one frame takes too long: no animation loop
            self._sync_buttons()
            self.app.toast.show(T("This drawing takes {0:.1f} s per frame - the animation is paused. Play shows "
                                  "it frame by frame.", self.render_ms / 1000), "warning", 6000)
        frame = self._backdrop(img.size)
        frame.alpha_composite(img)
        self.photo = ImageTk.PhotoImage(frame)
        c = self.canvas
        c.delete("all")
        cw, ch = c.winfo_width(), c.winfo_height()
        iw, ih = frame.size
        x, y = max(iw // 2, cw // 2), max(ih // 2, ch // 2)
        c.create_rectangle(x - iw // 2 - 1, y - ih // 2 - 1, x + iw - iw // 2, y + ih - ih // 2,
                           outline=C["border_strong"])
        c.create_image(x, y, image=self.photo)
        sw, sh = max(cw, iw + px(32)), max(ch, ih + px(32))
        c.configure(scrollregion=(0, 0, sw, sh))
        (self.vsb.grid if sh > ch + 1 else self.vsb.grid_remove)()
        (self.hsb.grid if sw > cw + 1 else self.hsb.grid_remove)()
        self.zoom_lbl.configure(text=f"{scale * 100:.0f}%")
        if self.anim is not None:
            self.time_lbl.configure(text=f"{t:5.1f} s" + (f" / {self.anim.end:.1f} s"
                                                          if self.anim.end != float("inf") else ""))
        else:
            self.time_lbl.configure(text=T("no animation"))
        self.app.update_status()
        if self.playing and self.anim is not None:
            delay = int(max(16, min(500, self.render_ms * 1.6)))     # heavy drawings: fewer frames, UI stays free
            self._job = self.app.root.after(delay, self.render_now)

    def _on_resize(self, _event):
        if self._resize_job is not None:
            self.app.root.after_cancel(self._resize_job)
        self._resize_job = self.app.root.after(60, self._resized)

    def _resized(self):
        self._resize_job = None
        if self.fit or not (self.playing and self.anim is not None):
            self.render_now()

    def zoom(self, step):
        if step == 0:
            self.fit = True
        else:
            current = self.effective_scale()
            self.fit = False
            self.scale = max(0.02, min(64.0, current * (1.25 if step > 0 else 0.8)))
        self.render_now()

    # ── tab hooks ──
    def on_show(self):
        if self.playing and self.anim is not None:
            self.render_now()

    def on_hide(self):
        self._cancel()                             # nothing is drawn while the tab is not visible

    def focus(self):
        try:
            self.canvas.focus_set()
        except tk.TclError:
            pass

    def status(self):
        w, h = self.size
        segs = ["SVG", f"{w} × {h}"]
        if self.anim is not None:
            segs.append(T("animated") + f" · {self.render_ms:.0f} ms")
        return segs

    def type_label(self):
        return "SVG"

    @property
    def display_path(self):
        src = self.source.path if self.source is not None and self.source.path else None
        return (src or self.path or "") + ("  \u25b6  " + T("preview of the code") if self.source is not None else "")

    def menu_title(self):
        return "SVG"

    def fill_menu(self, name, m):
        if name == "view":
            m.add_command(label=T("Zoom in"), accelerator=theme.keys("Ctrl++"), command=lambda: self.zoom(1))
            m.add_command(label=T("Zoom out"), accelerator=theme.keys("Ctrl+-"), command=lambda: self.zoom(-1))
            m.add_command(label=T("Fit to window"), accelerator=theme.keys("Ctrl+0"), command=lambda: self.zoom(0))
            sub = theme.popup_menu(m)
            self._background_menu(sub)
            m.add_cascade(label=T("Background"), menu=sub)
        elif name == "tools":
            state = "normal" if self.anim is not None else "disabled"
            m.add_command(label=T("Pause") if self.playing else T("Play"), accelerator="Space",
                          command=self.toggle_play, state=state)
            m.add_command(label=T("Restart"), command=self.restart, state=state)
            m.add_separator()
            m.add_command(label=T("Save as PNG…"), command=self.save_png)
            if self.source is not None:
                m.add_command(label=T("Code"), command=self.show_code)

    def _hires(self):
        """The current frame at least twice its own size (for saving and printing)."""
        w, h = self.size
        zoom = min(max(2.0, 2000 / max(w, h, 1)), (MAX_PIXELS / max(1, w * h)) ** 0.5)
        return render(self.frame_svg(self.current_time()), zoom, self.resources_dir())

    def save_png(self):
        from tkinter import filedialog
        base = os.path.splitext(self.title.replace(" ▶", ""))[0] or "drawing"
        path = filedialog.asksaveasfilename(parent=self.app.root, title=T("Save as PNG"),
                                            initialfile=base + ".png", defaultextension=".png",
                                            initialdir=self.app.last_dir,
                                            filetypes=[(T("PNG image"), "*.png")])
        if not path:
            return
        self._hires().save(path, "PNG")
        self.toast(T("Saved {0}", os.path.basename(path)))

    def print_document(self):
        from . import printing
        img = self._hires()
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.split()[3])
        return printing.image_document(flat)

    def destroy(self):
        self._cancel()
        if self._resize_job is not None:
            try:
                self.app.root.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        super().destroy()
