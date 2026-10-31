"""Signature panel: every digital signature of a PDF as a card (status, checks, certificate), like the
signature panel of Acrobat Reader. Opened from the signature banner (Details)."""

import os
import tkinter as tk
from tkinter import ttk

from . import pdfsig, theme, winutil
from .i18n import T
from .theme import C, FONTS, ToolButton, px

MARKS = {"ok": "✓", "warning": "!", "bad": "✕", "none": "–"}


def _level_color(level):
    return {"ok": C["success"], "warning": C["warning"], "bad": C["danger"]}.get(level, C["fg_muted"])


def _fingerprint(cert):
    from cryptography.hazmat.primitives import hashes
    raw = cert.fingerprint(hashes.SHA256()).hex().upper()
    return " ".join(raw[i:i + 2] for i in range(0, len(raw), 2))


def _key_text(cert):
    from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return f"RSA {key.key_size}"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return f"ECDSA {key.curve.name}"
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "Ed25519"
    if isinstance(key, dsa.DSAPublicKey):
        return f"DSA {key.key_size}"
    return key.__class__.__name__


def _date(value):
    return f"{value:%Y-%m-%d %H:%M}" if value else None


def overall(sigs):
    levels = [pdfsig.summary(s)[0] for s in sigs]
    if not sigs:
        return "none", T("This document has no digital signatures.")
    bad = levels.count("bad")
    warn = levels.count("warning")
    if bad:
        return "bad", T("{0} of {1} signatures have problems.", bad, len(sigs))
    if warn:
        return "warning", T("{0} of {1} signatures need attention.", warn, len(sigs))
    if len(sigs) == 1:
        return "ok", T("The signature is valid.")
    return "ok", T("All {0} signatures are valid.", len(sigs))


class SignaturePanel(tk.Toplevel):
    def __init__(self, tab):
        top = tab.app.root
        super().__init__(top)
        self.withdraw()
        self.tab = tab
        self.sigs = list(getattr(tab, "signatures", []) or [])
        self.trust = {}
        self.expanded = set()
        self.title(T("Digital signatures"))
        self.configure(bg=C["bg"])
        self.transient(top)
        self.minsize(px(560), px(420))
        self._build()
        self.render()
        w, h = px(720), min(px(760), max(px(480), top.winfo_height() - px(80)))
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 4)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        winutil.apply_dark_titlebar(self, C["bg"], C["border"])
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.focus_set()

    # ── frame ──
    def _build(self):
        self.head = tk.Frame(self, bg=C["panel"], padx=px(22), pady=px(16))
        self.head.pack(side="top", fill="x")
        tk.Frame(self, bg=C["border"], height=1).pack(side="top", fill="x")
        foot = tk.Frame(self, bg=C["chrome"], padx=px(14), pady=px(10))
        foot.pack(side="bottom", fill="x")
        tk.Frame(self, bg=C["border"], height=1).pack(side="bottom", fill="x")
        ToolButton(foot, T("Close"), None, self.close, bg=C["chrome"], pad=(14, 5)).pack(side="right")
        ToolButton(foot, T("Copy report"), "copy", self.copy_report, bg=C["chrome"], pad=(12, 5)).pack(
            side="right", padx=(0, px(6)))
        if any(s.get("cert") is not None for s in self.sigs):
            self.trust_btn = ToolButton(foot, T("Check signer trust"), "check", self.check_trust, variant="primary",
                                        pad=(14, 5))
            self.trust_btn.pack(side="left")
            tk.Label(foot, text=T("Asks Windows / macOS whether the certificates come from a trusted authority "
                                  "and are not revoked."), bg=C["chrome"], fg=C["fg_muted"], font=FONTS["tiny"],
                     anchor="w", justify="left", wraplength=px(300)).pack(side="left", padx=px(10))

        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=C["bg"], padx=px(18), pady=px(14))
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind_all_wheel(self)

    def bind_all_wheel(self, widget):
        def wheel(event):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(theme.wheel_units(event, 3), "units")
        widget.bind("<MouseWheel>", wheel, add="+")
        widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"), add="+")
        widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"), add="+")

    def close(self):
        if getattr(self.tab, "sig_panel", None) is self:
            self.tab.sig_panel = None
        self.destroy()

    # ── content ──
    def render(self):
        for w in self.head.winfo_children():
            w.destroy()
        for w in self.inner.winfo_children():
            w.destroy()
        level, text = overall(self.sigs)
        row = tk.Frame(self.head, bg=C["panel"])
        row.pack(fill="x")
        self._badge(row, level, 40, C["panel"]).pack(side="left", padx=(0, px(14)))
        txt = tk.Frame(row, bg=C["panel"])
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=T("Digital signatures"), font=FONTS["h2"], bg=C["panel"], fg=C["fg_bright"],
                 anchor="w").pack(fill="x")
        tk.Label(txt, text=text, font=FONTS["ui_bold"], bg=C["panel"], fg=_level_color(level),
                 anchor="w").pack(fill="x", pady=(px(2), 0))
        tk.Label(txt, text=os.path.basename(self.tab.path or self.tab.title), font=FONTS["small"], bg=C["panel"],
                 fg=C["fg_muted"], anchor="w").pack(fill="x")
        for n, sig in enumerate(self.sigs, 1):
            self._card(n, sig)
        tk.Label(self.inner, text=T("Integrity and certificate dates are checked here, offline. Whether the "
                                    "issuing authority is trusted is a separate check by the operating system."),
                 bg=C["bg"], fg=C["fg_muted"], font=FONTS["tiny"], anchor="w", justify="left",
                 wraplength=px(620)).pack(fill="x", pady=(px(4), 0))
        for w in self._all(self.inner):
            self.bind_all_wheel(w)

    def _all(self, widget):
        out = [widget]
        for child in widget.winfo_children():
            out.extend(self._all(child))
        return out

    def _badge(self, parent, level, size, bg):
        s = px(size)
        c = tk.Canvas(parent, width=s, height=s, bg=bg, highlightthickness=0, bd=0)
        col = _level_color(level)
        c.create_oval(1, 1, s - 1, s - 1, fill=theme.mix(col, bg, 0.82), outline=col, width=max(1, px(1.5)))
        c.create_text(s / 2, s / 2 + 1, text=MARKS[level], fill=col,
                      font=(FONTS["ui_bold"][0], max(8, int(size * 0.42)), "bold"))
        return c

    def _card(self, n, sig):
        level, text = pdfsig.summary(sig)
        col = _level_color(level)
        card = tk.Frame(self.inner, bg=C["panel"], highlightthickness=1,
                        highlightbackground=col if level != "ok" else C["border_strong"])
        card.pack(fill="x", pady=(0, px(12)))
        tk.Frame(card, bg=col, width=px(4)).pack(side="left", fill="y")
        body = tk.Frame(card, bg=C["panel"], padx=px(16), pady=px(14))
        body.pack(side="left", fill="both", expand=True)

        top = tk.Frame(body, bg=C["panel"])
        top.pack(fill="x")
        self._badge(top, level, 30, C["panel"]).pack(side="left", padx=(0, px(12)), anchor="n")
        title = tk.Frame(top, bg=C["panel"])
        title.pack(side="left", fill="x", expand=True)
        line = tk.Frame(title, bg=C["panel"])
        line.pack(fill="x")
        who = sig.get("signer") or sig.get("name") or T("unknown signer")
        tk.Label(line, text=who, font=FONTS["h3"], bg=C["panel"], fg=C["fg_bright"], anchor="w").pack(side="left")
        kind = T("Document timestamp") if sig.get("timestamp") else T("Signature {0}", n)
        tag = tk.Label(line, text=" " + kind + " ", font=FONTS["caption"], bg=C["hover_strong"], fg=C["fg_dim"])
        tag.pack(side="left", padx=(px(10), 0))
        status = text.split(": ", 1)[1] if text.startswith(who + ": ") else text
        status = status[:1].upper() + status[1:]
        tk.Label(title, text=status, font=FONTS["small"], bg=C["panel"], fg=col, anchor="w", justify="left",
                 wraplength=px(540)).pack(fill="x", pady=(px(2), 0))

        facts = [(T("Signed on"), _date(sig.get("time"))), (T("Reason"), sig.get("reason")),
                 (T("Location"), sig.get("location")),
                 (T("Name in the signature"), sig.get("name") if sig.get("name") != who else None),
                 (T("Format"), (sig.get("subfilter") or "") + ("  ·  " + T("old SHA-1 method")
                                                               if sig.get("legacy_sha1") else ""))]
        grid = tk.Frame(body, bg=C["panel"])
        grid.pack(fill="x", pady=(px(12), 0))
        r = 0
        for label, value in facts:
            if not value:
                continue
            tk.Label(grid, text=label, font=FONTS["small"], bg=C["panel"], fg=C["fg_muted"], anchor="w").grid(
                row=r, column=0, sticky="nw", padx=(0, px(18)), pady=px(1))
            tk.Label(grid, text=value, font=FONTS["small"], bg=C["panel"], fg=C["fg"], anchor="w", justify="left",
                     wraplength=px(440)).grid(row=r, column=1, sticky="nw", pady=px(1))
            r += 1
        grid.columnconfigure(1, weight=1)

        checks = tk.Frame(body, bg=C["panel"])
        checks.pack(fill="x", pady=(px(12), 0))
        for lvl, label in self._checks(n, sig):
            row = tk.Frame(checks, bg=C["panel"])
            row.pack(fill="x", pady=px(2))
            tk.Label(row, text=MARKS[lvl], font=FONTS["small_bold"], bg=C["panel"], fg=_level_color(lvl),
                     width=2, anchor="w").pack(side="left")
            tk.Label(row, text=label, font=FONTS["small"], bg=C["panel"], fg=C["fg"], anchor="w", justify="left",
                     wraplength=px(560)).pack(side="left", fill="x", expand=True)

        cert = sig.get("cert")
        if cert is not None:
            open_ = n in self.expanded
            toggle = tk.Label(body, text=("▾  " if open_ else "▸  ") + T("Certificate details"),
                              font=FONTS["small_bold"], bg=C["panel"], fg=C["accent"], cursor="hand2", anchor="w")
            toggle.pack(fill="x", pady=(px(12), 0))
            toggle.bind("<Button-1>", lambda e, k=n: self._toggle(k))
            if open_:
                self._cert_section(body, sig)

    def _checks(self, n, sig):
        out = []
        if sig.get("problem"):
            out.append(("bad", sig["problem"]))
        else:
            out.append(("ok", T("The signed content has not been changed and the signature matches the "
                                "signer's key.")) if sig.get("intact") else
                       ("bad", T("The signed content was changed or the signature does not match.")))
            if sig.get("covers_whole_file"):
                out.append(("ok", T("The signature covers the whole document.") + (
                    " " + T("(Validation data was added afterwards.)") if sig.get("dss_after") else "")))
            elif sig.get("later_signed"):
                out.append(("ok", T("Later revisions were added by further signatures or timestamps.")))
            else:
                out.append(("warning", T("The document was changed after this signature (a later revision).")))
        if sig.get("cert_valid_at_signing") is True:
            out.append(("ok", T("The certificate was valid when the document was signed.") + (
                " " + T("It has expired since.") if sig.get("cert_expired_now") else "")))
        elif sig.get("cert_valid_at_signing") is False:
            out.append(("warning", T("The certificate was NOT valid when the document was signed.")))
        if sig.get("legacy_sha1"):
            out.append(("warning", T("Signed with SHA-1, an old method that is no longer considered strong.")))
        if sig.get("cert") is not None:
            trust = self.trust.get(n)
            if trust is None:
                out.append(("none", T("Trust in the issuing authority has not been checked yet.")))
            else:
                ok, text = trust
                out.append(("ok" if ok else "bad" if ok is False else "warning", text))
        return out

    def _cert_section(self, parent, sig):
        cert = sig["cert"]
        start, end = pdfsig._validity(cert)
        box = tk.Frame(parent, bg=C["bg_deep"], padx=px(14), pady=px(10), highlightthickness=1,
                       highlightbackground=C["border"])
        box.pack(fill="x", pady=(px(6), 0))
        rows = [(T("Issued to"), cert.subject.rfc4514_string()), (T("Issued by"), cert.issuer.rfc4514_string()),
                (T("Valid from"), f"{start:%Y-%m-%d %H:%M} UTC"),
                (T("Valid until"), f"{end:%Y-%m-%d %H:%M} UTC" + (f"  ({T('expired')})"
                                                                   if sig.get("cert_expired_now") else "")),
                (T("Serial number"), format(cert.serial_number, "X")), (T("Key"), _key_text(cert)),
                (T("SHA-256 fingerprint"), _fingerprint(cert)),
                (T("Certificates in the signature"), str(len(sig.get("certs") or [])))]
        for r, (label, value) in enumerate(rows):
            tk.Label(box, text=label, font=FONTS["tiny"], bg=C["bg_deep"], fg=C["fg_muted"], anchor="w").grid(
                row=r, column=0, sticky="nw", padx=(0, px(14)), pady=px(1))
            mono = label in (T("Serial number"), T("SHA-256 fingerprint"))
            tk.Label(box, text=value, font=FONTS["kbd"] if mono else FONTS["small"], bg=C["bg_deep"], fg=C["fg"],
                     anchor="w", justify="left", wraplength=px(430)).grid(row=r, column=1, sticky="nw", pady=px(1))
        box.columnconfigure(1, weight=1)
        ToolButton(box, T("Save certificate…"), "save", lambda: self.save_certificate(cert),
                   bg=C["bg_deep"], hover=C["hover_strong"], pad=(10, 4)).grid(row=len(rows), column=0, columnspan=2,
                                                                                sticky="w", pady=(px(8), 0))

    def _toggle(self, n):
        self.expanded ^= {n}
        y = self.canvas.yview()[0]
        self.render()
        self.update_idletasks()
        self.canvas.yview_moveto(y)

    # ── actions ──
    def set_trust(self, trust):
        self.trust = dict(trust or {})
        self.render()

    def check_trust(self):
        self.tab.check_signer_trust()

    def copy_report(self):
        trust = {n: text for n, (_ok, text) in self.trust.items()}
        text = pdfsig.report(self.tab.path or self.tab.title, self.sigs, trust or None)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.tab.app.toast.show(T("The signature report was copied."), "info", 1800)

    def save_certificate(self, cert):
        from tkinter import filedialog
        from cryptography.hazmat.primitives import serialization
        name = pdfsig.common_name(cert) or "certificate"
        safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in name).strip() or "certificate"
        path = filedialog.asksaveasfilename(parent=self, title=T("Save certificate"), initialfile=safe + ".cer",
                                            defaultextension=".cer",
                                            filetypes=[(T("Certificate"), "*.cer *.crt"), (T("All files"), "*.*")])
        if not path:                                    # (the ReadOnly policy already blocks the dialog)
            return
        with open(path, "wb") as fh:
            fh.write(cert.public_bytes(serialization.Encoding.DER))
        self.tab.app.toast.show(T("Saved {0}", os.path.basename(path)), "info", 1800)


def show(tab):
    panel = getattr(tab, "sig_panel", None)
    if panel is not None and panel.winfo_exists():
        panel.lift()
        panel.focus_set()
        return panel
    tab.sig_panel = SignaturePanel(tab)
    return tab.sig_panel
