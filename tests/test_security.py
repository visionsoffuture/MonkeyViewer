import json
import os

import pytest

from viewer import audit, policy, safeio, winutil


@pytest.mark.parametrize("raw,expected", [
    ("..\\..\\Windows\\evil.exe", "evil.exe"), ("a/b/c.txt", "c.txt"), ("CON.txt", "_CON.txt"),
    ('bad<>:"|?*.pdf', "bad_______.pdf"), ("", "file"), ("..", "file"), ("name. ", "name"),
])
def test_safe_filename(raw, expected):
    assert safeio.safe_filename(raw) == expected


def test_sidecar_references_stay_next_to_the_document(tmp_path):
    doc = tmp_path / "model.gltf"
    doc.write_text("{}")
    assert safeio.resolve_sidecar(str(doc), "model.bin") == str(tmp_path / "model.bin")
    assert safeio.resolve_sidecar(str(doc), "sub/a%20b.bin") == str(tmp_path / "sub" / "a b.bin")
    for bad in ("../secret.bin", "..\\secret.bin", "/etc/passwd", "C:\\Windows\\win.ini", "\\\\server\\share\\x",
                "//server/share/x", "http://example.com/x.bin", "file:///c:/x", ""):
        assert safeio.resolve_sidecar(str(doc), bad) is None, bad


@pytest.mark.parametrize("name", ["x.exe", "x.PDF.exe", "x.bat", "x.ps1", "x.vbs", "x.js", "x.lnk", "x.msi",
                                  "x.py", "x.hta", "x.scr", "x.lua"])
def test_programs_are_never_launched(name):
    assert safeio.is_dangerous(name)
    with pytest.raises(winutil.BlockedFile):
        winutil.open_external(name)


@pytest.mark.parametrize("name", ["x.pdf", "x.dwg", "x.docx", "x.png"])
def test_documents_are_not_flagged(name):
    assert not safeio.is_dangerous(name)


@pytest.mark.parametrize("url", ["file:///c:/windows/system32/calc.exe", "javascript:alert(1)", "ms-msdt:/id x",
                                 "\\\\server\\share", ""])
def test_only_web_links_open(url):
    with pytest.raises(winutil.BlockedFile):
        winutil.open_url(url)


def test_xml_entity_bombs_are_refused(tmp_path):
    p = tmp_path / "bomb.xml"
    p.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><x>&b;</x>')
    with pytest.raises(Exception):
        safeio.xml_parse(str(p))
    ext = tmp_path / "ext.xml"
    ext.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
    with pytest.raises(Exception):
        safeio.xml_parse(str(ext))


def test_session_temp_is_private_and_removed(tmp_path):
    d = safeio.temp_dir("t")
    assert os.path.isdir(d) and d.startswith(safeio.session_dir())
    if os.name == "posix":
        assert (os.stat(safeio.session_dir()).st_mode & 0o077) == 0
    safeio.cleanup_session()
    assert not os.path.exists(d)


def test_sqlite_is_opened_read_only(tmp_path):
    import sqlite3
    tmp_path = tmp_path / "db"
    tmp_path.mkdir()
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("create table t (a)")
    con.commit()
    con.close()
    ro = safeio.sqlite_readonly(str(db))
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("insert into t values (1)")
    ro.close()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.db"]


def test_policies_default_off_and_override():
    assert policy.active() == {}
    policy.override({"ReadOnly": 1, "AuditLogPath": "%TEMP%\\x.log", "Unknown": 1})
    assert policy.get_bool("ReadOnly") and not policy.get_bool("DisableDecryption")
    assert policy.get_bool("ReadOnly") is True
    assert "AuditLogPath" in policy.active()


def test_policy_strings_are_parsed():
    policy.override({"ReadOnly": "0", "EventLog": "true"})
    assert not policy.get_bool("ReadOnly") and policy.get_bool("EventLog")


def test_audit_log_records_and_hides_secrets(tmp_path):
    audit.event("decrypt", path="C:\\x.enc", method="password", password="hunter2", passphrase="x", result="ok")
    lines = open(audit.log_path(), encoding="utf-8").read().splitlines()
    rec = json.loads(lines[-1])
    assert rec["action"] == "decrypt" and rec["result"] == "ok" and rec["path"] == "C:\\x.enc"
    assert "password" not in rec and "passphrase" not in rec and "hunter2" not in lines[-1]
    for key in ("time", "user", "computer", "app", "pid"):
        assert key in rec


def test_audit_central_copy_and_disable(tmp_path):
    central = tmp_path / "central" / "audit.jsonl"
    policy.override({"AuditLogPath": str(central), "DisableAuditLog": 1})
    audit.event("file_open", path="a.pdf")
    assert json.loads(central.read_text(encoding="utf-8").splitlines()[-1])["action"] == "file_open"
    assert not os.path.exists(audit.log_path())


def test_audit_file_hash_only_with_policy(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")
    assert audit.file_hash(str(f)) is None
    policy.override({"AuditFileHashes": 1})
    assert audit.file_hash(str(f)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_audit_log_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "MAX_BYTES", 300)
    for i in range(30):
        audit.event("file_open", path=f"file{i}.pdf")
    assert os.path.exists(audit.log_path() + ".1")


def test_single_instance_requires_the_user_token():
    inst = winutil.SingleInstance()
    if not inst.acquire():
        pytest.skip("port in use")
    try:
        import socket
        with socket.create_connection(("127.0.0.1", winutil._instance_port()), timeout=2) as c:
            c.sendall(json.dumps({"app": winutil.APP_ID, "token": "wrong", "files": ["x"]}).encode())
            c.shutdown(socket.SHUT_WR)
            assert c.recv(16) == b""
        assert winutil.SingleInstance.send(["C:\\a.pdf"])
        assert inst.queue.get(timeout=3) == ["C:\\a.pdf"]
        assert inst.queue.empty()
    finally:
        inst.sock.close()


def test_external_tools_can_be_disabled(monkeypatch, tmp_path):
    exe = tmp_path / ("gpg.exe" if os.name == "nt" else "gpg")
    exe.write_text("")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(winutil, "_program_dirs", lambda: [])     # e.g. Git for Windows ships its own gpg.exe
    if winutil.IS_MAC:
        pytest.skip("macOS uses its own search list")
    assert winutil.find_gpg() == str(exe)
    policy.override({"DisableExternalTools": 1})
    assert winutil.find_gpg() is None


def test_relative_path_entries_are_ignored(monkeypatch, tmp_path):
    exe = tmp_path / ("gpg.exe" if os.name == "nt" else "gpg")
    exe.write_text("")
    exe.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "." + os.pathsep + "relative")
    monkeypatch.setattr(winutil, "_program_dirs", lambda: [])
    if winutil.IS_MAC:
        pytest.skip("macOS uses its own search list")
    assert winutil.find_gpg() is None


def test_unique_path_never_suggests_an_existing_file(tmp_path):
    from viewer import safeio
    assert safeio.unique_path(str(tmp_path), "a.png") == str(tmp_path / "a.png")
    (tmp_path / "a.png").write_text("")
    assert safeio.unique_path(str(tmp_path), "a.png") == str(tmp_path / "a (1).png")
    (tmp_path / "a (1).png").write_text("")
    assert safeio.unique_path(str(tmp_path), "a (1).png") == str(tmp_path / "a (2).png")


def test_bundled_helpers_are_preferred(monkeypatch, tmp_path):
    exe = tmp_path / "tools" / "libredwg" / ("dwg2dxf.exe" if os.name == "nt" else "dwg2dxf")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    exe.chmod(0o755)
    monkeypatch.setattr(winutil, "resource_path", lambda name: str(tmp_path / name))
    assert winutil.find_dwg2dxf() == str(exe)
    policy.override({"DisableExternalTools": 1})
    assert winutil.find_dwg2dxf() is None
