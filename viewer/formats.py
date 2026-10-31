"""File-type registry: which viewer opens which file, labels, categories and text decoding."""

import os
import re

from .i18n import T

# category: (title, description, icon) for the welcome tiles and file-dialog filters.
# Monkey Viewer is a specialist tool: everyday Office documents, archives, mail and media are left to the
# programs made for them; what remains are the formats office staff usually *can't* open.
CATEGORIES = {
    "pdf": ("PDF & DjVu", "Edit, merge, crop \u00b7 DjVu", "document"),
    "cad": ("CAD", "DWG, DXF, IFC", "edit"),
    "gis": ("GIS", "SHP, KML, GPX, GPKG", "globe"),
    "secure": ("Signed & encrypted", ".p7m .pfx .gpg .enc", "lock"),
    "code": ("Lua & code", "Lua, Python, JSON\u2026", "code"),
    "table": ("Databases", "SQLite, dBASE, .pol", "table"),
    "image": ("Special images", "PSD, RAW, HEIC, TIFF", "picture"),
}

# ext -> (viewer kind, category, human label)
FORMATS = {}


def _reg(kind, category, label, exts):
    for ext in exts.split():
        FORMATS["." + ext] = (kind, category, label)


# Lua & code -------------------------------------------------------------------------------
_reg("text", "code", "Lua script", "lua luau rockspec wlua")
_reg("text", "code", "Python", "py pyw pyi")
_reg("text", "code", "JavaScript / TypeScript", "js mjs cjs jsx ts tsx")
_reg("text", "code", "JSON", "json jsonc json5 geojsonl ipynb webmanifest jsonl ndjson")
_reg("text", "code", "SVG drawing (Run SVG shows it)", "svg")
_reg("text", "code", "XML", "xml xsd xsl xslt xaml resx csproj vbproj vcxproj props targets nuspec "
                            "config manifest plist qgs qml sld gml x3d dae wsdl admx adml ps1xml cdxml")
_reg("text", "code", "Markdown", "md markdown rst adoc")
_reg("text", "code", "Config", "ini cfg conf toml yaml yml env properties reg inf editorconfig prj cpg wkt mof")
_reg("text", "code", "SQL", "sql psql")
_reg("text", "code", "PowerShell", "ps1 psm1 psd1")
_reg("text", "code", "Batch", "bat cmd")
_reg("text", "code", "Shell script", "sh bash zsh fish")
_reg("text", "code", "Source code", "c h cpp hpp cc cxx hh cs java kt kts go rs rb php pl pm r swift "
                                    "scala dart groovy gradle cmake asm f90 vb vbs fs tf hcl "
                                    "proto graphql gql sol zig nim jl ex exs erl hs clj lisp el tcl")
_reg("text", "code", "CNC G-code", "gcode nc ngc")
_reg("text", "cad", "IFC / STEP model (text)", "ifc step stp iges igs")

# PDF & DjVu -------------------------------------------------------------------------------
_reg("pdf", "pdf", "PDF document", "pdf")
_reg("pdf", "pdf", "Illustrator (PDF-compatible)", "ai")
_reg("document", "pdf", "XPS document", "xps oxps")
_reg("document", "pdf", "E-book", "epub mobi fb2 cbz")
_reg("djvu", "pdf", "DjVu document", "djvu djv")

# special images (common PNG / JPG / GIF stay with the system photo viewer) ----------------
_reg("image", "image", "Photoshop image", "psd")
_reg("image", "image", "TIFF / GeoTIFF image", "tif tiff")
_reg("image", "image", "HEIC / AVIF photo", "heic heif avif")
_reg("image", "image", "JPEG 2000 image", "jp2 j2k jpx")
_reg("image", "image", "Image", "tga pcx ppm pgm pbm pnm dds icns qoi sgi rgb blp xbm xpm")
_reg("image", "image", "Camera RAW photo", "cr2 cr3 crw nef nrw arw srf sr2 orf rw2 raf dng pef srw x3f 3fr erf "
                                           "kdc mrw mos raw rwl iiq")
_reg("image", "image", "Windows metafile", "emf wmf")
_reg("image", "image", "Layered image (OpenRaster / Krita)", "ora kra")

# CAD --------------------------------------------------------------------------------------
_reg("dxf", "cad", "AutoCAD DXF drawing", "dxf")
_reg("dwg", "cad", "AutoCAD DWG drawing", "dwg")
_reg("document", "cad", "Design Web Format (DWFx)", "dwfx")
_reg("info", "cad", "ArchiCAD project", "pln pla tpl pmk bpn")
_reg("info", "cad", "Revit project", "rvt rfa rte")
_reg("info", "cad", "CAD file", "dwf dgn 3dm skp")

# GIS --------------------------------------------------------------------------------------
_reg("map", "gis", "Shapefile", "shp")
_reg("map", "gis", "GeoJSON", "geojson topojson")
_reg("map", "gis", "Google Earth KML", "kml kmz")
_reg("map", "gis", "GPS track (GPX)", "gpx")
_reg("map", "gis", "GeoPackage", "gpkg")
_reg("map", "gis", "OpenStreetMap data", "osm")
_reg("image", "gis", "SRTM elevation tile", "hgt")
_reg("image", "gis", "ESRI ASCII grid", "asc")
_reg("table", "gis", "dBASE table", "dbf")
_reg("info", "gis", "ArcGIS / QGIS document", "mxd aprx lyr lyrx qgz")

# databases --------------------------------------------------------------------------------
_reg("table", "table", "SQLite database", "sqlite sqlite3 db db3 s3db sl3 mbtiles")
_reg("table", "table", "Group Policy registry file", "pol")

# signed & encrypted -----------------------------------------------------------------------
_reg("crypto", "secure", "Encrypted file", "enc encoded crypto crypt encrypted locked aes")
_reg("crypto", "secure", "Lock / protected file", "lock")
_reg("crypto", "secure", "AxCrypt encrypted file", "axx")
_reg("crypto", "secure", "GnuPG / PGP file", "gpg pgp gpe sig")
_reg("crypto", "secure", "Ansible Vault", "vault")
_reg("crypto", "secure", "age encrypted file", "age")
_reg("crypto", "secure", "Encoded file (Base64 / uuencode)", "b64 base64 uue uu jwt")
_reg("crypto", "secure", "KeePass database", "kdbx kdb")
_reg("crypto", "secure", "BitLocker recovery key", "bek")
_reg("cert", "secure", "Certificate", "cer crt der pem")
_reg("cert", "secure", "Personal certificate (with private key)", "pfx p12")
_reg("cert", "secure", "Certificate bundle", "p7b p7c spc")
_reg("cert", "secure", "Certificate request", "csr req")
_reg("cert", "secure", "Private key", "key")
_reg("cert", "secure", "Signed / encrypted document (S/MIME)", "p7m")
_reg("cert", "secure", "Digital signature", "p7s")

FILENAME_KINDS = {"makefile": "text", "dockerfile": "text", "readme": "text", "license": "text",
                  "cmakelists.txt": "text", "vagrantfile": "text", "gemfile": "text", "procfile": "text"}

BADGE_OVERRIDES = {".jpeg": "JPG", ".tiff": "TIF", ".geojson": "GEO", ".markdown": "MD",
                   ".rockspec": "LUA", ".topojson": "TOPO", ".sqlite3": "SQL", ".sqlite": "SQL"}


def ext_of(path):
    name = os.path.basename(path or "").lower()
    if name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return ".tgz"
    return os.path.splitext(name)[1]


def info(path):
    """(kind, category, label) for a path based on its extension (None if unknown)."""
    return FORMATS.get(ext_of(path))


def category_of(path):
    meta = info(path)
    return meta[1] if meta else "binary"


def badge_label(path):
    ext = ext_of(path)
    if ext in BADGE_OVERRIDES:
        return BADGE_OVERRIDES[ext]
    if not ext:
        return "TXT" if os.path.basename(path or "").lower() in FILENAME_KINDS else "FILE"
    return ext[1:5].upper()


def association_extensions():
    """Extensions to list Monkey Viewer under in Explorer's 'Open with' (ext -> category)."""
    return {ext: cat for ext, (_k, cat, _l) in FORMATS.items()}


MAX_FILTER = 240  # Windows file dialogs misbehave with very long filter patterns


def _pattern_string(patterns):
    out, length = [], 0
    for p in dict.fromkeys(patterns):
        if length + len(p) + 1 > MAX_FILTER:
            break
        out.append(p)
        length += len(p) + 1
    return " ".join(out)


def _category_patterns(cat):
    pats = [f"*{ext}" for ext, (_k, c, _l) in FORMATS.items() if c == cat]
    if cat == "code":
        pats = ["*.lua", "*.py", "*.json", "*.xml", "*.ps1", "*.bat", "*.sql", "*.ini"] + pats
    return pats


def dialog_filetypes():
    """'All files' first: every file can be opened, and long filters break the Windows dialog."""
    types = [(T("All files"), "*")]
    for cat, (title, _desc, _icon) in CATEGORIES.items():
        pats = _category_patterns(cat)
        if pats:
            types.append((T(title), _pattern_string(pats)))
    return types


def category_filetypes(cat):
    return [(T(CATEGORIES[cat][0]), _pattern_string(_category_patterns(cat))), (T("All files"), "*")]


# ─────────────────────────────── sniffing ───────────────────────────────
MAGIC = [
    (b"%PDF", "pdf"), (b"\x89PNG", "image"), (b"\xff\xd8\xff", "image"), (b"GIF8", "image"),
    (b"BM", None), (b"II*\x00", "image"), (b"MM\x00*", "image"), (b"RIFF", None),
    (b"SQLite format 3\x00", "table"), (b"AC10", "dwg"), (b"8BPS", "image"),
    (b"\x00\x00\x01\x00", "image"), (b"Salted__", "crypto"),
    (bytes.fromhex("C0B9072E4F93F146A015792CA1D9E821"), "crypto"), (b"$ANSIBLE_VAULT", "crypto"),
    (b"age-encryption.org", "crypto"), (bytes.fromhex("03D9A29A"), "crypto"), (b"-----BEGIN PGP", "crypto"),
    (b"-----BEGIN CERTIFICATE", "cert"), (b"-----BEGIN PKCS7", "cert"), (b"-----BEGIN PRIVATE KEY", "cert"),
    (b"-----BEGIN RSA PRIVATE", "cert"), (b"-----BEGIN ENCRYPTED PRIVATE", "cert"),
    (b"-----BEGIN CERTIFICATE REQUEST", "cert"), (b"AT&TFORM", "djvu"),
    (b"PReg", "table"), (b"MZ", "info"),
]


def sniff(path):
    """Guess a viewer kind from the file's first bytes (used for unknown extensions)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8192)
    except OSError:
        return "info"
    if len(head) > 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        return "image" if brand in (b"heic", b"heix", b"mif1", b"msf1", b"avif", b"hevc") else "info"
    for magic, kind in MAGIC:
        if head.startswith(magic):
            if magic == b"BM" and len(head) > 14 and head[6:10] == b"\x00\x00\x00\x00":
                return "image"
            if magic == b"RIFF":
                return "image" if head[8:12] == b"WEBP" else "info"
            if kind:
                return kind
    if looks_like_text(head):
        stripped = head.lstrip()
        if stripped.startswith((b"{", b"[")) and b'"type"' in head and b"Feature" in head:
            return "map"
        if stripped.startswith(b"U2FsdGVkX1"):
            return "crypto"
        return "text"
    return "info"


def looks_like_text(head):
    if not head:
        return True
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        if exc.start >= len(head) - 4:
            return True
    control = sum(1 for b in head if b < 9 or 13 < b < 32)
    return control / max(1, len(head)) < 0.02


def _head(path, n=256):
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def viewer_kind(path):
    """The viewer kind that should open *path*."""
    name = os.path.basename(path).lower()
    if name in FILENAME_KINDS:
        return "text"
    if name.startswith(".~lock.") or name.startswith("~$"):
        return "text" if looks_like_text(_head(path, 4096)) else "info"
    meta = info(path)
    ext = ext_of(path)
    if ext == ".asc":
        head = _head(path, 64).lstrip()
        if head[:5].lower() == b"ncols":
            return "image"
        return "crypto" if head.startswith(b"-----BEGIN PGP") else "text"
    if ext == ".key" and _head(path, 4) == b"PK\x03\x04":
        return "info"                                   # Apple Keynote, not a private key
    if ext == ".lock" and looks_like_text(_head(path, 4096)):
        return "text"
    if ext == ".db" and not _head(path, 16).startswith(b"SQLite format 3"):
        return "info"
    if meta:
        kind = meta[0]
        if kind == "text" and _head(path, 16).startswith((b"$ANSIBLE_VAULT", b"U2FsdGVkX1")):
            return "crypto"
        if kind == "pdf" and ext_of(path) == ".ai" and sniff(path) != "pdf":
            return "info"
        if ext_of(path) in (".json", ".geojsonl") and _is_geojson(path):
            return "map"
        return kind
    return sniff(path)


def _is_geojson(path):
    try:
        if os.path.getsize(path) > 200_000_000:
            return False
        with open(path, "rb") as fh:
            head = fh.read(4096)
        return b'"FeatureCollection"' in head or (b'"Feature"' in head and b'"geometry"' in head)
    except OSError:
        return False


def label_for(path):
    """Human label of the file type, in the interface language."""
    meta = info(path)
    return T(meta[2]) if meta else None


# ─────────────────────────────── text decoding ───────────────────────────────
ENCODINGS = ("utf-8-sig", "cp1251", "cp1252", "latin-1")
ENCODING_LABELS = {"utf-8": "UTF-8", "utf-8-sig": "UTF-8 BOM", "utf-16": "UTF-16",
                   "cp1252": "Windows-1252", "cp1251": "Windows-1251", "latin-1": "Latin-1"}


def decode_bytes(raw):
    """Returns (text, encoding)."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace"), "utf-16"
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
            if enc == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
                enc = "utf-8"
            return text, enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def read_text_file(path, limit=None):
    with open(path, "rb") as fh:
        raw = fh.read() if limit is None else fh.read(limit)
    text, enc = decode_bytes(raw)
    text = text.replace("\x00", "␀")
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), enc, eol


def natural_key(path):
    name = os.path.basename(path).lower()
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name)], path.lower()


def human_size(n):
    n = float(n)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n):,} bytes" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024
    return str(n)
