"""Viewers for protected files: encrypted / encoded data (CryptoTab) and certificates, keys and
S/MIME .p7m signed or encrypted documents (CertTab)."""

import datetime
import os
import re
import tkinter as tk
from tkinter import filedialog, ttk

from . import audit, crypto, formats, policy, theme, winutil
from .base import BaseTab
from .theme import C, FONTS, ToolButton, px
from .i18n import T

LINKS = {"gpg": ("Get Gpg4win", "https://gpg4win.org/download.html"),
         "axcrypt": ("Get AxCrypt", "https://www.axcrypt.net/")}


def _ago(delta_days):
    return T("{0} day", delta_days) if delta_days == 1 else T("{0} days", delta_days)


class CryptoTab(BaseTab):
    kind = "crypto"

    def __init__(self, app, path=None, title=None):
        super().__init__(app, path, title)
        self.analysis = None
        self.result = None

    def badge(self):
        return theme.badge_image(formats.badge_label(self.path), theme.KIND_COLORS["secure"])

    def type_label(self):
        return T(self.analysis.title) if self.analysis else T("Protected file")

    def load(self):
        self.bar.button(T("View as Hex"), "list", lambda: self.app.reopen_as(self, "hex"))
        self.bar.button(T("Show in Folder"), "reveal", lambda: self.app.reveal(self))
        self.bar.button(T("Open with Default App"), "external", lambda: self.app.open_external(self.path), side="right")
        self.run_async(lambda: crypto.analyse(self.path), self._show,
                       error=lambda exc: self.app.replace_with(self, "info", error=str(exc)),
                       text=T("Analysing…"))

    def _show(self, analysis):
        self.analysis = analysis
        if analysis.kind == "cms":
            self.app.replace_with(self, "cert")
            return
        outer = tk.Frame(self.body, bg=C["bg"])
        outer.pack(fill="both", expand=True)
        card = tk.Frame(outer, bg=C["bg"])
        card.place(relx=0.5, rely=0.42, anchor="center", relwidth=0.8)
        color = theme.KIND_COLORS["secure"]
        glyph = "" if theme.HAS_ICONS else "\U0001F512"
        tk.Label(card, image=theme.tile_image(color, 72, alpha=40), text=glyph, compound="center",
                 font=FONTS["icon_xl"] if theme.HAS_ICONS else FONTS["h1"], fg=color, bg=C["bg"]).pack()
        tk.Label(card, text=T(analysis.title), font=FONTS["h2"], bg=C["bg"], fg=C["fg_bright"]).pack(pady=(px(12), px(2)))
        tk.Label(card, text=self.title, font=FONTS["ui"], bg=C["bg"], fg=C["fg_dim"]).pack()
        grid = tk.Frame(card, bg=C["bg"])
        grid.pack(pady=(px(14), px(4)))
        for i, (k, v) in enumerate(analysis.facts):
            tk.Label(grid, text=T(k), font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"], anchor="e").grid(
                row=i, column=0, sticky="e", padx=(0, px(12)), pady=px(2))
            tk.Label(grid, text=v, font=FONTS["small"], bg=C["bg"], fg=C["fg"], anchor="w").grid(
                row=i, column=1, sticky="w", pady=px(2))
        if analysis.note:
            note = tk.Label(card, text=T(analysis.note), font=FONTS["ui"], bg=C["bg"], fg=C["fg_dim"], justify="center")
            note.pack(pady=(px(10), px(4)), fill="x")
            note.bind("<Configure>", lambda e: note.configure(wraplength=max(200, e.width - px(20))))
        self.status_lbl = tk.Label(card, text="", font=FONTS["small"], bg=C["bg"], fg=C["fg_muted"])
        self.status_lbl.pack(pady=(px(4), 0))
        row = tk.Frame(card, bg=C["bg"])
        row.pack(pady=px(16))
        self._actions(row, analysis)
        self.app.update_status()

    def _btn(self, row, text, icon_name, cmd, primary=False):
        b = ToolButton(row, text, icon_name, cmd, variant="primary" if primary else "ghost",
                       bg=None if primary else C["bg"], hover=None if primary else C["hover"], pad=(14, 6))
        b.pack(side="left", padx=px(4))
        return b

    def _actions(self, row, a):
        first = True
        no_decrypt = policy.get_bool("DisableDecryption")
        for action in a.actions:
            if no_decrypt and action in ("decrypt-password", "gpg", "pgp-extract"):
                if first:
                    tk.Label(row, text=T("Decryption is turned off by your administrator."), font=FONTS["small"],
                             bg=row.cget("bg"), fg=C["warning"]).pack(side="left", padx=px(4))
                    first = False
                continue
            if action == "decrypt-password":
                self._btn(row, T("Decrypt with password…"), "key", self.decrypt_password, first)
            elif action == "gpg":
                if winutil.find_gpg():
                    self._btn(row, T("Decrypt with GnuPG"), "check", self.decrypt_gpg, first)
                else:
                    label, url = LINKS["gpg"]
                    self._btn(row, T(label), "download", lambda u=url: winutil.open_url(u), first)
            elif action == "pgp-extract":
                self._btn(row, T("Extract content"), "open", self.extract_pgp, first)
            elif action == "gpg-show":
                self._btn(row, T("Show key details"), "info", self.show_keys, first)
            elif action == "decode":
                self._btn(row, T("Decode and open"), "open", self.decode, first)
            elif action == "open-as":
                self._btn(row, T("Open"), "open", lambda: self.app.replace_with(self, formats.sniff(self.path)), first)
            elif action == "open-external":
                self._btn(row, T("Open with Default App"), "external", lambda: self.app.open_external(self.path), first)
            elif action.startswith("link:"):
                self._btn(row, T("Download program"), "download", lambda u=action[5:]: winutil.open_url(u), first)
            elif action == "hex":
                self._btn(row, T("View as Hex"), "list", lambda: self.app.reopen_as(self, "hex"), first)
            else:
                continue
            first = False
        self.save_btn = self._btn(row, T("Save result…"), "save", self.save_result)
        self.save_btn.pack_forget()

    # ── actions ──
    def _deliver(self, result):
        name, data = result
        self.result = (name, data)
        audit.event("decrypt", path=self.path, method=getattr(self, "_method", "decode"), result="ok", output=name)
        path = crypto.save_temp(name, data)
        self.status_lbl.configure(text=T("✓  Opened {0} ({1}) in a new tab", name, formats.human_size(len(data))),
                                  fg=C["success"])
        self.save_btn.pack(side="left", padx=px(4))
        self.app.open_paths([path])

    def _fail(self, exc):
        audit.event("decrypt", warning=True, path=self.path, method=getattr(self, "_method", "decode"),
                    result="failed", reason=str(exc)[:200])
        self.status_lbl.configure(text=str(exc), fg=C["danger"])

    def decrypt_password(self):
        pw = theme.ask_string(self.frame, T("Decrypt"), T("Password for {0}:", self.title), secret=True, ok_text=T("Decrypt"))
        if pw is None:
            return
        a = self.analysis
        self._method = f"password ({a.kind})"
        self.run_async(lambda: crypto.decrypt_with_password(a, self.path, pw), self._deliver, self._fail,
                       text=T("Decrypting…"))

    def decrypt_gpg(self, passphrase=None):
        self._method = "gnupg"

        def failed(exc):
            if isinstance(exc, crypto.PassphraseNeeded):
                pw = theme.ask_string(self.frame, T("Decrypt"),
                                      T("Passphrase for {0}\n(the file's password, or the one of your private key):",
                                        self.title), secret=True, ok_text=T("Decrypt"))
                if pw:
                    self.decrypt_gpg(pw)
                return
            self._fail(exc)
        self.run_async(lambda: crypto.decrypt_gpg(self.path, passphrase), self._deliver, failed,
                       text=T("Decrypting…"))

    def extract_pgp(self):
        self._method = "pgp-literal"
        payload = self.analysis.payload
        self.run_async(lambda: crypto.extract_pgp_literal(payload), self._deliver, self._fail, text=T("Extracting…"))

    def decode(self):
        self._method = "decode"
        self.run_async(lambda: crypto.decode(self.path), self._deliver, self._fail, text=T("Decoding…"))

    def show_keys(self):
        def done(text):
            tab = self.app.create_tab(None, "text", title="key-details.txt", content=text)
            if tab:
                self.app.refresh_sidebar()
                self.app.select_tab(tab)
        self.run_async(lambda: crypto.gpg_show_keys(self.path), done, self._fail, text=T("Reading key…"))

    def save_result(self):
        if not self.result:
            return
        name, data = self.result
        path = filedialog.asksaveasfilename(parent=self.app.root, title=T("Save decrypted file"), initialfile=name,
                                            initialdir=os.path.dirname(self.path))
        if path:
            with open(path, "wb") as fh:
                fh.write(data)
            self.toast(T("Saved {0}", os.path.basename(path)))

    def status(self):
        return [self.type_label(), formats.human_size(os.path.getsize(self.path))]


# ─────────────────────────────── certificates & S/MIME ───────────────────────────────
def _name(n):
    try:
        attrs = {a.oid._name: a.value for a in n}
    except Exception:  # noqa: BLE001
        return str(n)
    return attrs


def _cn(cert_name):
    attrs = _name(cert_name)
    if isinstance(attrs, dict):
        return attrs.get("commonName") or attrs.get("organizationName") or ", ".join(attrs.values())
    return attrs


def describe_cert(cert):
    """List of (label, value) lines for an x509 certificate (cryptography)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
    rows = []

    def name_rows(label, n):
        attrs = _name(n)
        if isinstance(attrs, dict):
            order = ["commonName", "organizationName", "organizationalUnitName", "localityName",
                     "stateOrProvinceName", "countryName", "emailAddress", "serialNumber", "givenName", "surname"]
            pretty = {"commonName": "Name (CN)", "organizationName": "Organisation", "organizationalUnitName": "Unit",
                      "localityName": "City", "stateOrProvinceName": "Region", "countryName": "Country",
                      "emailAddress": "E-mail", "serialNumber": "Personal / ID number", "givenName": "Given name",
                      "surname": "Surname"}
            rows.append((label, None))
            for k in order + [k for k in attrs if k not in order]:
                if k in attrs:
                    rows.append(("  " + T(pretty.get(k, k)), str(attrs[k])))
        else:
            rows.append((label, str(attrs)))

    name_rows("Issued to", cert.subject)
    name_rows("Issued by", cert.issuer)
    rows.append(("Details", None))
    try:
        start, end = cert.not_valid_before_utc, cert.not_valid_after_utc
    except AttributeError:
        start = cert.not_valid_before.replace(tzinfo=datetime.timezone.utc)
        end = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    if now < start:
        state = T("NOT VALID YET (starts in {0})", _ago((start - now).days))
    elif now > end:
        state = T("EXPIRED {0} ago", _ago((now - end).days))
    else:
        state = T("Valid — {0} left", _ago((end - now).days))
    rows.append(("  Status", state))
    rows.append(("  Valid from", start.strftime("%Y-%m-%d %H:%M UTC")))
    rows.append(("  Valid until", end.strftime("%Y-%m-%d %H:%M UTC")))
    rows.append(("  Serial number", format(cert.serial_number, "X")))
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        ktxt = T("RSA {0} bit", key.key_size)
    elif isinstance(key, ec.EllipticCurvePublicKey):
        ktxt = T("EC {0} ({1} bit)", key.curve.name, key.key_size)
    elif isinstance(key, dsa.DSAPublicKey):
        ktxt = T("DSA {0} bit", key.key_size)
    elif isinstance(key, ed25519.Ed25519PublicKey):
        ktxt = "Ed25519"
    elif isinstance(key, ed448.Ed448PublicKey):
        ktxt = "Ed448"
    else:
        ktxt = key.__class__.__name__
    rows.append(("  Public key", ktxt))
    try:
        rows.append(("  Signature", T("{0} with {1}", cert.signature_hash_algorithm.name.upper(),
                                      cert.signature_algorithm_oid._name)))
    except Exception:  # noqa: BLE001
        pass
    rows.append(("  Self-signed", T("yes") if cert.subject == cert.issuer else T("no")))
    # SHA-1 thumbprint = the identifier Windows shows for certificates (not a security decision)
    rows.append(("  SHA-1 thumbprint", cert.fingerprint(hashes.SHA1()).hex().upper()))  # nosec B303
    rows.append(("  SHA-256", cert.fingerprint(hashes.SHA256()).hex().upper()))
    ext_rows = []
    for ext in cert.extensions:
        v = ext.value
        try:
            if isinstance(v, x509.SubjectAlternativeName):
                items = [f"{g.__class__.__name__.replace('Name', '').replace('RFC822', 'E-mail')}: {g.value}" for g in v]
                ext_rows.append(("  Alternative names", "\n".join(items)))
            elif isinstance(v, x509.KeyUsage):
                names = [n for n in ("digital_signature", "content_commitment", "key_encipherment",
                                     "data_encipherment", "key_agreement", "key_cert_sign", "crl_sign")
                         if getattr(v, n)]
                ext_rows.append(("  Key usage", ", ".join(n.replace("_", " ") for n in names)))
            elif isinstance(v, x509.ExtendedKeyUsage):
                ext_rows.append(("  Purposes", ", ".join(u._name for u in v)))
            elif isinstance(v, x509.BasicConstraints):
                ext_rows.append(("  Certificate authority", T("yes") if v.ca else T("no")))
            elif isinstance(v, x509.CRLDistributionPoints):
                urls = [n.value for dp in v for n in (dp.full_name or [])]
                ext_rows.append(("  CRL", "\n".join(urls)))
            elif isinstance(v, x509.AuthorityInformationAccess):
                urls = [f"{d.access_method._name}: {d.access_location.value}" for d in v]
                ext_rows.append(("  Authority info", "\n".join(urls)))
            elif isinstance(v, x509.CertificatePolicies):
                ext_rows.append(("  Policies", ", ".join(p.policy_identifier.dotted_string for p in v)))
        except Exception:  # noqa: BLE001
            continue
    if ext_rows:
        rows.append(("Extensions", None))
        rows += ext_rows
    return rows


class CertTab(BaseTab):
    kind = "cert"

    def __init__(self, app, path=None, title=None):
        super().__init__(app, path, title)
        self.items = []        # [(label, kind, obj)]
        self.cms = None
        self.cms_content = None
        self.has_key = False

    def badge(self):
        return theme.badge_image(formats.badge_label(self.path), theme.KIND_COLORS["secure"])

    def type_label(self):
        if self.cms:
            return T("Signed document (S/MIME)") if self.cms["type"] == "signed" else T("Encrypted document (S/MIME)")
        return formats.label_for(self.path) or T("Certificate")

    # ── loading ──
    def load(self):
        raw = open(self.path, "rb").read()
        ext = formats.ext_of(self.path)
        if ext in (".pfx", ".p12"):
            self._load_pfx(raw)
        else:
            self._load_any(raw)
        if not self.items and not self.cms:
            raise ValueError(T("No certificate, key or signed data found in this file"))
        self._build()

    def _load_pfx(self, raw):
        from cryptography.hazmat.primitives.serialization import pkcs12
        password = None
        for attempt in range(4):
            try:
                key, cert, extra = pkcs12.load_key_and_certificates(raw, password)
                break
            except ValueError:
                if attempt == 0:
                    password = b""
                    continue
                pw = theme.ask_string(self.app.root, T("Certificate password"),
                                      T("{0} is protected. Enter its password:", self.title) +
                                      ("" if attempt == 1 else "\n\n" + T("That password was not correct.")), secret=True)
                if pw is None:
                    raise ValueError(T("Password needed to open this certificate store"))
                password = pw.encode("utf-8")
        else:
            raise ValueError(T("Wrong password"))
        if cert is not None:
            self.items.append((_cn(cert.subject), "cert", cert))
        for c in extra or []:
            self.items.append((_cn(c.subject), "cert", c))
        if key is not None:
            self.has_key = True
            self.items.append((T("Private key"), "key", key))

    def _load_any(self, raw):
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import load_pem_private_key, pkcs7
        text = raw.decode("latin-1") if b"-----BEGIN" in raw[:200000] else None
        if text:
            for kind, body in re.findall(r"-----BEGIN ([A-Z0-9 ]+)-----(.*?)-----END \1-----", text, re.S):
                block = f"-----BEGIN {kind}-----{body}-----END {kind}-----".encode()
                try:
                    if kind in ("CERTIFICATE", "TRUSTED CERTIFICATE", "X509 CERTIFICATE"):
                        c = x509.load_pem_x509_certificate(block.replace(b"TRUSTED ", b"").replace(b"X509 ", b""))
                        self.items.append((_cn(c.subject), "cert", c))
                    elif "CERTIFICATE REQUEST" in kind:
                        r = x509.load_pem_x509_csr(block.replace(b"NEW ", b""))
                        self.items.append((T("Request: {0}", _cn(r.subject)), "csr", r))
                    elif "PRIVATE KEY" in kind:
                        if "ENCRYPTED" in kind or "Proc-Type: 4,ENCRYPTED" in body:
                            self.items.append((T("Private key (password protected)"), "enckey", None))
                        else:
                            self.items.append((T("Private key"), "key", load_pem_private_key(block, None)))
                    elif kind in ("PKCS7", "CMS"):
                        for c in pkcs7.load_pem_pkcs7_certificates(block):
                            self.items.append((_cn(c.subject), "cert", c))
                except Exception:  # noqa: BLE001
                    continue
            if self.items:
                return
        for loader in (x509.load_der_x509_certificate,):
            try:
                c = loader(raw)
                self.items.append((_cn(c.subject), "cert", c))
                return
            except Exception:  # noqa: BLE001
                pass
        try:
            r = x509.load_der_x509_csr(raw)
            self.items.append((T("Request: {0}", _cn(r.subject)), "csr", r))
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            parsed = crypto.parse_cms(raw)
        except Exception:  # noqa: BLE001
            parsed = None
        if parsed and parsed["type"] in ("signed", "enveloped", "authenveloped"):
            self.cms = parsed
            certs = []
            for der in parsed["certs"]:
                try:
                    c = x509.load_der_x509_certificate(der)
                    certs.append(c)
                    self.items.append((_cn(c.subject), "cert", c))
                except Exception:  # noqa: BLE001
                    continue
            self.cms_certs = certs
            return
        try:
            for c in pkcs7.load_der_pkcs7_certificates(raw):
                self.items.append((_cn(c.subject), "cert", c))
        except Exception:  # noqa: BLE001
            pass

    # ── UI ──
    def _build(self):
        bar = self.bar
        bar.button(T("Export Certificate…"), "export", self.export_cert, T("Save the selected certificate (.cer / .pem)"))
        bar.button(T("Copy Thumbprint"), "copy", self.copy_thumbprint, T("Copy the SHA-1 thumbprint"))
        bar.button(T("Copy Details"), "copy", self.copy_details)
        if theme.IS_WIN or theme.IS_MAC:
            bar.button(T("Check Trust"), "check", lambda: self.check_trust(None),
                       T("Ask Windows / macOS whether the selected certificate is valid and trusted"))
        if (theme.IS_WIN or theme.IS_MAC) and \
                formats.ext_of(self.path) in (".cer", ".crt", ".der", ".pfx", ".p12", ".p7b", ".p7c", ".pem"):
            bar.button(T("Add to Keychain…") if theme.IS_MAC else T("Install in Windows…"), "external",
                       lambda: self.app.open_external(self.path), side="right")
        if self.cms:
            self._cms_banner()
        main = tk.Frame(self.body, bg=C["bg"])
        main.pack(fill="both", expand=True)
        left = tk.Frame(main, bg=C["sidebar"], width=px(270))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text=T("CONTENTS"), font=FONTS["caption"], bg=C["sidebar"], fg=C["fg_muted"], anchor="w").pack(
            fill="x", padx=px(14), pady=(px(12), px(6)))
        self.tree = ttk.Treeview(left, style="Side.Treeview", show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True)
        for i, (label, kind, _obj) in enumerate(self.items):
            icon = {"cert": "CERT", "key": "KEY", "enckey": "KEY", "csr": "CSR"}.get(kind, "ITEM")
            self.tree.insert("", "end", iid=str(i), text=f" {label}",
                             image=theme.badge_image(icon, theme.KIND_COLORS["secure"], width=38))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_item())
        tk.Frame(main, bg=C["border"], width=1).pack(side="left", fill="y")
        self.text = tk.Text(main, bg=C["bg"], fg=C["fg"], font=FONTS["ui"], relief="flat", bd=0, wrap="word",
                            padx=px(24), pady=px(16), highlightthickness=0, cursor="arrow",
                            selectbackground=C["selection"], spacing1=px(2), spacing3=px(2))
        sb = ttk.Scrollbar(main, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("h", font=FONTS["h3"], foreground=C["fg_bright"], spacing1=px(12), spacing3=px(4))
        self.text.tag_configure("k", foreground=C["fg_muted"], font=FONTS["small"])
        self.text.tag_configure("v", foreground=C["fg"])
        self.text.tag_configure("ok", foreground=C["success"])
        self.text.tag_configure("bad", foreground=C["danger"])
        self.text.tag_configure("title", font=FONTS["h2"], foreground=C["fg_bright"], spacing3=px(6))
        self.text.configure(tabs=(px(200),))
        if self.items:
            self.tree.selection_set("0")
        self._show_item()

    def _cms_banner(self):
        c = self.cms
        box = tk.Frame(self.body, bg=C["panel"], padx=px(16), pady=px(10))
        box.pack(side="top", fill="x")
        if c["type"] == "signed":
            content = c["content"]
            certs = getattr(self, "cms_certs", [])
            lines = []
            state_ok = True
            for signer in c["signers"]:
                try:
                    content_ok, sig_ok, cert = crypto.verify_cms_signer(c, signer, certs)
                except Exception as exc:  # noqa: BLE001
                    content_ok, sig_ok, cert = None, False, None
                    winutil.log_error(f"CMS verify failed: {exc!r}")
                who = _cn(cert.subject) if cert is not None else signer.get("issuer", T("unknown signer"))
                when = signer["time"].strftime("%Y-%m-%d %H:%M") if signer.get("time") else T("time not recorded")
                good = sig_ok and content_ok is not False
                state_ok = state_ok and good
                mark = T("✓ Signature intact") if good else T("✗ Signature does NOT match the content")
                lines.append(f"{mark}  ·  " + T("signed by {0}", who) + f"  ·  {when}")
                audit.event("signature", warning=not good, path=self.path, result="intact" if good else "broken",
                            signer=who, signed=when)
                if cert is not None:
                    self.signer_cert = cert
            name = crypto.output_name(self.path, content or b"")
            self.cms_content = (name, content)
            size = formats.human_size(len(content)) if content else T("detached (content is in a separate file)")
            tk.Label(box, text=T("Signed document: {0}  ({1})", name, size), font=FONTS["ui_bold"], bg=C["panel"],
                     fg=C["fg_bright"], anchor="w").pack(fill="x")
            for line in lines:
                tk.Label(box, text=line, font=FONTS["small"], bg=C["panel"], anchor="w",
                         fg=C["success"] if state_ok else C["danger"]).pack(fill="x")
            tk.Label(box, text=T("\u201cIntact\u201d proves the document was not changed after signing. Use Check "
                               "signer trust to ask Windows / macOS whether the signer's certificate is valid and "
                               "trusted."), font=FONTS["tiny"], bg=C["panel"], fg=C["fg_muted"], anchor="w",
                     justify="left").pack(fill="x")
            row = tk.Frame(box, bg=C["panel"])
            row.pack(fill="x", pady=(px(8), 0))
            if getattr(self, "signer_cert", None) is not None and (theme.IS_WIN or theme.IS_MAC):
                ToolButton(row, T("Check signer trust"), "check", lambda: self.check_trust(self.signer_cert),
                           bg=C["panel"], hover=C["hover_strong"], pad=(12, 5)).pack(side="right")
            if content:
                ToolButton(row, T("Open document"), "open", self.open_content, variant="primary", pad=(12, 5)).pack(
                    side="left")
                ToolButton(row, T("Save document…"), "save", self.save_content, bg=C["panel"],
                           hover=C["hover_strong"], pad=(12, 5)).pack(side="left", padx=px(6))
        else:
            tk.Label(box, text=T("Encrypted document ({0})", c.get('cipher', '?')), font=FONTS["ui_bold"], bg=C["panel"],
                     fg=C["fg_bright"], anchor="w").pack(fill="x")
            for r in c["recipients"]:
                who = r.get("issuer", "") + ("  ·  " + T("serial {0}", format(r['serial'], 'X')) if "serial" in r else
                                            "  " + T("key id {0}", r.get('ski', '?')))
                tk.Label(box, text=T("For: {0}", who), font=FONTS["small"], bg=C["panel"], fg=C["fg_dim"],
                         anchor="w").pack(fill="x")
            row = tk.Frame(box, bg=C["panel"])
            row.pack(fill="x", pady=(px(8), 0))
            if policy.get_bool("DisableDecryption"):
                tk.Label(row, text=T("Decryption is turned off by your administrator."), font=FONTS["small"],
                         bg=C["panel"], fg=C["warning"]).pack(side="left")
            else:
                ToolButton(row, T("Decrypt with my certificate (.pfx)…"), "check", self.decrypt_cms, variant="primary",
                           pad=(12, 5)).pack(side="left")
            self.cms_status = tk.Label(row, text="", font=FONTS["small"], bg=C["panel"], fg=C["fg_muted"])
            self.cms_status.pack(side="left", padx=px(10))

    def _show_item(self):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        sel = self.tree.selection()
        if not sel:
            t.insert("end", T("Nothing to show"), "k")
            t.configure(state="disabled")
            return
        label, kind, obj = self.items[int(sel[0])]
        t.insert("end", f"{label}\n", "title")
        if kind == "cert":
            for k, v in describe_cert(obj):
                if v is None:
                    t.insert("end", f"{T(k)}\n", "h")
                else:
                    tag = "v"
                    if k.strip() == "Status":
                        tag = "ok" if v.startswith(("Valid", T("Valid"))) else "bad"
                    vv = v.replace("\n", "\n\t")
                    t.insert("end", f"{T(k.strip())}\t", "k")
                    t.insert("end", f"{vv}\n", tag)
        elif kind == "key":
            from cryptography.hazmat.primitives.asymmetric import ec, rsa
            desc = T("RSA {0} bit", obj.key_size) if isinstance(obj, rsa.RSAPrivateKey) else \
                f"EC {obj.curve.name}" if isinstance(obj, ec.EllipticCurvePrivateKey) else obj.__class__.__name__
            t.insert("end", T("Type") + "\t", "k")
            t.insert("end", desc + "\n", "v")
            t.insert("end", "\n" + T("The private key itself is never displayed."), "k")
        elif kind == "enckey":
            t.insert("end", T("This private key is protected with a password."), "v")
        elif kind == "csr":
            t.insert("end", T("Subject") + "\t", "k")
            t.insert("end", obj.subject.rfc4514_string() + "\n", "v")
            t.insert("end", T("Signature") + "\t", "k")
            t.insert("end", (T("valid") if obj.is_signature_valid else T("INVALID")) + "\n",
                     "ok" if obj.is_signature_valid else "bad")
            for ext in obj.extensions:
                t.insert("end", f"{ext.oid._name}\t", "k")
                t.insert("end", f"{ext.value}\n", "v")
        t.configure(state="disabled")

    def _selected_cert(self):
        sel = self.tree.selection()
        if sel:
            _l, kind, obj = self.items[int(sel[0])]
            if kind == "cert":
                return obj
        return next((o for _l, k, o in self.items if k == "cert"), None)

    def export_cert(self):
        from cryptography.hazmat.primitives.serialization import Encoding
        cert = self._selected_cert()
        if cert is None:
            self.toast(T("No certificate selected"), "info")
            return
        name = re.sub(r"[^\w.-]+", "_", str(_cn(cert.subject)))[:60] or "certificate"
        path = filedialog.asksaveasfilename(parent=self.app.root, title=T("Export certificate"), initialfile=name + ".cer",
                                            filetypes=[(T("DER certificate"), "*.cer"), (T("PEM certificate"), "*.pem")])
        if not path:
            return
        data = cert.public_bytes(Encoding.PEM if path.lower().endswith(".pem") else Encoding.DER)
        with open(path, "wb") as fh:
            fh.write(data)
        self.toast(T("Saved {0}", os.path.basename(path)))

    def copy_thumbprint(self):
        cert = self._selected_cert()
        if cert is not None:
            from cryptography.hazmat.primitives import hashes
            # SHA-1 thumbprint = the identifier Windows uses for certificates (not a security decision)
            self.app.set_clipboard(cert.fingerprint(hashes.SHA1()).hex().upper())  # nosec B303
            self.toast(T("Thumbprint copied"))

    def copy_details(self):
        self.app.set_clipboard(self.text.get("1.0", "end-1c"))
        self.toast(T("Details copied"))

    def open_content(self):
        if self.cms_content and self.cms_content[1]:
            name, data = self.cms_content
            self.app.open_paths([crypto.save_temp(name, data)])

    def save_content(self):
        if not self.cms_content or not self.cms_content[1]:
            return
        name, data = self.cms_content
        path = filedialog.asksaveasfilename(parent=self.app.root, title=T("Save document"), initialfile=name,
                                            initialdir=os.path.dirname(self.path))
        if path:
            with open(path, "wb") as fh:
                fh.write(data)
            self.toast(T("Saved {0}", os.path.basename(path)))

    def decrypt_cms(self):
        pfx = filedialog.askopenfilename(parent=self.app.root, title=T("Choose your certificate with private key"),
                                         filetypes=[(T("Personal certificate"), "*.pfx *.p12"), (T("All files"), "*")])
        if not pfx:
            return
        pw = theme.ask_string(self.app.root, T("Certificate password"), T("Password for {0}:", os.path.basename(pfx)),
                              secret=True)
        if pw is None:
            return
        data = open(pfx, "rb").read()
        parsed = self.cms

        def done(plain):
            name = crypto.output_name(self.path, plain)
            audit.event("decrypt", path=self.path, method="cms-certificate", result="ok", output=name)
            self.cms_status.configure(text=T("✓ Decrypted — {0}", name), fg=C["success"])
            self.app.open_paths([crypto.save_temp(name, plain)])

        def failed(exc):
            audit.event("decrypt", warning=True, path=self.path, method="cms-certificate", result="failed",
                        reason=str(exc)[:200])
            self.cms_status.configure(text=str(exc), fg=C["danger"])

        self.run_async(lambda: crypto.decrypt_cms(parsed, data, pw), done, failed, text=T("Decrypting…"))

    def check_trust(self, cert=None):
        cert = cert or self._selected_cert()
        if cert is None:
            self.toast(T("Select a certificate first"), "info")
            return
        who = _cn(cert.subject)

        def done(result):
            ok, summary, text = result
            audit.event("signature", warning=ok is not True, path=self.path, check="trust", signer=who,
                        result="trusted" if ok else "not trusted" if ok is False else "unknown")
            title = T("Trust check - {0}.txt", who)
            head = (T("TRUSTED: the operating system accepts this certificate.") if ok else
                    T("NOT TRUSTED / NOT VALID: see the details below.") if ok is False else summary)
            tab = self.app.create_tab(None, "text", title=title, content=f"{head}\n{summary}\n\n{text}")
            if tab:
                self.app.refresh_sidebar()
                self.app.select_tab(tab)
            self.toast(f"{who}: " + (T("trusted") if ok else T("not trusted")), "success" if ok else "warning", 4000)

        self.run_async(lambda: crypto.verify_trust(cert), done, text=T("Checking the certificate chain…"))

    def status(self):
        n = sum(1 for _l, k, _o in self.items if k == "cert")
        segs = [T("{0} certificate", n) if n == 1 else T("{0} certificates", n)]
        if self.has_key:
            segs.append(T("with private key"))
        return segs + [self.type_label()]

