"""Extrator de figuras para PDFs de livros didáticos.

Use `extract_figures` no pipeline do livro. Passe `page_images` se a página
já foi rasterizada — a detecção visual reutiliza esse raster; as imagens
nativas e as coordenadas continuam vindo do PDF.
"""

from .consumers import as_avalia_images, as_linear_figures
from .extract import extract_figures, iter_pages
from .models import (
    Anchor,
    DocumentExtraction,
    ExtractedFigure,
    ExtractOptions,
    PageExtraction,
)
from .geometry import BBox

__all__ = [
    "Anchor",
    "BBox",
    "DocumentExtraction",
    "ExtractOptions",
    "ExtractedFigure",
    "PageExtraction",
    "as_avalia_images",
    "as_linear_figures",
    "extract_figures",
    "iter_pages",
]
