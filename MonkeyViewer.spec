# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for Monkey Viewer (Windows and macOS).

    pyinstaller MonkeyViewer.spec --noconfirm --clean

Produces dist/MonkeyViewer/ (Windows, everything needed to run — no Python required) or
dist/Monkey Viewer.app (macOS). Product name, version and publisher come from viewer/app_info.py.
"""

import glob
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = os.path.abspath(SPECPATH)  # noqa: F821 - provided by PyInstaller
sys.path.insert(0, ROOT)

from viewer import app_info, formats  # noqa: E402

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

datas = [(os.path.join(ROOT, name), ".") for name in
         ("monkeyviewer.ico", "LICENSE.txt", "THIRD_PARTY_NOTICES.txt", "SECURITY.md", "PRIVACY.md")
         if os.path.exists(os.path.join(ROOT, name))]
datas.append((os.path.join(ROOT, "docs", "USER_GUIDE.md"), "."))          # More > User guide
# helper programs fetched (checksum-verified) by CI into build/vendor: DjVuLibre (ddjvu) and LibreDWG (dwg2dxf)
VENDOR = os.path.join(ROOT, "build", "vendor")
for tool in ("djvulibre", "libredwg", "gnupg"):
    base = os.path.join(VENDOR, tool)
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            datas.append((os.path.join(dirpath, name),
                          os.path.join("tools", tool, os.path.relpath(dirpath, base)).rstrip("." + os.sep)))
ICONS = os.path.join(ROOT, "packaging", "icons")                         # per-file-type icons (tools/make_icons.py)
if sys.platform == "darwin":
    datas += [(f, ".") for f in sorted(glob.glob(os.path.join(ICONS, "doc-*.icns")))]   # -> Contents/Resources
else:
    datas += [(f, "icons") for f in sorted(glob.glob(os.path.join(ICONS, "*.ico")))]
binaries = []
hiddenimports = ["PIL._tkinter_finder", "PIL.ImageTk", "ezdxf.addons.drawing.pymupdf", "pymupdf.mupdf",
                 "pymupdf.extra", "fitz", "defusedxml.ElementTree", "asn1crypto.cms", "resvg_py"]
hiddenimports += collect_submodules("viewer")
for package in ("pymupdf", "tkinterdnd2", "pi_heif"):
    try:
        d, b, h = collect_all(package)
    except Exception:  # optional package not installed
        continue
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("ezdxf")
datas = [d for d in datas if "mupdf-devel" not in d[0].replace("\\", "/")]   # C headers / link libraries
binaries = [b for b in binaries if "mupdf-devel" not in b[0].replace("\\", "/")]

# License texts of every bundled component -> licenses/<name>-<version>/ (required by their licenses)
import re  # noqa: E402
import sysconfig  # noqa: E402
from importlib import metadata  # noqa: E402

BUNDLED = ["pymupdf", "pillow", "numpy", "ezdxf", "pyshp", "cryptography", "asn1crypto", "defusedxml", "tkinterdnd2",
           "pi-heif", "resvg-py", "cffi", "pycparser", "fonttools", "pyparsing", "typing-extensions", "pyinstaller"]
for name in BUNDLED:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        continue
    target = f"licenses/{dist.metadata['Name']}-{dist.version}"
    for f in dist.files or []:
        rel = str(f).replace("\\", "/")
        if not re.search(r"(LICEN[CS]E|COPYING|NOTICE)", os.path.basename(rel), re.I) and "/licenses/" not in rel:
            continue
        src = str(dist.locate_file(f))
        if os.path.isfile(src):
            sub = rel.split("/licenses/", 1)[1] if "/licenses/" in rel else os.path.basename(rel)
            datas.append((src, os.path.dirname(f"{target}/{sub}")))
for cand in (os.path.join(sys.base_prefix, "LICENSE.txt"), os.path.join(sysconfig.get_paths()["stdlib"], "LICENSE.txt")):
    if os.path.isfile(cand):
        datas.append((cand, "licenses/Python"))
        break

excludes = ["matplotlib", "PySide6", "PyQt5", "PyQt6", "pandas", "scipy", "IPython", "pytest", "bandit",
            "pip_audit", "openpyxl", "xlrd", "msoffcrypto", "mutagen", "olefile", "pyodbc", "Evtx", "lxml",
            "defusedxml.lxml", "cyclonedx", "jsonschema", "requests", "rich", "pygments", "_pytest", "pluggy"]

# Windows file properties (Explorer > Properties > Details)
version_file = None
if IS_WIN:
    major, minor, patch, build = app_info.version_tuple()
    version_file = os.path.join(ROOT, "build", "version_info.txt")
    os.makedirs(os.path.dirname(version_file), exist_ok=True)
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, {build}), prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', {app_info.PUBLISHER!r}),
      StringStruct('FileDescription', {app_info.NAME!r}),
      StringStruct('FileVersion', {app_info.VERSION!r}),
      StringStruct('InternalName', {app_info.APP_ID!r}),
      StringStruct('LegalCopyright', {app_info.COPYRIGHT!r}),
      StringStruct('OriginalFilename', 'MonkeyViewer.exe'),
      StringStruct('ProductName', {app_info.NAME!r}),
      StringStruct('ProductVersion', {app_info.VERSION!r}),
      StringStruct('Comments', {app_info.DESCRIPTION!r})])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "monkey_viewer.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MonkeyViewer",
    console=False,
    icon=os.path.join(ROOT, "monkeyviewer.icns" if IS_MAC else "monkeyviewer.ico"),
    version=version_file,
    upx=False,                       # compressed executables trigger antivirus false positives
    codesign_identity=os.environ.get("MAC_SIGN_IDENTITY") or None,
    entitlements_file=os.path.join(ROOT, "packaging", "macos", "entitlements.plist") if IS_MAC else None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MonkeyViewer")  # noqa: F821

if IS_MAC:
    from viewer.winutil import PROGIDS, _progid_for
    groups = {}                                     # one document type (and Finder icon) per file-type family
    for ext, (_kind, cat, _label) in formats.FORMATS.items():
        groups.setdefault(_progid_for(ext, cat).split(".", 1)[1], []).append(ext.lstrip("."))
    doc_types = [{"CFBundleTypeName": PROGIDS[suffix][0], "CFBundleTypeRole": "Viewer",
                  "LSHandlerRank": "Alternate", "CFBundleTypeIconFile": f"doc-{suffix}.icns",
                  "CFBundleTypeExtensions": sorted(set(exts))} for suffix, exts in sorted(groups.items())]
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{app_info.NAME}.app",
        icon=os.path.join(ROOT, "monkeyviewer.icns"),
        bundle_identifier=app_info.BUNDLE_ID,
        version=app_info.VERSION,
        info_plist={
            "CFBundleName": app_info.NAME,
            "CFBundleDisplayName": app_info.NAME,
            "CFBundleShortVersionString": app_info.VERSION,
            "CFBundleVersion": app_info.VERSION,
            "CFBundleDocumentTypes": doc_types,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": app_info.COPYRIGHT,
        },
    )
