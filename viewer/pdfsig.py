"""Digital signatures inside PDF files (Adobe / PAdES: adbe.pkcs7.detached, ETSI.CAdES.detached, adbe.pkcs7.sha1,
ETSI.RFC3161 document timestamps and the old adbe.x509.rsa_sha1).

For every signature the check answers three separate questions, like Adobe Reader does:
  * integrity   - the signed bytes are unchanged and the CMS signature matches the signer's key;
  * coverage    - whether the file was changed (a later revision appended) after this signature;
  * certificate - who signed, whether the certificate was valid at signing time; trust in the issuing
                  authority is asked from the operating system separately (crypto.verify_trust).
"""

import binascii
import datetime
import hashlib
import re

from . import crypto
from .i18n import T

BYTERANGE = re.compile(rb"/ByteRange\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\]")


def _der_length(der):
    """Length of the outer DER element (the /Contents string is zero-padded after it)."""
    if len(der) < 2 or der[0] != 0x30:
        raise ValueError("not DER")
    first = der[1]
    if first < 0x80:
        return 2 + first
    n = first & 0x7F
    return 2 + n + int.from_bytes(der[2:2 + n], "big")


OBJ_START = re.compile(rb"\d+\s+\d+\s+obj\b")


def _literal(data, i):
    """Decode the PDF literal string starting at data[i] == '('; returns (bytes, index after ')')."""
    out, depth, i = bytearray(), 1, i + 1
    esc = {b"n"[0]: 10, b"r"[0]: 13, b"t"[0]: 9, b"b"[0]: 8, b"f"[0]: 12}
    while i < len(data):
        ch = data[i]
        if ch == 0x5C:                                   # backslash
            i += 1
            if i >= len(data):
                break
            nx = data[i]
            if nx in esc:
                out.append(esc[nx])
            elif 0x30 <= nx <= 0x37:                     # up to three octal digits
                j = i
                while j < min(i + 3, len(data)) and 0x30 <= data[j] <= 0x37:
                    j += 1
                out.append(int(data[i:j], 8) & 0xFF)
                i = j
                continue
            elif nx in (10, 13):                         # line continuation
                if nx == 13 and i + 1 < len(data) and data[i + 1] == 10:
                    i += 1
            else:
                out.append(nx)
        elif ch == 0x28:
            depth += 1
            out.append(ch)
        elif ch == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    raise ValueError("unterminated string")


def _string_at(data, i):
    """A PDF string (hex <..> or literal (..)) starting at data[i], skipping white space: (bytes, end) or None."""
    while i < len(data) and data[i] in b" \t\r\n\x0c\x00":
        i += 1
    if i >= len(data):
        return None
    if data[i:i + 1] == b"(":
        return _literal(data, i)
    if data[i:i + 1] == b"<" and data[i + 1:i + 2] != b"<":
        j = data.find(b">", i)
        if j < 0:
            return None
        hexd = re.sub(rb"\s", b"", data[i + 1:j])
        if len(hexd) % 2:
            hexd += b"0"
        return binascii.unhexlify(hexd), j + 1
    return None


def _strings(window, key):
    """Every string value of /key: a single string or an array of strings ([] when absent)."""
    for m in re.finditer(rb"/" + key + rb"(?![A-Za-z0-9])\s*", window):   # /Name may also be a /Prop_Build name
        i = m.end()
        if window[i:i + 1] == b"[":
            out, i = [], i + 1
            while True:
                got = _string_at(window, i)
                if got is None:
                    break
                out.append(got[0])
                i = got[1]
            if out:
                return out
            continue
        got = _string_at(window, i)
        if got:
            return [got[0]]
    return []


def _dictionary_window(data, m, c):
    """The bytes of the signature dictionary around /ByteRange: from its 'n 0 obj' to 'endobj', without the
    (large) /Contents value. Falls back to a fixed slice for files without the usual object syntax."""
    size = len(data)
    lo = max(0, m.start() - 65536)
    starts = list(OBJ_START.finditer(data, lo, m.start()))
    begin = starts[-1].start() if starts else max(0, m.start() - 6000)
    finish = data.find(b"endobj", max(c, m.end()))
    finish = finish if 0 <= finish - max(c, m.end()) < 65536 else min(size, max(c, m.end()) + 1500)
    if c > m.end():                                      # usual case: /Contents comes after /ByteRange
        return data[begin:m.end()] + data[c:finish]
    return data[begin:finish]


def _field(window, key):
    try:
        found = _strings(window, key)
    except (ValueError, binascii.Error):
        found = []
    if not found:
        return None
    raw = found[0]
    if raw[:2] in (b"\xfe\xff", b"\xff\xfe"):
        return raw.decode("utf-16", "replace")
    return raw.decode("latin-1")


def _pdf_date(text):
    m = re.match(r"(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", text or "")
    if not m:
        return None
    parts = [int(p) if p else d for p, d in zip(m.groups(), (0, 1, 1, 0, 0, 0))]
    try:
        return datetime.datetime(*parts)
    except ValueError:
        return None


def has_signatures(data):
    return b"/ByteRange" in data


def verify(data):
    """List of dicts, one per signature, in file order."""
    from cryptography import x509
    results = []
    size = len(data)
    end_of_file = len(data.rstrip(b"\r\n\x00 \t%EOF"))
    for m in BYTERANGE.finditer(data):
        a, b, c, d = (int(v) for v in m.groups())
        sig = {"subfilter": None, "name": None, "reason": None, "location": None, "time": None,
               "intact": False, "signature_ok": None, "covers_whole_file": False, "cert": None, "certs": [],
               "signer": None, "problem": None, "cert_valid_at_signing": None}
        results.append(sig)
        window = _dictionary_window(data, m, c) if c <= size else data[max(0, m.start() - 6000):m.end()]
        sub = re.search(rb"/SubFilter\s*/([\w.#]+)", window)
        sig["subfilter"] = sub.group(1).decode() if sub else None
        sig["name"], sig["reason"] = _field(window, b"Name"), _field(window, b"Reason")
        sig["location"] = _field(window, b"Location")
        sig["time"] = _pdf_date(_field(window, b"M"))
        if a != 0 or b <= 0 or c < b or c + d > size:
            sig["problem"] = T("The signature's byte range is damaged.")
            continue
        sig["end"] = c + d
        sig["covers_whole_file"] = c + d >= end_of_file
        try:
            got = _string_at(data[b:c], 0)
        except (ValueError, binascii.Error):
            got = None
        if not got or not got[0].strip(b"\x00"):
            sig["problem"] = T("The signature value is missing.")
            continue
        signed = data[a:a + b] + data[c:c + d]
        if (sig["subfilter"] or "").lower() == "adbe.x509.rsa_sha1":
            _verify_x509_rsa_sha1(sig, got[0], window, signed)
            continue
        try:
            der = got[0]
            der = der[:_der_length(der)]
            parsed = crypto.parse_cms(der)
        except Exception as exc:  # noqa: BLE001
            sig["problem"] = T("Signature format not supported ({0}).", sig["subfilter"] or exc.__class__.__name__)
            continue
        if parsed["type"] != "signed" or not parsed["signers"]:
            sig["problem"] = T("Signature format not supported ({0}).", sig["subfilter"] or "?")
            continue
        if sig["subfilter"] == "ETSI.RFC3161" or parsed.get("content_type") == "tst_info":
            sig["timestamp"] = True                     # document timestamp: the TSA signs a hash of the bytes
            sha1_ok = _timestamp_imprint_ok(parsed["content"], signed)
        elif parsed["content"] is not None:             # adbe.pkcs7.sha1: the SHA-1 of the bytes is signed
            sha1_ok = parsed["content"] == hashlib.sha1(signed, usedforsecurity=False).digest()  # nosec B324
        else:
            parsed = dict(parsed, content=signed)
            sha1_ok = True
        certs = []
        for raw in parsed["certs"]:
            try:
                certs.append(x509.load_der_x509_certificate(raw))
            except ValueError:
                continue
        sig["certs"] = certs
        signer = parsed["signers"][0]
        try:
            content_ok, sig_ok, cert = crypto.verify_cms_signer(parsed, signer, certs)
        except Exception as exc:  # noqa: BLE001
            sig["problem"] = str(exc)
            continue
        sig["cert"] = cert
        sig["signature_ok"] = bool(sig_ok)
        sig["intact"] = bool(content_ok) and sha1_ok and bool(sig_ok)
        if signer.get("time") and not sig["time"]:
            sig["time"] = signer["time"].replace(tzinfo=None)
        if cert is not None:
            sig["signer"] = common_name(cert)
            when = signer.get("time") or sig["time"]
            if when is not None:
                when = when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)
                start, end = _validity(cert)
                sig["cert_valid_at_signing"] = start <= when <= end
            sig["cert_expired_now"] = _validity(cert)[1] < datetime.datetime.now(datetime.timezone.utc)
        if not sig["signer"]:
            sig["signer"] = sig["name"] or T("unknown signer")
    # a final revision that only adds validation data (PAdES DSS: certificates, CRLs, OCSP) changes no content
    ends = [s["end"] for s in results if s.get("intact") and s.get("end")]
    if ends:
        last = max(ends)
        tail = data[last:]
        if tail.strip() and re.search(rb"/DSS\b|/VRI\b|/OCSPs\b|/CRLs\b", tail) and not re.search(
                rb"/Type\s*/Page\b|/Subtype\s*/(?:Widget|FreeText|Ink|Square|Circle|Stamp|Text|Line|Highlight)",
                tail):
            for s in results:
                if s.get("end") == last:
                    s["covers_whole_file"] = True
                    s["dss_after"] = True
    # a signature that does not cover the final file is normal when the later revisions were added by
    # further intact signatures / timestamps (multi-signature documents, PAdES long-term validation)
    for n, sig in enumerate(results):
        later = results[n + 1:]
        sig["later_signed"] = bool(later) and later[-1].get("intact") and later[-1].get("covers_whole_file")
    return results


def _verify_x509_rsa_sha1(sig, contents, window, signed):
    """adbe.x509.rsa_sha1: /Contents is a DER OCTET STRING holding a PKCS#1 v1.5 signature over the SHA-1 of the
    signed bytes; the signer's certificate (and its chain) is in /Cert, a string or an array of strings."""
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    certs = []
    try:
        raw_certs = _strings(window, b"Cert")
    except (ValueError, binascii.Error):
        raw_certs = []
    for raw in raw_certs:
        try:
            certs.append(x509.load_der_x509_certificate(raw[:_der_length(raw)]))
        except ValueError:
            continue
    sig["certs"] = certs
    if not certs:
        sig["problem"] = T("The signer's certificate is missing from the signature.")
        return
    value = contents
    try:
        from asn1crypto import core
        if value[:1] == b"\x04":                        # OCTET STRING wrapper (the usual form)
            value = core.OctetString.load(value[:_der_length_any(value)]).native
    except Exception:  # noqa: BLE001
        value = contents.rstrip(b"\x00")
    cert = certs[0]
    key = cert.public_key()
    if not isinstance(key, rsa.RSAPublicKey):
        sig["problem"] = T("Signature format not supported ({0}).", sig["subfilter"])
        return
    ok = False
    # verifying an existing legacy signature (reported as weak), never creating one
    for algo in (hashes.SHA1(), hashes.SHA256()):  # nosec B303 - rsa_sha1 by name; some writers used SHA-256
        try:
            key.verify(value, signed, padding.PKCS1v15(), algo)
            ok = True
            break
        except (InvalidSignature, ValueError):
            continue
    sig["cert"] = cert
    sig["signature_ok"] = ok
    sig["intact"] = ok
    sig["signer"] = common_name(cert) or sig["name"]
    sig["legacy_sha1"] = True
    when = sig["time"]
    if when is not None:
        start, end = _validity(cert)
        sig["cert_valid_at_signing"] = start <= when.replace(tzinfo=datetime.timezone.utc) <= end
    sig["cert_expired_now"] = _validity(cert)[1] < datetime.datetime.now(datetime.timezone.utc)


def _der_length_any(der):
    """Length of the outer DER element of any tag."""
    first = der[1]
    if first < 0x80:
        return 2 + first
    n = first & 0x7F
    return 2 + n + int.from_bytes(der[2:2 + n], "big")


def _timestamp_imprint_ok(tst_der, signed):
    from asn1crypto import tsp
    try:
        info = tsp.TSTInfo.load(tst_der)
        imprint = info["message_imprint"]
        algo = imprint["hash_algorithm"]["algorithm"].native.replace("_", "")
        return hashlib.new(algo, signed, usedforsecurity=algo not in ("md5", "sha1")).digest() == \
            imprint["hashed_message"].native
    except Exception:  # noqa: BLE001
        return False


def common_name(cert):
    from cryptography.x509.oid import NameOID
    for oid in (NameOID.COMMON_NAME, NameOID.ORGANIZATION_NAME):
        attrs = cert.subject.get_attributes_for_oid(oid)
        if attrs:
            return str(attrs[0].value)
    return cert.subject.rfc4514_string()


def _validity(cert):
    try:
        return cert.not_valid_before_utc, cert.not_valid_after_utc
    except AttributeError:
        return (cert.not_valid_before.replace(tzinfo=datetime.timezone.utc),
                cert.not_valid_after.replace(tzinfo=datetime.timezone.utc))


def summary(sig):
    """(level, text): level 'ok' | 'warning' | 'bad' for one verified signature."""
    who = sig.get("signer") or sig.get("name") or T("unknown signer")
    if sig.get("timestamp"):
        who = T("Document timestamp ({0})", who)
    if sig.get("problem"):
        return "bad", f"{who}: {sig['problem']}"
    if not sig["intact"]:
        return "bad", T("{0}: the signature is INVALID - the document was changed or the signature is damaged.", who)
    if not sig["covers_whole_file"] and sig.get("later_signed"):
        return "ok", T("{0}: signature valid - later revisions were added by further signatures or timestamps.",
                       who)
    if not sig["covers_whole_file"]:
        return "warning", T("{0}: signature valid for the signed version - the file was changed after signing "
                            "(a later revision was added).", who)
    if sig.get("cert_valid_at_signing") is False:
        return "warning", T("{0}: signature intact, but the certificate was not valid at signing time.", who)
    text = T("{0}: signature valid - the document has not been changed since it was signed.", who)
    if sig.get("cert_expired_now"):
        text += " " + T("(The certificate has expired since; it was valid at signing time.)")
    return "ok", text


def signatures(path):
    """verify() for a file on disk ([] when it has no signatures)."""
    with open(path, "rb") as fh:
        data = fh.read()
    return verify(data) if has_signatures(data) else []


def report(path, sigs, trust=None):
    """Plain-text report of every signature (the Details tab); *trust*: {n: text} from the OS trust check."""
    import os
    lines = [T("Digital signatures - {0}", os.path.basename(path)), ""]
    for n, s in enumerate(sigs, 1):
        level, text = summary(s)
        mark = {"ok": "✓", "warning": "!", "bad": "✗"}[level]
        lines.append(f"{mark} {T('Signature {0}', n)}: {text}")
        for label, value in ((T("Signed by"), s.get("signer")), (T("Name in the signature"), s.get("name")),
                             (T("Time"), s["time"].strftime("%Y-%m-%d %H:%M") if s.get("time") else None),
                             (T("Reason"), s.get("reason")), (T("Location"), s.get("location")),
                             (T("Format"), s.get("subfilter"))):
            if value:
                lines.append(f"    {label}: {value}")
        cert = s.get("cert")
        if cert is not None:
            start, end = _validity(cert)
            lines.append(f"    {T('Certificate')}: {cert.subject.rfc4514_string()}")
            lines.append(f"    {T('Issued by')}: {cert.issuer.rfc4514_string()}")
            lines.append(f"    {T('Valid from')}: {start:%Y-%m-%d}  {T('Valid until')}: {end:%Y-%m-%d}"
                         + (f"  ({T('expired')})" if s.get("cert_expired_now") else ""))
            if s.get("cert_valid_at_signing") is not None:
                lines.append("    " + (T("The certificate was valid when the document was signed.")
                                       if s["cert_valid_at_signing"] else
                                       T("The certificate was NOT valid when the document was signed.")))
        lines.append("    " + (T("Covers the whole file.") if s.get("covers_whole_file") else
                               T("The file was changed after this signature (later revision).")))
        if trust and n in trust:
            lines.append(f"    {T('Trust')}: {trust[n]}")
        lines.append("")
    if not trust:
        lines.append(T("Use \"Check signer trust\" to ask Windows / macOS whether the signers' certificates come from "
                       "a trusted authority and are not revoked."))
    return "\n".join(lines)
