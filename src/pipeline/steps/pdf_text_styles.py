"""Extração de trechos textuais com estilo tipográfico a partir do PDF nativo (PyMuPDF)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

try:
    import fitz
except ImportError:  # pragma: no cover - extração de PDF exige PyMuPDF
    fitz = None  # type: ignore[assignment]

# PyMuPDF span flags: bit 0 superscript, 1 italic, 2 serifed, 3 monospaced, 4 bold
_FLAG_ITALIC = 1 << 1
_FLAG_BOLD = 1 << 4

_BOLD_NAME_RE = re.compile(r"(bold|black|heavy|semibold|demi)", re.IGNORECASE)
_ITALIC_NAME_RE = re.compile(
    r"(italic|oblique|kursiv|cursive|(?<![a-z])ital(?![a-z]))",
    re.IGNORECASE,
)
# Minion-It, Times,Italic, Fonte_I — não casar "Times" nem "Semi".
_ITALIC_SUFFIX_RE = re.compile(r"[,+\-_](it|i)(?:mt|std)?$", re.IGNORECASE)
# Nomes curtos Base-14 do PyMuPDF (Helvetica-Oblique, Times-Italic, …).
_ITALIC_SHORT_NAMES = frozenset({"heit", "hebi", "tito", "tibo", "coui", "cobo"})
_BOLD_SHORT_NAMES = frozenset({"hebo", "hebi", "tibo", "cobo"})

FONT_STYLES = frozenset({"normal", "negrito", "italico", "negrito_italico"})


@dataclass(frozen=True)
class TextRun:
    text: str
    estilo: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class PageTextStyles:
    page_number: int
    runs: list[TextRun]
    char_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "runs": [run.to_dict() for run in self.runs],
            "char_count": self.char_count,
        }


def _font_basename(name: str) -> str:
    raw = (name or "").strip()
    if "+" in raw:
        raw = raw.rsplit("+", 1)[-1]
    return raw


def _name_looks_bold(name: str) -> bool:
    base = _font_basename(name)
    if not base:
        return False
    if base.lower() in _BOLD_SHORT_NAMES:
        return True
    return bool(_BOLD_NAME_RE.search(base))


def _name_looks_italic(name: str) -> bool:
    base = _font_basename(name)
    if not base:
        return False
    if base.lower() in _ITALIC_SHORT_NAMES:
        return True
    if _ITALIC_NAME_RE.search(base):
        return True
    return bool(_ITALIC_SUFFIX_RE.search(base))


def classify_font_style(
    flags: int,
    font_name: str,
    extra_names: tuple[str, ...] = (),
) -> str:
    names = (font_name or "", *extra_names)
    bold = bool(flags & _FLAG_BOLD) or any(_name_looks_bold(n) for n in names if n)
    italic = bool(flags & _FLAG_ITALIC) or any(_name_looks_italic(n) for n in names if n)
    if bold and italic:
        return "negrito_italico"
    if bold:
        return "negrito"
    if italic:
        return "italico"
    return "normal"


def _font_alias_map(page: Any) -> dict[str, str]:
    """Mapeia o nome do span para o basefont (costuma trazer Italic/Bold)."""
    aliases: dict[str, str] = {}
    try:
        items = page.get_fonts() or []
    except Exception:  # noqa: BLE001
        return aliases
    for item in items:
        if not item or len(item) < 5:
            continue
        basefont = str(item[3] or "")
        name = str(item[4] or "")
        if name and basefont:
            aliases[name] = basefont
        if basefont:
            aliases.setdefault(basefont, basefont)
    return aliases


def _iter_raw_spans(page: Any) -> list[tuple[str, str]]:
    """Retorna (texto, estilo) por span na ordem de leitura do PyMuPDF."""
    out: list[tuple[str, str]] = []
    aliases = _font_alias_map(page)
    data = page.get_text("dict")
    for block in data.get("blocks") or []:
        if int(block.get("type") or 0) != 0:
            continue
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                text = str(span.get("text") or "")
                if not text:
                    continue
                font = str(span.get("font") or "")
                extra = aliases.get(font, "")
                extras = (extra,) if extra and extra != font else ()
                estilo = classify_font_style(int(span.get("flags") or 0), font, extras)
                out.append((text, estilo))
            # Marca fim de linha para desifenação (não vira run).
            if out and not out[-1][0].endswith("\n"):
                out.append(("\n", out[-1][1] if out else "normal"))
    return out


def _dehyphenate_and_merge(raw: list[tuple[str, str]]) -> list[TextRun]:
    """Remove hífen de quebra de linha e funde runs adjacentes com o mesmo estilo."""
    if not raw:
        return []

    # Concatena numa fita char+estilo, juntando "-\n" + minúscula.
    chars: list[tuple[str, str]] = []
    i = 0
    flat: list[tuple[str, str]] = []
    for text, estilo in raw:
        for ch in text:
            flat.append((ch, estilo))

    while i < len(flat):
        ch, estilo = flat[i]
        if (
            ch == "-"
            and i + 1 < len(flat)
            and flat[i + 1][0] == "\n"
            and i + 2 < len(flat)
            and flat[i + 2][0].islower()
        ):
            i += 2  # drop '-' and '\n'
            continue
        if ch == "\n":
            # Quebra de linha vira espaço se ambos os lados forem alfanuméricos.
            prev = chars[-1][0] if chars else ""
            nxt = flat[i + 1][0] if i + 1 < len(flat) else ""
            if prev and nxt and not prev.isspace() and not nxt.isspace():
                chars.append((" ", estilo))
            i += 1
            continue
        chars.append((ch, estilo))
        i += 1

    runs: list[TextRun] = []
    buf = ""
    cur_style = "normal"
    for ch, estilo in chars:
        if buf and estilo != cur_style:
            runs.append(TextRun(text=buf, estilo=cur_style))
            buf = ch
            cur_style = estilo
        else:
            if not buf:
                cur_style = estilo
            buf += ch
    if buf:
        runs.append(TextRun(text=buf, estilo=cur_style))
    return runs


def extract_page_text_styles(page: Any, page_number: int) -> PageTextStyles:
    raw = _iter_raw_spans(page)
    runs = _dehyphenate_and_merge(raw)
    char_count = sum(len(run.text) for run in runs)
    return PageTextStyles(page_number=page_number, runs=runs, char_count=char_count)


def extract_text_styles_from_pdf(
    pdf_bytes: bytes,
    *,
    page_start: int = 1,
    page_end: int | None = None,
) -> list[PageTextStyles]:
    """Extrai runs tipográficos de todas as páginas (1-indexed)."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) nao instalado.")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total = doc.page_count
        start = max(1, int(page_start))
        end = int(page_end) if page_end is not None else total
        end = min(end, total)
        pages: list[PageTextStyles] = []
        for idx in range(start - 1, end):
            page = doc.load_page(idx)
            pages.append(extract_page_text_styles(page, page_number=idx + 1))
        return pages
    finally:
        doc.close()


def pages_to_payload(pages: list[PageTextStyles]) -> dict[str, Any]:
    return {
        "pages": [page.to_dict() for page in pages],
        "total_pages": len(pages),
        "total_chars": sum(page.char_count for page in pages),
    }


def pages_from_payload(payload: Any) -> dict[int, PageTextStyles]:
    """Converte artefato/checkpoint em mapa page_number → PageTextStyles."""
    out: dict[int, PageTextStyles] = {}
    if not isinstance(payload, dict):
        return out
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list):
        return out
    for item in raw_pages:
        if not isinstance(item, dict):
            continue
        try:
            page_number = int(item.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if page_number <= 0:
            continue
        runs_raw = item.get("runs") or []
        runs: list[TextRun] = []
        if isinstance(runs_raw, list):
            for run in runs_raw:
                if not isinstance(run, dict):
                    continue
                text = str(run.get("text") or "")
                estilo = str(run.get("estilo") or "normal")
                if estilo not in FONT_STYLES:
                    estilo = "normal"
                if text:
                    runs.append(TextRun(text=text, estilo=estilo))
        char_count = int(item.get("char_count") or sum(len(r.text) for r in runs))
        out[page_number] = PageTextStyles(page_number=page_number, runs=runs, char_count=char_count)
    return out
