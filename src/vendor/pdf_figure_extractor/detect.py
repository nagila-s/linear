from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import BBox, merge_nearby
from .models import ExtractOptions, TextBlock
from .pdf_ops import pdf_bbox_to_px


@dataclass(slots=True)
class RawRegion:
    bbox: BBox
    bbox_px: BBox
    source: str
    fill_ratio: float = 1.0
    inner_std: float = 0.0
    # Imagem aparada pela transparência: tamanho e proporção são julgados pela
    # área cheia, calibrada assim; posição e recorte, pelo bbox aparado.
    extent: BBox | None = None
    # xref da imagem embutida; cópias da mesma imagem têm o mesmo.
    xref: int | None = None


def detect_visual_regions(
    raster: np.ndarray,
    text_blocks: list[TextBlock],
    page_width: float,
    page_height: float,
    sx: float,
    sy: float,
    options: ExtractOptions,
    known: list[BBox] | None = None,
) -> list[RawRegion]:
    """Detecta figuras no raster da página por diferença de pixels, com texto apagado.

    `known` são as figuras que o PDF já descreve (imagem embutida, mapa
    vetorial). Ficam fora da detecção: o raster só procura o que sobra, e uma
    mancha não pode colar duas fotos vizinhas nem a foto na faixa de título.
    """
    work = _suppress_text(raster, text_blocks, sx, sy)
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    scanned = _looks_scanned(text_blocks, page_width, page_height)
    if scanned:
        textish = _text_like_mask(gray)
        work[textish > 0] = _background_color(raster)
        gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)

    diff = _pixel_difference_map(gray)
    text_mask = _text_mask(raster.shape[:2], text_blocks, sx, sy, dilate_px=int(round(3 * sx)))
    if scanned:
        text_mask = cv2.bitwise_or(text_mask, _text_like_mask(gray))
    if known:
        known_mask = _box_mask(raster.shape[:2], known, sx, sy, dilate_px=int(round(3 * sx)))
        text_mask = cv2.bitwise_or(text_mask, known_mask)
    diff[text_mask > 0] = 0

    _, binary = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary[text_mask > 0] = 0

    close_w = max(7, int(round(page_width * sx / 90)))
    close_h = max(7, int(round(page_height * sy / 90)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_w, close_h))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    closed = cv2.dilate(closed, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))

    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    boxes: list[BBox] = []
    extra: dict[tuple[int, int, int, int], tuple[float, float]] = {}
    for label in range(1, n_labels):
        x, y, w, h, area = stats[label]
        if w < 8 or h < 8:
            continue
        bbox_px = BBox(float(x), float(y), float(w), float(h))
        bbox = BBox(x / sx, y / sy, w / sx, h / sy)
        boxes.append(bbox)
        extra[bbox.as_xywh_int()] = (area / max(w * h, 1), _inner_std(raster, bbox_px))

    merged = merge_nearby(boxes, options.merge_gap_pt)
    regions: list[RawRegion] = []
    for bbox in merged:
        bbox_px = pdf_bbox_to_px(bbox, sx, sy)
        fill_ratio, inner_std = extra.get(bbox.as_xywh_int(), (1.0, _inner_std(raster, bbox_px)))
        regions.append(
            RawRegion(
                bbox=bbox,
                bbox_px=bbox_px,
                source="visual_edges",
                fill_ratio=fill_ratio,
                inner_std=inner_std,
            )
        )
    return regions


def _pixel_difference_map(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    g = blur.astype(np.int16)
    mag = np.zeros(gray.shape, dtype=np.float32)
    dx = np.abs(g[:, 1:] - g[:, :-1])
    dy = np.abs(g[1:, :] - g[:-1, :])
    mag[:, 1:] += dx
    mag[:, :-1] += dx
    mag[1:, :] += dy
    mag[:-1, :] += dy
    mag /= 4.0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    morph = cv2.morphologyEx(blur, cv2.MORPH_GRADIENT, kernel).astype(np.float32)
    combined = 0.65 * mag + 0.35 * morph
    return np.clip(combined, 0, 255).astype(np.uint8)


def _background_color(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[:2]
    mh, mw = max(1, h // 40), max(1, w // 40)
    patches = [
        rgb[:mh, :mw],
        rgb[:mh, w - mw :],
        rgb[h - mh :, :mw],
        rgb[h - mh :, w - mw :],
    ]
    stacked = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)
    return np.median(stacked, axis=0).astype(np.uint8)


def _text_mask(
    shape_hw: tuple[int, int],
    text_blocks: list[TextBlock],
    sx: float,
    sy: float,
    dilate_px: int,
) -> np.ndarray:
    return _box_mask(shape_hw, [block.bbox for block in text_blocks], sx, sy, dilate_px)


def _box_mask(
    shape_hw: tuple[int, int],
    boxes: list[BBox],
    sx: float,
    sy: float,
    dilate_px: int,
) -> np.ndarray:
    mask = np.zeros(shape_hw, dtype=np.uint8)
    h, w = shape_hw
    for bbox in boxes:
        box = pdf_bbox_to_px(bbox, sx, sy).padded(dilate_px, w, h)
        x, y, bw, bh = box.as_xywh_int()
        mask[y : y + bh, x : x + bw] = 255
    return mask


def _suppress_text(
    raster: np.ndarray,
    text_blocks: list[TextBlock],
    sx: float,
    sy: float,
) -> np.ndarray:
    out = raster.copy()
    bg = _background_color(raster)
    h, w = out.shape[:2]
    dilate = max(2, int(round(2.5 * sx)))
    for block in text_blocks:
        box = pdf_bbox_to_px(block.bbox, sx, sy).padded(dilate, w, h)
        x, y, bw, bh = box.as_xywh_int()
        out[y : y + bh, x : x + bw] = bg
    return out


def _looks_scanned(text_blocks: list[TextBlock], page_width: float, page_height: float) -> bool:
    if not text_blocks:
        return True
    covered = sum(b.bbox.area for b in text_blocks)
    return covered < 0.04 * page_width * page_height


def _text_like_mask(gray: np.ndarray) -> np.ndarray:
    """Aproxima linhas de texto em página escaneada (projeção / traços horizontais)."""
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 35, 15
    )
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(18, gray.shape[1] // 40), 2))
    lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    glyphs = cv2.morphologyEx(binary, cv2.MORPH_OPEN, small)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(glyphs, connectivity=8)
    w, h, area = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT], stats[:, cv2.CC_STAT_AREA]
    is_glyph = (h >= 2) & (h <= 28) & (w >= 2) & (w <= 80) & (area < 900)
    is_glyph[0] = False  # rótulo 0 é o fundo
    glyph_mask = np.where(is_glyph[labels], 255, 0).astype(np.uint8)
    merged = cv2.bitwise_or(lines, glyph_mask)
    return cv2.dilate(merged, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 7)))


def _inner_std(raster: np.ndarray, bbox_px: BBox) -> float:
    x, y, w, h = bbox_px.as_xywh_int()
    crop = raster[y : y + h, x : x + w]
    if crop.size == 0:
        return 0.0
    m = max(1, min(crop.shape[0], crop.shape[1]) // 10)
    inner = crop[m : crop.shape[0] - m or None, m : crop.shape[1] - m or None]
    if inner.size == 0:
        inner = crop
    return float(inner.std())
