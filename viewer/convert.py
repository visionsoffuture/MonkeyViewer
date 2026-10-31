"""PDF tools: images / documents -> PDF, merge PDFs, PDF -> PNG pages, HTML -> PDF (for code export)."""

import io
import os

from . import formats
from .i18n import T

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # noqa: F401


def unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    k = 1
    while os.path.exists(f"{stem} ({k}){ext}"):
        k += 1
    return f"{stem} ({k}){ext}"


def output_path(src):
    folder = os.path.dirname(src)
    if not os.access(folder, os.W_OK):
        folder = os.path.join(os.path.expanduser("~"), "Documents")
        os.makedirs(folder, exist_ok=True)
    return unique_path(os.path.join(folder, os.path.splitext(os.path.basename(src))[0] + ".pdf"))


BASE_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.3; color: #111; }
p { margin: 0 0 6pt 0; }
h1 { font-size: 20pt; margin: 10pt 0 6pt 0; } h2 { font-size: 16pt; margin: 10pt 0 5pt 0; }
h3 { font-size: 13.5pt; margin: 8pt 0 4pt 0; } h4, h5, h6 { font-size: 12pt; margin: 6pt 0 3pt 0; }
table { border-collapse: collapse; margin: 4pt 0 8pt 0; }
td, th { border: 0.6pt solid #888; padding: 2pt 4pt; vertical-align: top; }
th { background-color: #eef1f6; font-weight: bold; }
"""


def story_to_pdf(html, css, archive=None, page=(595, 842), margins=(56, 56, 56, 56)):
    story = fitz.Story(html, user_css=css, archive=archive)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    mediabox = fitz.Rect(0, 0, *page)
    where = mediabox + (margins[3], margins[0], -margins[1], -margins[2])
    more, pages = 1, 0
    while more and pages < 5000:
        dev = writer.begin_page(mediabox)
        more, _filled = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
    writer.close()
    return buf.getvalue()


# ─────────────────────────────── images, merging, rendering ───────────────────────────────
def _image_page(doc, path):
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.seek(0) if hasattr(im, "seek") else None
        w, h = im.size
        buf = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P"):
            im.convert("RGBA").save(buf, "PNG")
        else:
            im.convert("RGB").save(buf, "JPEG", quality=92)
    pw, ph = (842, 595) if w > h else (595, 842)
    page = doc.new_page(width=pw, height=ph)
    m = 18
    page.insert_image(fitz.Rect(m, m, pw - m, ph - m), stream=buf.getvalue(), keep_proportion=True)


def files_to_pdf(paths):
    """Combine PDFs, images and other documents (XPS, EPUB, SVG…) into one PDF."""
    doc = fitz.open()
    for path in paths:
        kind = formats.viewer_kind(path)
        if kind == "pdf":
            with fitz.open(path) as src:
                doc.insert_pdf(src)
        elif kind == "image":
            _image_page(doc, path)
        elif kind in ("document", "svg"):
            with fitz.open(path) as src:
                pdf = fitz.open("pdf", src.convert_to_pdf())
                doc.insert_pdf(pdf)
        else:
            raise ValueError(T("Can't add {0} to a PDF", os.path.basename(path)))
    if len(doc) == 0:
        raise ValueError(T("Nothing to combine"))
    return doc.tobytes(garbage=3, deflate=True)


def images_to_pdf(paths):
    return files_to_pdf(paths)


def merge_pdfs(paths):
    return files_to_pdf(paths)


def pdf_to_images(path, folder, dpi=150):
    stem = os.path.splitext(os.path.basename(path))[0]
    out = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            dst = os.path.join(folder, f"{stem}_page{i + 1:03d}.png")
            pix.save(dst)
            out.append(dst)
    return out
