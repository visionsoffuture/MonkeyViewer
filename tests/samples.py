"""Builders for small, deterministic test files (nothing is downloaded)."""

import datetime
import struct



def pdf(path, pages=2):
    import pymupdf as fitz
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_htmlbox(fitz.Rect(50, 50, 500, 200), f"<p>Page {i + 1} გამარჯობა</p>")
    doc.save(str(path))
    return path


def dxf(path):
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 50), dxfattribs={"layer": "Pipes"})
    msp.add_circle((50, 25), 10, dxfattribs={"layer": "Wells"})
    doc.saveas(str(path))
    return path


def shapefile(base):
    import shapefile as shp
    with shp.Writer(str(base)) as w:
        w.field("name", "C")
        w.point(44.8, 41.7)
        w.record("თბილისი")
        w.point(41.6, 41.6)
        w.record("Batumi")
    return str(base) + ".shp"


def self_signed(cn="Monkey Viewer Test", key_size=2048):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    return key, cert


def cms_signed(content, key, cert):
    """A CMS SignedData (.p7m, attached content) signed with RSA/SHA-256 and signed attributes."""
    import hashlib
    from asn1crypto import algos, cms, core, x509 as ax509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    acert = ax509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
    attrs = cms.CMSAttributes([
        cms.CMSAttribute({"type": "content_type", "values": ["data"]}),
        cms.CMSAttribute({"type": "signing_time", "values": [cms.Time({"utc_time": core.UTCTime(
            datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0))})]}),
        cms.CMSAttribute({"type": "message_digest", "values": [hashlib.sha256(content).digest()]}),
    ])
    signature = key.sign(attrs.dump(), padding.PKCS1v15(), hashes.SHA256())
    signer = cms.SignerInfo({
        "version": "v1",
        "sid": cms.SignerIdentifier({"issuer_and_serial_number": cms.IssuerAndSerialNumber({
            "issuer": acert.issuer, "serial_number": acert.serial_number})}),
        "digest_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
        "signed_attrs": attrs,
        "signature_algorithm": algos.SignedDigestAlgorithm({"algorithm": "rsassa_pkcs1v15"}),
        "signature": signature,
    })
    signed = cms.SignedData({
        "version": "v1",
        "digest_algorithms": [algos.DigestAlgorithm({"algorithm": "sha256"})],
        "encap_content_info": {"content_type": "data", "content": content},
        "certificates": [acert],
        "signer_infos": [signer],
    })
    return cms.ContentInfo({"content_type": "signed_data", "content": signed}).dump()


def pol(path):
    def entry(key, val, typ, data):
        z = lambda s: (s + "\0").encode("utf-16-le")  # noqa: E731
        sep = ";".encode("utf-16-le")
        return ("[".encode("utf-16-le") + z(key) + sep + z(val) + sep + struct.pack("<I", typ) + sep +
                struct.pack("<I", len(data)) + sep + data + "]".encode("utf-16-le"))
    data = b"PReg" + struct.pack("<I", 1) + entry(r"Software\Policies\Test", "Enabled", 4, struct.pack("<I", 1))
    path.write_bytes(data)
    return path


def _pdf_literal(raw):
    out = bytearray(b"(")
    for ch in raw:
        if ch in b"()\\":
            out += b"\\" + bytes([ch])
        elif ch == 13:
            out += b"\\r"
        elif ch < 32 or ch > 126:
            out += b"\\%03o" % ch
        else:
            out.append(ch)
    return bytes(out + b")")


def x509_signed_pdf(path, key, cert, chain=(), tamper=False, literal=True):
    """A PDF signed the old way (adbe.x509.rsa_sha1, Acrobat 5 era): PKCS#1 signature in an OCTET STRING,
    certificates in /Cert. *literal* writes /Contents and /Cert as (...) strings, as some old signers did."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    der_certs = [c.public_bytes(serialization.Encoding.DER) for c in (cert,) + tuple(chain)]
    enc = _pdf_literal if literal else (lambda raw: b"<" + raw.hex().encode() + b">")
    cert_entry = enc(der_certs[0]) if not chain else b"[" + b" ".join(enc(c) for c in der_certs) + b"]"
    size_guess = key.key_size // 8 + 4
    placeholder = enc(b"\x00" * (size_guess * 2 if literal else size_guess))
    objs = [
        b"<</Type/Catalog/Pages 2 0 R/AcroForm<</Fields[4 0 R]/SigFlags 3>>>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Annots[4 0 R]/Contents 6 0 R>>",
        b"<</Type/Annot/Subtype/Widget/FT/Sig/T(Signature1)/Rect[0 0 0 0]/V 5 0 R/P 3 0 R/F 132>>",
        b"<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/adbe.x509.rsa_sha1/Name(Old Signer)/M(D:20240101120000Z)"
        b"/Prop_Build<</Filter<</Name/Adobe.PPKLite>>>>"
        b"/ByteRange[0 0000000000 0000000000 0000000000]/Contents" + placeholder + b"/Cert" + cert_entry + b">>",
        b"<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (Signed text) Tj ET\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    data = bytes(out)
    start = data.index(b"/Contents" + placeholder) + len(b"/Contents")
    end = start + len(placeholder)
    br = b"0 %010d %010d %010d" % (start, end, len(data) - end)
    data = data.replace(b"0 0000000000 0000000000 0000000000", br, 1)
    signed = data[:start] + data[end:]
    raw_sig = key.sign(signed, padding.PKCS1v15(), hashes.SHA1())
    octet = b"\x04" + (bytes([len(raw_sig)]) if len(raw_sig) < 128 else b"\x82" + len(raw_sig).to_bytes(2, "big"))
    value = enc(octet + raw_sig)
    assert len(value) <= len(placeholder), (len(value), len(placeholder))
    if literal:                                       # the gap keeps its size: spaces after the string
        value = value + b" " * (len(placeholder) - len(value))
    else:                                             # zero padding inside <...>, like Acrobat
        value = value[:-1] + b"0" * (len(placeholder) - len(value)) + b">"
    data = data[:start] + value + data[end:]
    if tamper:
        data = data.replace(b"(Signed text)", b"(Forged text)")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def signed_pdf(path, key, cert, tamper=False, append=b""):
    """A one-page PDF with an adbe.pkcs7.detached signature (built by hand, like Acrobat does)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7
    placeholder = b"0" * 8192
    objs = [
        b"<</Type/Catalog/Pages 2 0 R/AcroForm<</Fields[4 0 R]/SigFlags 3>>>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Annots[4 0 R]/Contents 6 0 R>>",
        b"<</Type/Annot/Subtype/Widget/FT/Sig/T(Signature1)/Rect[0 0 0 0]/V 5 0 R/P 3 0 R/F 132>>",
        b"<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/adbe.pkcs7.detached/Name(Test Signer)"
        b"/M(D:20260101120000Z)/Reason(Approved)/Location(Tbilisi)"
        b"/ByteRange[0 0000000000 0000000000 0000000000]/Contents<" + placeholder + b">>>",
        b"<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (Signed text) Tj ET\nendstream",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    data = bytes(out)
    start = data.index(b"/Contents<") + len(b"/Contents")
    end = start + len(placeholder) + 2
    br = b"0 %010d %010d %010d" % (start, end, len(data) - end)
    data = data.replace(b"0 0000000000 0000000000 0000000000", br, 1)
    signed = data[:start] + data[end:]
    sig = pkcs7.PKCS7SignatureBuilder().set_data(signed).add_signer(cert, key, hashes.SHA256()).sign(
        serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary])
    hexsig = sig.hex().encode().ljust(len(placeholder), b"0")
    data = data[:start + 1] + hexsig + data[end - 1:]
    if tamper:
        data = data.replace(b"(Signed text)", b"(Forged text)")
    with open(path, "wb") as fh:
        fh.write(data + append)
    return path


def met_forecast(start="2026-10-27T08:00:00Z", hours=48, days=8):
    """A MET Norway locationforecast/compact response: hourly steps, then 6-hourly ones."""
    import datetime as dt
    t0 = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    series = []
    for h in range(hours):
        t = t0 + dt.timedelta(hours=h)
        entry = {"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": {
            "instant": {"details": {"air_temperature": 10 + (h % 24) / 2, "wind_speed": 3.2,
                                    "relative_humidity": 61.0}},
            "next_1_hours": {"summary": {"symbol_code": "partlycloudy_day" if 6 <= t.hour <= 14 else
                                         "clearsky_night"}, "details": {"precipitation_amount": 0.0}}}}
        if t.hour % 6 == 0:
            entry["data"]["next_6_hours"] = {"summary": {"symbol_code": "lightrain"},
                                             "details": {"precipitation_amount": 1.5}}
        series.append(entry)
    t = t0 + dt.timedelta(hours=hours)
    t = t.replace(hour=(t.hour // 6) * 6)
    while t < t0 + dt.timedelta(days=days):
        series.append({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": {
            "instant": {"details": {"air_temperature": 5.0 + t.hour / 3}},
            "next_6_hours": {"summary": {"symbol_code": "heavysnowshowers_day"},
                             "details": {"precipitation_amount": 2.0}}}})
        t += dt.timedelta(hours=6)
    return {"type": "Feature", "properties": {"meta": {"updated_at": start}, "timeseries": series}}
