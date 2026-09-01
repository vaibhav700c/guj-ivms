"""Minimal dependency-free PDF generator for report exports (plan §20 Week 3).

Produces simple multi-page landscape text-table PDFs using the base-14
Helvetica/Courier fonts — no third-party dependencies required.
"""
from datetime import datetime, timezone

PAGE_W, PAGE_H = 792, 612  # US Letter, landscape
MARGIN = 36
LINE_H = 13
COURIER_CHAR_W = 8 * 0.6  # 8pt Courier -> 4.8pt per char
TOTAL_COLS_CHARS = int((PAGE_W - 2 * MARGIN) / COURIER_CHAR_W)  # ~150 chars


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _latin(v) -> str:
    if v is None:
        return ""
    return str(v).encode("latin-1", "replace").decode("latin-1")


def _column_widths(header: list[str], rows: list[list[str]]) -> list[int]:
    """Proportional column widths (in characters) summing to TOTAL_COLS_CHARS."""
    n = len(header)
    maxima = [
        max([len(header[i])] + [len(r[i]) if i < len(r) else 0 for r in rows[:500]]) or 1
        for i in range(n)
    ]
    cap = max(TOTAL_COLS_CHARS // 3, 12)  # no column wider than a third of the page
    clamped = [min(m, cap) for m in maxima]
    total = sum(clamped)
    widths = [max(int(w * TOTAL_COLS_CHARS / total), 6) for w in clamped]
    widths[-1] += TOTAL_COLS_CHARS - sum(widths)  # fix rounding drift
    return widths


def _format_row(cells: list[str], widths: list[int]) -> str:
    out = []
    for i, w in enumerate(widths):
        cell = cells[i] if i < len(cells) else ""
        out.append(cell[:w].ljust(w))
    return "".join(out).rstrip()


def _paginate(title: str, subtitle: str, header: list[str],
              rows: list[list[str]]) -> list[list[tuple[str, str]]]:
    """Return pages, each a list of (kind, text) tuples.

    Kinds: H1, SUB, COLHDR, RULE, TXT, GAP.
    """
    widths = _column_widths(header, rows)
    fmt_hdr = _format_row([h.upper() for h in header], widths)

    usable_lines = (PAGE_H - 2 * MARGIN) // LINE_H
    title_block: list[tuple[str, str]] = [
        ("H1", title),
        ("SUB", subtitle),
        ("SUB", f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} UTC · "
                f"{len(rows)} records"),
        ("GAP", ""),
        ("COLHDR", fmt_hdr),
        ("RULE", ""),
    ]
    per_page = usable_lines - 2  # footer clearance
    rows_first = per_page - len(title_block)
    rows_rest = per_page - 2  # continuation pages repeat the column header

    pages: list[list[tuple[str, str]]] = []
    row_iter = iter(rows)
    chunk = [r for _, r in zip(range(rows_first), row_iter)]
    pages.append(title_block + [("TXT", _format_row(r, widths)) for r in chunk])
    while True:
        chunk = [r for _, r in zip(range(rows_rest), row_iter)]
        if not chunk:
            break
        pages.append([("COLHDR", fmt_hdr), ("RULE", "")]
                     + [("TXT", _format_row(r, widths)) for r in chunk])
    return pages
def build_pdf(title: str, subtitle: str, header: list[str], rows: list[list],
              footer: str = "Gujarat IVMS — Integrated Video Management & Analytics Platform") -> bytes:
    pages = _paginate(title, subtitle, header, [[_latin(c) for c in r] for r in rows])
    n = len(pages)
    streams = []

    for pno, lines in enumerate(pages, 1):
        cmds = []
        y = PAGE_H - MARGIN
        for kind, text in lines:
            if kind == "GAP":
                y -= LINE_H // 2
                continue
            if kind == "H1":
                cmds.append(f"BT /F1 16 Tf {MARGIN} {y} Td ({_esc(text)}) Tj ET")
                y -= 20
            elif kind == "SUB":
                cmds.append(f"BT /F1 9 Tf {MARGIN} {y} Td ({_esc(text)}) Tj ET")
                y -= LINE_H
            elif kind == "COLHDR":
                cmds.append(f"BT /F1 8 Tf {MARGIN} {y} Td ({_esc(text)}) Tj ET")
                y -= LINE_H
            elif kind == "RULE":
                cmds.append(f"0.8 w {MARGIN} {y + 3} m {PAGE_W - MARGIN} {y + 3} l S")
                y -= LINE_H
            else:
                cmds.append(f"BT /F2 8 Tf {MARGIN} {y} Td ({_esc(text)}) Tj ET")
                y -= LINE_H
        cmds.append(f"BT /F1 8 Tf {MARGIN} {MARGIN - 14} Td "
                    f"({_esc(footer)} - page {pno} of {n}) Tj ET")
        streams.append("\n".join(cmds).encode("latin-1", "replace"))

    # ── Assemble PDF object graph ────────────────────────────────────────────
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")                       # 1
    kids = " ".join(f"{4 + 3 * i} 0 R" for i in range(n))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())   # 2
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3
    obj_no = 4
    for content in streams:
        objects.append(                                                        # page
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R /F2 {obj_no + 1} 0 R >> >> "
            f"/Contents {obj_no + 2} 0 R >>".encode()
        )
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
        objects.append(b"<< /Length " + str(len(content)).encode()
                       + b" >>\nstream\n" + content + b"\nendstream")
        obj_no += 3

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)
