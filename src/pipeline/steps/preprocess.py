import io
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
from pdf2image import convert_from_bytes
from PIL import Image


@dataclass
class PageArtifact:
    page_number: int
    page_name: str
    page_png: bytes
    source_rgb_image: Image.Image


@dataclass
class FigureArtifact:
    page_number: int
    figure_key: str
    figure_index: int
    page_folder: str
    figure_name: str
    figure_png: bytes


def preprocess_pdf(pdf_bytes: bytes, dpi: int = 150) -> List[PageArtifact]:
    pages_rgb = convert_from_bytes(pdf_bytes, dpi=dpi, fmt="png")
    output: List[PageArtifact] = []
    for idx, img in enumerate(pages_rgb, start=1):
        grayscale = img.convert("L")
        page_name = f"p{idx:04}.png"
        buffer = io.BytesIO()
        grayscale.save(buffer, format="PNG")
        output.append(
            PageArtifact(
                page_number=idx,
                page_name=page_name,
                page_png=buffer.getvalue(),
                source_rgb_image=img,
            )
        )
    return output


def extract_figures_from_page(page: PageArtifact) -> List[FigureArtifact]:
    """
    Heuristica inicial: se pagina tem conteudo colorido relevante, salva uma figura unica.
    Em producao, esta etapa deve ser substituida por detector com bbox por elemento.
    """
    rgb = np.array(page.source_rgb_image.convert("RGB"))
    color_distance = np.abs(rgb[:, :, 0] - rgb[:, :, 1]) + np.abs(rgb[:, :, 1] - rgb[:, :, 2])
    colorful_pixels = int((color_distance > 24).sum())
    ratio = colorful_pixels / float(rgb.shape[0] * rgb.shape[1])
    if ratio < 0.01:
        return []

    figure_name = "fig0001.png"
    figure_key = f"p{page.page_number:04}_fig0001"
    page_folder = f"p{page.page_number:04}"
    buffer = io.BytesIO()
    page.source_rgb_image.save(buffer, format="PNG")
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
