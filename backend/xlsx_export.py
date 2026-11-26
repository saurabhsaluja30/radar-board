"""Excel (.xlsx) downloads for admin exports.

Uses openpyxl's write-only mode, which streams rows instead of building the whole sheet in memory.
"""
import io
from typing import Any, Iterable, List, Tuple

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

CELL_MAX = 32000  # Excel's per-cell limit is 32,767 characters
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def flat(v: Any) -> Any:
    """A cell value: numbers and booleans stay as they are, lists become "a; b", dicts their values."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, dict):
        v = ", ".join(str(x) for x in v.values() if x not in (None, ""))
    elif isinstance(v, list):
        v = "; ".join(flat(x) if isinstance(x, dict) else str(x) for x in v if x not in (None, ""))
    s = "".join(ch for ch in str(v) if ch in "\t\n" or ord(ch) >= 32)  # control characters make Excel reject the file
    return s[:CELL_MAX]


def build_xlsx(columns: List[Tuple[str, str]], rows: Iterable[dict], sheet: str = "Sheet1") -> bytes:
    """`columns` is [(key, header)]. Text is always stored as text, so a value starting with "=" can't run as a
    formula when the file is opened."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(sheet[:31])
    ws.freeze_panes = "A2"
    for i, (key, header) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = 60 if key == "cv_text" else min(40, max(12, len(header) + 4))
    head = []
    for _, header in columns:
        c = WriteOnlyCell(ws, value=header)
        c.font = Font(bold=True)
        head.append(c)
    ws.append(head)
    for row in rows:
        cells = []
        for key, _ in columns:
            v = flat(row.get(key))
            c = WriteOnlyCell(ws, value=v)
            if isinstance(v, str):
                c.data_type = "s"
            cells.append(c)
        ws.append(cells)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_response(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type=XLSX_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
