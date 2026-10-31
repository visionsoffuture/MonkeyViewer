"""The user guide (docs/USER_GUIDE.md) shown as a laid-out document instead of Markdown source."""

import html
import os
import re

CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1d2333; }
h1 { font-size: 21pt; color: #2f6fe0; margin: 0 0 8pt 0; }
h2 { font-size: 14pt; color: #1d2333; margin: 16pt 0 6pt 0; padding-bottom: 3pt; border-bottom: 1pt solid #d9dce5; }
h3 { font-size: 12pt; margin: 12pt 0 4pt 0; }
p { margin: 0 0 7pt 0; }
ul { margin: 0 0 8pt 0; padding-left: 14pt; }
li { margin: 0 0 4pt 0; }
code { font-family: monospace; font-size: 9.5pt; background-color: #eef1f7; }
table { border-collapse: collapse; margin: 4pt 0 10pt 0; }
th { background-color: #eef1f7; text-align: left; padding: 3pt 8pt; border: 0.5pt solid #c9cedb; }
td { padding: 3pt 8pt; border: 0.5pt solid #d9dce5; }
"""


def _inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


def markdown_to_html(md):
    """Headings, paragraphs, '-' lists (with continuation lines), tables, **bold**, `code`, [links](url)."""
    out, para, items, rows = [], [], [], []

    def flush():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
        if rows:
            head, body = rows[0], rows[1:]
            cells = "".join(f"<th>{_inline(c)}</th>" for c in head)
            body_html = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
            out.append(f"<table><tr>{cells}</tr>{body_html}</table>")
            rows.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        m = re.match(r"(#{1,3})\s+(.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue
        if stripped.startswith("|"):
            if para or items:
                flush()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            rows.append(cells)
            continue
        if re.match(r"\s*[-*]\s+", line) and not line.startswith("  " * 3):
            if para or rows:
                flush()
            items.append(re.sub(r"^\s*[-*]\s+", "", line))
            continue
        if items and raw.startswith("  "):        # continuation of the list item above
            items[-1] += " " + stripped
            continue
        if rows:
            flush()
        para.append(stripped)
    flush()
    return "\n".join(out)


def guide_pdf(md_path, title):
    """PDF bytes of the guide, laid out on A4 pages with the title and page numbers."""
    from . import printing
    with open(md_path, encoding="utf-8") as fh:
        md = fh.read()
    doc = printing.story_document(markdown_to_html(md), title, CSS)
    try:
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def write_guide(md_path, title):
    """The laid-out guide in this session's private temp folder (deleted when the program closes)."""
    from . import safeio
    out = os.path.join(safeio.session_dir(), "User guide.pdf")
    data = guide_pdf(md_path, title)
    with open(out, "wb") as fh:
        fh.write(data)
    return out
