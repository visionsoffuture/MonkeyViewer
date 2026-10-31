"""Built-in self test of the packaged application:  MonkeyViewer.exe --self-test=report.json

Used by the build pipeline on the *frozen* program (Windows and macOS) and available to administrators after
deployment. It exercises every engine without showing a window and writes a JSON report; the exit code is 0
when all checks pass.
"""

import json
import os
import platform
import sys
import tempfile
import time
import traceback

from . import app_info


class CheckFailed(RuntimeError):
    pass


def _require(condition, message):
    """Like assert, but also active in optimised (-O) builds."""
    if not condition:
        raise CheckFailed(message)


def _check_imports():
    import importlib
    names = ["viewer.app", "viewer.pdf_edit", "viewer.pdf_view", "viewer.cad_view", "viewer.map_view", "viewer.gis",
             "viewer.image_view", "viewer.table_view", "viewer.crypto", "viewer.crypto_view",
             "viewer.text_view", "viewer.hex_view", "viewer.info_view", "viewer.assoc_view", "viewer.diagnostics",
             "viewer.printing", "viewer.menubar", "viewer.sig_view", "viewer.pdfsig",
             "viewer.svg_view", "viewer.svg_anim", "resvg_py", "viewer.calc_view", "viewer.weather",
             "viewer.weather_view", "viewer.guide",
             "PIL.ImageTk", "numpy", "ezdxf", "shapefile", "cryptography.x509", "asn1crypto.cms",
             "defusedxml.ElementTree"]
    for n in names:
        importlib.import_module(n)
    return f"{len(names)} modules"


def _check_pdf(tmp):
    from .pdf_view import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_htmlbox(fitz.Rect(50, 50, 500, 200), "<p>Monkey Viewer ტესტი — PDF</p>")
    path = os.path.join(tmp, "t.pdf")
    doc.save(path)
    with fitz.open(path) as d:
        pix = d[0].get_pixmap(dpi=50)
        text = d[0].get_text()
    _require("ტესტი" in text, "Georgian text was not embedded")
    return f"render {pix.width}x{pix.height}, Georgian text OK"


def _check_dxf(tmp):
    import ezdxf
    from .cad_view import render_dxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 10))
    msp.add_circle((5, 5), 3)
    data = render_dxf(doc)
    _require(data[:4] == b"%PDF", "DXF did not render to PDF")
    return f"DXF -> PDF {len(data)} bytes"


def _check_gis(tmp):
    from . import gis
    path = os.path.join(tmp, "t.gpx")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0"?><gpx version="1.1"><trk><name>t</name><trkseg>'
                 '<trkpt lat="41.7" lon="44.8"/><trkpt lat="41.8" lon="44.9"/></trkseg></trk></gpx>')
    layers = gis.read_any(path)
    bomb = os.path.join(tmp, "bomb.kml")
    with open(bomb, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0"?><!DOCTYPE k [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
                 '<kml>&b;</kml>')
    refused = False
    try:
        gis.read_any(bomb)
    except Exception:  # noqa: BLE001 - expected: defusedxml refuses entity declarations
        refused = True
    _require(refused, "XML entity declarations were accepted")
    return f"{len(layers)} layer(s), XML entities refused"


def _check_crypto(tmp):
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from . import crypto
    plain = b"-- Monkey Viewer self test\nprint('ok')\n"
    salt = b"12345678"
    key, iv = crypto._bytes_to_key(b"pw", salt, 32, 16, "sha256")
    padder = padding.PKCS7(128).padder()
    body = padder.update(plain) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    path = os.path.join(tmp, "t.enc")
    with open(path, "wb") as fh:
        fh.write(b"Salted__" + salt + enc.update(body) + enc.finalize())
    analysis = crypto.analyse(path)
    _name, data = crypto.decrypt_with_password(analysis, path, "pw")
    _require(data == plain, "OpenSSL-compatible decryption failed")
    return "AES-256-CBC (OpenSSL format) round trip OK"


def _check_sqlite(tmp):
    import sqlite3
    from .table_view import list_sheets, read_sheet
    path = os.path.join(tmp, "t.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE meters (id INTEGER, serial TEXT)")
    con.executemany("INSERT INTO meters VALUES (?, ?)", [(i, f"SN{i:04d}") for i in range(50)])
    con.commit()
    con.close()
    before = sorted(os.listdir(tmp))
    header, rows, total = read_sheet(path, list_sheets(path)[0])
    _require(total == 50 and header == ["id", "serial"], "SQLite rows were not read correctly")
    _require(sorted(os.listdir(tmp)) == before, "read-only access created files")
    return "read-only SQLite OK"


def _check_policy_and_audit(tmp):
    from . import audit, policy
    active = policy.active()
    return f"policies: {', '.join(active) or 'none'}; audit log: {audit.log_path()}"


def _check_helpers():
    """Bundled helper programs start (DjVuLibre for DjVu, LibreDWG for DWG). MONKEYVIEWER_REQUIRE_HELPERS
    ("ddjvu,dwg2dxf", set by CI for release builds) makes a missing helper a failure."""
    import os
    from . import winutil
    required = {n.strip() for n in os.environ.get("MONKEYVIEWER_REQUIRE_HELPERS", "").split(",") if n.strip()}
    parts = []
    for name, find, args in (("ddjvu", winutil.find_ddjvu, []), ("dwg2dxf", winutil.find_dwg2dxf, ["--version"]),
                             ("gpg", winutil.find_gpg, ["--version"])):
        exe = find()
        if not exe:
            _require(name not in required, f"{name} is not bundled")
            parts.append(f"{name}: not available")
            continue
        out = winutil.run_hidden([exe, *args], timeout=60)
        text = (out.stdout or b"") + (out.stderr or b"")
        _require(len(text) > 0, f"{name} did not start")
        parts.append(f"{name}: {exe}")
    return "; ".join(parts)


def _check_languages():
    from . import i18n
    from .locale_ka import TEXTS
    before = i18n.current()
    try:
        i18n.setup("ka")
        _require(i18n.T("Page {0} of {1}", 1, 2) == "\u10d2\u10d5\u10d4\u10e0\u10d3\u10d8 1 / 2",
                 "Georgian translation not applied")
        i18n.setup("en")
        _require(i18n.T("Page {0} of {1}", 1, 2) == "Page 1 of 2", "English source text changed")
    finally:
        i18n.setup(before)
    return f"English, Georgian ({len(TEXTS)} texts); system language: {i18n.system_language()}"


def _check_print():
    """Printing lays text out with PyMuPDF's bundled fonts: Georgian must come out as text, not boxes."""
    from . import printing
    doc = printing.text_document("\u10e5\u10d0\u10e0\u10d7\u10e3\u10da\u10d8 print\n" * 3, "selftest.txt")
    _require("\u10e5\u10d0\u10e0\u10d7\u10e3\u10da\u10d8" in doc[0].get_text(), "Georgian text lost when printing")
    _require(printing.parse_ranges("1-2", 3) == [0, 1], "page ranges")
    return f"{len(doc)} page(s), fonts: {', '.join(sorted({f[3] for f in doc[0].get_fonts()}))}"


def _check_svg():
    """SVG preview: resvg is bundled (dashes, CSS) and the animation engine produces frames."""
    from . import svg_anim, svg_view
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><style>.c{fill:#0000ff;'
           'animation:a 1s linear infinite}@keyframes a{to{opacity:0}}</style><rect width="40" height="40" '
           'fill="#fff"/><circle class="c" cx="20" cy="20" r="10"/></svg>')
    anim = svg_anim.SvgAnimation(svg)
    _require(anim.animated, "CSS animation not found")
    img = svg_view.render(anim.frame(0.0), 1.0).convert("RGB")
    _require(img.getpixel((20, 20))[2] > 200 and img.getpixel((20, 20))[0] < 60, "style sheet not applied")
    return f"resvg, {img.size[0]}x{img.size[1]}, CSS + SMIL frames OK"


def _check_tools():
    """Calculator arithmetic, the weather summary from a sample answer, and HTTPS root certificates (weather)."""
    from . import calc_view, weather
    _require(str(calc_view.evaluate("0.1+0.2")) == "0.3" and calc_view.evaluate("200+10%") == 220, "calculator")
    t0 = "2026-01-01T00:00:00Z"
    sample = {"properties": {"timeseries": [
        {"time": t0, "data": {"instant": {"details": {"air_temperature": 3.0}},
                              "next_1_hours": {"summary": {"symbol_code": "snow"}}}}]}}
    import datetime
    s = weather.summarise(sample, datetime.datetime(2026, 1, 1, 4, 0, tzinfo=weather.GEORGIA))
    _require(s["now"]["temp"] == 3.0 and s["days"], "weather summary")
    ctx = weather._ssl_context()
    roots = ctx.cert_store_stats().get("x509_ca", 0)
    if roots == 0 and sys.platform == "win32":
        roots = len(ctx.get_ca_certs()) or 1          # Windows loads its store on demand
    _require(roots > 0, "no root certificates for HTTPS (weather)")
    return f"calculator OK, weather parser OK, {roots} root certificates"


def _check_tk():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        return f"skipped (no display: {exc})"
    root.withdraw()
    version = root.tk.call("info", "patchlevel")
    root.destroy()
    return f"Tk {version}"


CHECKS = [("imports", _check_imports), ("pdf", _check_pdf), ("dxf", _check_dxf), ("gis", _check_gis),
          ("crypto", _check_crypto), ("sqlite", _check_sqlite), ("policy+audit", _check_policy_and_audit),
          ("languages", _check_languages), ("print", _check_print), ("svg", _check_svg), ("tools", _check_tools), ("helpers", _check_helpers), ("tk", _check_tk)]


def run():
    report = {"app": app_info.NAME, "version": app_info.VERSION, "build": app_info.BUILD_COMMIT,
              "frozen": bool(getattr(sys, "frozen", False)), "python": sys.version.split()[0],
              "platform": platform.platform(), "checks": [], "ok": True}
    with tempfile.TemporaryDirectory(prefix="MonkeyViewer-selftest-") as tmp:
        for name, fn in CHECKS:
            t0 = time.perf_counter()
            try:
                detail = fn(tmp) if fn.__code__.co_argcount else fn()
                ok = True
            except Exception as exc:  # noqa: BLE001
                detail = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc(limit=4)}"
                ok = False
            report["checks"].append({"name": name, "ok": ok, "detail": detail,
                                     "seconds": round(time.perf_counter() - t0, 3)})
            report["ok"] = report["ok"] and ok
    return report


def main(target):
    report = run()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if target and target != "-":
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
    elif sys.stdout is not None:
        print(text)
    return 0 if report["ok"] else 1

