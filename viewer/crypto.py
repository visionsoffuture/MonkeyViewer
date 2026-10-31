"""Recognise and (with the right password or key) decrypt / decode protected files.

Supported: OpenSSL `enc` files (Salted__), Ansible Vault, OpenPGP / GnuPG (via gpg), Base64 / uuencode /
JWT text, CMS / PKCS#7 (.p7m signed or encrypted, .p7s), and recognition of AxCrypt, KeePass, age,
BitLocker, LUKS and generic encrypted data (entropy analysis). Nothing is guessed or brute-forced: decryption
only happens with the password / key the user supplies."""

import base64
import binascii
import bz2
import hashlib
import hmac
import math
import os
import re
import shutil
import zlib

from . import formats, safeio, winutil
from .i18n import T

PGP_PUBKEY = {1: "RSA", 2: "RSA", 3: "RSA", 16: "ElGamal", 17: "DSA", 18: "ECDH", 19: "ECDSA", 22: "EdDSA",
              25: "X25519", 26: "X448"}
PGP_SYM = {1: "IDEA", 2: "3DES", 3: "CAST5", 4: "Blowfish", 7: "AES-128", 8: "AES-192", 9: "AES-256",
           10: "Twofish", 11: "Camellia-128", 12: "Camellia-192", 13: "Camellia-256"}
AXCRYPT_GUID = bytes.fromhex("C0B9072E4F93F146A015792CA1D9E821")


class NeedsPassword(Exception):
    quiet = True        # an expected prompt, not an error worth logging


class Analysis:
    def __init__(self, kind, title, facts=None, note="", actions=(), payload=None):
        self.kind = kind            # short id: openssl, vault, pgp, base64, uu, jwt, cms, axcrypt, ...
        self.title = title          # "OpenSSL encrypted file"
        self.facts = facts or []    # [(label, value)]
        self.note = note            # explanation for the user
        self.actions = list(actions)  # "decrypt-password", "decode", "gpg", "open-external", "cms"
        self.payload = payload      # parsed data for the action


# ─────────────────────────────── helpers ───────────────────────────────
def entropy(data):
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts if c)


def _read(path, limit=None):
    with open(path, "rb") as fh:
        return fh.read() if limit is None else fh.read(limit)


def output_name(path, data):
    """Name for a decrypted/decoded file: strip the protection extension, add one from the content."""
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    if ext.lower() in (".enc", ".encoded", ".crypto", ".crypt", ".encrypted", ".locked", ".lock", ".gpg", ".pgp",
                       ".gpe", ".asc", ".p7m", ".vault", ".aes", ".b64", ".base64", ".axx", ".age", ".uue"):
        base = stem
    if not os.path.splitext(base)[1]:
        guess = guess_extension(data)
        if guess:
            base += guess
    return base or "decrypted.bin"


MAGIC_EXT = [(b"%PDF", ".pdf"), (b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"),
             (b"PK\x03\x04", ".zip"), (b"\xd0\xcf\x11\xe0", ".doc"), (b"7z\xbc\xaf", ".7z"), (b"Rar!", ".rar"),
             (b"SQLite format 3", ".sqlite"), (b"II*\x00", ".tif"), (b"MM\x00*", ".tif"), (b"AC10", ".dwg"),
             (b"{\\rtf", ".rtf"), (b"\x1f\x8b", ".gz"), (b"BM", ".bmp"), (b"RIFF", ".wav"), (b"ID3", ".mp3")]


def guess_extension(data):
    for magic, ext in MAGIC_EXT:
        if data.startswith(magic):
            if ext == ".zip":
                head = data[:4000]
                if b"word/" in head:
                    return ".docx"
                if b"xl/" in head:
                    return ".xlsx"
                if b"ppt/" in head:
                    return ".pptx"
            return ext
    if formats.looks_like_text(data[:4096]):
        return ".txt"
    return ".bin"


def save_temp(name, data):
    """Decrypted / decoded results live only in this session's private temp folder (removed on exit)."""
    folder = safeio.temp_dir("result")
    path = os.path.join(folder, safeio.safe_filename(name, "decrypted.bin"))
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def plausible(data):
    """How much decrypted bytes look like real content (0..3)."""
    if not data:
        return 0
    if guess_extension(data) not in (".txt", ".bin"):
        return 3
    head = data[:4096]
    if formats.looks_like_text(head):
        return 2
    return 1 if entropy(head) < 7.5 else 0


# ─────────────────────────────── analysis ───────────────────────────────
def analyse(path):
    head = _read(path, 1 << 20)
    size = os.path.getsize(path)
    facts = [("Size", formats.human_size(size))]
    text = None
    if formats.looks_like_text(head[:8192]):
        try:
            text = head.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            text = head.decode("latin-1")

    if head.startswith(b"Salted__"):
        return Analysis("openssl", "OpenSSL encrypted file", facts + [("Format", "openssl enc (salted)"),
                        ("Salt", head[8:16].hex())],
                        "Encrypted with a password using the OpenSSL “enc” command (usually AES-256-CBC). "
                        "Enter the password to decrypt it.", ["decrypt-password"])
    if text and text.lstrip().startswith("U2FsdGVkX1"):
        return Analysis("openssl-b64", "OpenSSL encrypted text (Base64)", facts + [("Format", "openssl enc -a")],
                        "Base64 text produced by “openssl enc -a”. Enter the password to decrypt it.",
                        ["decrypt-password"])
    if text and text.startswith("$ANSIBLE_VAULT"):
        header = text.split("\n", 1)[0].strip().split(";")
        return Analysis("vault", "Ansible Vault", facts + [("Version", header[1] if len(header) > 1 else "?"),
                        ("Cipher", header[2] if len(header) > 2 else "?")] +
                        ([("Vault ID", header[3])] if len(header) > 3 else []),
                        "Encrypted with ansible-vault (AES-256). Enter the vault password to decrypt it.",
                        ["decrypt-password"])
    if text and text.startswith("age-encryption.org/v1"):
        return Analysis("age", "age encrypted file", facts,
                        "Encrypted with the “age” tool. Decrypt it with age and your identity file.",
                        ["open-external"])
    if head.startswith(AXCRYPT_GUID):
        return Analysis("axcrypt", "AxCrypt encrypted file", facts + [("Format", "AxCrypt")],
                        "Encrypted with AxCrypt. Open it in AxCrypt (Open with Default App) and enter your "
                        "password there.", ["open-external", "link:https://www.axcrypt.net/"])
    if head[:8] == bytes.fromhex("03D9A29A67FB4BB5") or head[:4] == bytes.fromhex("03D9A29A"):
        return Analysis("keepass", "KeePass password database", facts,
                        "A KeePass database. Open it in KeePass / KeePassXC with your master password.",
                        ["open-external"])
    if head[3:11] == b"-FVE-FS-":
        return Analysis("bitlocker", "BitLocker volume image", facts, "A BitLocker-encrypted volume image.", [])
    if head.startswith(b"LUKS\xba\xbe"):
        return Analysis("luks", "LUKS encrypted volume", facts, "A Linux LUKS encrypted volume.", [])

    # OpenPGP (binary or armored)
    pgp = parse_pgp(head, text)
    if pgp:
        return pgp

    # CMS / PKCS#7 (signed / enveloped)
    cms_info = sniff_cms(head, text)
    if cms_info:
        return cms_info

    if text is not None:
        stripped = text.strip()
        if stripped.startswith("begin ") and re.match(r"begin [0-7]{3,4} \S", stripped):
            return Analysis("uu", "uuencoded file", facts + [("Original name", stripped.split(None, 2)[2].split("\n")[0])],
                            "Text-encoded binary (uuencode). Decode it to get the original file.", ["decode"])
        if re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", stripped) and stripped.startswith("eyJ"):
            return Analysis("jwt", "JSON Web Token", facts, "A JWT. Decoding shows its header and claims "
                            "(the signature is not verified).", ["decode"])
        b64 = _base64_payload(stripped)
        if b64 is not None:
            ext = guess_extension(b64)
            return Analysis("base64", "Base64 encoded data", facts + [("Decoded size", formats.human_size(len(b64))),
                            ("Looks like", ext.lstrip(".").upper())],
                            "Text-encoded binary (Base64). Decode it to open the original content.", ["decode"])
        return Analysis("text", "Text file", facts, "This file is plain text — it is not encrypted.", [])

    ent = entropy(head)
    facts.append(("Entropy", T("{0:.3f} bits per byte", ent)))
    kind = sniff_known(head)
    if kind:
        return Analysis("known", T("Not encrypted — looks like {0}", kind), facts,
                        "The content has a recognisable format. It can be opened directly.", ["open-as"],
                        payload=kind)
    if ent > 7.9:
        note = T("No known header and the data looks random, so it is encrypted (or compressed) by a program that "
                 "doesn't label its files. It can only be opened with the program and key that created it. If this "
                 "file appeared unexpectedly with many others (for example after a virus), don't pay anyone — "
                 "check backups and report it to your IT security team.")
        return Analysis("unknown-encrypted", "Encrypted data (unknown program)", facts, note, ["open-external"])
    return Analysis("binary", "Binary data", facts, "No encryption header was found. Try the Hex view.", ["hex"])


def sniff_known(head):
    ext = guess_extension(head)
    return None if ext in (".txt", ".bin") else ext.lstrip(".").upper()


def _base64_payload(text):
    body = re.sub(r"^data:[^,]*;base64,", "", text)
    body = re.sub(r"-----(BEGIN|END)[^-]+-----", "", body)
    compact = re.sub(r"\s+", "", body)
    if len(compact) < 16 or not re.fullmatch(r"[A-Za-z0-9+/_-]+=*", compact):
        return None
    try:
        data = base64.b64decode(compact + "=" * (-len(compact) % 4), altchars=b"-_" if "-" in compact or "_" in compact else None)
    except (binascii.Error, ValueError):
        return None
    if formats.looks_like_text(data[:512]) and re.fullmatch(r"[A-Za-z0-9]+", compact[:64] or "x") and len(compact) < 40:
        return None
    return data


# ─────────────────────────────── decoding ───────────────────────────────
def decode(path):
    """Decode Base64 / uuencode / JWT text. Returns (name, bytes)."""
    text = _read(path).decode("utf-8-sig", errors="replace").strip()
    if text.startswith("begin "):
        lines = text.splitlines()
        name = lines[0].split(None, 2)[2].strip()
        out = bytearray()
        for line in lines[1:]:
            if line.strip() == "end":
                break
            if line.strip() in ("", "`"):
                continue
            try:
                out += binascii.a2b_uu(line)
            except binascii.Error:
                n = ((ord(line[0]) - 32) & 63) * 4 // 3 + 3
                out += binascii.a2b_uu(line[:n])
        return name, bytes(out)
    if text.startswith("eyJ") and text.count(".") == 2:
        import json
        parts = text.split(".")
        out = {}
        for label, part in (("header", parts[0]), ("payload", parts[1])):
            raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
            out[label] = json.loads(raw)
        return os.path.splitext(os.path.basename(path))[0] + "_decoded.json", \
            json.dumps(out, indent=2, ensure_ascii=False).encode("utf-8")
    data = _base64_payload(text)
    if data is None:
        raise ValueError(T("This isn't valid Base64 text"))
    return output_name(path, data), data


# ─────────────────────────────── OpenSSL enc ───────────────────────────────
def _bytes_to_key(password, salt, key_len, iv_len, hash_name):
    d, out = b"", b""
    while len(out) < key_len + iv_len:
        # OpenSSL's legacy EVP_BytesToKey (needed to *read* files made by "openssl enc"); not used to protect data
        d = hashlib.new(hash_name, d + password + salt, usedforsecurity=False).digest()  # nosec B303
        out += d
    return out[:key_len], out[key_len:key_len + iv_len]


def _unpad(data, block=16):
    if not data or len(data) % block:
        return None
    n = data[-1]
    if not 1 <= n <= block or data[-n:] != bytes([n]) * n:
        return None
    return data[:-n]


def decrypt_openssl(path, password):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = _read(path)
    if not raw.startswith(b"Salted__"):
        raw = base64.b64decode(re.sub(rb"\s+", b"", raw))
    if not raw.startswith(b"Salted__"):
        raise ValueError(T("Not an OpenSSL salted file"))
    salt, body = raw[8:16], raw[16:]
    pw = password.encode("utf-8")
    candidates = []
    for key_len in (32, 16, 24):
        derivations = [("pbkdf2-sha256", lambda kl: _pbkdf2_split(pw, salt, kl, "sha256", 10000)),
                       ("sha256", lambda kl: _bytes_to_key(pw, salt, kl, 16, "sha256")),
                       ("md5", lambda kl: _bytes_to_key(pw, salt, kl, 16, "md5")),
                       ("pbkdf2-sha512", lambda kl: _pbkdf2_split(pw, salt, kl, "sha512", 10000))]
        for name, derive in derivations:
            key, iv = derive(key_len)
            dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            plain = _unpad(dec.update(body) + dec.finalize())
            if plain is not None:
                candidates.append((plausible(plain), key_len == 32, name, plain))
    if not candidates:
        raise ValueError(T("Wrong password (or an unsupported cipher)"))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    if candidates[0][0] == 0:
        raise ValueError(T("Wrong password (or an unsupported cipher)"))
    return output_name(path, candidates[0][3]), candidates[0][3]


def _pbkdf2_split(pw, salt, key_len, hash_name, iterations):
    out = hashlib.pbkdf2_hmac(hash_name, pw, salt, iterations, key_len + 16)
    return out[:key_len], out[key_len:]


# ─────────────────────────────── Ansible Vault ───────────────────────────────
def decrypt_vault(path, password):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    text = _read(path).decode("utf-8")
    lines = text.strip().splitlines()
    body = binascii.unhexlify("".join(l.strip() for l in lines[1:]))
    salt_hex, mac_hex, cipher_hex = body.split(b"\n", 2)
    salt, mac, ciphertext = binascii.unhexlify(salt_hex), binascii.unhexlify(mac_hex), binascii.unhexlify(cipher_hex.strip())
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 10000, 80)
    key1, key2, iv = derived[:32], derived[32:64], derived[64:80]
    if not hmac.compare_digest(hmac.new(key2, ciphertext, hashlib.sha256).digest(), mac):
        raise ValueError(T("Wrong vault password"))
    dec = Cipher(algorithms.AES(key1), modes.CTR(iv)).decryptor()
    plain = dec.update(ciphertext) + dec.finalize()
    plain = _unpad(plain) or plain
    stem = os.path.splitext(os.path.basename(path))[0]
    name = stem if os.path.splitext(stem)[1] else stem + ".yml"
    return name, plain


def decrypt_with_password(analysis, path, password):
    if analysis.kind in ("openssl", "openssl-b64"):
        return decrypt_openssl(path, password)
    if analysis.kind == "vault":
        return decrypt_vault(path, password)
    if analysis.kind == "pgp":
        return decrypt_gpg(path, password)
    raise ValueError(T("Password decryption isn't available for this format"))


# ─────────────────────────────── OpenPGP ───────────────────────────────
def _pgp_dearmor(text):
    m = re.search(r"-----BEGIN PGP ([A-Z ]+)-----\s*\n(.*?)\n\s*\n(.*?)\n=?[A-Za-z0-9+/=]*\s*-----END PGP", text, re.S)
    if not m:
        m2 = re.search(r"-----BEGIN PGP ([A-Z ]+)-----\s*\n(.*?)-----END PGP", text, re.S)
        if not m2:
            return None, None
        return m2.group(1), None
    body = re.sub(r"\s+", "", m.group(3))
    try:
        return m.group(1), base64.b64decode(body + "=" * (-len(body) % 4))
    except (binascii.Error, ValueError):
        return m.group(1), None


def pgp_packets(data):
    pos, out = 0, []
    while pos < len(data) and len(out) < 64:
        b = data[pos]
        if not b & 0x80:
            break
        if b & 0x40:
            tag = b & 0x3F
            l0 = data[pos + 1]
            if l0 < 192:
                length, hdr = l0, 2
            elif l0 < 224:
                length, hdr = ((l0 - 192) << 8) + data[pos + 2] + 192, 3
            elif l0 == 255:
                length, hdr = int.from_bytes(data[pos + 2:pos + 6], "big"), 6
            else:
                length, hdr = len(data) - pos - 2, 2  # partial body: treat rest as one packet
        else:
            tag = (b >> 2) & 0x0F
            lt = b & 3
            if lt == 3:
                length, hdr = len(data) - pos - 1, 1
            else:
                n = (1, 2, 4)[lt]
                length, hdr = int.from_bytes(data[pos + 1:pos + 1 + n], "big"), 1 + n
        out.append((tag, data[pos + hdr:pos + hdr + length]))
        pos += hdr + length
    return out


def parse_pgp(head, text):
    armor_kind = None
    data = head
    if text and "-----BEGIN PGP" in text:
        armor_kind, data = _pgp_dearmor(text)
        if armor_kind == "SIGNED MESSAGE":
            return Analysis("pgp-clearsigned", "PGP signed text", [("Format", "OpenPGP clear-signed message")],
                            "Readable text with a PGP signature attached — not encrypted.", [])
        if armor_kind in ("PUBLIC KEY BLOCK", "PRIVATE KEY BLOCK"):
            return Analysis("pgp-key", f"PGP {armor_kind.title()}", [("Format", "OpenPGP key")],
                            "An OpenPGP key. Import it into GnuPG / Kleopatra to use it.", ["gpg-show"])
        if data is None:
            return None
    if not data or not data[0] & 0x80:
        return None
    try:
        packets = pgp_packets(data)
    except IndexError:
        return None
    if not packets or packets[0][0] not in (1, 3, 4, 8, 2, 5, 6, 11, 18, 9, 20):
        return None
    facts = [("Format", "OpenPGP " + ("(ASCII armored)" if armor_kind else "(binary)"))]
    recipients, symmetric, encrypted = [], False, False
    for tag, body in packets:
        if tag == 1 and len(body) >= 10:
            recipients.append(f"{body[1:9].hex().upper()}  ({PGP_PUBKEY.get(body[9], body[9])})")
        elif tag == 3 and len(body) >= 2:
            symmetric = True
            facts.append(("Cipher", PGP_SYM.get(body[1], str(body[1]))))
        elif tag in (9, 18, 20):
            encrypted = True
    if not (encrypted or recipients or symmetric):
        return Analysis("pgp-signed", "PGP signed / compressed data", facts,
                        "Signed (not encrypted) OpenPGP data. The content can be extracted.", ["pgp-extract", "gpg"],
                        payload=data)
    for r in recipients:
        facts.append(("Encrypted for key", r))
    if symmetric and not recipients:
        note = T("Encrypted with a passphrase (gpg -c). Enter the passphrase to decrypt it.")
    else:
        note = T("Encrypted for the key(s) above. GnuPG (Gpg4win) decrypts it with your private key — its own "
                 "password window will ask for your passphrase.")
    actions = ["gpg"] + (["decrypt-password"] if symmetric else [])
    return Analysis("pgp", "GnuPG / PGP encrypted file", facts, note, actions)


def extract_pgp_literal(data):
    """Content of a signed-only OpenPGP message (handles compression)."""
    for tag, body in pgp_packets(data):
        if tag == 8:
            algo = body[0]
            raw = body[1:]
            inner = zlib.decompress(raw, -15) if algo == 1 else zlib.decompress(raw) if algo == 2 else \
                bz2.decompress(raw) if algo == 3 else raw
            return extract_pgp_literal(inner)
        if tag == 11:
            n = body[1]
            name = body[2:2 + n].decode("utf-8", "replace") or "content"
            return name, body[2 + n + 4:]
    raise ValueError(T("No literal data in this message"))


class PassphraseNeeded(Exception):
    """GnuPG needs a passphrase (for the file, or for the private key it was encrypted for)."""


def _gpg_base(gpg):
    """Common options; a bundled GnuPG is told where its own agent / keyboxd are (macOS builds)."""
    args = [gpg, "--batch", "--yes", "--no-auto-key-retrieve"]
    folder = os.path.dirname(gpg)
    ext = ".exe" if winutil.IS_WIN else ""
    for option, name in (("--agent-program", "gpg-agent"), ("--keyboxd-program", "keyboxd")):
        helper = os.path.join(folder, name + ext)
        if winutil.bundled_tool("gnupg", os.path.join("bin", "gpg")) == gpg and os.path.isfile(helper) \
                and not winutil.IS_WIN:
            args += [option, helper]
    return args


def decrypt_gpg(path, passphrase=None):
    """Decrypt with GnuPG. The passphrase is asked by Monkey Viewer itself (loopback - no extra pinentry program)
    and handed over on stdin, never on the command line. Raises PassphraseNeeded when one is required."""
    gpg = winutil.find_gpg()
    if not gpg:
        raise RuntimeError(T("GnuPG is not installed. Install Gpg4win (gpg4win.org) to decrypt PGP files."))
    folder = safeio.temp_dir("gpg")
    out = os.path.join(folder, "out.bin")
    args = _gpg_base(gpg) + ["--output", out, "--pinentry-mode", "loopback", "--passphrase-fd", "0",
                             "--decrypt", path]
    try:
        proc = winutil.run_hidden(args, timeout=300, input=(passphrase or "").encode("utf-8") + b"\n")
        ok = proc.returncode == 0 and os.path.exists(out)
        data = None
        if ok:
            with open(out, "rb") as fh:
                data = fh.read()
    finally:
        shutil.rmtree(folder, ignore_errors=True)     # the cleartext never stays on disk here
    if not ok:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        reason = next((l for l in reversed(msg) if "gpg:" in l), msg[-1] if msg else "gpg failed")
        text = proc.stderr.decode("utf-8", "replace").lower()
        if "no secret key" in text:
            reason = T("You don't have the private key this file was encrypted for (gpg: No secret key).")
        elif any(s in text for s in ("bad passphrase", "bad session key", "no passphrase given",
                                     "decryption failed", "problem with the agent")):
            if not passphrase:
                raise PassphraseNeeded()
            reason = T("Wrong passphrase.")
        raise ValueError(reason.replace("gpg: ", ""))
    name = output_name(path, data)
    m = re.search(rb'original file name=[\'"]?([^\'"\r\n]+)', proc.stderr)
    if m:
        name = os.path.basename(m.group(1).decode("utf-8", "replace")) or name
    return name, data


def gpg_show_keys(path):
    gpg = winutil.find_gpg()
    if not gpg:
        raise RuntimeError(T("GnuPG is not installed (gpg4win.org)"))
    proc = winutil.run_hidden(_gpg_base(gpg) + ["--show-keys", "--with-fingerprint", path], timeout=60)
    return (proc.stdout + proc.stderr).decode("utf-8", "replace")


# ─────────────────────────────── CMS / PKCS#7 ───────────────────────────────
CMS_OIDS = {"1.2.840.113549.1.7.2": "signed", "1.2.840.113549.1.7.3": "enveloped",
            "1.2.840.113549.1.9.16.1.23": "authenveloped", "1.2.840.113549.1.7.1": "data"}


def load_cms_bytes(raw):
    """DER bytes of a CMS ContentInfo from DER, PEM or S/MIME (base64) input."""
    if raw[:1] == b"\x30":
        return raw
    text = raw.decode("latin-1")
    m = re.search(r"-----BEGIN (?:PKCS7|CMS|PKCS #7 SIGNED DATA)-----(.*?)-----END", text, re.S)
    if m:
        return base64.b64decode(re.sub(r"\s+", "", m.group(1)))
    if "Content-Type:" in text and "pkcs7" in text.lower():
        parts = re.split(r"\r?\n\r?\n", text, 1)
        body = parts[1] if len(parts) > 1 else text
        body = re.split(r"\r?\n--", body)[0]
        return base64.b64decode(re.sub(r"\s+", "", body))
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"[A-Za-z0-9+/]+=*", compact or "x"):
        return base64.b64decode(compact)
    raise ValueError(T("Not a CMS / PKCS#7 structure"))


def sniff_cms(head, text):
    try:
        der = load_cms_bytes(head)
    except Exception:  # noqa: BLE001
        return None
    try:
        from asn1crypto import cms
        info = cms.ContentInfo.load(der)
        ctype = info["content_type"].dotted
    except Exception:  # noqa: BLE001
        return None
    kind = CMS_OIDS.get(ctype)
    if not kind:
        return None
    return Analysis("cms", "S/MIME / PKCS#7 " + (T("signed file") if kind == "signed" else T("encrypted file")),
                    [("Structure", f"CMS {kind} data")], "", ["cms"])


def parse_cms(raw):
    """Returns a dict describing a CMS ContentInfo (signed or enveloped)."""
    from asn1crypto import cms
    der = load_cms_bytes(raw)
    info = cms.ContentInfo.load(der)
    ctype = CMS_OIDS.get(info["content_type"].dotted, info["content_type"].native)
    out = {"type": ctype, "certs": [], "signers": [], "recipients": [], "content": None, "der": der}
    content = info["content"]
    if ctype == "signed":
        eci = content["encap_content_info"]
        out["content"] = eci["content"].native if eci["content"].native is not None else None
        out["content_type"] = eci["content_type"].native
        for c in content["certificates"] or []:
            if c.name == "certificate":
                out["certs"].append(c.chosen.dump())
        for si in content["signer_infos"]:
            signer = {"digest": si["digest_algorithm"]["algorithm"].native,
                      "signature_algo": si["signature_algorithm"]["algorithm"].native, "time": None,
                      "message_digest": None, "info": si}
            sid = si["sid"]
            if sid.name == "issuer_and_serial_number":
                signer["serial"] = sid.chosen["serial_number"].native
                signer["issuer"] = sid.chosen["issuer"].human_friendly
                signer["issuer_der"] = sid.chosen["issuer"].dump()
            else:
                signer["ski"] = sid.chosen.native.hex()
            for attr in si["signed_attrs"] or []:
                name = attr["type"].native
                if name == "signing_time":
                    signer["time"] = attr["values"][0].native
                elif name == "message_digest":
                    signer["message_digest"] = attr["values"][0].native
            out["signers"].append(signer)
    elif ctype in ("enveloped", "authenveloped"):
        eci = content["encrypted_content_info"]
        out["cipher"] = eci["content_encryption_algorithm"]["algorithm"].native
        out["encrypted"] = eci["encrypted_content"].native
        out["enc_params"] = eci["content_encryption_algorithm"]
        for ri in content["recipient_infos"]:
            r = {"kind": ri.name}
            if ri.name == "ktri":
                rid = ri.chosen["rid"]
                if rid.name == "issuer_and_serial_number":
                    r["issuer"] = rid.chosen["issuer"].human_friendly
                    r["serial"] = rid.chosen["serial_number"].native
                else:
                    r["ski"] = rid.chosen.native.hex()
                r["algo"] = ri.chosen["key_encryption_algorithm"]["algorithm"].native
                r["key"] = ri.chosen["encrypted_key"].native
            out["recipients"].append(r)
    return out


def verify_cms_signer(parsed, signer, certs):
    """(content_ok, signature_ok, cert) — integrity only; certificate trust is checked separately
    (verify_trust). The signer's certificate is matched exactly (issuer + serial, or subject key id)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    content = parsed["content"]
    cert = None
    for c in certs:
        if "serial" in signer:
            if c.serial_number == signer["serial"] and \
                    (not signer.get("issuer_der") or c.issuer.public_bytes() == signer["issuer_der"]):
                cert = c
                break
        elif signer.get("ski"):
            try:
                ski = c.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest.hex()
            except x509.ExtensionNotFound:
                ski = None
            if ski == signer["ski"]:
                cert = c
                break
    if cert is None and "serial" in signer:          # issuer encodings can differ: accept a unique serial match
        same = [c for c in certs if c.serial_number == signer["serial"]]
        cert = same[0] if len(same) == 1 else None
    digest_name = signer["digest"].replace("sha", "sha").lower()
    content_ok = None
    if content is not None and signer["message_digest"] is not None:
        algo = digest_name.replace("_", "")
        h = hashlib.new(algo, content, usedforsecurity=algo not in ("md5", "sha1")).digest()
        content_ok = h == signer["message_digest"]
    sig_ok = None
    si = signer["info"]
    if cert is not None and (si["signed_attrs"] or content is not None):
        if si["signed_attrs"]:
            attrs = si["signed_attrs"].dump()
            attrs = b"\x31" + attrs[1:]
        else:                     # no signed attributes (older signers): the content itself is signed
            attrs = content
            content_ok = True if content_ok is None else content_ok
        sig = si["signature"].native
        # SHA-1 only to *verify* signatures that were made with it (old e-documents); never used to create one
        hash_algo = {"sha1": hashes.SHA1(), "sha256": hashes.SHA256(), "sha384": hashes.SHA384(),  # nosec B303
                     "sha512": hashes.SHA512()}.get(digest_name.replace("_", ""), hashes.SHA256())
        key = cert.public_key()
        try:
            if isinstance(key, rsa.RSAPublicKey):
                if "pss" in signer["signature_algo"]:
                    key.verify(sig, attrs, padding.PSS(padding.MGF1(hash_algo), padding.PSS.AUTO), hash_algo)
                else:
                    key.verify(sig, attrs, padding.PKCS1v15(), hash_algo)
            elif isinstance(key, ec.EllipticCurvePublicKey):
                key.verify(sig, attrs, ec.ECDSA(hash_algo))
            else:
                key.verify(sig, attrs)
            sig_ok = True
        except Exception:  # noqa: BLE001
            sig_ok = False
    return content_ok, sig_ok, cert


def decrypt_cms(parsed, pfx_data, password):
    """Decrypt an enveloped CMS with a PKCS#12 key (RSA key transport)."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.serialization import pkcs12
    key, cert, _extra = pkcs12.load_key_and_certificates(pfx_data, password.encode("utf-8") if password else None)
    if key is None:
        raise ValueError(T("The .pfx file has no private key"))
    cek = None
    for r in parsed["recipients"]:
        if r["kind"] != "ktri":
            continue
        if "serial" in r and cert is not None and r["serial"] != cert.serial_number:
            continue
        try:
            if r["algo"] == "rsaes_oaep":
                from cryptography.hazmat.primitives import hashes
                # RSAES-OAEP as defined for CMS uses SHA-1 by default (RFC 3560); required to read such files
                cek = key.decrypt(r["key"], padding.OAEP(padding.MGF1(hashes.SHA1()), hashes.SHA1(), None))  # nosec
            else:
                cek = key.decrypt(r["key"], padding.PKCS1v15())
            break
        except Exception:  # noqa: BLE001
            continue
    if cek is None:
        raise ValueError(T("This certificate's key can't open the file (it was encrypted for someone else)"))
    algo = parsed["enc_params"]
    name = algo["algorithm"].native
    iv = algo["parameters"].native
    if "aes" in name:
        cipher = algorithms.AES(cek)
    elif "tripledes" in name or "des_ede3" in name:
        try:
            from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
        except ImportError:
            TripleDES = algorithms.TripleDES
        cipher = TripleDES(cek)
    else:
        raise ValueError(T("Unsupported content cipher {0}", name))
    dec = Cipher(cipher, modes.CBC(iv)).decryptor()
    plain = dec.update(parsed["encrypted"]) + dec.finalize()
    return _unpad(plain, 16 if "aes" in name else 8) or plain


# ─────────────────────────────── certificate trust (operating system) ───────────────────────────────
def verify_trust(cert):
    """Ask the operating system whether *cert* chains to a trusted root and is not revoked.
    Windows: certutil -verify (the CryptoAPI chain engine, which may download the CRL / OCSP data named in
    the certificate). macOS: security verify-cert. Returns (ok: True/False/None, summary, full output)."""
    from cryptography.hazmat.primitives.serialization import Encoding
    folder = safeio.temp_dir("trust")
    path = os.path.join(folder, "certificate.cer")
    try:
        with open(path, "wb") as fh:
            fh.write(cert.public_bytes(Encoding.DER))
        if winutil.IS_WIN:
            exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "certutil.exe")
            proc = winutil.run_hidden([exe, "-verify", path], timeout=180)
            raw = proc.stdout + proc.stderr
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("mbcs", "replace")
        elif winutil.IS_MAC:
            proc = winutil.run_hidden(["/usr/bin/security", "verify-cert", "-c", path], timeout=180)
            text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        else:
            return None, "The trust check uses Windows or macOS certificate stores.", ""
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    ok = proc.returncode == 0
    keys = ("FAILED", "ERROR", "CERT_E_", "CRYPT_E_", "UNTRUSTED", "REVOKED", "EXPIRED", "verification failed",
            "successful", "completed successfully", "revocation check passed")
    summary = next((ln for ln in reversed(lines) if any(k.lower() in ln.lower() for k in keys)),
                   lines[-1] if lines else "")
    return ok, summary, text
