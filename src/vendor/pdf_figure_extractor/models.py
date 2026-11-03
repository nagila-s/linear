from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import numpy as np

from .geometry import BBox

FigureSource = Literal["pdf_xobject", "pdf_vector", "visual_edges", "hybrid"]


@dataclass(frozen=True, slots=True)
class ExtractOptions:
    """Limiares pensados para página de livro didático (A5/A4)."""

    dpi: int = 160
    min_area_ratio: float = 0.012
    min_side_pt: float = 48.0
    header_ratio: float = 0.07
    footer_ratio: float = 0.06
    max_aspect_ratio: float = 8.0
    min_fill_ratio: float = 0.08
    max_text_coverage: float = 0.42
    min_inner_std: float = 10.0
    merge_gap_pt: float = 14.0
    crop_padding_pt: float = 4.0
    # PNG entregue: renderizado do PDF, com o lado maior entre estes limites.
    crop_min_long_px: int = 768
    crop_max_long_px: int = 2048
    crop_max_dpi: int = 400
    # Imagens pequenas demais sozinhas entram quando formam grade (cédulas,
    # fotos de animais lado a lado): duas ou mais, de tamanho parecido, alinhadas.
    grid_min_area_ratio: float = 0.004
    grid_min_side_pt: float = 30.0
    use_native: bool = True
    use_visual: bool = True
    skip_full_page_xobjects: bool = True
    full_page_ratio: float = 0.85
    pages: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class TextBlock:
    bbox: BBox
    text: str
    index: int


@dataclass(frozen=True, slots=True)
class Anchor:
    text: str
    bbox: BBox
    block_index: int

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "block_index": self.block_index,
        }


@dataclass(slots=True)
class ExtractedFigure:
    id: str
    page: int
    page_width: float
    page_height: float
    bbox: BBox
    bbox_px: BBox
    png_bytes: bytes
    source: FigureSource
    confidence: float
    caption: str | None
    anchor: Anchor | None
    reading_order: int
    file_name: str | None = None

    def to_dict(self, *, include_image: bool = False) -> dict:
        payload: dict = {
            "id": self.id,
            "page": self.page,
            "page_width": round(self.page_width, 2),
            "page_height": round(self.page_height, 2),
            "bbox": self.bbox.to_dict(),
            "bbox_px": self.bbox_px.to_dict(),
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "caption": self.caption,
            "anchor": self.anchor.to_dict() if self.anchor else None,
            "reading_order": self.reading_order,
            "file_name": self.file_name,
        }
        if include_image:
            import base64

            payload["png_base64"] = base64.b64encode(self.png_bytes).decode("ascii")
        return payload


@dataclass(slots=True)
class PageExtraction:
    page: int
    width: float
    height: float
    raster_width: int
    raster_height: int
    figures: list[ExtractedFigure] = field(default_factory=list)
    text_blocks: list[TextBlock] = field(default_factory=list)
    # Preenchido quando a página falhou; as demais seguem normalmente.
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "width": round(self.width, 2),
            "height": round(self.height, 2),
            "raster_width": self.raster_width,
            "raster_height": self.raster_height,
            "figures": [fig.to_dict() for fig in self.figures],
            "error": self.error,
        }


@dataclass(slots=True)
class DocumentExtraction:
    source_name: str | None
    page_count: int
    figures: list[ExtractedFigure]
    pages: list[PageExtraction]

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "page_count": self.page_count,
            "figure_count": len(self.figures),
            "figures": [fig.to_dict() for fig in self.figures],
            "pages": [page.to_dict() for page in self.pages],
        }


# Página 1-based -> RGB uint8 (H, W, 3), já produzida pelo pipeline do livro.
PageImages = Mapping[int, np.ndarray]
