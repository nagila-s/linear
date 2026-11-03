"""
Extrator de figuras v3 (src/vendor/pdf_figure_extractor) no contrato do Linear.

Devolve a mesma `ExtractedPdfImage` do extrator atual (`pdf_images.py`), para que
upload, banco, linearização e Dorina não mudem. O que muda é a extração:

- `image_index` segue a ordem de leitura da página (colunas, depois fileiras), a
  mesma em que a IA numera `fig1..N`;
- fotos grandes, mapas e diagramas vetoriais entram; fundo, cabeçalho, tabela e
  caixa pedagógica ficam de fora;
- o PNG é renderizado do PDF em cor, com o lado maior entre 768 e 2048 px.

A página sem figura recebe a página inteira, como no extrator atual: o contexto
de figuras da linearização só liga quando a página tem alguma `figure_key`.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

import fitz

from src.pipeline.steps.pdf_images import ExtractedPdfImage, _render_full_page

if TYPE_CHECKING:
    from src.vendor.pdf_figure_extractor import ExtractedFigure

logger = logging.getLogger(__name__)

# Muda junto com a cópia vendorizada: invalida o extract_checkpoint de jobs antigos.
EXTRACTOR_VERSION = "v3@8aeb965"

_KIND_BY_SOURCE = {
    "pdf_xobject": "raster",
    "hybrid": "raster",
    "pdf_vector": "vector",
    "visual_edges": "vector",
}


def extract_images_v3(
    pdf_bytes: bytes,
    *,
    render_fallback_dpi: int | None = 0,
) -> list[ExtractedPdfImage]:
    return list(iter_extract_images_v3(pdf_bytes, render_fallback_dpi=render_fallback_dpi))


def iter_extract_images_v3(
    pdf_bytes: bytes,
    *,
    render_fallback_dpi: int | None = 0,
) -> Iterator[ExtractedPdfImage]:
    """Uma página por vez; só os PNGs da página corrente ficam em memória."""
    # Import tardio: sem OpenCV no ambiente, só o v3 falha — o worker e o legacy seguem.
    from src.vendor.pdf_figure_extractor import ExtractOptions, iter_pages

    fallback_dpi = max(0, render_fallback_dpi or 0)
    doc: fitz.Document | None = None
    try:
        for page in iter_pages(pdf_bytes, options=ExtractOptions()):
            if page.error:
                logger.warning("Extrator v3 falhou na página %s: %s", page.page, page.error)
            if page.figures:
                for figure in page.figures:
                    yield _to_linear(figure)
                continue
            if fallback_dpi:
                doc = doc or fitz.open(stream=pdf_bytes, filetype="pdf")
                yield from _render_full_page(doc[page.page - 1], page_number=page.page, dpi=fallback_dpi)
    finally:
        if doc is not None:
            doc.close()


def _to_linear(figure: ExtractedFigure) -> ExtractedPdfImage:
    png = figure.png_bytes
    box = figure.bbox
    return ExtractedPdfImage(
        page_number=figure.page,
        image_index=figure.reading_order,
        format="png",
        image_bytes=png,
        width_px=int.from_bytes(png[16:20], "big"),
        height_px=int.from_bytes(png[20:24], "big"),
        content_hash=hashlib.sha256(png).hexdigest(),
        source_key=(
            f"pdf:p{figure.page}:{figure.source}:"
            f"x{int(box.x)}y{int(box.y)}w{int(box.width)}h{int(box.height)}"
        ),
        kind=_KIND_BY_SOURCE.get(figure.source, "raster"),
        meta={
            "extractor": EXTRACTOR_VERSION,
            "bbox": box.to_dict(),
            "source": figure.source,
            "confidence": round(figure.confidence, 3),
            "caption": figure.caption,
            "anchor": figure.anchor.text if figure.anchor else None,
        },
    )
