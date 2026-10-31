"""PDF editor: text, edit text, highlight, pen, rectangle, whiteout, image, crop, page operations, undo."""

import html
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

from . import formats, theme
from .pdf_view import PdfView, fitz, open_pdf_bytes
from .theme import C, FONTS, px
from .i18n import T

TOOLS = [
    # key, label, icon, tooltip, shortcut
    ("select", "Select", "pointer", "Select text / annotations", "v"),
    ("text", "Text", "text", "Add text — click where it should go", "t"),
    ("edit", "Edit", "edit", "Edit existing text — click a line", "e"),
    ("highlight", "Mark", "highlight", "Highlight text", "h"),
    ("pen", "Pen", "pen", "Draw freehand", "p"),
    ("rect", "Box", "rect", "Draw a rectangle", "r"),
    ("whiteout", "Erase", "erase", "Whiteout — permanently erase an area", "w"),
    ("image", "Image", "picture", "Insert an image or signature", "i"),
    ("crop", "Crop", "crop", "Crop pages — draw a frame, adjust it, then apply", "c"),
]
TEXT_SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64)
STROKES = (1, 2, 3, 4, 6, 8, 12)
UNDO_LIMIT = 30


def rgb01(hex_color):
    r, g, b = theme.hex_to_rgb(hex_color)
    return r / 255, g / 255, b / 255


def parse_ranges(spec, count):
    """'1-3, 5, 8-' -> [0, 1, 2, 4, 7, ...]"""
    pages = []
    for part in re.split(r"[,;\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else count
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(T("'{0}' is not a page or range", part))
        if a > b:
            a, b = b, a
        pages += [i - 1 for i in range(a, b + 1) if 1 <= i <= count]
    return list(dict.fromkeys(pages))


def format_ranges(indices):
    out, run = [], []
    for i in sorted(indices):
        if run and i == run[-1] + 1:
            run.append(i)
        else:
            if run:
                out.append(run)
            run = [i]
    if run:
        out.append(run)
    return ", ".join(f"{r[0] + 1}" if len(r) == 1 else f"{r[0] + 1}-{r[-1] + 1}" for r in out)


def text_to_html(text):
    out = []
    for line in text.split("\n"):
        esc = html.escape(line)
        esc = re.sub(r"  +", lambda m: "&nbsp;" * len(m.group()), esc)
        out.append(esc or "&nbsp;")
    return "<br>".join(out)


class PdfTab(PdfView):
    kind = "pdf"
    savable = True
    editable = True

    def __init__(self, app, path=None, title=None, data=None):
        self.tool = "select"
        self.crop, self.crop_bar = None, None        # pending crop frame (page, display rect, target)
        self.undo_stack, self.redo_stack = [], []
        self.colors = {"text": "#000000", "edit": "#000000", "pen": "#e53935", "rect": "#e53935",
                       "highlight": "#fdd835"}
        self.text_size = 12
        self.stroke = 2
        self.image_path = None
        self.sel_annot = None
        self.editor = None
        self.save_needs_new_path = path is None
        self.tool_buttons = {}
        super().__init__(app, path, title, data)

    # ─────────────────────────── toolbar ───────────────────────────
    def build_tools(self):
        bar = self.bar
        for key, label, icon_name, tip, short in TOOLS:
            b = bar.button(T(label), icon_name, lambda k=key: self.set_tool(k), f"{T(tip)}  ({short.upper()})",
                           compact=True)
            self.tool_buttons[key] = b
        bar.divider()
        self.swatch = tk.Frame(bar.left, bg=C["bg"], cursor="hand2")
        self.swatch.pack(side="left", padx=px(4), pady=px(10))
        self.swatch_inner = tk.Frame(self.swatch, width=px(18), height=px(18), bg="#000000",
                                     highlightthickness=1, highlightbackground=C["border_strong"])
        self.swatch_inner.pack()
        for w in (self.swatch, self.swatch_inner):
            w.bind("<Button-1>", self._color_menu)
        theme.Tooltip([self.swatch, self.swatch_inner], T("Colour"))
        self.size_btn = bar.button(T("12 pt"), None, tooltip=T("Text size / line width"), menu=self._size_menu)
        bar.divider()
        bar.button("", "undo", self.undo, T("Undo  (Ctrl+Z)"), compact=True)
        bar.button("", "redo", self.redo, T("Redo  (Ctrl+Y)"), compact=True)
        bar.divider()
        bar.button(T("Pages"), "page", tooltip=T("Page operations"), menu=self.fill_page_menu)
        self.tool_buttons["select"].set_toggled(True)
        self._sync_options()

    def fill_menu(self, name, m):
        if name == "edit":
            m.add_command(label=T("Select all pages"), command=self.select_all_pages)
            m.add_command(label=T("Delete selected pages"), command=self.delete_pages)
        if name == "tools":
            var = theme.menu_var(m, "str", self.tool)
            for key, label, _icon, _tip, letter in TOOLS:
                m.add_radiobutton(label=T(label), value=key, variable=var,
                                  accelerator=letter.upper(), command=lambda k=key: self.set_tool(k))
            m.add_separator()
            m.add_command(label=T("Colour\u2026"), command=self._color_menu)
            m.add_separator()
        super().fill_menu(name, m)

    def _color_menu(self, event=None):
        key = self.tool if self.tool in self.colors else "text"
        theme.pick_color(self.app.settings, self.swatch, self.colors[key], self.set_color,
                         eyedropper=self.start_eyedropper)

    def start_eyedropper(self):
        """Next click on a page takes the colour under the pointer (Esc cancels)."""
        self._eyedrop = True
        self.canvas.configure(cursor="tcross")
        self.canvas.focus_set()
        self.toast(T("Click on the page to take its colour (Esc cancels)."), "info", 3500)

    def _sample_color(self, i, cx, cy):
        x, y, _w, _h = self.boxes[i]
        page = self.doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)      # rendered as displayed (rotation)
        px_, py_ = int((cx - x) / self.ppp * 2), int((cy - y) / self.ppp * 2)
        px_, py_ = min(max(px_, 0), pix.width - 1), min(max(py_, 0), pix.height - 1)
        r, g, b = pix.pixel(px_, py_)[:3]
        return "#%02x%02x%02x" % (r, g, b)

    def _color_picked(self, color):
        recent = [color] + [c for c in self.app.settings.get("recent_colors", []) if c != color]
        self.app.settings["recent_colors"] = recent[:8]
        self.app.settings.save()
        self.set_color(color)

    def _size_menu(self, m):
        if self.tool in ("pen", "rect"):
            for s in STROKES:
                m.add_command(label=T("{0} px", s), command=lambda v=s: self.set_stroke(v))
        else:
            for s in TEXT_SIZES:
                m.add_command(label=T("{0} pt", s), command=lambda v=s: self.set_text_size(v))

    def set_color(self, value):
        key = self.tool if self.tool in self.colors else "text"
        self.colors[key] = value
        self._sync_options()

    def set_text_size(self, v):
        self.text_size = v
        self._sync_options()

    def set_stroke(self, v):
        self.stroke = v
        self._sync_options()

    def _sync_options(self):
        key = self.tool if self.tool in self.colors else "text"
        self.swatch_inner.configure(bg=self.colors[key])
        if self.tool in ("pen", "rect"):
            self.size_btn.set_text(T("{0} px", self.stroke))
        else:
            self.size_btn.set_text(T("{0} pt", self.text_size))

    def set_tool(self, key):
        self.commit_editor()
        if key != "crop" and self.crop is not None:
            self.cancel_crop()
        if key == "image":
            path = filedialog.askopenfilename(parent=self.app.root, title=T("Choose an image or signature"),
                                              filetypes=formats.category_filetypes("image"))
            if not path:
                return
            self.image_path = path
            self.toast(T("Click on the page to place the image, or drag to size it."), "info", 3500)
        self.tool = key
        for k, b in self.tool_buttons.items():
            b.set_toggled(k == key)
        self.sel_annot = None
        self._sync_options()
        self.draw_overlays()
        if self.app.active is self:
            self.app.update_status()

    # ─────────────────────────── undo ───────────────────────────
    def snapshot(self):
        self.undo_stack.append(self.doc.tobytes())
        total = sum(len(b) for b in self.undo_stack)
        while len(self.undo_stack) > UNDO_LIMIT or (total > 600_000_000 and len(self.undo_stack) > 1):
            total -= len(self.undo_stack.pop(0))
        self.redo_stack.clear()
        self.set_dirty(True)

    def undo(self):
        self.commit_editor()
        if not self.undo_stack:
            self.toast(T("Nothing to undo"), "info", 1500)
            return
        self.redo_stack.append(self.doc.tobytes())
        self.set_document(open_pdf_bytes(self.undo_stack.pop()), keep_view=True)
        self.set_dirty(True)

    def redo(self):
        if not self.redo_stack:
            self.toast(T("Nothing to redo"), "info", 1500)
            return
        self.undo_stack.append(self.doc.tobytes())
        self.set_document(open_pdf_bytes(self.redo_stack.pop()), keep_view=True)
        self.set_dirty(True)

    # ─────────────────────────── saving ───────────────────────────
    IMAGE_TYPES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF", ".bmp": "BMP",
                   ".webp": "WEBP"}

    def save_filetypes(self):
        return [(T("PDF document"), "*.pdf"), (T("PNG image (each page)"), "*.png"),
                (T("JPEG image (each page)"), "*.jpg *.jpeg"), (T("TIFF image (each page)"), "*.tif *.tiff"),
                (T("BMP image (each page)"), "*.bmp"), (T("WebP image (each page)"), "*.webp"),
                (T("All files"), "*")]

    def default_extension(self):
        return ".pdf"

    def confirm_save(self, path):
        """Saving rewrites the PDF, which ends the validity of its digital signatures - say so first."""
        if os.path.splitext(path)[1].lower() in self.IMAGE_TYPES or not getattr(self, "signatures", None):
            return True
        return messagebox.askyesno(
            T("Signed document"),
            T("This PDF is digitally signed. Saving it with changes makes the existing signatures invalid "
              "(the original file keeps them).\n\nSave anyway?"), parent=self.app.root, icon=messagebox.WARNING)

    def save_to(self, path):
        self.commit_editor()
        ext = os.path.splitext(path)[1].lower()
        if ext in self.IMAGE_TYPES:
            self.exported = self.save_page_images(path, self.IMAGE_TYPES[ext])
            return None
        try:
            self.doc.subset_fonts()
        except Exception:  # noqa: BLE001
            pass
        data = self.doc.tobytes(garbage=3, deflate=True)
        tmp = path + ".tmp~"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        return None

    def save_page_images(self, path, fmt, dpi=200):
        """Every page (or the selected pages) as an image: "name.png" for one page, else name_page001.png..."""
        from PIL import Image
        from . import safeio
        pages = sorted(self.selected) if len(self.selected) > 1 else list(range(self.page_count))
        folder, name = os.path.split(path)
        stem, ext = os.path.splitext(name)
        out = []
        for i in pages:
            pix = self.doc[i].get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            target = path if len(pages) == 1 else safeio.unique_path(folder, f"{stem}_page{i + 1:03d}{ext}")
            img.save(target, fmt, **({"quality": 92} if fmt in ("JPEG", "WEBP") else {}),
                     dpi=(dpi, dpi))
            out.append(target)
        return out

    def pdf_bytes(self):
        self.commit_editor()
        return self.doc.tobytes(garbage=3, deflate=True)

    # ─────────────────────────── mouse ───────────────────────────
    def cursor_for(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if getattr(self, "_eyedrop", False):
            return "tcross"
        if self.page_at(cx, cy) is None:
            return ""
        return {"select": "xterm", "text": "xterm", "edit": "xterm", "highlight": "xterm", "pen": "pencil",
                "rect": "crosshair", "whiteout": "crosshair", "image": "crosshair", "crop": "crosshair"}[self.tool]

    def on_tool_press(self, event, cx, cy, i):
        if getattr(self, "_eyedrop", False):
            self._eyedrop = False
            self.canvas.configure(cursor="")
            if i is not None:
                self._color_picked(self._sample_color(i, cx, cy))
            return
        if self.editor is not None:
            self.commit_editor()
            return
        if self.tool == "select":
            if i is not None:
                annot = self._annot_at(i, cx, cy)
                if annot is not None:
                    self.sel_annot = (i, annot.xref)
                    self.text_sel = None
                    self.draw_overlays()
                    self._drag = None
                    return
            self.sel_annot = None
            return super().on_tool_press(event, cx, cy, i)
        if i is None:
            self._drag = ("pan", event.x, event.y)
            self.canvas.scan_mark(event.x, event.y)
            return
        if self.tool == "crop":
            self._crop_press(i, cx, cy)
            return
        if self.tool == "text":
            self.open_editor(i, cx, cy, "", self.text_size, self.colors["text"], "#ffffff", self._commit_new_text)
        elif self.tool == "edit":
            self._start_edit_line(i, cx, cy)
        elif self.tool == "pen":
            self._drag = ("pen", i, [(cx, cy)])
        else:
            self._drag = (self.tool, i, cx, cy)

    def on_tool_drag(self, event, cx, cy):
        d = self._drag
        if d and d[0] == "cropbox":
            self._crop_drag(cx, cy)
            return
        if not d or d[0] in ("pan", "select"):
            return super().on_tool_drag(event, cx, cy)
        c = self.canvas
        c.delete("preview")
        if d[0] == "pen":
            pts = d[2]
            pts.append((cx, cy))
            c.create_line(*[v for p in pts for v in p], fill=self.colors["pen"], width=max(1, self.stroke * self.ppp),
                          capstyle="round", joinstyle="round", smooth=True, tags=("preview", "overlay"))
            return
        _k, i, x0, y0 = d
        x, y, w, h = self.boxes[i]
        cx, cy = min(max(cx, x), x + w), min(max(cy, y), y + h)
        if d[0] == "whiteout":
            c.create_rectangle(x0, y0, cx, cy, fill="#ffffff", outline=C["accent"], tags=("preview", "overlay"))
        elif d[0] == "rect":
            c.create_rectangle(x0, y0, cx, cy, outline=self.colors["rect"], width=max(1, self.stroke * self.ppp),
                               tags=("preview", "overlay"))
        elif d[0] == "highlight":
            r = self.canvas_rect_to_page(i, x0, y0, cx, cy)
            for wd in self.words(i):
                if fitz.Rect(wd[:4]).intersects(r):
                    c.create_rectangle(*self.page_rect_to_canvas(i, wd[:4]), fill=self.colors["highlight"],
                                       stipple="gray50", outline="", tags=("preview", "overlay"))
            c.create_rectangle(x0, y0, cx, cy, outline=C["accent"], dash=(3, 2), tags=("preview", "overlay"))
        elif d[0] == "image":
            c.create_rectangle(x0, y0, cx, cy, outline=C["accent"], width=2, dash=(6, 3), tags=("preview", "overlay"))

    def on_tool_release(self, event, cx, cy):
        d = self._drag
        if d and d[0] == "cropbox":
            self._drag = None
            self._crop_release()
            return
        if not d or d[0] in ("pan", "select"):
            return super().on_tool_release(event, cx, cy)
        self._drag = None
        self.canvas.delete("preview")
        kind = d[0]
        if kind == "pen":
            self._add_ink(d[1], d[2])
            return
        _k, i, x0, y0 = d
        x, y, w, h = self.boxes[i]
        cx, cy = min(max(cx, x), x + w), min(max(cy, y), y + h)
        small = abs(cx - x0) < 4 and abs(cy - y0) < 4
        r = self.canvas_rect_to_page(i, x0, y0, cx, cy)
        if kind == "image":
            self._add_image(i, x0, y0, None if small else r)
            return
        if small:
            return
        if kind == "rect":
            self._add_rect(i, r)
        elif kind == "whiteout":
            self._whiteout(i, r)
        elif kind == "highlight":
            self._add_highlight(i, r)

    def on_delete_key(self):
        if self.focus_area == "thumbs":
            self.delete_pages()
        elif self.sel_annot:
            self._delete_annot()

    def on_escape(self):
        if getattr(self, "_eyedrop", False):
            self._eyedrop = False
            self.canvas.configure(cursor="")
        elif self.crop is not None:
            self.cancel_crop()
        elif self.editor is not None:
            self.cancel_editor()
        elif self.tool != "select":
            self.set_tool("select")
        else:
            self.sel_annot = None
            super().on_escape()

    def _annot_at(self, i, cx, cy):
        p = self.to_page(i, cx, cy)
        found = None
        for annot in self.doc[i].annots() or []:
            if annot.rect.contains(p):
                found = annot
        return found

    def draw_extra_overlays(self):
        self._draw_crop()
        if self.sel_annot and self.doc is not None:
            i, xref = self.sel_annot
            try:
                annot = self.doc[i].load_annot(xref)
            except Exception:  # noqa: BLE001
                annot = None
            if annot is not None:
                x0, y0, x1, y1 = self.page_rect_to_canvas(i, annot.rect)
                self.canvas.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3, outline=C["accent"], width=2, dash=(4, 2),
                                             tags=("overlay",))

    def layout(self):
        self.commit_editor()
        super().layout()

    # ─────────────────────────── annotations ───────────────────────────
    def _finish(self, annot, i):
        annot.update()
        self.refresh_pages([i])

    def _add_ink(self, i, pts):
        if len(pts) < 2:
            return
        self.snapshot()
        page = self.doc[i]
        stroke = [tuple(self.to_page(i, x, y)) for x, y in pts]
        annot = page.add_ink_annot([stroke])
        annot.set_colors(stroke=rgb01(self.colors["pen"]))
        annot.set_border(width=self.stroke)
        self._finish(annot, i)

    def _add_rect(self, i, r):
        self.snapshot()
        annot = self.doc[i].add_rect_annot(r)
        annot.set_colors(stroke=rgb01(self.colors["rect"]))
        annot.set_border(width=self.stroke)
        self._finish(annot, i)

    def _add_highlight(self, i, r):
        page = self.doc[i]
        area = fitz.Rect(r).normalize() & page.rect
        # words with a zero width / height (spaces, odd fonts) make PyMuPDF refuse the whole highlight
        words = [w for w in (fitz.Rect(x[:4]) & page.rect for x in self.words(i))
                 if w.intersects(area) and w.width > 0.5 and w.height > 0.5]
        candidates = [words] if words else []
        if not area.is_empty and area.width >= 1 and area.height >= 1:
            candidates.append(area)
        if candidates:
            was_dirty = self.dirty
            self.snapshot()
            for target in candidates:
                try:
                    annot = page.add_highlight_annot(target)
                except ValueError:
                    continue
                annot.set_colors(stroke=rgb01(self.colors["highlight"]))
                self._finish(annot, i)
                return
            self.undo_stack.pop()                  # nothing was changed
            self.set_dirty(was_dirty)
        self.toast(T("Nothing to highlight here - drag across the text."), "info", 2500)

    def _delete_annot(self):
        i, xref = self.sel_annot
        self.snapshot()
        page = self.doc[i]
        page.delete_annot(page.load_annot(xref))
        self.sel_annot = None
        self.refresh_pages([i])
        self.draw_overlays()

    @staticmethod
    def _apply_redactions(page, images, graphics):
        try:
            page.apply_redactions(images=images, graphics=graphics)
        except TypeError:
            page.apply_redactions(images=images)

    def _whiteout(self, i, r):
        self.snapshot()
        page = self.doc[i]
        page.add_redact_annot(r, fill=(1, 1, 1))
        self._apply_redactions(page, fitz.PDF_REDACT_IMAGE_PIXELS, 1)
        self.refresh_pages([i])

    def _add_image(self, i, cx, cy, rect):
        if not self.image_path:
            return
        from PIL import Image
        page = self.doc[i]
        if rect is None:
            with Image.open(self.image_path) as im:
                iw, ih = im.size
            pw, ph = page.rect.width, page.rect.height
            scale = min(1.0, pw * 0.4 / iw, ph * 0.4 / ih)
            d = self.to_display(i, cx, cy)
            disp = fitz.Rect(d.x, d.y, d.x + iw * scale, d.y + ih * scale)
            rect = (disp * page.derotation_matrix).normalize()
        self.snapshot()
        page.insert_image(rect, filename=self.image_path, keep_proportion=True, rotate=page.rotation)
        self.refresh_pages([i])
        self.set_tool("select")

    # ─────────────────────────── crop: adjustable frame, then Apply ───────────────────────────
    HANDLE = 7

    def _crop_canvas_rect(self):
        i, r = self.crop["page"], self.crop["rect"]
        x, y, _w, _h = self.boxes[i]
        return x + r.x0 * self.ppp, y + r.y0 * self.ppp, x + r.x1 * self.ppp, y + r.y1 * self.ppp

    def _crop_hit(self, cx, cy):
        """Which part of the pending frame is under the pointer: 'move', an edge set like 'nw', or None."""
        x0, y0, x1, y1 = self._crop_canvas_rect()
        h = px(self.HANDLE) + 3
        edges = ("n" if abs(cy - y0) <= h else "s" if abs(cy - y1) <= h else "") + \
                ("w" if abs(cx - x0) <= h else "e" if abs(cx - x1) <= h else "")
        inside_x, inside_y = x0 - h <= cx <= x1 + h, y0 - h <= cy <= y1 + h
        if edges and inside_x and inside_y:
            return edges
        if x0 < cx < x1 and y0 < cy < y1:
            return "move"
        return None

    def _crop_press(self, i, cx, cy):
        if self.crop is not None and self.crop["page"] == i:
            hit = self._crop_hit(cx, cy)
            if hit:
                self._drag = ("cropbox", hit, cx, cy, fitz.Rect(self.crop["rect"]))
                return
        p = self.to_display(i, cx, cy)
        if i not in self.selected and len(self.selected) <= 1:      # a stale single selection must not be cropped
            self.selected = {i}
            self.draw_thumbs_state()
        self.crop = {"page": i, "rect": fitz.Rect(p, p), "target": (self.crop or {}).get("target", "this")}
        self._drag = ("cropbox", "se", cx, cy, fitz.Rect(p, p))

    def _crop_drag(self, cx, cy):
        _k, mode, sx, sy, start = self._drag
        i = self.crop["page"]
        x, y, w, h = self.boxes[i]
        cx, cy = min(max(cx, x), x + w), min(max(cy, y), y + h)
        dx, dy = (cx - sx) / self.ppp, (cy - sy) / self.ppp
        pw, ph = w / self.ppp, h / self.ppp
        r = fitz.Rect(start)
        if mode == "move":
            dx = min(max(dx, -r.x0), pw - r.x1)
            dy = min(max(dy, -r.y0), ph - r.y1)
            r = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
        else:
            if "n" in mode:
                r.y0 = start.y0 + dy
            if "s" in mode:
                r.y1 = start.y1 + dy
            if "w" in mode:
                r.x0 = start.x0 + dx
            if "e" in mode:
                r.x1 = start.x1 + dx
        self.crop["rect"] = r
        self._sync_margins()
        self.draw_overlays()

    def _crop_release(self):
        r = self.crop["rect"].normalize()
        self.crop["rect"] = r
        if r.width * self.ppp < 6 or r.height * self.ppp < 6:
            self.cancel_crop()
            return
        self._show_crop_bar()
        self.draw_overlays()

    def _draw_crop(self):
        c = self.canvas
        c.delete("crop")
        if self.crop is None or self.crop["page"] >= len(self.boxes):
            return
        i = self.crop["page"]
        x, y, w, h = self.boxes[i]
        x0, y0, x1, y1 = self._crop_canvas_rect()
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if not (self._drag and self._drag[0] == "cropbox"):      # dim what will be cut off (not while dragging)
            self._crop_shade = self._shade_image(int(w), int(h), int(x0 - x), int(y0 - y), int(x1 - x), int(y1 - y))
            if self._crop_shade is not None:
                c.create_image(x, y, image=self._crop_shade, anchor="nw", tags=("overlay", "crop"))
        c.create_rectangle(x0, y0, x1, y1, outline="#ffffff", width=3, tags=("overlay", "crop"))
        c.create_rectangle(x0, y0, x1, y1, outline=C["accent"], width=2, dash=(6, 3), tags=("overlay", "crop"))
        hs = px(self.HANDLE) / 2
        for hx in (x0, (x0 + x1) / 2, x1):
            for hy in (y0, (y0 + y1) / 2, y1):
                if hx == (x0 + x1) / 2 and hy == (y0 + y1) / 2:
                    continue
                c.create_rectangle(hx - hs, hy - hs, hx + hs, hy + hs, fill="#ffffff", outline=C["accent"], width=2,
                                   tags=("overlay", "crop"))
        r = self.crop["rect"].normalize()
        label = f"{r.width * 25.4 / 72:.0f} \u00d7 {r.height * 25.4 / 72:.0f} mm"
        tid = c.create_text(x1 - 6, y1 - 6, text=label, anchor="se", fill="#ffffff", font=FONTS["small_bold"],
                            tags=("overlay", "crop"))
        bx0, by0, bx1, by1 = c.bbox(tid)
        c.tag_lower(c.create_rectangle(bx0 - 5, by0 - 2, bx1 + 5, by1 + 2, fill=C["accent"], outline="",
                                       tags=("overlay", "crop")), tid)

    @staticmethod
    def _shade_image(w, h, x0, y0, x1, y1):
        """Semi-transparent dark layer over the page with a clear hole where the crop frame is."""
        try:
            from PIL import Image, ImageDraw, ImageTk
        except ImportError:
            return None
        if w <= 0 or h <= 0 or w * h > 40_000_000:
            return None
        img = Image.new("RGBA", (w, h), (10, 12, 20, 140))
        ImageDraw.Draw(img).rectangle((max(0, x0), max(0, y0), min(w, x1) - 1, min(h, y1) - 1), fill=(0, 0, 0, 0))
        return ImageTk.PhotoImage(img)

    def _crop_targets(self, choice=None):
        i = self.crop["page"]
        choice = choice or self.crop.get("target", "this")
        return {"this": [i], "selected": sorted(k for k in self.selected | {i} if 0 <= k < self.page_count),
                "all": list(range(self.page_count))}[choice]

    @staticmethod
    def _pages_text(pages):
        """[0, 1, 2, 5] -> '1–3, 6'"""
        out, start, prev = [], None, None
        for k in pages + [None]:
            if k is not None and prev is not None and k == prev + 1:
                prev = k
                continue
            if start is not None:
                out.append(str(start + 1) if start == prev else f"{start + 1}\u2013{prev + 1}")
            start = prev = k
        return ", ".join(out)

    def _target_label(self, key):
        names = {"this": T("This page"), "selected": T("Selected pages"), "all": T("All pages")}
        pages = self._crop_targets(key)
        if key == "all":
            return f"{names[key]} ({len(pages)})"
        return f"{names[key]}: {self._pages_text(pages)}"

    def crop_nudge(self, dx, dy, grow=False):
        """Arrow keys move the frame by 1 pt (Shift: 10 pt); with Alt they move the right/bottom edge."""
        if self.crop is None:
            return
        i = self.crop["page"]
        _x, _y, w, h = self.boxes[i]
        pw, ph = w / self.ppp, h / self.ppp
        r = fitz.Rect(self.crop["rect"])
        if grow:
            r.x1 = min(max(r.x0 + 5, r.x1 + dx), pw)
            r.y1 = min(max(r.y0 + 5, r.y1 + dy), ph)
        else:
            dx = min(max(dx, -r.x0), pw - r.x1)
            dy = min(max(dy, -r.y0), ph - r.y1)
            r = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
        self.crop["rect"] = r
        self._sync_margins()
        self.draw_overlays()

    def _sync_margins(self):
        """Keep the exact-margin fields of the crop bar in step with the frame."""
        fields = getattr(self, "_margin_vars", None)
        if not fields or self.crop is None:
            return
        i = self.crop["page"]
        _x, _y, w, h = self.boxes[i]
        pw, ph = w / self.ppp, h / self.ppp
        r = self.crop["rect"].normalize()
        self._margin_sync = True
        for key, val in (("left", r.x0), ("top", r.y0), ("right", pw - r.x1), ("bottom", ph - r.y1)):
            fields[key].set(f"{max(0.0, val) * 25.4 / 72:.1f}")
        self._margin_sync = False

    def _margins_changed(self, *_a):
        if getattr(self, "_margin_sync", False) or self.crop is None:
            return
        i = self.crop["page"]
        _x, _y, w, h = self.boxes[i]
        pw, ph = w / self.ppp, h / self.ppp
        try:
            m = {k: max(0.0, float(v.get().replace(",", "."))) * 72 / 25.4 for k, v in self._margin_vars.items()}
        except ValueError:
            return
        r = fitz.Rect(m["left"], m["top"], pw - m["right"], ph - m["bottom"])
        if r.width >= 5 and r.height >= 5:
            self.crop["rect"] = r
            self.draw_overlays()

    def _show_crop_bar(self):
        if self.crop_bar is not None:
            self.crop_bar.lift()
            self._sync_margins()
            return
        bar = tk.Frame(self.canvas.master, bg=C["panel"], highlightthickness=1, highlightbackground=C["border_strong"])
        top = tk.Frame(bar, bg=C["panel"])
        top.pack(fill="x")
        tk.Label(top, text=T("Drag the frame or its corners, then apply."), bg=C["panel"], fg=C["fg_dim"],
                 font=FONTS["small"]).pack(side="left", padx=(px(12), px(8)), pady=px(6))

        def target_menu(m):
            for key in ("this", "selected", "all"):
                m.add_command(label=self._target_label(key),
                              command=lambda k=key: (self.crop and self.crop.update(target=k),
                                                     target_btn.set_text(self._target_label(k))))
        target_btn = theme.ToolButton(top, self._target_label(self.crop.get("target", "this")), None,
                                      menu=target_menu, bg=C["panel"], hover=C["hover_strong"], pad=(10, 4))
        target_btn.pack(side="left")
        theme.ToolButton(top, T("Crop  (Enter)"), "crop", self.apply_crop, variant="primary", pad=(12, 4)).pack(
            side="left", padx=px(6), pady=px(4))
        theme.ToolButton(top, T("Cancel  (Esc)"), None, self.cancel_crop, bg=C["panel"], hover=C["hover_strong"],
                         pad=(10, 4)).pack(side="left", padx=(0, px(6)))
        # exact margins in millimetres: typing a value moves the frame, dragging the frame updates the values
        row = tk.Frame(bar, bg=C["panel"])
        row.pack(fill="x", padx=px(12), pady=(0, px(6)))
        head = tk.Label(row, text=T("Margins, mm:"), bg=C["panel"], fg=C["fg_dim"], font=FONTS["small"])
        head.pack(side="left")
        theme.Tooltip(head, T("Arrows move the frame, Shift = 10 pt, Alt = resize"))
        self._margin_vars = {}
        for key, text in (("left", T("Left")), ("top", T("Top")), ("right", T("Right")), ("bottom", T("Bottom"))):
            tk.Label(row, text=text, bg=C["panel"], fg=C["fg"], font=FONTS["small"]).pack(side="left",
                                                                                          padx=(px(10), px(3)))
            var = tk.StringVar(bar)
            ent = tk.Entry(row, textvariable=var, width=6, relief="flat", bg=C["input"], fg=C["fg"],
                           insertbackground=C["fg"], highlightthickness=1, highlightbackground=C["border"],
                           highlightcolor=C["accent"], font=FONTS["small"], justify="right")
            ent.pack(side="left")
            ent.bind("<Return>", lambda e: (self.apply_crop(), "break")[1])
            ent.bind("<Escape>", lambda e: (self.cancel_crop(), "break")[1])
            self._margin_vars[key] = var
        self._sync_margins()
        for var in self._margin_vars.values():
            var.trace_add("write", self._margins_changed)
        bar.place(in_=self.canvas, relx=0.5, y=px(12), anchor="n")
        self.crop_bar = bar
        self.canvas.bind("<Return>", lambda e: (self.apply_crop(), "break")[1])
        for key, (ddx, ddy) in {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}.items():
            self.canvas.bind(f"<{key}>", lambda e, a=ddx, b=ddy: self._crop_key(e, a, b))
            self.canvas.bind(f"<Shift-{key}>", lambda e, a=ddx, b=ddy: self._crop_key(e, a * 10, b * 10))
            self.canvas.bind(f"<Alt-{key}>", lambda e, a=ddx, b=ddy: self._crop_key(e, a, b, True))
            self.canvas.bind(f"<Alt-Shift-{key}>", lambda e, a=ddx, b=ddy: self._crop_key(e, a * 10, b * 10, True))
        self.canvas.focus_set()

    def _crop_key(self, _event, dx, dy, grow=False):
        if self.crop is None:                # no frame: the keys do what they did before
            if dy:
                self._scroll(-2 if dy < 0 else 2)
                return "break"
            return None
        self.crop_nudge(dx, dy, grow)
        return "break"

    def cancel_crop(self):
        self.crop = None
        self._margin_vars = None
        if self.crop_bar is not None:
            self.crop_bar.destroy()
            self.crop_bar = None
        self.draw_overlays()

    def apply_crop(self):
        if self.crop is None:
            return
        i, disp = self.crop["page"], self.crop["rect"].normalize()
        targets = self._crop_targets()
        src_w, src_h = self.doc[i].rect.width, self.doc[i].rect.height
        self.cancel_crop()
        self.snapshot()
        done = 0
        for k in targets:
            page = self.doc[k]
            d = fitz.Rect(disp)
            w, h = page.rect.width, page.rect.height
            if abs(w - src_w) > 0.5 or abs(h - src_h) > 0.5:     # another page size: keep the same proportions
                d = fitz.Rect(d.x0 / src_w * w, d.y0 / src_h * h, d.x1 / src_w * w, d.y1 / src_h * h)
            r = (d * page.derotation_matrix).normalize()
            r = r + (page.cropbox_position.x, page.cropbox_position.y, page.cropbox_position.x,
                     page.cropbox_position.y)
            r = r & page.mediabox
            if r.is_empty or r.width < 5 or r.height < 5:
                continue
            page.set_cropbox(r)
            done += 1
        self.refresh_pages(structure=True)
        self.toast(T("Cropped {0} page{1} \u2014 Pages \u2192 Reset crop brings the full page back", done,
                     "s" if done != 1 else ""))

    # ─────────────────────────── inline text editor ───────────────────────────
    def open_editor(self, i, cx, cy, text, size_pt, color, bg, on_commit, extra=None):
        size_px = max(6, int(round(size_pt * self.ppp)))
        family = FONTS["ui"][0]
        font = tkfont.Font(self.app.root, family=family, size=-size_px)
        lines = text.split("\n") or [""]
        ed = tk.Text(self.canvas, font=font, fg=color, bg=bg, insertbackground=color if color != bg else "#000",
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=C["accent"],
                     highlightcolor=C["accent"], padx=1, pady=0, wrap="none", undo=True,
                     width=max(6, max(len(ln) for ln in lines) + 2), height=max(1, len(lines)),
                     selectbackground="#b3d4ff", selectforeground="#000000")
        ed.insert("1.0", text)
        ed.tag_add("sel", "1.0", "end-1c") if text else None
        win = self.canvas.create_window(cx, cy, window=ed, anchor="nw", tags=("editor",))

        def autosize(_e=None):
            ls = ed.get("1.0", "end-1c").split("\n")
            ed.configure(width=max(6, max(len(x) for x in ls) + 2), height=max(1, len(ls)))

        ed.bind("<KeyRelease>", autosize)
        ed.bind("<Escape>", lambda e: (self.cancel_editor(), "break")[1])
        ed.bind(f"<{theme.PRIMARY}-Return>", lambda e: (self.commit_editor(), "break")[1])
        self.editor = {"widget": ed, "item": win, "page": i, "commit": on_commit, "font": font, "cx": cx, "cy": cy,
                       "original": text, "extra": extra, "size": size_pt, "color": color}
        ed.focus_set()
        ed.mark_set("insert", "end-1c")

    def cancel_editor(self):
        ed, self.editor = self.editor, None
        if ed:
            self.canvas.delete(ed["item"])
            ed["widget"].destroy()
            self.canvas.focus_set()

    def commit_editor(self):
        ed = self.editor
        if not ed:
            return
        text = ed["widget"].get("1.0", "end-1c")
        self.cancel_editor()
        if text != ed["original"]:
            try:
                ed["commit"](ed, text)
            except Exception as exc:  # noqa: BLE001
                self.toast(T("Couldn't apply the text: {0}", exc), "error", 4000)

    @staticmethod
    def _css(size, color, family="sans-serif", bold=False, italic=False):
        return (f"* {{font-family: {family}; font-size: {size:.2f}px; color: {color}; line-height: 1.18;"
                f" font-weight: {'bold' if bold else 'normal'}; font-style: {'italic' if italic else 'normal'};}}")

    def _commit_new_text(self, ed, text):
        if not text.strip():
            return
        i = ed["page"]
        page = self.doc[i]
        d = self.to_display(i, ed["cx"], ed["cy"])
        pr = page.rect
        disp = fitz.Rect(d.x, d.y, max(pr.width, d.x + 50), max(pr.height, d.y + 50))
        rect = (disp * page.derotation_matrix).normalize()
        self.snapshot()
        page.insert_htmlbox(rect, text_to_html(text), css=self._css(ed["size"], ed["color"]), rotate=page.rotation)
        self.refresh_pages([i])

    # ── edit existing text ──
    def _line_at(self, i, cx, cy):
        p = self.to_page(i, cx, cy)
        info = self.doc[i].get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        best = None
        for block in info.get("blocks", []):
            for line in block.get("lines", []):
                bbox = fitz.Rect(line["bbox"])
                if bbox.contains(p) or (bbox + (-2, -2, 2, 2)).contains(p):
                    best = line
        return best

    def _start_edit_line(self, i, cx, cy):
        line = self._line_at(i, cx, cy)
        if line is None:
            if not self.words(i):            # a scanned page / an image saved as PDF has no text to edit
                self.toast(T("This page is a picture without a text layer (for example a scan or an image saved "
                             "as PDF) - its letters and numbers can't be edited. Use Text to write over it, or "
                             "Erase to cover parts of it."), "warning", 7000)
            else:
                self.toast(T("Click directly on a line of text to edit it."), "info", 2500)
            return
        if abs(line["dir"][1]) > 0.01 or line["dir"][0] < 0:
            self.toast(T("Only horizontal text can be edited."), "warning")
            return
        spans = [s for s in line["spans"] if s["text"]]
        if not spans:
            return
        text = "".join(s["text"] for s in spans)
        main = max(spans, key=lambda s: len(s["text"].strip()))
        bbox = fitz.Rect(line["bbox"])
        bg = self._sample_background(i, bbox)
        bg_hex = "#%02x%02x%02x" % tuple(int(v * 255) for v in bg)
        color = "#%06x" % (main.get("color", 0) & 0xFFFFFF)
        font_name = main.get("font", "")
        flags = main.get("flags", 0)
        style = {"bold": bool(flags & 16) or "bold" in font_name.lower() or "black" in font_name.lower(),
                 "italic": bool(flags & 2) or "italic" in font_name.lower() or "oblique" in font_name.lower(),
                 "family": "monospace" if (flags & 8 or re.search(r"courier|mono|consol", font_name, re.I))
                 else "serif" if (flags & 4 or re.search(r"times|serif|georgia|cambria|garamond|minion|book",
                                                          font_name, re.I) and "sans" not in font_name.lower())
                 else "sans-serif"}
        x0, y0, _x1, _y1 = self.page_rect_to_canvas(i, bbox)
        self.open_editor(i, x0, y0, text, main["size"], color, bg_hex, self._commit_edit_line,
                         extra={"bbox": bbox, "bg": bg, "style": style, "size": main["size"], "color": color})

    def _sample_background(self, i, bbox):
        page = self.doc[i]
        clip = (bbox * page.rotation_matrix) + (-1.5, -1.5, 1.5, 1.5)
        try:
            pix = page.get_pixmap(clip=clip & page.rect, alpha=False)
        except Exception:  # noqa: BLE001
            return 1, 1, 1
        w, h = pix.width, pix.height
        counts = {}
        for x, y in [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + \
                    [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]:
            px_ = pix.pixel(x, y)
            counts[px_] = counts.get(px_, 0) + 1
        best = max(counts, key=counts.get) if counts else (255, 255, 255)
        return tuple(v / 255 for v in best[:3])

    def _commit_edit_line(self, ed, text):
        info = ed["extra"]
        i = ed["page"]
        page = self.doc[i]
        bbox = info["bbox"]
        self.snapshot()
        page.add_redact_annot(bbox, fill=info["bg"])
        self._apply_redactions(page, fitz.PDF_REDACT_IMAGE_NONE, 0)
        if text.strip():
            disp = bbox * page.rotation_matrix
            pr = page.rect
            room = fitz.Rect(disp.x0, disp.y0 - info["size"] * 0.06, max(pr.width, disp.x0 + 50),
                             max(pr.height, disp.y1 + 50))
            rect = (room * page.derotation_matrix).normalize()
            st = info["style"]
            page.insert_htmlbox(rect, text_to_html(text),
                                css=self._css(info["size"], info["color"], st["family"], st["bold"], st["italic"]),
                                rotate=page.rotation)
        self.refresh_pages([i])

    # ─────────────────────────── page operations ───────────────────────────
    def fill_page_menu(self, m):
        n = len(self.selected)
        label = f"{n} pages" if n > 1 else f"page {self.cur + 1}" if n == 1 and self.cur in self.selected else "pages"
        m.add_command(label=T("Rotate right  ({0})", label), command=lambda: self.rotate_pages(90))
        m.add_command(label=T("Rotate left"), command=lambda: self.rotate_pages(-90))
        m.add_separator()
        m.add_command(label=T("Copy pages"), accelerator="Ctrl+C", command=self.copy_pages)
        m.add_command(label=T("Cut pages"), accelerator="Ctrl+X", command=self.cut_pages)
        m.add_command(label=T("Paste pages after current"), accelerator="Ctrl+V", command=self.paste_pages,
                      state="normal" if self.app.page_clipboard else "disabled")
        m.add_command(label=T("Duplicate"), command=self.duplicate_pages)
        m.add_command(label=T("Delete"), accelerator="Del", command=self.delete_pages)
        m.add_separator()
        m.add_command(label=T("Move up"), command=lambda: self.move_pages(-1))
        m.add_command(label=T("Move down"), command=lambda: self.move_pages(1))
        m.add_separator()
        m.add_command(label=T("Extract pages to new PDF…"), command=self.extract_dialog)
        m.add_command(label=T("Split into files…"), command=self.split_dialog)
        m.add_command(label=T("Insert blank page after"), command=self.insert_blank)
        m.add_command(label=T("Insert pages from file…"), command=self.insert_from_file)
        m.add_command(label=T("Reset crop"), command=self.reset_crop)
        m.add_separator()
        m.add_command(label=T("Select all pages"), accelerator="Ctrl+A", command=self.select_all_pages)
        m.add_command(label=T("Export page images…"), command=self.export_images)

    def sel_list(self):
        return sorted(i for i in self.selected if 0 <= i < self.page_count) or [self.cur]

    def select_all_pages(self):
        self.selected = set(range(self.page_count))
        self.draw_thumbs_state()

    def rotate_pages(self, angle):
        pages = self.sel_list()
        self.snapshot()
        for i in pages:
            page = self.doc[i]
            page.set_rotation((page.rotation + angle) % 360)
        self.refresh_pages(structure=True)

    def _subset_bytes(self, pages):
        new = fitz.open()
        for i in pages:
            new.insert_pdf(self.doc, from_page=i, to_page=i)
        data = new.tobytes(garbage=3, deflate=True)
        new.close()
        return data

    def copy_pages(self):
        pages = self.sel_list()
        self.app.page_clipboard = self._subset_bytes(pages)
        self.toast(T("Copied {0} page{1} — paste with Ctrl+V in any PDF", len(pages), 's' if len(pages) != 1 else ''))

    def cut_pages(self):
        pages = self.sel_list()
        if len(pages) >= self.page_count:
            self.toast(T("A PDF needs at least one page."), "warning")
            return
        self.app.page_clipboard = self._subset_bytes(pages)
        self._delete(pages)
        self.toast(T("Cut {0} page{1} — paste with Ctrl+V", len(pages), 's' if len(pages) != 1 else ''))

    def paste_pages(self):
        data = self.app.page_clipboard
        if not data:
            self.toast(T("Copy or cut some pages first."), "info")
            return
        src = open_pdf_bytes(data)
        at = self.cur + 1
        self.snapshot()
        self.doc.insert_pdf(src, start_at=at)
        n = len(src)
        src.close()
        self.selected = set(range(at, at + n))
        self.cur = at
        self.refresh_pages(structure=True)
        self.goto_page(at)

    def delete_pages(self):
        pages = self.sel_list()
        if len(pages) >= self.page_count:
            self.toast(T("A PDF needs at least one page."), "warning")
            return
        if len(pages) > 1 and not messagebox.askyesno(T("Delete pages"), T("Delete {0} pages?", len(pages)),
                                                      parent=self.app.root):
            return
        self._delete(pages)

    def _delete(self, pages):
        self.snapshot()
        drop = set(pages)
        self.doc.select([i for i in range(self.page_count) if i not in drop])
        self.cur = min(pages[0], self.page_count - 1)
        self.selected = {self.cur}
        self.refresh_pages(structure=True)

    def duplicate_pages(self):
        pages = self.sel_list()
        order = list(range(self.page_count))
        last = pages[-1]
        order[last + 1:last + 1] = pages
        self.snapshot()
        self.doc.select(order)
        self.selected = set(range(last + 1, last + 1 + len(pages)))
        self.refresh_pages(structure=True)

    def move_pages(self, step):
        pages = self.sel_list()
        n = self.page_count
        if (step < 0 and pages[0] == 0) or (step > 0 and pages[-1] == n - 1):
            return
        chosen = set(pages)
        rest = [i for i in range(n) if i not in chosen]
        pos = rest.index(pages[0] - 1) if step < 0 else rest.index(pages[-1] + 1) + 1
        new = rest[:pos] + pages + rest[pos:]
        self.snapshot()
        self.doc.select(new)
        start = new.index(pages[0])
        self.selected = set(range(start, start + len(pages)))
        self.cur = start
        self.refresh_pages(structure=True)

    def insert_blank(self):
        page = self.doc[self.cur]
        w, h = page.rect.width, page.rect.height
        self.snapshot()
        self.doc.new_page(pno=self.cur + 1, width=w, height=h)
        self.selected = {self.cur + 1}
        self.refresh_pages(structure=True)
        self.goto_page(self.cur + 1)

    def insert_from_file(self):
        paths = filedialog.askopenfilenames(
            parent=self.app.root, title=T("Insert pages from…"),
            filetypes=[(T("PDF, images, documents"), "*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp "
                                                  "*.xps *.epub"), (T("All files"), "*")])
        if not paths:
            return
        from . import convert
        paths = sorted(self.app.root.tk.splitlist(paths), key=formats.natural_key)
        at = self.cur + 1
        try:
            data = convert.files_to_pdf(paths)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(T("Insert pages"), str(exc), parent=self.app.root)
            return
        src = open_pdf_bytes(data)
        self.snapshot()
        self.doc.insert_pdf(src, start_at=at)
        n = len(src)
        src.close()
        self.selected = set(range(at, at + n))
        self.refresh_pages(structure=True)
        self.goto_page(at)
        self.toast(T("Inserted {0} page{1}", n, 's' if n != 1 else ''))

    def reset_crop(self):
        self.snapshot()
        for i in self.sel_list():
            page = self.doc[i]
            page.set_cropbox(page.mediabox)
        self.refresh_pages(structure=True)

    def extract_dialog(self):
        default = format_ranges(self.sel_list())
        spec = theme.ask_string(self.frame, T("Extract pages"), T("Pages to extract into a new PDF:"), default,
                                hint=T("Examples: 1-3, 5, 8-   (this document has {0} pages)", self.page_count),
                                ok_text=T("Extract"))
        if not spec:
            return
        try:
            pages = parse_ranges(spec, self.page_count)
        except ValueError as exc:
            messagebox.showerror(T("Extract pages"), str(exc), parent=self.app.root)
            return
        if not pages:
            return
        stem = os.path.splitext(self.title)[0]
        self.app.open_pdf_bytes(self._subset_bytes(pages), f"{stem} (pages {format_ranges(pages)}).pdf")

    def split_dialog(self):
        spec = theme.ask_string(self.frame, T("Split PDF"), T("Pages per file:"), "1",
                                hint=T("Every file gets this many pages. The files are saved to a folder you choose."),
                                ok_text=T("Split"))
        if not spec:
            return
        try:
            per = max(1, int(spec))
        except ValueError:
            return
        folder = filedialog.askdirectory(parent=self.app.root, title=T("Save the parts to…"),
                                         initialdir=os.path.dirname(self.path) if self.path else self.app.last_dir)
        if not folder:
            return
        stem = os.path.splitext(self.title)[0]
        written = []
        for k, start in enumerate(range(0, self.page_count, per)):
            pages = list(range(start, min(self.page_count, start + per)))
            name = f"{stem}_{k + 1:03d}.pdf" if per > 1 else f"{stem}_page{start + 1:03d}.pdf"
            path = os.path.join(folder, name)
            with open(path, "wb") as fh:
                fh.write(self._subset_bytes(pages))
            written.append(path)
        self.toast(T("Saved {0} files to {1}", len(written), os.path.basename(folder)))

    # ─────────────────────────── keyboard actions ───────────────────────────
    def edit_action(self, action):
        if action == "undo":
            self.undo()
            return True
        if action == "redo":
            self.redo()
            return True
        if self.focus_area == "thumbs":
            fn = {"copy": self.copy_pages, "cut": self.cut_pages, "paste": self.paste_pages,
                  "selectall": self.select_all_pages}.get(action)
            if fn:
                fn()
                return True
        if action == "paste" and self.app.page_clipboard:
            self.paste_pages()
            return True
        return super().edit_action(action)

    def build_ui(self):
        super().build_ui()
        self.canvas.bind("<KeyPress>", self._on_key, add="+")

    def _on_key(self, event):
        if theme.has_modifier(event):
            return None
        from .app import shortcut_key
        key = shortcut_key(event)
        for k, _label, _icon, _tip, short in TOOLS:
            if key == short:
                self.set_tool(k)
                return "break"
        return None

    def status(self):
        segs = super().status()
        label = next(t[1] for t in TOOLS if t[0] == self.tool)
        return [T("Tool: {0}", T(label))] + segs
