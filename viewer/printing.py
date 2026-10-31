"""Printing for every document type.

Each tab hands over a page-based document (PyMuPDF): PDF/DjVu/XPS/CAD pages as they are, text and tables laid
out on A4 pages, images and maps fitted on a page. Then:
  * Windows - the system Print dialog (printer, page range, copies, printer properties) and GDI: every page is
    rendered at the printer's resolution and sent to the device context chosen in the dialog;
  * macOS / Linux - a small dialog (printer, pages, copies, two-sided) and CUPS 'lp' with a temporary PDF.
"""

import html
import os
import re
import shutil
import subprocess  # nosec B404 - lp / lpstat with fixed arguments
import sys
import tempfile
import tkinter as tk

from . import theme
from .i18n import T
from .theme import C, FONTS, px

A4 = (595.0, 842.0)
MARGIN = 42.0
MAX_DPI = 300


# ─────────────────────────────── documents for printing ───────────────────────────────
def _fitz():
    import fitz
    return fitz


def _story_pdf(body_html, title, css, landscape=False):
    """Lay HTML out on A4 pages, with the title and 'page n / N' in the margins."""
    fitz = _fitz()
    w, h = (A4[1], A4[0]) if landscape else A4
    story = fitz.Story(html=body_html, user_css=css)
    import io
    out = io.BytesIO()
    writer = fitz.DocumentWriter(out)
    where = fitz.Rect(MARGIN, MARGIN + 14, w - MARGIN, h - MARGIN - 10)
    more = True
    pages = 0
    while more:
        dev = writer.begin_page(fitz.Rect(0, 0, w, h))
        more, _filled = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
        if pages > 5000:
            break
    writer.close()
    buf = fitz.open("pdf", out.getvalue())
    for n, page in enumerate(buf, 1):
        page.insert_htmlbox(fitz.Rect(MARGIN, MARGIN - 18, w - MARGIN, MARGIN + 8),
                            f"<div style='font-family:sans-serif;font-size:7.5pt;color:#777'>"
                            f"{html.escape(title)}</div>")
        page.insert_htmlbox(fitz.Rect(MARGIN, h - MARGIN + 2, w - MARGIN, h - MARGIN + 22),
                            f"<div style='font-family:sans-serif;font-size:7.5pt;color:#777;text-align:right'>"
                            f"{n} / {len(buf)}</div>")
    return buf


def story_document(body_html, title, css):
    """HTML laid out on A4 pages (title in the header, page numbers in the footer)."""
    return _story_pdf(body_html, title, css)


def text_document(text, title, mono=True):
    css = ("pre {font-family: monospace; font-size: 8.5pt; line-height: 1.3; white-space: pre-wrap;}"
           if mono else "p {font-family: sans-serif; font-size: 10.5pt; line-height: 1.45;}")
    text = text.expandtabs(4)
    body = f"<pre>{html.escape(text)}</pre>" if mono else "".join(
        f"<p>{html.escape(par)}</p>" for par in text.split("\n"))
    return _story_pdf(body, title, css)


def table_document(header, rows, title, limit=20000):
    rows = list(rows)[:limit]
    landscape = len(header) > 6
    css = ("table {border-collapse: collapse; font-family: sans-serif; font-size: 7.5pt; width: 100%;}"
           "th {background-color: #e8ebf2; text-align: left; padding: 2pt 4pt; border: 0.5pt solid #b8bdcc;}"
           "td {padding: 2pt 4pt; border: 0.5pt solid #d0d4de; vertical-align: top;}")
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return _story_pdf(f"<table><tr>{head}</tr>{body}</table>", title, css, landscape)


def image_document(image):
    """One page, A4 portrait or landscape like the image, the image fitted inside the margins."""
    import io
    fitz = _fitz()
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG")
    iw, ih = image.size
    w, h = (A4[1], A4[0]) if iw > ih else A4
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    box = fitz.Rect(MARGIN / 2, MARGIN / 2, w - MARGIN / 2, h - MARGIN / 2)
    scale = min(box.width / iw, box.height / ih)
    dw, dh = iw * scale, ih * scale
    x0, y0 = box.x0 + (box.width - dw) / 2, box.y0 + (box.height - dh) / 2
    page.insert_image(fitz.Rect(x0, y0, x0 + dw, y0 + dh), stream=buf.getvalue())
    return doc


def as_pdf_bytes(doc):
    if getattr(doc, "is_pdf", False):
        return doc.tobytes(garbage=0)
    return doc.convert_to_pdf()


# ─────────────────────────────── page ranges ───────────────────────────────
def parse_ranges(text, count):
    """'1-3, 5, 8-' -> [0, 1, 2, 4, 7, ...] (0-based, within 1..count). Raises ValueError on nonsense."""
    out = []
    for part in re.split(r"[,;]\s*", (text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"\s*(\d*)\s*[-–]\s*(\d*)\s*|\s*(\d+)\s*", part)
        if not m:
            raise ValueError(part)
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else count
        if a < 1 or b < a or a > count:
            raise ValueError(part)
        out.extend(range(a - 1, min(b, count)))
    if not out:
        raise ValueError(text)
    seen = set()
    return [p for p in out if not (p in seen or seen.add(p))]


# ─────────────────────────────── Windows: Print dialog + GDI ───────────────────────────────
def to_dib(rgb, w, h):
    """Top-down RGB pixels -> 24-bit DIB rows: BGR order, each row padded to a multiple of 4 bytes."""
    bgr = bytearray(rgb)
    bgr[0::3], bgr[2::3] = rgb[2::3], rgb[0::3]
    row, stride = w * 3, (w * 3 + 3) & ~3
    if row == stride:
        return bgr
    out = bytearray(stride * h)
    for y in range(h):
        out[y * stride:y * stride + row] = bgr[y * row:(y + 1) * row]
    return out


def _win_print_dialog(owner_hwnd, count, current, selected):
    """Show the Windows Print dialog. Returns (hdc, pages, copies_done_by_driver) or None when cancelled."""
    import ctypes
    from ctypes import wintypes

    class PRINTDLGW(ctypes.Structure):
        if ctypes.sizeof(ctypes.c_void_p) == 4:
            _pack_ = 1
        _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND),
                    ("hDevMode", wintypes.HGLOBAL), ("hDevNames", wintypes.HGLOBAL), ("hDC", wintypes.HDC),
                    ("Flags", wintypes.DWORD), ("nFromPage", wintypes.WORD), ("nToPage", wintypes.WORD),
                    ("nMinPage", wintypes.WORD), ("nMaxPage", wintypes.WORD), ("nCopies", wintypes.WORD),
                    ("hInstance", wintypes.HINSTANCE), ("lCustData", wintypes.LPARAM),
                    ("lpfnPrintHook", ctypes.c_void_p), ("lpfnSetupHook", ctypes.c_void_p),
                    ("lpPrintTemplateName", wintypes.LPCWSTR), ("lpSetupTemplateName", wintypes.LPCWSTR),
                    ("hPrintTemplate", wintypes.HGLOBAL), ("hSetupTemplate", wintypes.HGLOBAL)]

    PD_SELECTION, PD_PAGENUMS, PD_NOSELECTION = 0x1, 0x2, 0x4
    PD_RETURNDC, PD_USEDEVMODECOPIESANDCOLLATE = 0x100, 0x40000
    comdlg = ctypes.windll.comdlg32
    comdlg.PrintDlgW.argtypes = [ctypes.POINTER(PRINTDLGW)]
    pd = PRINTDLGW()
    pd.lStructSize = ctypes.sizeof(PRINTDLGW)
    pd.hwndOwner = owner_hwnd
    pd.Flags = PD_RETURNDC | PD_USEDEVMODECOPIESANDCOLLATE | (0 if len(selected) > 1 else PD_NOSELECTION)
    pd.nMinPage, pd.nMaxPage = 1, max(1, min(count, 0xFFFF))
    pd.nFromPage = pd.nToPage = current + 1
    pd.nCopies = 1
    if not comdlg.PrintDlgW(ctypes.byref(pd)):
        return None
    kernel = ctypes.windll.kernel32
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    for handle in (pd.hDevMode, pd.hDevNames):
        if handle:
            kernel.GlobalFree(handle)
    if pd.Flags & PD_PAGENUMS:
        pages = list(range(pd.nFromPage - 1, min(pd.nToPage, count)))
    elif pd.Flags & PD_SELECTION:
        pages = sorted(selected)
    else:
        pages = list(range(count))
    return pd.hDC, pages


def _win_print(hdc, doc, pages, title, progress=None):
    """Render *pages* of *doc* to the printer DC (runs in a worker thread)."""
    import ctypes
    from ctypes import wintypes
    fitz = _fitz()
    gdi = ctypes.windll.gdi32

    class DOCINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR), ("lpszOutput", wintypes.LPCWSTR),
                    ("lpszDatatype", wintypes.LPCWSTR), ("fwType", wintypes.DWORD)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    for name in ("StartDocW", "StartPage", "EndPage", "EndDoc", "AbortDoc", "DeleteDC", "GetDeviceCaps",
                 "SetStretchBltMode", "StretchDIBits", "SetBrushOrgEx"):
        getattr(gdi, name).restype = ctypes.c_int
    gdi.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
    gdi.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi.StretchDIBits.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_void_p, wintypes.UINT, wintypes.DWORD]
    for name in ("StartPage", "EndPage", "EndDoc", "AbortDoc", "DeleteDC"):
        getattr(gdi, name).argtypes = [wintypes.HDC]
    gdi.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]

    HORZRES, VERTRES, LOGPIXELSX, LOGPIXELSY = 8, 10, 88, 90
    info = DOCINFOW(ctypes.sizeof(DOCINFOW), title, None, None, 0)
    if gdi.StartDocW(hdc, ctypes.byref(info)) <= 0:
        gdi.DeleteDC(hdc)
        raise OSError(T("The printer did not accept the document."))
    ok = False
    try:
        area_w, area_h = gdi.GetDeviceCaps(hdc, HORZRES), gdi.GetDeviceCaps(hdc, VERTRES)
        dpi = min(gdi.GetDeviceCaps(hdc, LOGPIXELSX), gdi.GetDeviceCaps(hdc, LOGPIXELSY)) or 300
        for n, k in enumerate(pages):
            if progress:
                progress(n, len(pages))
            page = doc[k]
            rotate = (page.rect.width > page.rect.height) != (area_w > area_h) and \
                abs(page.rect.width - page.rect.height) > 1
            pw, ph = (page.rect.height, page.rect.width) if rotate else (page.rect.width, page.rect.height)
            scale = min(area_w / (pw / 72 * dpi), area_h / (ph / 72 * dpi), 1.0)       # shrink, never enlarge
            dw, dh = int(pw / 72 * dpi * scale), int(ph / 72 * dpi * scale)
            render_dpi = min(dpi * scale, MAX_DPI)
            mat = fitz.Matrix(render_dpi / 72, render_dpi / 72).prerotate(90 if rotate else 0)
            pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
            w, h = pix.width, pix.height
            buf = to_dib(pix.samples, w, h)
            bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 24, 0, 0, 0, 0, 0, 0)
            if gdi.StartPage(hdc) <= 0:
                raise OSError(T("The printer stopped."))
            gdi.SetStretchBltMode(hdc, 4)           # HALFTONE
            gdi.SetBrushOrgEx(hdc, 0, 0, None)
            x, y = (area_w - dw) // 2, (area_h - dh) // 2
            data = (ctypes.c_char * len(buf)).from_buffer(buf)
            gdi.StretchDIBits(hdc, x, y, dw, dh, 0, 0, w, h, data, ctypes.byref(bmi), 0, 0x00CC0020)
            if gdi.EndPage(hdc) <= 0:
                raise OSError(T("The printer stopped."))
        ok = True
    finally:
        if ok:
            gdi.EndDoc(hdc)
        else:
            gdi.AbortDoc(hdc)
        gdi.DeleteDC(hdc)
    return len(pages)


# ─────────────────────────────── macOS / Linux: CUPS ───────────────────────────────
def cups_printers():
    """([names], default) from lpstat; ([], None) when CUPS is not available."""
    lpstat = shutil.which("lpstat")
    if not lpstat:
        return [], None
    names, default = [], None
    try:
        out = subprocess.run([lpstat, "-a"], capture_output=True, text=True, timeout=8).stdout  # nosec B603
        names = [line.split()[0] for line in out.splitlines() if line.strip()]
        out = subprocess.run([lpstat, "-d"], capture_output=True, text=True, timeout=8).stdout  # nosec B603
        m = re.search(r":\s*(\S+)\s*$", out.strip())
        default = m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        pass
    return names, default if default in names else (names[0] if names else None)


def cups_print(pdf_bytes, title, printer, copies=1, pages=None, sides=None):
    lp = shutil.which("lp")
    if not lp:
        raise OSError(T("Printing needs CUPS (the 'lp' command), which was not found."))
    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="monkeyviewer-print-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)
        cmd = [lp, "-t", title[:120], "-n", str(max(1, int(copies)))]
        if printer:
            cmd += ["-d", printer]
        if pages:
            cmd += ["-P", pages]
        if sides:
            cmd += ["-o", f"sides={sides}"]
        cmd.append(path)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)  # nosec B603
        if res.returncode != 0:
            raise OSError(res.stderr.strip() or res.stdout.strip() or "lp failed")
        return res.stdout.strip()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


class CupsDialog(theme.Dialog):
    def __init__(self, parent, title, count, current, selected, printers, default):
        super().__init__(parent, T("Print"), min_width=440)
        self.count, self.current, self.selected = count, current, selected
        b = self.body
        tk.Label(b, text=title, font=FONTS["h3"], bg=C["panel"], fg=C["fg_bright"], anchor="w").pack(fill="x")
        tk.Label(b, text=T("{0} pages", count) if count != 1 else T("1 page"), font=FONTS["small"],
                 bg=C["panel"], fg=C["fg_muted"], anchor="w").pack(fill="x", pady=(0, px(12)))
        grid = tk.Frame(b, bg=C["panel"])
        grid.pack(fill="x")

        def label(r, text):
            tk.Label(grid, text=text, font=FONTS["ui"], bg=C["panel"], fg=C["fg_dim"], anchor="w").grid(
                row=r, column=0, sticky="nw", padx=(0, px(16)), pady=px(5))

        label(0, T("Printer"))
        self.printer = tk.StringVar(value=default or "")
        theme.ToolButton(grid, default or T("Default printer"), None, menu=self._printer_menu(printers),
                         bg=C["input"], hover=C["hover_strong"], pad=(10, 4)).grid(row=0, column=1, sticky="w")
        label(1, T("Pages"))
        pages = tk.Frame(grid, bg=C["panel"])
        pages.grid(row=1, column=1, sticky="w")
        self.which = tk.StringVar(value="all")
        options = [("all", T("All")), ("current", T("Current page ({0})", current + 1))]
        if len(selected) > 1:
            options.append(("selected", T("Selected pages ({0})", len(selected))))
        options.append(("range", T("Pages:")))
        for value, text in options:
            row = tk.Frame(pages, bg=C["panel"])
            row.pack(fill="x", anchor="w")
            tk.Radiobutton(row, text=text, value=value, variable=self.which, bg=C["panel"], fg=C["fg"],
                           selectcolor=C["input"], activebackground=C["panel"], activeforeground=C["fg"],
                           highlightthickness=0, font=FONTS["ui"]).pack(side="left")
            if value == "range":
                self.range_var = tk.StringVar(value=f"1-{count}")
                box, entry = theme.styled_entry(row, self.range_var, width=14)
                box.pack(side="left", padx=(px(6), 0))
                entry.bind("<FocusIn>", lambda e: self.which.set("range"))
        label(2, T("Copies"))
        self.copies = tk.Spinbox(grid, from_=1, to=999, width=5, font=FONTS["ui"], bg=C["input"], fg=C["fg"],
                                 buttonbackground=C["panel"], relief="flat", highlightthickness=1,
                                 highlightbackground=C["border"], insertbackground=C["fg"])
        self.copies.grid(row=2, column=1, sticky="w", pady=px(5))
        self.duplex = tk.BooleanVar(value=False)
        tk.Checkbutton(grid, text=T("Print on both sides"), variable=self.duplex, bg=C["panel"], fg=C["fg"],
                       selectcolor=C["input"], activebackground=C["panel"], activeforeground=C["fg"],
                       highlightthickness=0, font=FONTS["ui"]).grid(row=3, column=1, sticky="w")
        self.error = tk.Label(b, text="", font=FONTS["small"], bg=C["panel"], fg=C["danger"], anchor="w")
        self.error.pack(fill="x", pady=(px(8), 0))
        self.add_buttons(T("Print"))

    def _printer_menu(self, printers):
        def fill(m):
            for name in printers or []:
                m.add_radiobutton(label=name, value=name, variable=self.printer)
            if not printers:
                m.add_command(label=T("No printers found"), state="disabled")
        return fill

    def ok(self):
        try:
            which = self.which.get()
            if which == "current":
                pages = [self.current]
            elif which == "selected":
                pages = sorted(self.selected)
            elif which == "range":
                pages = parse_ranges(self.range_var.get(), self.count)
            else:
                pages = list(range(self.count))
            copies = max(1, min(999, int(self.copies.get())))
        except ValueError:
            self.error.configure(text=T("Check the page range, e.g. 1-3, 5"))
            return
        self.result = {"printer": self.printer.get() or None, "pages": pages, "copies": copies,
                       "sides": "two-sided-long-edge" if self.duplex.get() else None}
        self.destroy()


def _lp_ranges(pages):
    out, start, prev = [], None, None
    for k in pages + [None]:
        if k is not None and prev is not None and k == prev + 1:
            prev = k
            continue
        if start is not None:
            out.append(str(start + 1) if start == prev else f"{start + 1}-{prev + 1}")
        start = prev = k
    return ",".join(out)


# ─────────────────────────────── entry point ───────────────────────────────
def print_tab(app, tab):
    """Print the active document (File -> Print, Ctrl+P)."""
    from . import audit, policy
    if policy.get_bool("DisablePrinting"):
        app.toast.show(T("Printing is turned off by your administrator."), "warning", 3500)
        return
    try:
        doc = tab.print_document()
    except Exception as exc:  # noqa: BLE001
        app.toast.show(T("This document cannot be printed: {0}", exc), "error", 4500)
        return
    if doc is None or len(doc) == 0:
        app.toast.show(T("This view has nothing to print."), "info", 2500)
        return
    if doc is getattr(tab, "doc", None):     # the tab keeps drawing its own copy; PyMuPDF is not thread-safe
        doc = _fitz().open("pdf", as_pdf_bytes(doc))
    title = tab.title
    count = len(doc)
    current = min(max(0, getattr(tab, "cur", 0)), count - 1)
    selected = {k for k in getattr(tab, "selected", set()) if 0 <= k < count} if tab.kind == "pdf" else set()

    def finish(ok, value):
        if ok:
            app.toast.show(T("Sent {0} page(s) to the printer.", value), "success", 3000)
            audit.event("print", path=tab.path or title, pages=value)
        else:
            app.toast.show(T("Printing failed: {0}", value), "error", 6000)

    if sys.platform == "win32":
        from . import watchdog
        hwnd = _owner_hwnd(app.root)
        chosen = watchdog.native_dialog("print", _win_print_dialog)(hwnd, count, current, selected)
        if not chosen:
            return
        hdc, pages = chosen
        app.toast.show(T("Printing {0}…", title), "info", 2000)
        app.run_in_thread(lambda: _win_print(hdc, doc, pages, title), finish)
        return
    printers, default = cups_printers()
    if not printers and not shutil.which("lp"):
        app.toast.show(T("Printing needs CUPS (the 'lp' command), which was not found."), "error", 5000)
        return
    dlg = CupsDialog(app.root, title, count, current, selected, printers, default)
    opts = dlg.run()
    if not opts:
        return
    data = as_pdf_bytes(doc)
    rng = None if opts["pages"] == list(range(count)) else _lp_ranges(opts["pages"])

    def work():
        cups_print(data, title, opts["printer"], opts["copies"], rng, opts["sides"])
        return len(opts["pages"])
    app.run_in_thread(work, finish)


def _owner_hwnd(root):
    try:
        import ctypes
        return ctypes.windll.user32.GetParent(root.winfo_id())
    except Exception:  # noqa: BLE001
        return None
