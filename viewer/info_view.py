"""File information card (for formats without a full viewer) and the font preview."""

import io
import os
import struct
import time
import tkinter as tk

from . import formats, theme, winutil
from .base import BaseTab
from .theme import C, FONTS, px
from .i18n import T

DWG_VERSIONS = {"AC1.2": "R1.2", "AC1.40": "R1.40", "AC1.50": "R2.05", "AC2.10": "R2.10", "AC1001": "R2.22",
                "AC1002": "R2.50", "AC1003": "R2.60", "AC1004": "R9", "AC1006": "R10", "AC1009": "R11/R12",
                "AC1012": "R13", "AC1014": "R14", "AC1015": "AutoCAD 2000", "AC1018": "AutoCAD 2004",
                "AC1021": "AutoCAD 2007", "AC1024": "AutoCAD 2010", "AC1027": "AutoCAD 2013",
                "AC1032": "AutoCAD 2018+"}
DWG_SENTINEL = bytes.fromhex("1F256D07D43628289D57CA3F9D44102B")

NOTES = {
    ("pln", "pla", "tpl", "pmk", "bpn"): (
        "ArchiCAD project",
        "ArchiCAD files are a closed format — the model itself opens only in ArchiCAD (or the free BIMx "
        "viewer). Shown here is the preview stored in the file. Export from ArchiCAD to PDF, DWG/DXF or IFC to "
        "view the drawings or model here."),
    ("rvt", "rfa", "rte"): (
        "Revit project", "Revit files open only in Autodesk Revit. Export to IFC, DWG/DXF or PDF to view here."),
    ("dwf", "dgn", "3dm", "skp"): (
        "CAD file", "This CAD format needs its own application. DXF, DWG (with ODA File Converter) and PDF "
                    "exports can be viewed here."),
    ("mxd", "aprx", "lyr", "lyrx"): (
        "ArcGIS document", "ArcGIS documents reference data stored elsewhere. Open the layers themselves "
                           "(Shapefile, GeoPackage, GeoJSON, KML) to view them on the map here."),
}
EVERYDAY = {
    "office": ("docx docm doc dot dotx rtf odt ott xlsx xlsm xls xlsb xlt ods csv tsv pptx pptm ppt pps ppsx odp "
               "vsd vsdx pub one msg eml pst ost mdb accdb",
               "An everyday Office document \u2014 open it with Microsoft Office (Open with Default App). "
               "Monkey Viewer is for the specialist files Office can't open."),
    "archive": ("zip rar 7z tar gz tgz bz2 xz cab", "An archive \u2014 open it with Windows Explorer or your archive "
                                                       "program (Open with Default App)."),
    "media": ("mp3 wav flac m4a aac wma ogg mp4 mov avi mkv wmv webm", "Audio / video \u2014 use Open with Default App "
                                                                      "to play it."),
}
for _exts, _note in EVERYDAY.values():
    NOTES[tuple(_exts.split())] = (None, _note)
NOTES.update({
    ("djvu", "djv"): ("DjVu document",
                      "DjVu pages are shown through the free DjVuLibre program. Install it once and reopen this file \u2014 "
                      "the pages then open in the normal document viewer (zoom, search, export to PDF)."),
    ("exe", "dll", "sys", "ocx", "cpl", "scr", "msu"): (None, "A program file. Details are read from its header; it is "
                                                         "never run by Monkey Viewer."),
    ("lnk",): ("Windows shortcut", None),
})
LINKS = {"djvu": ("Get DjVuLibre (free)", "https://sourceforge.net/projects/djvu/files/DjVuLibre_Windows/"),
         "djv": ("Get DjVuLibre (free)", "https://sourceforge.net/projects/djvu/files/DjVuLibre_Windows/")}


def parse_lnk(path):
    """Target and options of a Windows .lnk shortcut (MS-SHLLINK)."""
    with open(path, "rb") as fh:
        data = fh.read(1 << 20)
    if data[:4] != b"\x4c\x00\x00\x00":
        return None
    flags = struct.unpack_from("<I", data, 0x14)[0]
    pos = 0x4C
    out = {}
    if flags & 0x01:
        pos += 2 + struct.unpack_from("<H", data, pos)[0]

    def cstr(at, wide=False):
        if wide:
            end = at
            while data[end:end + 2] != b"\x00\x00":
                end += 2
            return data[at:end].decode("utf-16-le", "replace")
        end = data.index(b"\x00", at)
        return data[at:end].decode("mbcs" if os.name == "nt" else "latin-1", "replace")

    if flags & 0x02:
        start = pos
        size, header, li_flags = struct.unpack_from("<III", data, pos)
        base_off, net_off, suffix_off = struct.unpack_from("<III", data, pos + 16)
        suffix = cstr(start + suffix_off) if suffix_off else ""
        if li_flags & 1:
            base = cstr(start + base_off)
            if header >= 0x24:
                uoff = struct.unpack_from("<I", data, pos + 28)[0]
                if uoff:
                    base = cstr(start + uoff, True)
            out["target"] = base + suffix
        elif li_flags & 2 and net_off:
            net = start + net_off
            name_off = struct.unpack_from("<I", data, net + 8)[0]
            out["target"] = cstr(net + name_off) + ("\\" + suffix if suffix else "")
        pos += size
    wide = bool(flags & 0x80)
    for bit, key in ((0x04, "description"), (0x08, "relative"), (0x10, "folder"), (0x20, "arguments"),
                     (0x40, "icon")):
        if flags & bit:
            n = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            raw = data[pos:pos + (n * 2 if wide else n)]
            pos += n * 2 if wide else n
            out[key] = raw.decode("utf-16-le" if wide else "latin-1", "replace")
    if "target" not in out and "relative" in out:
        out["target"] = os.path.normpath(os.path.join(os.path.dirname(path), out["relative"]))
    return out


def pe_info(path):
    """Rows describing a Windows program (architecture, type, version resource)."""
    rows = []
    with open(path, "rb") as fh:
        data = fh.read(4096)
    if data[:2] != b"MZ" or len(data) < 0x40:
        return rows
    e = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e:e + 4] != b"PE\x00\x00":
        return rows
    machine, _nsec, stamp = struct.unpack_from("<HHI", data, e + 4)
    chars = struct.unpack_from("<H", data, e + 22)[0]
    opt = e + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    subsystem = struct.unpack_from("<H", data, opt + 68)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    sec_size = struct.unpack_from("<I", data, dd + 4 * 8 + 4)[0] if dd + 40 <= len(data) else 0
    rows.append(("Architecture", {0x14C: "x86 (32-bit)", 0x8664: "x64 (64-bit)", 0xAA64: "ARM64",
                                  0x1C0: "ARM"}.get(machine, hex(machine))))
    rows.append(("Kind", T("Library (DLL)") if chars & 0x2000 else {2: T("Windows application"), 3: T("Console application"),
                                                                  1: T("Driver / native")}.get(subsystem, T("Program"))))
    if 946684800 < stamp < 2147483647:
        rows.append(("Built", time.strftime("%d %b %Y", time.gmtime(stamp))))
    rows.append(("Digital signature", T("present") if sec_size else T("none")))
    rows += version_info(path)
    return rows


def version_info(path):
    if not winutil.IS_WIN:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return []
        buf = ctypes.create_string_buffer(size)
        ver.GetFileVersionInfoW(path, 0, size, buf)
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length))
        if not length.value:
            return []
        lang, cp = struct.unpack("<HH", ctypes.string_at(ptr, 4))
        rows = []
        for key, label in (("FileDescription", "Description"), ("CompanyName", "Company"),
                           ("ProductName", "Product"), ("FileVersion", "File version"),
                           ("ProductVersion", "Product version"), ("LegalCopyright", "Copyright"),
                           ("OriginalFilename", "Original name")):
            q = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{key}"
            if ver.VerQueryValueW(buf, q, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
                value = ctypes.wstring_at(ptr, length.value).rstrip("\x00").strip()
                if value:
                    rows.append((label, value))
        return rows
    except Exception:  # noqa: BLE001
        return []


def note_for(path):
    """(title, note) for formats Monkey Viewer explains instead of opening, in the interface language."""
    ext = formats.ext_of(path)[1:]
    for exts, (title, note) in NOTES.items():
        if ext in exts:
            return T(title), T(note)
    return None, None


def dwg_info(path):
    """(version label, preview PIL image or None) for a DWG file."""
    from PIL import Image
    with open(path, "rb") as fh:
        head = fh.read(0x20)
        code = head[:6].decode("ascii", "replace")
        version = DWG_VERSIONS.get(code, code)
        if len(head) < 0x11 or code < "AC1012":
            return version, None
        seeker = struct.unpack_from("<I", head, 0x0D)[0]
        fh.seek(seeker)
        data = fh.read(21)
        if data[:16] != DWG_SENTINEL:
            return version, None
        entries = [struct.unpack("<BII", fh.read(9)) for _ in range(data[20])]
        best = None
        for kind, start, size in entries:
            if size <= 0 or size > 50_000_000:
                continue
            fh.seek(start)
            blob = fh.read(size)
            try:
                if kind == 6:
                    img = Image.open(io.BytesIO(blob))
                elif kind == 2:
                    hdr, _w, _h, _planes, bpp = struct.unpack_from("<IiiHH", blob, 0)
                    used = struct.unpack_from("<I", blob, 32)[0]
                    ncol = used or (1 << bpp if bpp <= 8 else 0)
                    bmp = b"BM" + struct.pack("<IHHI", 14 + len(blob), 0, 0, 14 + hdr + ncol * 4) + blob
                    img = Image.open(io.BytesIO(bmp))
                else:
                    continue
                img.load()
                if best is None or img.size[0] * img.size[1] > best.size[0] * best.size[1]:
                    best = img
            except Exception:  # noqa: BLE001
                continue
        return version, best


def find_embedded_preview(path, limit=48 * 1024 * 1024):
    """Scan a binary for an embedded PNG/JPEG thumbnail (ArchiCAD, SketchUp, Revit, many others)."""
    from PIL import Image
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit)
    except OSError:
        return None
    best = None

    def consider(blob):
        nonlocal best
        try:
            img = Image.open(io.BytesIO(blob))
            img.load()
        except Exception:  # noqa: BLE001
            return
        w, h = img.size
        if w >= 48 and h >= 48 and (best is None or w * h > best.size[0] * best.size[1]):
            best = img

    pos, found = 0, 0
    while found < 40:
        i = data.find(b"\x89PNG\r\n\x1a\n", pos)
        if i < 0:
            break
        j = data.find(b"IEND\xaeB`\x82", i)
        if j < 0:
            break
        consider(data[i:j + 8])
        pos, found = j + 8, found + 1
    pos, found = 0, 0
    while found < 25:
        i = data.find(b"\xff\xd8\xff", pos)
        if i < 0:
            break
        end = i + 2
        for _try in range(6):
            end = data.find(b"\xff\xd9", end + 2)
            if end < 0:
                break
            if end - i > 2000:
                before = best
                consider(data[i:end + 2])
                if best is not before:
                    break
        pos, found = i + 3, found + 1
    return best


class FitImage(tk.Canvas):
    """Canvas that shows a PIL image scaled to fit (never upscaled beyond 2x), centered."""

    def __init__(self, master, bg=None, max_upscale=2.0, margin=24):
        super().__init__(master, bg=bg or C["bg"], highlightthickness=0, bd=0)
        self.image, self.photo, self.max_upscale, self.margin = None, None, max_upscale, px(margin)
        self._job = None
        self.bind("<Configure>", lambda e: self._schedule())

    def set_image(self, img):
        self.image = img
        self._schedule()

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(40, self._render)

    def _render(self):
        self._job = None
        self.delete("all")
        if self.image is None:
            return
        from PIL import Image, ImageTk
        w, h = self.winfo_width() - 2 * self.margin, self.winfo_height() - 2 * self.margin
        if w < 20 or h < 20:
            return
        iw, ih = self.image.size
        scale = min(w / iw, h / ih, self.max_upscale)
        size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        img = self.image
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img = img.resize(size, Image.LANCZOS if scale < 1 else Image.BICUBIC)
        self.photo = ImageTk.PhotoImage(img)
        self.create_image(self.winfo_width() // 2, self.winfo_height() // 2, image=self.photo)


class InfoTab(BaseTab):
    kind = "info"

    def __init__(self, app, path=None, title=None, error=None, notice=None):
        super().__init__(app, path, title)
        self.error = error
        self.notice = notice
        self.preview = None
        self.extra = []

    def load(self):
        st = os.stat(self.path)
        self.stat = st
        title, note = note_for(self.path)
        self.type_name = title or formats.label_for(self.path) or winutil.shell_type_name(self.path) or T("File")
        if formats.ext_of(self.path) and not formats.label_for(self.path):
            self.type_name = winutil.shell_type_name(self.path) or T("{0} file", formats.ext_of(self.path)[1:].upper())
        self.note = note
        self._build()
        self.run_async(self._find_preview, self._show_preview, error=lambda e: self._show_preview(None),
                       text=T("Looking for a preview…"))

    def _find_preview(self):
        ext = formats.ext_of(self.path)
        try:
            if ext == ".lnk":
                self.lnk = parse_lnk(self.path) or {}
                for key, label in (("target", "Target"), ("arguments", "Arguments"), ("folder", "Start in"),
                                   ("description", "Comment"), ("icon", "Icon")):
                    if self.lnk.get(key):
                        self.extra.append((label, self.lnk[key]))
            elif ext in (".exe", ".dll", ".sys", ".ocx", ".cpl", ".scr") or formats.sniff(self.path) == "info" \
                    and open(self.path, "rb").read(2) == b"MZ":
                self.extra += pe_info(self.path)
            elif ext in (".djvu", ".djv"):
                from .pdf_view import djvu_info
                meta = djvu_info(self.path)
                if meta:
                    self.extra += [("Pages", str(meta[0]))] + ([("Page size", T("{0} \u00D7 {1} px at {2} dpi", meta[1], meta[2],
                                                                                meta[3]))] if meta[1] else [])
        except Exception:  # noqa: BLE001
            pass
        if formats.category_of(self.path) == "binary" or ext in (".lnk", ".msi"):
            img = winutil.shell_thumbnail(self.path, 256, allow_icon=True)
            if img is not None:
                return img, T("Icon")
        if ext == ".dwg":
            version, img = dwg_info(self.path)
            self.extra.append(("DWG version", version))
            if img is not None:
                return img, T("Preview stored in the drawing")
        img = winutil.shell_thumbnail(self.path, 768)
        if img is not None:
            return img, T("Quick Look thumbnail") if winutil.IS_MAC else T("Windows Explorer thumbnail")
        if os.path.getsize(self.path) > 0 and formats.category_of(self.path) not in ("media", "binary", "archive"):
            img = find_embedded_preview(self.path)
            if img is not None:
                return img, T("Preview stored in the file")
        return None

    def _build(self):
        bar = self.bar
        bar.button(T("Open with Default App"), "external", lambda: self.app.open_external(self.path),
                   T("Open in the program Windows uses for this file type"))
        bar.button(T("Show in Folder"), "reveal", lambda: self.app.reveal(self))
        bar.divider()
        bar.button(T("View as Hex"), "list", lambda: self.app.reopen_as(self, "hex"))
        bar.button(T("Copy Path"), "copy", lambda: self.app.copy_path(self), side="right")

        body = self.body
        if self.error or self.notice:
            text = self.notice or T("The built-in viewer couldn't open this file: {0}", self.error)
            banner = tk.Label(body, text=text, bg=C["panel"], fg=C["accent"] if self.notice else C["warning"],
                              font=FONTS["small"], anchor="w", padx=px(14), pady=px(6), justify="left")
            banner.pack(side="top", fill="x")
            banner.bind("<Configure>", lambda e: banner.configure(wraplength=max(200, e.width - px(30))))
        main = tk.Frame(body, bg=C["bg"])
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(0, weight=3, uniform="c")
        main.grid_columnconfigure(1, weight=2, uniform="c")
        main.grid_rowconfigure(0, weight=1)
        self.preview_area = tk.Frame(main, bg=C["bg_deep"])
        self.preview_area.grid(row=0, column=0, sticky="nsew")
        self.fit = FitImage(self.preview_area, bg=C["bg_deep"])
        self.preview_caption = tk.Label(self.preview_area, text="", bg=C["bg_deep"], fg=C["fg_muted"],
                                        font=FONTS["small"])
        self.preview_caption.pack(side="bottom", pady=px(10))
        self.placeholder = self._placeholder(self.preview_area)
        self.placeholder.place(relx=0.5, rely=0.47, anchor="center")

        info = tk.Frame(main, bg=C["bg"], padx=px(28), pady=px(26))
        info.grid(row=0, column=1, sticky="nsew")
        self.info = info
        self._wrapped = []
        info.bind("<Configure>", self._rewrap)
        row = tk.Frame(info, bg=C["bg"])
        row.pack(fill="x")
        tk.Label(row, image=self.badge(), bg=C["bg"]).pack(side="left", padx=(0, px(10)))
        tk.Label(row, text=self.type_name, font=FONTS["small_bold"], bg=C["bg"],
                 fg=theme.KIND_COLORS.get(self.category, C["fg_dim"])).pack(side="left")
        title = tk.Label(info, text=self.title, font=FONTS["h2"], bg=C["bg"], fg=C["fg_bright"], anchor="w",
                         justify="left")
        title.pack(fill="x", pady=(px(10), px(14)))
        self._wrapped.append((title, 0))
        self.details = tk.Frame(info, bg=C["bg"])
        self.details.pack(fill="x")
        self._fill_details()
        if self.note:
            box = tk.Frame(info, bg=C["panel"], padx=px(14), pady=px(12))
            box.pack(fill="x", pady=(px(18), 0))
            note = tk.Label(box, text=self.note, font=FONTS["small"], bg=C["panel"], fg=C["fg_dim"], justify="left",
                            anchor="w")
            note.pack(fill="x")
            self._wrapped.append((note, px(28)))
            link = LINKS.get(formats.ext_of(self.path)[1:])
            if link:
                theme.ToolButton(box, T(link[0]), "download", lambda u=link[1]: winutil.open_url(u), bg=C["panel"],
                                 hover=C["hover_strong"], pad=(8, 4)).pack(anchor="w", pady=(px(8), 0))
        self.action_box = tk.Frame(info, bg=C["bg"])
        self.action_box.pack(fill="x", pady=(px(14), 0))
        if formats.ext_of(self.path) == ".dwg":
            self._dwg_hint(info)

    def _dwg_hint(self, info):
        box = tk.Frame(info, bg=C["panel"], padx=px(14), pady=px(12))
        box.pack(fill="x", pady=(px(12), 0))
        hint = tk.Label(box, text=T("To view and convert the full drawing, install the free ODA File Converter, "
                                  "then reopen this file."), font=FONTS["small"], bg=C["panel"], fg=C["fg_dim"],
                        justify="left", anchor="w")
        hint.pack(fill="x")
        self._wrapped.append((hint, px(28)))
        theme.ToolButton(box, T("Get ODA File Converter"), "download",
                         lambda: winutil.open_url("https://www.opendesign.com/guestfiles/oda_file_converter"),
                         bg=C["panel"], hover=C["hover_strong"], pad=(8, 4)).pack(anchor="w", pady=(px(8), 0))

    def _fill_details(self):
        for w in self.details.winfo_children():
            w.destroy()
        st = self.stat
        rows = [("Size", formats.human_size(st.st_size)),
                ("Modified", time.strftime("%d %b %Y, %H:%M", time.localtime(st.st_mtime))),
                ("Created", time.strftime("%d %b %Y, %H:%M", time.localtime(st.st_ctime))),
                ("Folder", os.path.dirname(self.path))]
        shell_name = winutil.shell_type_name(self.path)
        if shell_name and shell_name != self.type_name:
            rows.insert(1, ("Windows type", shell_name))
        rows += self.extra
        for i, (k, v) in enumerate(rows):
            tk.Label(self.details, text=T(k), font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"], anchor="nw").grid(
                row=i, column=0, sticky="nw", pady=px(3), padx=(0, px(16)))
            val = tk.Label(self.details, text=v, font=FONTS["small"], bg=C["bg"], fg=C["fg"], anchor="w",
                           justify="left", wraplength=self._value_wrap())
            val.grid(row=i, column=1, sticky="w", pady=px(3))

    def _value_wrap(self):
        w = self.info.winfo_width() if hasattr(self, "info") else 0
        return max(px(160), w - px(150)) if w > 1 else px(260)

    def _rewrap(self, event):
        for lbl, pad in self._wrapped:
            lbl.configure(wraplength=max(px(160), event.width - px(56) - pad))
        for child in self.details.grid_slaves(column=1):
            child.configure(wraplength=max(px(160), event.width - px(175)))

    def _placeholder(self, parent):
        box = tk.Frame(parent, bg=C["bg_deep"])
        color = theme.KIND_COLORS.get(self.category, C["fg_muted"])
        glyph, _f = theme.icon(formats.CATEGORIES.get(self.category, (0, 0, "document"))[2])
        tk.Label(box, image=theme.tile_image(color, 96, alpha=36), text=glyph or formats.badge_label(self.path),
                 compound="center", font=FONTS["icon_xl"] if glyph else FONTS["h2"], fg=color,
                 bg=C["bg_deep"]).pack()
        self.placeholder_text = tk.Label(box, text="", font=FONTS["small"], bg=C["bg_deep"], fg=C["fg_muted"])
        self.placeholder_text.pack(pady=(px(12), 0))
        return box

    def _show_preview(self, result):
        if self.extra:
            self._fill_details()
        target = getattr(self, "lnk", {}).get("target")
        if target:
            theme.ToolButton(self.action_box, T("Open target"), "open",
                             lambda: self.app.open_paths([target]) if os.path.isfile(target)
                             else self.app.open_external(target), variant="primary", pad=(12, 5)).pack(side="left")
            if os.path.exists(target):
                theme.ToolButton(self.action_box, T("Show target in folder"), "reveal", lambda: winutil.reveal(target),
                                 bg=C["bg"], hover=C["hover"], pad=(12, 5)).pack(side="left", padx=px(6))
        if not result:
            self.placeholder_text.configure(text=T("No preview available"))
            return
        img, caption = result
        self.preview = img
        self.placeholder.place_forget()
        self.fit.pack(fill="both", expand=True)
        self.fit.set_image(img)
        self.preview_caption.configure(text=f"{caption}  ·  {img.size[0]}×{img.size[1]}")

    def status(self):
        return [self.type_name, formats.human_size(self.stat.st_size)] if hasattr(self, "stat") else []
