"""Components, helper programs, policies (More -> Components & diagnostics)."""

import importlib
import sys
import tkinter as tk

from . import app_info, policy, winutil


def _module(name, attr="__version__"):
    try:
        mod = importlib.import_module(name)
        return True, str(getattr(mod, attr, "") or "installed")
    except Exception as exc:  # noqa: BLE001
        return False, f"not available ({exc.__class__.__name__}: {exc})"


def _pdf_engine():
    try:
        from .pdf_view import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "test")
        pix = page.get_pixmap()
        return True, f"PyMuPDF {getattr(fitz, 'VersionBind', '?')} — render test OK ({pix.width}×{pix.height})"
    except Exception as exc:  # noqa: BLE001
        return False, f"FAILED: {exc.__class__.__name__}: {exc}"


def collect():
    rows = [(app_info.NAME, True, f"{app_info.VERSION} ({app_info.BUILD_COMMIT} {app_info.BUILD_DATE}) · "
                                  f"Python {sys.version.split()[0]}, Tk {tk.TkVersion}, "
                                  f"{'installed build' if winutil.FROZEN else 'running from source'}")]
    ok, detail = _pdf_engine()
    rows.append(("PDF engine", ok, detail))
    for label, name, attr in (("Images (Pillow)", "PIL", "__version__"), ("NumPy", "numpy", "__version__"),
                              ("CAD (ezdxf)", "ezdxf", "__version__"), ("Shapefile (pyshp)", "shapefile", "__version__"),
                              ("Certificates (cryptography)", "cryptography", "__version__"),
                              ("Signed files (asn1crypto)", "asn1crypto", "__version__"),
                              ("Safe XML (defusedxml)", "defusedxml", "__version__"),
                              ("HEIC photos (pi-heif)", "pi_heif", "__version__"),
                              ("SVG (resvg)", "resvg_py", "__name__"),
                              ("Drag & drop (tkinterdnd2)", "tkinterdnd2", "__name__")):
        ok, detail = _module(name, attr)
        rows.append((label, ok, detail))
    for label, finder in (("LibreDWG (DWG)", winutil.find_dwg2dxf),
                          ("ODA File Converter (DWG, optional)", winutil.find_oda_converter),
                          ("GnuPG", winutil.find_gpg), ("DjVuLibre", winutil.find_ddjvu)):
        path = finder()
        rows.append((f"Helper: {label}", bool(path), path or "not found (optional)"))
    active = policy.active()
    rows.append(("Policies", True, ", ".join(f"{k}={v}" for k, v in active.items()) or "none set"))
    rows.append(("Weather (api.met.no)", not policy.get_bool("DisableWeather"),
                 "turned off by policy - no internet connection" if policy.get_bool("DisableWeather")
                 else "on - the only internet connection"))
    rows.append(("Settings", True, winutil.config_dir()))
    return rows


def report(rows):
    return "\n".join(f"{'OK  ' if ok else '--  '}{name}: {detail}" for name, ok, detail in rows)


def show(app):
    """Components & diagnostics: what is installed and working, grouped, with Copy report and a self-test."""
    from . import theme
    from .i18n import T
    from .theme import C, FONTS, ToolButton, px
    rows = collect()
    dlg = theme.Dialog(app.root, T("Components & diagnostics"), min_width=640)
    b = dlg.body
    head = tk.Frame(b, bg=C["panel"])
    head.pack(fill="x")
    tk.Label(head, image=theme.logo_image(px(40), plate=True), bg=C["panel"]).pack(side="left", padx=(0, px(12)))
    col = tk.Frame(head, bg=C["panel"])
    col.pack(side="left", fill="x", expand=True)
    tk.Label(col, text=T("Components & diagnostics"), font=FONTS["h2"], bg=C["panel"], fg=C["fg_bright"],
             anchor="w").pack(fill="x")
    missing = [r for r in rows[1:] if not r[1] and "optional" not in r[2] and not r[0].startswith("Weather")]
    status = T("Everything needed is in place.") if not missing else T("{0} component(s) need attention.",
                                                                          len(missing))
    tk.Label(col, text=status, font=FONTS["ui_bold"], bg=C["panel"], fg=C["success"] if not missing else C["warning"],
             anchor="w").pack(fill="x")
    tk.Label(col, text=rows[0][2], font=FONTS["small"], bg=C["panel"], fg=C["fg_muted"], anchor="w",
             justify="left", wraplength=px(520)).pack(fill="x")
    groups = [(T("Components"), [r for r in rows[1:] if not r[0].startswith("Helper:") and
                                 r[0] not in ("Policies", "Settings") and not r[0].startswith("Weather")]),
              (T("Helper programs"), [(r[0][len("Helper: "):], r[1], r[2]) for r in rows if r[0].startswith("Helper:")]),
              (T("Administration"), [r for r in rows if r[0] in ("Policies", "Settings") or r[0].startswith("Weather")])]
    for title, items in groups:
        tk.Label(b, text=title.upper(), font=FONTS["caption"], bg=C["panel"], fg=C["fg_muted"], anchor="w").pack(
            fill="x", pady=(px(10), px(3)))
        box = tk.Frame(b, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="x")
        for r, (name, ok, detail) in enumerate(items):
            optional = not ok and "optional" in detail
            mark, color = ("\u2713", C["success"]) if ok else (("\u2013", C["fg_muted"]) if optional
                                                                 else ("!", C["warning"]))
            tk.Label(box, text=mark, font=FONTS["small_bold"], bg=C["bg"], fg=color, width=2).grid(
                row=r, column=0, sticky="nw", padx=(px(8), 0), pady=px(2))
            tk.Label(box, text=T(name), font=FONTS["small"], bg=C["bg"], fg=C["fg"], anchor="w").grid(
                row=r, column=1, sticky="nw", padx=(px(4), px(12)), pady=px(2))
            tk.Label(box, text=T(detail), font=FONTS["small"], bg=C["bg"], fg=C["fg_dim"], anchor="w",
                     justify="left", wraplength=px(380)).grid(row=r, column=2, sticky="nw", padx=(0, px(10)),
                                                              pady=px(2))
        box.grid_columnconfigure(1, minsize=px(230))
        box.grid_columnconfigure(2, weight=1)

    def copy():
        app.set_clipboard(report(rows))
        app.toast.show(T("The report was copied."), "info", 1800)

    def run_selftest():
        """The self-test in a separate process (it starts its own Tk and switches languages)."""
        import json
        import os
        import subprocess  # nosec B404 - runs this program itself
        import tempfile
        fd, out = tempfile.mkstemp(suffix=".json", prefix="monkeyviewer-selftest-")
        os.close(fd)
        try:
            if winutil.FROZEN:
                cmd = [sys.executable, f"--self-test={out}"]
            else:
                main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "monkey_viewer.py")
                cmd = [sys.executable, main, f"--self-test={out}"]
            flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
            subprocess.run(cmd, timeout=180, capture_output=True, creationflags=flags)  # nosec B603
            with open(out, encoding="utf-8") as fh:
                return json.load(fh)
        finally:
            try:
                os.remove(out)
            except OSError:
                pass

    def self_test():
        test_btn.set_enabled(False)

        def done(ok, result):
            if not dlg.winfo_exists():
                return
            test_btn.set_enabled(True)
            if ok and result.get("ok"):
                app.toast.show(T("Self-test passed: {0} checks.", len(result["checks"])), "success", 3500)
            else:
                failed = [c["name"] for c in result["checks"] if not c["ok"]] if ok else [str(result)]
                app.toast.show(T("Self-test failed: {0}", ", ".join(failed)), "error", 6000)
        app.run_in_thread(run_selftest, done)
    ToolButton(dlg.footer, T("Copy report"), "copy", copy, bg=C["chrome"], pad=(12, 5)).pack(side="left")
    test_btn = ToolButton(dlg.footer, T("Run self-test"), "check", self_test, bg=C["chrome"], pad=(12, 5))
    test_btn.pack(side="left", padx=(px(6), 0))
    dlg.add_buttons(T("Close"), None)
    dlg.run()
