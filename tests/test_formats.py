import pytest

from viewer import formats


@pytest.mark.parametrize("name,kind", [
    ("a.lua", "text"), ("a.pdf", "pdf"), ("a.djvu", "djvu"), ("a.dxf", "dxf"), ("a.dwg", "dwg"),
    ("a.shp", "map"), ("a.kml", "map"), ("a.gpx", "map"), 
    ("a.p7m", "cert"), ("a.pfx", "cert"), ("a.gpg", "crypto"), ("a.enc", "crypto"), ("a.psd", "image"),
    ("a.dbf", "table"), ("a.pol", "table"),
])
def test_specialist_formats_are_registered(name, kind):
    assert formats.info(name)[0] == kind


@pytest.mark.parametrize("name", ["a.docx", "a.xlsx", "a.pptx", "a.doc", "a.odt", "a.zip", "a.rar", "a.7z",
                                  "a.msg", "a.eml", "a.mp3", "a.mp4", "a.csv", "a.txt"])
def test_everyday_formats_are_left_to_their_programs(name):
    assert formats.info(name) is None


def test_unknown_office_file_opens_as_info(tmp_path):
    p = tmp_path / "report.docx"
    p.write_bytes(b"PK\x03\x04" + b"\0" * 100)
    assert formats.viewer_kind(str(p)) == "info"


def test_sniffing(tmp_path):
    p = tmp_path / "noext"
    p.write_bytes(b"%PDF-1.7\n")
    assert formats.viewer_kind(str(p)) == "pdf"
    p.write_bytes(b"Salted__12345678" + b"x" * 32)
    assert formats.viewer_kind(str(p)) == "crypto"
    p.write_bytes(b"-- lua\nprint('x')\n")
    assert formats.viewer_kind(str(p)) == "text"


def test_dialog_filters_are_short():
    for _title, pattern in formats.dialog_filetypes():
        assert len(pattern) <= formats.MAX_FILTER
    assert formats.dialog_filetypes()[0] == ("All files", "*")
