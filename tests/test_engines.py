import base64
import os

import pytest

import samples


def test_pdf_render_and_tools(tmp_path):
    from viewer import convert
    from viewer.pdf_view import fitz
    a = samples.pdf(tmp_path / "a.pdf", 2)
    b = samples.pdf(tmp_path / "b.pdf", 1)
    merged = fitz.open("pdf", convert.merge_pdfs([str(a), str(b)]))
    assert len(merged) == 3
    pngs = convert.pdf_to_images(str(a), str(tmp_path), dpi=40)
    assert len(pngs) == 2 and all(os.path.getsize(p) > 0 for p in pngs)


def test_dxf_renders(tmp_path):
    import ezdxf
    from viewer.cad_view import render_dxf
    doc = ezdxf.readfile(str(samples.dxf(tmp_path / "plan.dxf")))
    assert render_dxf(doc)[:4] == b"%PDF"


def test_gis_readers(tmp_path):
    from viewer import gis
    layers = gis.read_any(samples.shapefile(tmp_path / "points"))
    assert layers[0].geom == "point" and len(layers[0].features) == 2
    gpx = tmp_path / "t.gpx"
    gpx.write_text('<gpx><trk><trkseg><trkpt lat="41.7" lon="44.8"/><trkpt lat="41.71" lon="44.81"/>'
                   '</trkseg></trk></gpx>')
    assert gis.read_any(str(gpx))[0].geom == "line"
    kml = tmp_path / "t.kml"
    kml.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>x</name><Point>'
                   '<coordinates>44.8,41.7</coordinates></Point></Placemark></kml>')
    assert gis.read_any(str(kml))[0].features
    osm = tmp_path / "t.osm"
    osm.write_text('<osm><node id="1" lat="41.7" lon="44.8"><tag k="name" v="x"/></node>'
                   '<node id="2" lat="41.8" lon="44.9"/><way id="3"><nd ref="1"/><nd ref="2"/>'
                   '<tag k="highway" v="primary"/></way></osm>')
    assert {l.geom for l in gis.read_any(str(osm))} == {"line", "point"}


def test_databases(tmp_path):
    import sqlite3
    from viewer.table_view import list_sheets, read_sheet
    db = tmp_path / "m.db"
    con = sqlite3.connect(db)
    con.execute('create table "odd ""name""" (a, b)')
    con.execute('insert into "odd ""name""" values (1, 2)')
    con.commit()
    con.close()
    sheet = list_sheets(str(db))[0]
    header, rows, total = read_sheet(str(db), sheet)
    assert header == ["a", "b"] and rows == [[1, 2]] and total == 1
    with pytest.raises(ValueError):
        read_sheet(str(db), "x; drop table y")
    header, rows, _ = read_sheet(str(samples.pol(tmp_path / "Registry.pol")))
    assert rows[0][1] == "Enabled" and rows[0][2] == "REG_DWORD"


def test_openssl_and_encoded_files(tmp_path):
    from viewer import crypto
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    plain = b"print('secret')\n" * 3
    salt = b"saltsalt"
    key, iv = crypto._bytes_to_key(b"pw", salt, 32, 16, "md5")
    p = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    f = tmp_path / "a.lua.enc"
    f.write_bytes(b"Salted__" + salt + enc.update(p.update(plain) + p.finalize()) + enc.finalize())
    a = crypto.analyse(str(f))
    assert a.kind == "openssl"
    with pytest.raises(ValueError):
        crypto.decrypt_with_password(a, str(f), "wrong")
    name, data = crypto.decrypt_with_password(a, str(f), "pw")
    assert data == plain and name.endswith(".lua")
    b64 = tmp_path / "x.b64"
    b64.write_bytes(base64.b64encode(b"%PDF-1.4 test"))
    name, data = crypto.decode(str(b64))
    assert data.startswith(b"%PDF")


def test_decrypted_output_goes_to_session_temp():
    from viewer import crypto, safeio
    path = crypto.save_temp("..\\..\\evil.exe", b"x")
    assert path.startswith(safeio.session_dir()) and os.path.basename(path) == "evil.exe"


def test_cms_signature_intact_and_tampered(tmp_path):
    from cryptography import x509
    from viewer import crypto
    key, cert = samples.self_signed()
    der = samples.cms_signed(b"%PDF-1.4 signed content", key, cert)
    parsed = crypto.parse_cms(der)
    assert parsed["type"] == "signed" and parsed["content"].startswith(b"%PDF")
    certs = [x509.load_der_x509_certificate(c) for c in parsed["certs"]]
    content_ok, sig_ok, who = crypto.verify_cms_signer(parsed, parsed["signers"][0], certs)
    assert content_ok and sig_ok and who.serial_number == cert.serial_number
    tampered = dict(parsed, content=b"%PDF-1.4 changed content")
    content_ok, sig_ok, _ = crypto.verify_cms_signer(tampered, parsed["signers"][0], certs)
    assert content_ok is False
    _k2, other = samples.self_signed("Someone else")
    content_ok, sig_ok, who = crypto.verify_cms_signer(parsed, parsed["signers"][0], [other])
    assert who is None and sig_ok is None


def test_pfx_and_pem(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    key, cert = samples.self_signed()
    pfx = pkcs12.serialize_key_and_certificates(b"t", key, cert, None,
                                                serialization.BestAvailableEncryption(b"1234"))
    loaded = pkcs12.load_key_and_certificates(pfx, b"1234")
    assert loaded[1].subject == cert.subject
    from viewer import formats
    pem = tmp_path / "c.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    assert formats.viewer_kind(str(pem)) == "cert"


def test_selftest_passes():
    from viewer import selftest
    report = selftest.run()
    failed = [c for c in report["checks"] if not c["ok"]]
    assert not failed, failed


def test_admx_matches_policy_definitions():
    import xml.etree.ElementTree as ET  # trusted file from this repository
    from viewer.policy import DEFINITIONS
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "admx")
    ns = {"p": "http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"}
    admx = ET.parse(os.path.join(root, "MonkeyViewer.admx"))  # noqa: S314
    names = {p.get("name") for p in admx.getroot().iterfind(".//p:policy", ns)}
    assert names == set(DEFINITIONS)
    for lang in ("en-US", "ka-GE"):
        adml = ET.parse(os.path.join(root, lang, "MonkeyViewer.adml"))  # noqa: S314
        ids = {s.get("id") for s in adml.getroot().iterfind(".//p:string", ns)}
        assert all(n in ids and f"{n}_Help" in ids for n in DEFINITIONS)


def test_pdf_signatures_are_verified(tmp_path):
    from viewer import pdfsig
    key, cert = samples.self_signed("PDF Signer")
    good = samples.signed_pdf(str(tmp_path / "good.pdf"), key, cert)
    [s] = pdfsig.signatures(good)
    assert s["intact"] and s["covers_whole_file"] and s["signer"] == "PDF Signer"
    assert s["reason"] == "Approved" and s["time"].year == 2026 and pdfsig.summary(s)[0] == "ok"
    bad = samples.signed_pdf(str(tmp_path / "bad.pdf"), key, cert, tamper=True)
    [b] = pdfsig.signatures(bad)
    assert not b["intact"] and pdfsig.summary(b)[0] == "bad"
    later = samples.signed_pdf(str(tmp_path / "later.pdf"), key, cert, append=b"\n% added later\n1 0 obj\n<<>>\nendobj\n")
    [l] = pdfsig.signatures(later)
    assert l["intact"] and not l["covers_whole_file"] and pdfsig.summary(l)[0] == "warning"
    assert "PDF Signer" in pdfsig.report(good, [s])
    assert pdfsig.signatures(samples.pdf(tmp_path / "plain.pdf")) == []


def test_legacy_x509_rsa_sha1_signatures(tmp_path):
    """adbe.x509.rsa_sha1 (PKCS#1 in an OCTET STRING, certificates in /Cert), hex and literal strings."""
    from viewer import pdfsig
    key, cert = samples.self_signed("Legacy Signer")
    for literal in (True, False):
        good = samples.x509_signed_pdf(str(tmp_path / f"ok{literal}.pdf"), key, cert, chain=(cert,), literal=literal)
        bad = samples.x509_signed_pdf(str(tmp_path / f"bad{literal}.pdf"), key, cert, tamper=True, literal=literal)
        s = pdfsig.signatures(good)[0]
        assert s["intact"] and s["signer"] == "Legacy Signer" and s["name"] == "Old Signer" and not s["problem"]
        assert len(s["certs"]) == 2
        assert not pdfsig.signatures(bad)[0]["intact"]


def test_pdf_literal_strings():
    from viewer import pdfsig
    data, end = pdfsig._literal(b"(a\\(b\\)c (nested) \\101\\n\\\\)rest", 0)
    assert data == b"a(b)c (nested) A\n\\" and end == len(b"(a\\(b\\)c (nested) \\101\\n\\\\)")


def test_print_documents_and_page_ranges():
    from PIL import Image
    from viewer import printing
    doc = printing.text_document("local x = 1 -- გამარჯობა\n" * 400, "test.lua")
    assert len(doc) > 3 and "გამარჯობა" in doc[0].get_text() and f"1 / {len(doc)}" in doc[0].get_text()
    table = printing.table_document(["a", "b"], [["1", "ქ"], ["2", "x"]], "t.csv")
    assert "ქ" in table[0].get_text()
    img = printing.image_document(Image.new("RGB", (800, 400), "red"))
    assert len(img) == 1 and img[0].rect.width > img[0].rect.height       # landscape image, landscape page
    assert printing.as_pdf_bytes(img).startswith(b"%PDF")
    assert printing.parse_ranges("1-3, 5, 8-", 9) == [0, 1, 2, 4, 7, 8]
    assert printing.parse_ranges("2", 3) == [1]
    for bad in ("0", "5", "3-1", "x", ""):
        with pytest.raises(ValueError):
            printing.parse_ranges(bad, 4)
    assert printing._lp_ranges([0, 1, 2, 4, 7, 8]) == "1-3,5,8-9"


def test_dib_rows_for_windows_printing():
    from viewer import printing
    rgb = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])          # 2 x 2 pixels, rows of 6 bytes
    assert bytes(printing.to_dib(rgb, 2, 2)) == bytes([3, 2, 1, 6, 5, 4, 0, 0, 9, 8, 7, 12, 11, 10, 0, 0])
    assert bytes(printing.to_dib(bytes(range(12)), 4, 1)) == bytes([2, 1, 0, 5, 4, 3, 8, 7, 6, 11, 10, 9])


def test_dxf_with_every_layer_hidden_or_an_empty_layout(tmp_path):
    import ezdxf
    import fitz
    from viewer.cad_view import render_dxf
    doc = ezdxf.readfile(str(samples.dxf(tmp_path / "d.dxf")))
    data = render_dxf(doc, hidden_layers={"Pipes", "Wells", "0"})
    page = fitz.open("pdf", data)[0]
    assert "hidden" in page.get_text()
    doc.layouts.new("Empty")
    assert "empty" in fitz.open("pdf", render_dxf(doc, "Empty"))[0].get_text()


def test_svg_fonts_come_from_the_windows_registry(monkeypatch, tmp_path):
    import sys
    import types
    from viewer import svg_view, theme
    fonts = tmp_path / "Fonts"
    fonts.mkdir()
    for f in ("arial.ttf", "arialbd.ttf", "times.ttf", "cour.ttf", "sylfaen.ttf", "CAMBRIA.TTC", "Fancy.otf"):
        (fonts / f).write_bytes(b"x")
    values = [("Arial (TrueType)", "arial.ttf"), ("Arial Bold (TrueType)", "arialbd.ttf"),
              ("Times New Roman (TrueType)", "times.ttf"), ("Courier New (TrueType)", "cour.ttf"),
              ("Sylfaen (TrueType)", "sylfaen.ttf"), ("Cambria & Cambria Math (TrueType)", "CAMBRIA.TTC"),
              ("Fancy Display Regular (OpenType)", str(fonts / "Fancy.otf"))]

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def enum(_key, i):
        if i >= len(values):
            raise OSError
        return values[i][0], values[i][1], 1
    fake = types.SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2, OpenKey=lambda h, s: Key() if h == 1
                                 else (_ for _ in ()).throw(OSError()), EnumValue=enum)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(theme, "IS_WIN", True)
    monkeypatch.setattr(theme, "IS_MAC", False)
    monkeypatch.setenv("WINDIR", str(tmp_path))
    monkeypatch.setattr(svg_view, "_FONT_INDEX", None)
    opts = svg_view.font_options('<svg><text style="font-family: \'Fancy Display\', Cambria, serif">ქ</text></svg>')
    names = {os.path.basename(p) for p in opts["font_files"]}
    assert {"Fancy.otf", "CAMBRIA.TTC", "times.ttf", "arial.ttf", "arialbd.ttf", "sylfaen.ttf"} <= names
    assert opts["skip_system_fonts"] and opts["sans_serif_family"] == "Arial"
    monkeypatch.setattr(svg_view, "_FONT_INDEX", None)
