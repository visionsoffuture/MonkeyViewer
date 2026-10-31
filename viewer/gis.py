"""GIS readers: Shapefile, GeoJSON, KML/KMZ, GPX, GeoPackage and OpenStreetMap XML -> layers of numpy geometries."""

import json
import os
import re
import sqlite3
import struct
import zipfile

import numpy as np

from . import safeio
from .i18n import T

LAYER_COLORS = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e", "#bb9af7", "#2ac3de", "#ff9e64", "#73daca"]


class Feature:
    __slots__ = ("kind", "parts", "holes", "props", "bbox")

    def __init__(self, kind, parts, props, holes=()):
        self.kind = kind            # "point" | "line" | "polygon"
        self.parts = parts          # list of (N, 2) float arrays
        self.holes = set(holes)     # indices of polygon rings that are holes
        self.props = props          # list aligned with Layer.fields
        allpts = np.concatenate(parts) if len(parts) > 1 else parts[0]
        self.bbox = (float(allpts[:, 0].min()), float(allpts[:, 1].min()),
                     float(allpts[:, 0].max()), float(allpts[:, 1].max()))


class Layer:
    def __init__(self, name, fields, features, crs=None, color=None):
        self.name = name
        self.fields = fields
        self.features = features
        self.crs = crs
        self.color = color or LAYER_COLORS[0]
        self.visible = True
        kinds = {f.kind for f in features}
        self.geom = kinds.pop() if len(kinds) == 1 else ("mixed" if kinds else "empty")
        if features:
            self.bboxes = np.array([f.bbox for f in features], dtype=float)
            self.bbox = (self.bboxes[:, 0].min(), self.bboxes[:, 1].min(),
                         self.bboxes[:, 2].max(), self.bboxes[:, 3].max())
        else:
            self.bboxes = np.zeros((0, 4))
            self.bbox = None

    @property
    def geographic(self):
        c = (self.crs or "").upper()
        if re.match(r"\s*PROJ(CS|CRS)\[", c) or any(k in c for k in ("MERCATOR", "UTM", "3857", "TM ")):
            return False
        if re.match(r"\s*GEOG(CS|CRS)\[", c) or "CRS84" in c or "4326" in c or c.strip() in ("WGS 84", "WGS84"):
            return True
        if self.bbox is None:
            return False
        x0, y0, x1, y1 = self.bbox
        return -181 <= x0 and x1 <= 181 and -91 <= y0 and y1 <= 91


def crs_name(wkt):
    if not wkt:
        return None
    m = re.match(r'\s*\w+\[\s*"([^"]+)"', wkt)
    return m.group(1) if m else wkt[:60]


def _ring_area(arr):
    x, y = arr[:, 0], arr[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _feature(kind, parts, props, holes=()):
    parts = [p for p in parts if len(p)]
    if not parts:
        return None
    return Feature(kind, parts, props, holes)


# ─────────────────────────────── Shapefile ───────────────────────────────
def _shp_encoding(path):
    cpg = os.path.splitext(path)[0] + ".cpg"
    try:
        with open(cpg, "r", encoding="ascii", errors="ignore") as fh:
            code = fh.read().strip().lower()
    except OSError:
        return "utf-8"
    if "utf" in code and "8" in code:
        return "utf-8"
    digits = re.sub(r"\D", "", code)
    if digits:
        return {"1251": "cp1251", "1252": "cp1252", "1257": "cp1257", "65001": "utf-8", "866": "cp866",
                "88591": "latin-1"}.get(digits, f"cp{digits}")
    return "utf-8"


def read_shapefile(path):
    import shapefile
    enc = _shp_encoding(path)
    try:
        r = shapefile.Reader(path, encoding=enc, encodingErrors="replace")
    except LookupError:
        r = shapefile.Reader(path, encoding="utf-8", encodingErrors="replace")
    fields = [f[0] for f in r.fields[1:]]
    feats = []
    for sr in r.iterShapeRecords():
        shp = sr.shape
        pts = shp.points
        if not pts:
            continue
        arr = np.asarray(pts, dtype=float)[:, :2]
        st = shp.shapeType % 10 if shp.shapeType != 31 else 5
        props = list(sr.record)
        if st in (1, 8):
            f = _feature("point", [arr], props)
        else:
            idx = list(shp.parts) + [len(arr)]
            parts = [arr[idx[k]:idx[k + 1]] for k in range(len(idx) - 1)]
            if st == 3:
                f = _feature("line", parts, props)
            else:
                holes = [k for k, p in enumerate(parts) if len(p) > 2 and _ring_area(p) > 0] if len(parts) > 1 else []
                if len(holes) == len(parts):
                    holes = []
                f = _feature("polygon", parts, props, holes)
        if f:
            feats.append(f)
    prj = os.path.splitext(path)[0] + ".prj"
    crs = None
    if os.path.exists(prj):
        with open(prj, "r", encoding="utf-8", errors="replace") as fh:
            crs = fh.read().strip()
    return [Layer(os.path.splitext(os.path.basename(path))[0], fields, feats, crs)]


# ─────────────────────────────── GeoJSON ───────────────────────────────
def _geojson_geom(geom, props, out):
    if not geom:
        return
    t, c = geom.get("type"), geom.get("coordinates")
    try:
        if t == "Point":
            out.append(_feature("point", [np.array([c[:2]], float)], props))
        elif t == "MultiPoint":
            out.append(_feature("point", [np.array([p[:2] for p in c], float)], props))
        elif t == "LineString":
            out.append(_feature("line", [np.array([p[:2] for p in c], float)], props))
        elif t == "MultiLineString":
            out.append(_feature("line", [np.array([p[:2] for p in ln], float) for ln in c], props))
        elif t == "Polygon":
            rings = [np.array([p[:2] for p in r], float) for r in c]
            out.append(_feature("polygon", rings, props, range(1, len(rings))))
        elif t == "MultiPolygon":
            rings, holes = [], []
            for poly in c:
                for k, r in enumerate(poly):
                    if k:
                        holes.append(len(rings))
                    rings.append(np.array([p[:2] for p in r], float))
            out.append(_feature("polygon", rings, props, holes))
        elif t == "GeometryCollection":
            for g in geom.get("geometries", []):
                _geojson_geom(g, props, out)
    except (TypeError, IndexError, ValueError):
        pass


def read_geojson(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    items = data.get("features") if data.get("type") == "FeatureCollection" else \
        [data] if data.get("type") == "Feature" else [{"geometry": data, "properties": {}}]
    keys = {}
    for it in items:
        for k in (it.get("properties") or {}):
            keys.setdefault(k, None)
    fields = list(keys)
    feats = []
    for it in items:
        p = it.get("properties") or {}
        props = [p.get(k) for k in fields]
        _geojson_geom(it.get("geometry"), props, feats)
    crs = None
    if isinstance(data.get("crs"), dict):
        crs = (data["crs"].get("properties") or {}).get("name")
    return [Layer(os.path.splitext(os.path.basename(path))[0], fields, [f for f in feats if f], crs or "WGS 84")]


# ─────────────────────────────── KML / KMZ ───────────────────────────────
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _coords(text):
    pts = []
    for tok in (text or "").split():
        bits = tok.split(",")
        if len(bits) >= 2:
            try:
                pts.append((float(bits[0]), float(bits[1])))
            except ValueError:
                pass
    return np.array(pts, float).reshape(-1, 2)


def _kml_geoms(el, out_parts):
    name = _local(el.tag)
    if name == "Point":
        for c in el.iter():
            if _local(c.tag) == "coordinates":
                out_parts.append(("point", [_coords(c.text)], []))
    elif name in ("LineString", "LinearRing"):
        for c in el.iter():
            if _local(c.tag) == "coordinates":
                out_parts.append(("line", [_coords(c.text)], []))
    elif name == "Polygon":
        rings, holes = [], []
        for b in el:
            bn = _local(b.tag)
            if bn in ("outerBoundaryIs", "innerBoundaryIs"):
                for c in b.iter():
                    if _local(c.tag) == "coordinates":
                        if bn == "innerBoundaryIs":
                            holes.append(len(rings))
                        rings.append(_coords(c.text))
        out_parts.append(("polygon", rings, holes))
    elif name == "Track":
        pts = []
        for c in el:
            if _local(c.tag) == "coord":
                bits = (c.text or "").split()
                if len(bits) >= 2:
                    pts.append((float(bits[0]), float(bits[1])))
        if pts:
            out_parts.append(("line", [np.array(pts, float)], []))
    else:
        for child in el:
            _kml_geoms(child, out_parts)


def read_kml(path):
    if path.lower().endswith(".kmz"):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
            if not name:
                raise ValueError(T("No KML document inside the KMZ"))
            root = safeio.xml_fromstring(z.read(name))
    else:
        root = safeio.xml_parse(path).getroot()
    rows = []
    keys = {"name": None, "description": None}
    for pm in root.iter():
        if _local(pm.tag) != "Placemark":
            continue
        props = {}
        geoms = []
        for child in pm:
            n = _local(child.tag)
            if n in ("name", "description"):
                text = re.sub(r"<[^>]+>", " ", child.text or "").strip()
                props[n] = re.sub(r"\s+", " ", text)[:500]
            elif n == "ExtendedData":
                for d in child.iter():
                    dn = _local(d.tag)
                    if dn == "Data":
                        val = next((x.text for x in d if _local(x.tag) == "value"), None)
                        props[d.get("name")] = val
                    elif dn == "SimpleData":
                        props[d.get("name")] = d.text
            else:
                _kml_geoms(child, geoms)
        for k in props:
            keys.setdefault(k, None)
        rows.append((props, geoms))
    fields = list(keys)
    feats = []
    for props, geoms in rows:
        values = [props.get(k) for k in fields]
        for kind, parts, holes in geoms:
            f = _feature(kind, parts, values, holes)
            if f:
                feats.append(f)
    return [Layer(os.path.splitext(os.path.basename(path))[0], fields, feats, "WGS 84")]


# ─────────────────────────────── GPX ───────────────────────────────
def read_gpx(path):
    root = safeio.xml_parse(path).getroot()
    wpts, tracks, routes = [], [], []

    def text_of(el, name):
        return next((c.text for c in el if _local(c.tag) == name), None)

    for el in root:
        n = _local(el.tag)
        if n == "wpt":
            wpts.append(_feature("point", [np.array([[float(el.get("lon")), float(el.get("lat"))]])],
                                 [text_of(el, "name"), text_of(el, "ele"), text_of(el, "time")]))
        elif n in ("trk", "rte"):
            parts = []
            segs = [s for s in el if _local(s.tag) == "trkseg"] if n == "trk" else [el]
            for seg in segs:
                pts = [(float(p.get("lon")), float(p.get("lat"))) for p in seg if _local(p.tag) in ("trkpt", "rtept")]
                if pts:
                    parts.append(np.array(pts, float))
            f = _feature("line", parts, [text_of(el, "name"), sum(len(p) for p in parts)])
            if f:
                (tracks if n == "trk" else routes).append(f)
    layers = []
    stem = os.path.splitext(os.path.basename(path))[0]
    if tracks:
        layers.append(Layer(f"{stem} — tracks", ["name", "points"], tracks, "WGS 84"))
    if routes:
        layers.append(Layer(f"{stem} — routes", ["name", "points"], routes, "WGS 84"))
    if wpts:
        layers.append(Layer(f"{stem} — waypoints", ["name", "ele", "time"], wpts, "WGS 84"))
    return layers


# ─────────────────────────────── GeoPackage / WKB ───────────────────────────────
def parse_wkb(buf, off=0):
    """Returns (list of (kind, parts, holes), new offset)."""
    e = "<" if buf[off] == 1 else ">"
    t = struct.unpack_from(e + "I", buf, off + 1)[0]
    off += 5
    has_z = bool(t & 0x80000000)
    has_m = bool(t & 0x40000000)
    if t & 0x20000000:
        off += 4
    t &= 0x0FFFFFFF
    if t >= 3000:
        has_z = has_m = True
        t -= 3000
    elif t >= 2000:
        has_m, t = True, t - 2000
    elif t >= 1000:
        has_z, t = True, t - 1000
    dims = 2 + has_z + has_m

    def points(n, o):
        arr = np.frombuffer(buf, dtype=e + "f8", count=n * dims, offset=o).reshape(n, dims)[:, :2].astype(float)
        return arr, o + n * dims * 8

    if t == 1:
        arr, off = points(1, off)
        return ([("point", [arr], [])] if not np.isnan(arr).any() else []), off
    if t == 2:
        n = struct.unpack_from(e + "I", buf, off)[0]
        arr, off = points(n, off + 4)
        return [("line", [arr], [])], off
    if t == 3:
        nr = struct.unpack_from(e + "I", buf, off)[0]
        off += 4
        rings = []
        for _ in range(nr):
            n = struct.unpack_from(e + "I", buf, off)[0]
            arr, off = points(n, off + 4)
            rings.append(arr)
        return [("polygon", rings, list(range(1, len(rings))))], off
    if t in (4, 5, 6, 7):
        n = struct.unpack_from(e + "I", buf, off)[0]
        off += 4
        out = []
        for _ in range(n):
            sub, off = parse_wkb(buf, off)
            out += sub
        if t in (4, 5, 6) and out:
            kind = out[0][0]
            parts, holes = [], []
            for _k, ps, hs in out:
                holes += [len(parts) + h for h in hs]
                parts += ps
            return [(kind, parts, holes)], off
        return out, off
    raise ValueError(T("Unsupported WKB geometry type {0}", t))


def gpkg_geometry(blob):
    if blob is None or len(blob) < 8 or blob[:2] != b"GP":
        return []
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((flags >> 1) & 0x07, 0)
    if flags & 0x10:  # empty geometry
        return []
    geoms, _off = parse_wkb(blob, 8 + env)
    return geoms


def read_gpkg(path):
    con = safeio.sqlite_readonly(path)
    try:
        tables = con.execute("SELECT c.table_name, g.column_name, g.srs_id FROM gpkg_contents c "
                             "JOIN gpkg_geometry_columns g ON g.table_name = c.table_name "
                             "WHERE c.data_type = 'features'").fetchall()
        layers = []
        for k, (table, geom_col, srs_id) in enumerate(tables):
            crs = None
            try:
                row = con.execute("SELECT srs_name, definition FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                                  (srs_id,)).fetchone()
                if row:
                    crs = row[1] if row[1] and row[1] != "undefined" else row[0]
            except sqlite3.Error:
                pass
            ident = safeio.quote_ident(table)
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({ident})")]
            fields = [c for c in cols if c != geom_col]
            gi = cols.index(geom_col)
            feats = []
            # table name comes from the file's gpkg_contents and is quoted as an identifier
            for row in con.execute(f"SELECT * FROM {ident}"):  # nosec B608
                props = [v for i, v in enumerate(row) if i != gi]
                try:
                    for kind, parts, holes in gpkg_geometry(row[gi]):
                        f = _feature(kind, parts, props, holes)
                        if f:
                            feats.append(f)
                except Exception:  # noqa: BLE001
                    continue
            layers.append(Layer(table, fields, feats, crs, LAYER_COLORS[k % len(LAYER_COLORS)]))
        return layers
    finally:
        con.close()


# ─────────────────────────────── OpenStreetMap XML ───────────────────────────────
OSM_AREA_KEYS = ("building", "landuse", "natural", "leisure", "amenity", "area", "water", "place", "boundary")
OSM_TYPE_KEYS = ("highway", "railway", "waterway", "building", "landuse", "natural", "leisure", "amenity",
                 "shop", "tourism", "place", "boundary", "power", "barrier", "man_made")


def _osm_type(tags):
    for k in OSM_TYPE_KEYS:
        if k in tags:
            return f"{k}={tags[k]}"
    return next((f"{k}={v}" for k, v in tags.items() if k not in ("name", "source", "created_by")), "")


def read_osm(path, max_nodes=5_000_000):
    nodes, points, lines, areas = {}, [], [], []
    fields = ["id", "name", "type"]
    tags, refs, cur = {}, [], None
    for event, el in safeio.xml_iterparse(path, events=("start", "end")):
        tag = el.tag
        if event == "start":
            if tag in ("node", "way"):
                cur, tags, refs = el, {}, []
            continue
        if tag == "tag" and cur is not None:
            tags[el.get("k")] = el.get("v")
        elif tag == "nd" and cur is not None:
            refs.append(el.get("ref"))
        elif tag == "node":
            try:
                lon, lat = float(el.get("lon")), float(el.get("lat"))
            except (TypeError, ValueError):
                lon = None
            if lon is not None:
                if len(nodes) < max_nodes:
                    nodes[el.get("id")] = (lon, lat)
                if tags and any(k not in ("source", "created_by") for k in tags):
                    f = _feature("point", [np.array([[lon, lat]])], [el.get("id"), tags.get("name"), _osm_type(tags)])
                    if f:
                        points.append(f)
            cur = None
            el.clear()
        elif tag == "way":
            pts = [nodes[r] for r in refs if r in nodes]
            if len(pts) >= 2:
                arr = np.array(pts, float)
                closed = len(refs) > 3 and refs[0] == refs[-1]
                is_area = closed and (tags.get("area") != "no") and any(k in tags for k in OSM_AREA_KEYS)
                f = _feature("polygon" if is_area else "line", [arr],
                             [el.get("id"), tags.get("name"), _osm_type(tags)])
                if f:
                    (areas if is_area else lines).append(f)
            cur = None
            el.clear()
        elif tag == "relation":
            el.clear()
    stem = os.path.splitext(os.path.basename(path))[0]
    layers = []
    if areas:
        layers.append(Layer(f"{stem} — areas", fields, areas, "WGS 84", LAYER_COLORS[2]))
    if lines:
        layers.append(Layer(f"{stem} — ways", fields, lines, "WGS 84", LAYER_COLORS[0]))
    if points:
        layers.append(Layer(f"{stem} — points", fields, points, "WGS 84", LAYER_COLORS[3]))
    if not layers and nodes:
        arr = np.array(list(nodes.values()), float)
        layers.append(Layer(f"{stem} — nodes", ["count"],
                            [Feature("point", [arr[i:i + 1]], [1]) for i in range(min(len(arr), 200_000))], "WGS 84"))
    return layers


def read_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".shp":
        layers = read_shapefile(path)
    elif ext in (".geojson", ".json", ".topojson", ".geojsonl"):
        layers = read_geojson(path)
    elif ext in (".kml", ".kmz"):
        layers = read_kml(path)
    elif ext == ".gpx":
        layers = read_gpx(path)
    elif ext == ".gpkg":
        layers = read_gpkg(path)
    elif ext == ".osm":
        layers = read_osm(path)
    else:
        raise ValueError(T("Unsupported GIS format {0}", ext))
    for k, layer in enumerate(layers):
        if layer.color == LAYER_COLORS[0] and k:
            layer.color = LAYER_COLORS[k % len(LAYER_COLORS)]
    if not any(l.features for l in layers):
        raise ValueError(T("No geometries found in this file"))
    return layers
