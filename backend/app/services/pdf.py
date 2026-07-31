"""PDF rendering (HTML + WeasyPrint).

The timetable comes from the same :func:`app.services.timetable.build_timetable`
the on-screen grid uses, so the printed and the on-screen version cannot
disagree.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.schedule import Timetable
from app.timeutil import format_hhmm

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

#: Trip columns that fit across one landscape A4 page next to a 46 mm stop
#: column. Wider tables are split across pages rather than being squeezed
#: until the times stop being readable.
COLUMNS_PER_PAGE = 16

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)
_env.filters["hhmm"] = lambda seconds: format_hhmm(seconds) or ""


def render_timetable_pdf(
    timetable: Timetable,
    board_name: str,
    line_color: str | None = None,
    line_text_color: str | None = None,
    landscape: bool = True,
) -> bytes:
    from weasyprint import HTML  # imported lazily: pulls in the pango stack

    column_count = len(timetable.trip_ids)
    chunks = [
        list(range(start, min(start + COLUMNS_PER_PAGE, column_count)))
        for start in range(0, max(column_count, 1), COLUMNS_PER_PAGE)
    ] or [[]]

    html = _env.get_template("timetable.html").render(
        t=timetable,
        chunks=chunks,
        board_name=board_name,
        page_size="A4 landscape" if landscape else "A4 portrait",
        line_color=f"#{line_color}" if line_color else "#1f4e79",
        line_text_color=f"#{line_text_color}" if line_text_color else "#ffffff",
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    return HTML(string=html).write_pdf()


def safe_filename(*parts: str) -> str:
    """Build a download filename that survives every OS and browser."""
    cleaned = []
    for part in parts:
        keep = "".join(
            ch if ch.isalnum() or ch in "-_" else "-" for ch in (part or "").strip()
        )
        keep = "-".join(filter(None, keep.split("-")))
        if keep:
            cleaned.append(keep)
    return "_".join(cleaned) or "export"
