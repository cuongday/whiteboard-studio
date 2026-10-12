import io
import re
from pathlib import Path

_TS = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->")

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1258"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def srt_blocks(text: str) -> list[str]:
    blocks = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        lines = [l for l in lines if not l.strip().isdigit() and not _TS.match(l.strip())]
        if lines:
            blocks.append(" ".join(l.strip() for l in lines))
    return blocks

def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        return _decode(data).strip()
    if ext == ".srt":
        return "\n".join(srt_blocks(_decode(data)))
    if ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
    if ext == ".pdf":
        from pypdf import PdfReader
        pages = [pg.extract_text() or "" for pg in PdfReader(io.BytesIO(data)).pages]
        return "\n".join(t.strip() for t in pages if t.strip())
    raise ValueError(f"Định dạng không hỗ trợ: {ext}")
