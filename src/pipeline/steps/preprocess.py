import io
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
from pdf2image import convert_from_bytes, pdfinfo_from_bytes
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class PageArtifact:
    page_number: int
    page_name: str
    page_png: bytes
    width_px: int
    height_px: int
    # Mantido só por compatibilidade com heurística legada; o pipeline v2 não retém RGB.
    source_rgb_image: Optional[Image.Image] = None


@dataclass
class FigureArtifact:
    page_number: int
    figure_key: str
    figure_index: int
    page_folder: str
    figure_name: str
    figure_png: bytes


def _pdf_page_count(pdf_bytes: bytes) -> int:
    info = pdfinfo_from_bytes(pdf_bytes)
    pages = int(info.get("Pages") or 0)
    if pages <= 0:
        raise ValueError("Nao foi possivel determinar o numero de paginas do PDF.")
    return pages


def count_pdf_pages(pdf_bytes: bytes) -> int:
    """Contagem leve de paginas (PyMuPDF), com fallback Poppler."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            pages = int(doc.page_count)
        finally:
            doc.close()
        if pages > 0:
            return pages
    except Exception:  # noqa: BLE001
        logger.debug("PyMuPDF falhou na contagem de paginas; tentando Poppler.", exc_info=True)
    return _pdf_page_count(pdf_bytes)

def preprocess_pdf(
    pdf_bytes: bytes,
    dpi: int = 150,
    *,
    batch_size: int = 10,
    keep_rgb: bool = False,
) -> List[PageArtifact]:
    """Rasteriza o PDF em lotes para limitar o pico de memoria.

    Por padrao nao retém `source_rgb_image` (só width/height + PNG grayscale).
    """
    total_pages = _pdf_page_count(pdf_bytes)
    batch = max(1, int(batch_size))
    output: List[PageArtifact] = []

    for first_page in range(1, total_pages + 1, batch):
        last_page = min(first_page + batch - 1, total_pages)
        pages_rgb = convert_from_bytes(
            pdf_bytes,
            dpi=dpi,
            fmt="png",
            first_page=first_page,
            last_page=last_page,
        )
        try:
            for offset, img in enumerate(pages_rgb):
                page_number = first_page + offset
                width_px, height_px = img.size
                grayscale = img.convert("L")
                page_name = f"p{page_number:04}.png"
                buffer = io.BytesIO()
                grayscale.save(buffer, format="PNG")
                grayscale.close()

                rgb_keep: Optional[Image.Image] = None
                if keep_rgb:
                    rgb_keep = img.copy()

                output.append(
                    PageArtifact(
                        page_number=page_number,
                        page_name=page_name,
                        page_png=buffer.getvalue(),
                        width_px=width_px,
                        height_px=height_px,
                        source_rgb_image=rgb_keep,
                    )
                )
                img.close()
        finally:
            for img in pages_rgb:
                try:
                    img.close()
                except Exception:
                    pass
            pages_rgb.clear()

        logger.info(
            "preprocess batch pages=%s-%s/%s dpi=%s",
            first_page,
            last_page,
            total_pages,
            dpi,
        )

    return output


def extract_figures_from_page(page: PageArtifact) -> List[FigureArtifact]:
    """
    Heuristica inicial: se pagina tem conteudo colorido relevante, salva uma figura unica.
    Em producao, esta etapa deve ser substituida por detector com bbox por elemento.
    """
    if page.source_rgb_image is not None:
        source = page.source_rgb_image.convert("RGB")
    else:
        source = Image.open(io.BytesIO(page.page_png)).convert("RGB")

    rgb = np.array(source)
    if page.source_rgb_image is None:
        source.close()

    color_distance = np.abs(rgb[:, :, 0] - rgb[:, :, 1]) + np.abs(rgb[:, :, 1] - rgb[:, :, 2])
    colorful_pixels = int((color_distance > 24).sum())
    ratio = colorful_pixels / float(rgb.shape[0] * rgb.shape[1])
    if ratio < 0.01:
        return []

    figure_name = "fig0001.png"
    figure_key = f"p{page.page_number:04}_fig0001"
    page_folder = f"p{page.page_number:04}"
    buffer = io.BytesIO()
    if page.source_rgb_image is not None:
        page.source_rgb_image.save(buffer, format="PNG")
    else:
        Image.fromarray(rgb).save(buffer, format="PNG")
    return [
        FigureArtifact(
            page_number=page.page_number,
            figure_key=figure_key,
            figure_index=1,
            page_folder=page_folder,
            figure_name=figure_name,
            figure_png=buffer.getvalue(),
        )
    ]


def map_figures_by_page(figures: List[FigureArtifact]) -> Dict[int, List[FigureArtifact]]:
    grouped: Dict[int, List[FigureArtifact]] = {}
    for figure in figures:
        grouped.setdefault(figure.page_number, []).append(figure)
    return grouped
