from __future__ import annotations

import cv2
import numpy as np

from .detect import RawRegion
from .geometry import BBox
from .models import ExtractOptions, TextBlock
from .pdf_ops import pdf_bbox_to_px


def keep_region(
    region: RawRegion,
    raster: np.ndarray,
    text_blocks: list[TextBlock],
    page_width: float,
    page_height: float,
    sx: float,
    sy: float,
    options: ExtractOptions,
    *,
    native: bool = False,
) -> tuple[bool, float, str]:
    bbox = region.bbox
    size = region.extent or bbox
    page_area = page_width * page_height
    reasons: list[str] = []
    score = 0.55 if native else 0.48

    if size.area < options.min_area_ratio * page_area:
        return False, 0.0, "pequena demais"
    if min(size.width, size.height) < options.min_side_pt:
        return False, 0.0, "lado mínimo"

    if options.skip_full_page_xobjects and bbox.area >= options.full_page_ratio * page_area:
        return False, 0.0, "quase a página inteira"

    if size.aspect_ratio > options.max_aspect_ratio:
        return False, 0.0, "faixa ornamental"

    in_header = bbox.y1 <= page_height * options.header_ratio or (
        bbox.cy < page_height * options.header_ratio and bbox.height < page_height * 0.14
    )
    in_footer = bbox.y0 >= page_height * (1.0 - options.footer_ratio) or (
        bbox.cy > page_height * (1.0 - options.footer_ratio) and bbox.height < page_height * 0.12
    )
    if in_header or in_footer:
        return False, 0.0, "cabeçalho/rodapé"

    text_cov = _text_coverage(bbox, text_blocks)
    if text_cov > options.max_text_coverage and not native:
        return False, 0.0, "majoritariamente texto"
    if not native and _is_title_band(bbox, text_cov, page_width):
        return False, 0.0, "faixa de título"
    if not native and _is_page_panel(bbox, page_width, page_height):
        return False, 0.0, "painel de fundo"
    if not native and bbox.area >= 0.5 * page_area:
        return False, 0.0, "diagramação (metade da página)"
    if text_cov < 0.12:
        score += 0.08

    if not native and region.fill_ratio < options.min_fill_ratio:
        return False, 0.0, "moldura oca"
    if not native and _is_ruled_area(raster, bbox, text_blocks, sx, sy):
        return False, 0.0, "pauta para escrever"

    inner = region.inner_std or _inner_complexity(raster, region.bbox_px)
    if not native and inner < options.min_inner_std:
        return False, 0.0, "fundo liso / callout"
    if native and inner < 2.0:
        return False, 0.0, "imagem lisa"
    if inner > 28:
        score += 0.12
    elif inner > 18:
        score += 0.05

    # Desenho vetorial já foi qualificado pelos próprios paths (contornos curvos
    # e vários preenchimentos); a grade de coordenadas de um mapa parece tabela no raster.
    drawn = region.source in ("pdf_vector", "hybrid")
    if not drawn and _looks_like_table(raster, bbox, text_blocks, sx, sy, text_cov):
        return False, 0.0, "tabela"
    # Carta, ficha catalográfica e parágrafo rasterizado: o PDF não tem texto
    # selecionável, então a cobertura textual fica zero. O mapa vetorial e a
    # foto colorida não entram — o primeiro já saiu em `drawn`, a segunda não
    # tem fundo de papel nem linhas de composição regulares.
    if not drawn and _is_typeset_block(raster, region.bbox_px):
        return False, 0.0, "bloco de texto"

    if native:
        score += 0.18
        reasons.append("xobject")

    return True, min(0.97, score), "ok"


def _is_title_band(bbox: BBox, text_cov: float, page_width: float) -> bool:
    """Faixa com texto: abertura de unidade, cabeçalho de seção ou de quadro.

    A de abertura sangra no topo de borda a borda. As outras são tiras baixas
    e largas — fita colorida, aba com ícone — em que o texto é o conteúdo.
    """
    bleeds = bbox.y0 <= 2.0 and bbox.x0 <= 2.0 and bbox.x1 >= page_width - 2.0
    if bleeds and text_cov >= 0.15:
        return True
    strip = bbox.height <= 130.0 and bbox.width >= 3.0 * bbox.height
    return strip and text_cov >= 0.2


def _is_page_panel(bbox: BBox, page_width: float, page_height: float) -> bool:
    """Área de fundo que sangra em três bordas da página: coluna colorida, página reduzida."""
    edges = sum(
        (bbox.x0 <= 2.0, bbox.y0 <= 2.0, bbox.x1 >= page_width - 2.0, bbox.y1 >= page_height - 2.0)
    )
    return edges >= 3 and bbox.area >= 0.3 * page_width * page_height


def _text_coverage(bbox: BBox, text_blocks: list[TextBlock]) -> float:
    if bbox.area <= 0:
        return 0.0
    covered = 0.0
    for block in text_blocks:
        inter = bbox.intersection(block.bbox)
        if inter:
            covered += inter.area
    return min(1.0, covered / bbox.area)


def _inner_complexity(raster: np.ndarray, bbox_px: BBox) -> float:
    x, y, w, h = bbox_px.as_xywh_int()
    crop = raster[y : y + h, x : x + w]
    if crop.size == 0:
        return 0.0
    m = max(1, min(h, w) // 10)
    inner = crop[m : h - m or None, m : w - m or None]
    if inner.size == 0:
        inner = crop
    return float(inner.std())


def _is_ruled_area(
    raster: np.ndarray,
    bbox: BBox,
    text_blocks: list[TextBlock],
    sx: float,
    sy: float,
) -> bool:
    """Pauta para o estudante escrever: linhas paralelas de lado a lado e nada mais.

    Linha do tempo tem um eixo só; gráfico e tabela têm conteúdo entre as linhas.
    """
    box = pdf_bbox_to_px(bbox, sx, sy)
    x, y, w, h = box.as_xywh_int()
    crop = raster[y : y + h, x : x + w]
    if crop.size == 0 or w < 40 or h < 40:
        return False
    edges = cv2.Canny(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), 40, 120)
    for block in text_blocks:
        inner = pdf_bbox_to_px(block.bbox, sx, sy)
        bx0, by0 = max(0, int(inner.x0) - x), max(0, int(inner.y0) - y)
        bx1, by1 = min(w, int(inner.x1) - x + 1), min(h, int(inner.y1) - y + 1)
        if bx1 > bx0 and by1 > by0:
            edges[by0:by1, bx0:bx1] = 0
    horiz = cv2.morphologyEx(edges, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, w // 2), 1)))
    vert = cv2.morphologyEx(edges, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, h // 2))))
    rows = horiz.sum(axis=1) > 0.6 * w * 255
    rules = int(np.count_nonzero(rows[1:] & ~rows[:-1])) + int(rows[0])
    if rules < 3:
        return False
    lines = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((5, 5), np.uint8))
    rest = cv2.bitwise_and(edges, cv2.bitwise_not(lines))
    return np.count_nonzero(rest) < 0.01 * w * h


def _is_typeset_block(raster: np.ndarray, bbox_px: BBox) -> bool:
    """Parágrafo impresso virado imagem: fundo de papel e linhas de tinta regulares."""
    x, y, w, h = bbox_px.as_xywh_int()
    crop = raster[y : y + h, x : x + w]
    if crop.size == 0 or w < 80 or h < 80:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    if float(np.median(gray)) < 240:
        return False
    ink = gray < 200
    ink_ratio = float(ink.mean())
    if not 0.03 <= ink_ratio <= 0.16:
        return False
    density = ink.mean(axis=1)
    rows = (density > 0.015) & (density < 0.40)
    starts = np.where(rows[1:] & ~rows[:-1])[0] + 1
    if rows[0]:
        starts = np.concatenate([[0], starts])
    merged: list[int] = []
    for start in starts.tolist():
        if not merged or start - merged[-1] >= 8:
            merged.append(start)
    if len(merged) < 8:
        return False
    gaps = np.diff(merged)
    median_gap = float(np.median(gaps))
    if not 12 <= median_gap <= 50:
        return False
    # Poema visual, caligrama e texto em curva não têm nem linhas da mesma
    # altura nem margem; parágrafo, ficha, verbete e quadro lateral têm um dos dois.
    bands = _text_bands(rows)
    return _line_height_spread(bands) <= 2.5 or _left_aligned(ink, bands, w) >= 0.6


def _text_bands(rows: np.ndarray) -> list[tuple[int, int]]:
    """Faixas horizontais contínuas de tinta (linhas de texto), com 3 px ou mais."""
    bands: list[tuple[int, int]] = []
    start = None
    for i, active in enumerate([*rows.tolist(), False]):
        if active and start is None:
            start = i
        elif not active and start is not None:
            if i - start >= 3:
                bands.append((start, i))
            start = None
    return bands


def _left_aligned(ink: np.ndarray, bands: list[tuple[int, int]], width: int) -> float:
    """Fração das linhas que começam na mesma margem esquerda."""
    lefts = []
    for start, end in bands:
        cols = np.flatnonzero(ink[start:end].any(axis=0))
        if cols.size:
            lefts.append(cols[0] / width)
    if len(lefts) < 3:
        return 1.0
    margin = float(np.median(lefts))
    return float(np.mean([abs(left - margin) <= 0.03 for left in lefts]))


def _line_height_spread(bands: list[tuple[int, int]]) -> float:
    """Quanto as faixas de texto mais altas fogem da altura típica de linha.

    Parágrafo, carta, ficha catalográfica e verbete têm linhas da mesma altura.
    Poema visual, caligrama e texto em curva ou na vertical formam faixas
    muito mais altas que uma linha: são figura, não bloco de texto.
    """
    heights = [end - start for start, end in bands]
    if len(heights) < 3:
        return 1.0
    return float(np.percentile(heights, 90) / np.median(heights))


def _looks_like_table(
    raster: np.ndarray,
    bbox: BBox,
    text_blocks: list[TextBlock],
    sx: float,
    sy: float,
    text_cov: float,
) -> bool:
    if text_cov < 0.18:
        return False
    box = pdf_bbox_to_px(bbox, sx, sy)
    x, y, w, h = box.as_xywh_int()
    crop = raster[y : y + h, x : x + w]
    if crop.size == 0 or w < 40 or h < 40:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, w // 10), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, h // 10)))
    horiz = cv2.morphologyEx(edges, cv2.MORPH_OPEN, hk)
    vert = cv2.morphologyEx(edges, cv2.MORPH_OPEN, vk)
    h_rows = int(np.count_nonzero(horiz.sum(axis=1) > 0.45 * w * 255))
    v_cols = int(np.count_nonzero(vert.sum(axis=0) > 0.45 * h * 255))
    return h_rows >= 3 and v_cols >= 3
