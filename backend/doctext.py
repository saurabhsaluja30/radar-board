"""Plain text from old Word 97–2003 (.doc) files, without converters or external programs.

Reads the document's piece table, which lists where each run of text is stored and whether it is 8-bit or UTF-16.
Covers resumes saved by Word 97 and later; very old Word 6/95 files are rejected with a clear message.
"""
import io
import re
import struct

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class DocError(ValueError):
    pass


def is_doc(data: bytes) -> bool:
    return data[:8] == OLE_MAGIC


def doc_to_text(data: bytes, max_chars: int = 200_000) -> str:
    import olefile
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as e:
        raise DocError(f"not a Word file: {e}")
    try:
        if not ole.exists("WordDocument"):
            raise DocError("no WordDocument stream (not a Word file)")
        wd = ole.openstream("WordDocument").read()
        if len(wd) < 0x1AA:
            raise DocError("file too short")
        ident, nfib = struct.unpack_from("<HH", wd, 0)
        if ident != 0xA5EC:
            raise DocError("unexpected Word header")
        if nfib < 0x00C1:
            raise DocError("Word 6/95 format is not supported")
        flags = struct.unpack_from("<H", wd, 0x0A)[0]
        if flags & 0x0100:
            raise DocError("password-protected document")
        table_name = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(table_name):
            raise DocError("missing table stream")
        table = ole.openstream(table_name).read()
        fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
        clx = table[fc_clx:fc_clx + lcb_clx]
    finally:
        ole.close()

    # Skip Prc entries (formatting) to reach the Pcdt (piece table).
    i = 0
    while i < len(clx) and clx[i] == 0x01:
        i += 3 + struct.unpack_from("<h", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise DocError("piece table not found")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    out, total = [], 0
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        count = cps[k + 1] - cps[k]
        if count <= 0:
            continue
        if fc & 0x40000000:  # 8-bit text (Windows-1252)
            start = (fc & 0x3FFFFFFF) // 2
            chunk = wd[start:start + count].decode("cp1252", errors="replace")
        else:  # UTF-16
            start = fc & 0x3FFFFFFF
            chunk = wd[start:start + 2 * count].decode("utf-16-le", errors="replace")
        out.append(chunk)
        total += len(chunk)
        if total >= max_chars:
            break
    return clean("".join(out))[:max_chars]


def clean(text: str) -> str:
    # Field codes: keep the displayed result, drop the instruction between \x13 and \x14 (or \x15).
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", text)
    text = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", text)
    text = text.replace("\x15", "").replace("\r", "\n").replace("\x07", "\t").replace("\x0b", "\n")
    text = text.replace("\x0c", "\n").replace("\x1e", "-").replace("\x1f", "").replace("\xa0", " ")
    text = re.sub(r"[\x00-\x08\x0e-\x1d]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
