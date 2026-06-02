"""
Extração de figuras de PDF via PyMuPDF.

Estratégia (corrige "só a primeira imagem" do fluxo antigo baseado em get_images/xref):
1. page.get_image_info(xrefs=True) — cada *ocorrência* visível na página (mesmo xref repetido conta).
2. Recorte renderizado do bbox — captura inline, máscaras e aparência real no layout.
3. page.cluster_drawings() — agrupamentos vetoriais (tabelas, gráficos, ícones, equações desenhadas).
4. Fallback: página inteira renderizada quando a página não tiver nenhum item.
"""

from __future__ import annotations

import hashlib
import io
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import fitz
from PIL import Image

EMF_FORMATS = {"emf", "wmf"}
EXTENSION_MAP = {"jpg": "jpeg", "jpe": "jpeg"}

PageProgressCallback = Callable[[int, int, list["ExtractedPdfImage"], float, int], None]
"""(page_number, total_pages, items_da_pagina, segundos_na_pagina, ignoradas_na_pagina)"""


@dataclass
class ExtractedPdfImage:
    page_number: int
    image_index: int
    format: str
    image_bytes: bytes
    width_px: int
    height_px: int
    content_hash: str
    source_key: str
    kind: str = "raster"


def extract_images_from_pdf(
    pdf_bytes: bytes,
    *,
    min_width_px: int = 0,
    min_height_px: int = 0,
    dedupe: bool = False,
    merge_nearby_rasters: bool = True,
    merge_tiles_only: bool = True,
    merge_min_count: int = 5,
    merge_gap_pt: float = 14.0,
    render_dpi: int = 150,
    render_fallback_dpi: int | None = 0,
    include_vector_clusters: bool = False,
    filter_decorative: bool = True,
    page_start: int = 1,
    page_end: int | None = None,
    on_page_done: PageProgressCallback | None = None,
) -> list[ExtractedPdfImage]:
    images = list(
        iter_extract_images_from_pdf(
            pdf_bytes,
            min_width_px=min_width_px,
            min_height_px=min_height_px,
            render_dpi=render_dpi,
            render_fallback_dpi=render_fallback_dpi,
            merge_nearby_rasters=merge_nearby_rasters,
            merge_tiles_only=merge_tiles_only,
            merge_min_count=merge_min_count,
            merge_gap_pt=merge_gap_pt,
            include_vector_clusters=include_vector_clusters,
            filter_decorative=filter_decorative,
            page_start=page_start,
            page_end=page_end,
            on_page_done=on_page_done,
        )
    )
    if dedupe:
        images = _dedupe_by_hash(images)
    return images


def iter_extract_images_from_pdf(
    pdf_bytes: bytes,
    *,
    min_width_px: int = 0,
    min_height_px: int = 0,
    render_dpi: int = 150,
    render_fallback_dpi: int | None = 0,
    merge_nearby_rasters: bool = True,
    merge_tiles_only: bool = True,
    merge_min_count: int = 5,
    merge_gap_pt: float = 14.0,
    include_vector_clusters: bool = False,
    filter_decorative: bool = True,
    page_start: int = 1,
    page_end: int | None = None,
    on_page_done: PageProgressCallback | None = None,
) -> Iterator[ExtractedPdfImage]:
    """
    Gera figuras página a página (permite progresso e export incremental).

    page_start/page_end são 1-based e inclusivos.
    """
    dpi = render_dpi if render_dpi > 0 else 150
    fallback_dpi = 0 if render_fallback_dpi is None else max(0, render_fallback_dpi)
    start = max(1, page_start)
    end = page_end

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total_pages = len(doc)
        last_page = end if end is not None else total_pages
        last_page = min(last_page, total_pages)
        if start > last_page:
            return

        pages_in_job = last_page - start + 1
        for page_num in range(start - 1, last_page):
            t0 = time.perf_counter()
            page = doc[page_num]
            page_number = page_num + 1
            page_items, skipped = _extract_page_items(
                doc,
                page,
                page_number=page_number,
                dpi=dpi,
                min_width_px=min_width_px,
                min_height_px=min_height_px,
                merge_nearby_rasters=merge_nearby_rasters,
                merge_tiles_only=merge_tiles_only,
                merge_min_count=merge_min_count,
                merge_gap_pt=merge_gap_pt,
                include_vector_clusters=include_vector_clusters,
                filter_decorative=filter_decorative,
            )
            if not page_items and fallback_dpi > 0:
                page_items = _render_full_page(page, page_number=page_number, dpi=fallback_dpi)
                skipped = 0

            elapsed = time.perf_counter() - t0
            if on_page_done is not None:
                on_page_done(page_number, pages_in_job, page_items, elapsed, skipped)

            for item in page_items:
                yield item
    finally:
        doc.close()


def _extract_page_items(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    page_number: int,
    dpi: int,
    min_width_px: int,
    min_height_px: int,
    merge_nearby_rasters: bool,
    merge_tiles_only: bool,
    merge_min_count: int,
    merge_gap_pt: float,
    include_vector_clusters: bool,
    filter_decorative: bool,
) -> tuple[list[ExtractedPdfImage], int]:
    output: list[ExtractedPdfImage] = []
    skipped = 0
    occurrence = 0

    def try_add(
        png_bytes: bytes,
        width_px: int,
        height_px: int,
        *,
        bbox: fitz.Rect,
        source_key: str,
        kind: str,
    ) -> None:
        nonlocal occurrence, skipped
        if not _passes_min_size(width_px, height_px, min_width_px, min_height_px):
            skipped += 1
            return
        if filter_decorative and _is_decorative_junk(
            png_bytes, width_px, height_px, bbox=bbox, kind=kind
        ):
            skipped += 1
            return
        output.append(
            ExtractedPdfImage(
                page_number=page_number,
                image_index=occurrence,
                format="png",
                image_bytes=png_bytes,
                width_px=width_px,
                height_px=height_px,
                content_hash=hashlib.sha256(png_bytes).hexdigest(),
                source_key=source_key,
                kind=kind,
            )
        )
        occurrence += 1

    try:
        infos = page.get_image_info(xrefs=True, hashes=True)
    except Exception:
        infos = []

    raster_candidates: list[tuple[fitz.Rect, dict]] = []
    for info in infos:
        bbox = fitz.Rect(info.get("bbox") or ())
        if bbox.is_empty or bbox.width < 0.5 or bbox.height < 0.5:
            continue
        if filter_decorative and _bbox_too_small_on_page(bbox, kind="raster"):
            skipped += 1
            continue
        raster_candidates.append((bbox, info))

    page_rect = page.rect
    raw_bboxes = [bbox for bbox, _ in raster_candidates]
    merged_groups = _plan_raster_groups(
        raw_bboxes,
        page_rect=page_rect,
        merge_nearby=merge_nearby_rasters,
        merge_tiles_only=merge_tiles_only,
        merge_min_count=merge_min_count,
        merge_gap_pt=merge_gap_pt,
    )

    for group_index, bbox in enumerate(merged_groups):
        if _is_near_full_page_crop(bbox, page_rect):
            skipped += 1
            continue
        rendered = _render_bbox_clip(page, bbox, dpi=dpi)
        if rendered is None:
            continue

        png_bytes, width_px, height_px = rendered
        source_key = f"pdf:p{page_number}:group{group_index}:{_bbox_key(bbox)}"
        try_add(png_bytes, width_px, height_px, bbox=bbox, source_key=source_key, kind="raster")

    if include_vector_clusters:
        try:
            clusters = page.cluster_drawings()
        except Exception:
            clusters = []
        for cluster_index, bbox in enumerate(clusters):
            rect = fitz.Rect(bbox)
            if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
                continue
            if filter_decorative and _bbox_too_small_on_page(
                rect, kind="vector", relaxed=include_vector_clusters
            ):
                skipped += 1
                continue
            rendered = _render_bbox_clip(page, rect, dpi=dpi)
            if rendered is None:
                continue
            png_bytes, width_px, height_px = rendered
            source_key = f"pdf:p{page_number}:vector{cluster_index}:{_bbox_key(rect)}"
            try_add(png_bytes, width_px, height_px, bbox=rect, source_key=source_key, kind="vector")

    return output, skipped


def _render_bbox_clip(page: fitz.Page, bbox: fitz.Rect, *, dpi: int) -> tuple[bytes, int, int] | None:
    try:
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, clip=bbox, alpha=False)
        if pix.width < 1 or pix.height < 1:
            return None
        return pix.tobytes("png"), pix.width, pix.height
    except Exception:
        return None


def _extract_from_xref(doc: fitz.Document, xref: int, *, dpi: int) -> tuple[bytes, int, int] | None:
    png_bytes = _pixmap_to_rgb_png(doc, xref)
    if png_bytes:
        try:
            width_px, height_px = _image_dimensions(png_bytes)
        except Exception:
            return None
        return png_bytes, width_px, height_px

    try:
        base_image = doc.extract_image(xref)
    except Exception:
        return None
    ext = EXTENSION_MAP.get(base_image["ext"].lower(), base_image["ext"].lower())
    if ext in EMF_FORMATS:
        return None
    raw = base_image.get("image") or b""
    if not raw:
        return None
    try:
        width_px, height_px = _image_dimensions(raw)
    except Exception:
        return None
    return raw, width_px, height_px


def _render_full_page(page: fitz.Page, *, page_number: int, dpi: int) -> list[ExtractedPdfImage]:
    try:
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        raw_bytes = pix.tobytes("png")
    except Exception:
        return []
    return [
        ExtractedPdfImage(
            page_number=page_number,
            image_index=0,
            format="png",
            image_bytes=raw_bytes,
            width_px=pix.width,
            height_px=pix.height,
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            source_key=f"pdf_render:p{page_number}:full",
            kind="page",
        )
    ]


def _pixmap_to_rgb_png(doc: fitz.Document, xref: int) -> bytes | None:
    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception:
        return None
    try:
        if pix.width < 1 or pix.height < 1 or pix.colorspace is None:
            return None
        if pix.colorspace == fitz.csRGB and pix.alpha == 0:
            return pix.tobytes("png")
        rgb = fitz.Pixmap(fitz.csRGB, pix)
        try:
            return rgb.tobytes("png")
        finally:
            rgb = None
    finally:
        pix = None


def _image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.size


def _passes_min_size(width_px: int, height_px: int, min_width_px: int, min_height_px: int) -> bool:
    if min_width_px <= 0 and min_height_px <= 0:
        return True
    if min_width_px > 0 and width_px < min_width_px:
        return False
    if min_height_px > 0 and height_px < min_height_px:
        return False
    return True


def _bbox_too_small_on_page(bbox: fitz.Rect, *, kind: str, relaxed: bool = False) -> bool:
    """Ignora retângulos minúsculos na página (marcadores, quadradinhos de layout)."""
    if kind == "vector":
        min_pt = 14.0 if relaxed else 36.0
    else:
        min_pt = 24.0
    return bbox.width < min_pt or bbox.height < min_pt


def _is_decorative_junk(
    image_bytes: bytes,
    width_px: int,
    height_px: int,
    *,
    bbox: fitz.Rect,
    kind: str,
) -> bool:
    """
    Descarta blocos quase sólidos (ex.: quadrados azuis de máscara/placeholder do PDF)
    e faixas minúsculas sem conteúdo útil.
    """
    area = width_px * height_px
    min_side = min(width_px, height_px)
    min_area = 900 if kind == "vector" else 3600
    min_side_px = 20 if kind == "vector" else 40

    if area < min_area or min_side < min_side_px:
        return True

    aspect = max(width_px, height_px) / max(1, min_side)
    if aspect > 14 and area < 25000:
        return True

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            thumb = img.convert("RGB")
            thumb.thumbnail((96, 96))
            pixels = list(thumb.getdata())
    except Exception:
        return False

    if not pixels:
        return True

    counts = Counter(pixels)
    dominant_rgb, dominant_count = counts.most_common(1)[0]
    coverage = dominant_count / len(pixels)
    if coverage < 0.88:
        return False

    r, g, b = dominant_rgb
    # Placeholder/máscara: azul ou ciano quase puro
    is_blue_block = b >= 120 and b >= r + 25 and b >= g + 15
    is_cyan_block = b >= 120 and g >= 100 and r <= 80 and coverage >= 0.92
    is_gray_block = abs(r - g) < 15 and abs(g - b) < 15 and coverage >= 0.95 and max(r, g, b) < 230

    if is_blue_block or is_cyan_block:
        return True
    # Quadrado pequeno cinza/branco uniforme (caixa de layout)
    if is_gray_block and area < 120000:
        return True
    # Qualquer cor quase 100% uniforme em área moderada = provável artefato
    if coverage >= 0.97 and area < 80000:
        return True

    return False


def _bbox_key(bbox: fitz.Rect) -> str:
    return f"x{int(bbox.x0)}y{int(bbox.y0)}w{int(bbox.width)}h{int(bbox.height)}"


def _plan_raster_groups(
    bboxes: list[fitz.Rect],
    *,
    page_rect: fitz.Rect,
    merge_nearby: bool,
    merge_tiles_only: bool,
    merge_min_count: int,
    merge_gap_pt: float,
) -> list[fitz.Rect]:
    """Define recortes raster: agrupa tiles repetidos; mantém figuras grandes separadas."""
    if not bboxes:
        return []

    if not merge_nearby:
        return [b for b in bboxes if not _is_near_full_page_crop(b, page_rect)]

    tile_bboxes, standalone_bboxes = (
        _partition_tile_and_standalone(bboxes, page_rect)
        if merge_tiles_only
        else (bboxes, [])
    )

    groups: list[fitz.Rect] = []
    merge_pool = tile_bboxes if merge_tiles_only else bboxes
    if len(merge_pool) >= max(2, merge_min_count):
        merged = _merge_raster_bboxes_in_rows(
            merge_pool,
            page_rect=page_rect,
            gap_pt=merge_gap_pt,
        )
        groups.extend(g for g in merged if not _is_near_full_page_crop(g, page_rect))
    else:
        groups.extend(b for b in merge_pool if not _is_near_full_page_crop(b, page_rect))

    if merge_tiles_only:
        groups.extend(b for b in standalone_bboxes if not _is_near_full_page_crop(b, page_rect))

    return groups


def _partition_tile_and_standalone(
    bboxes: list[fitz.Rect],
    page_rect: fitz.Rect,
) -> tuple[list[fitz.Rect], list[fitz.Rect]]:
    """
    Tiles = elementos pequenos e parecidos (cédulas, ícones repetidos).
    Standalone = figuras maiores que devem sair separadas no Word.
    """
    if len(bboxes) < 2:
        return bboxes, []

    areas = sorted(b.width * b.height for b in bboxes)
    median_area = areas[len(areas) // 2]
    page_area = page_rect.width * page_rect.height
    tiles: list[fitz.Rect] = []
    standalone: list[fitz.Rect] = []

    for bbox in bboxes:
        area = bbox.width * bbox.height
        is_tile = (
            area <= max(median_area * 4.0, page_area * 0.07)
            and bbox.width <= page_rect.width * 0.38
            and bbox.height <= page_rect.height * 0.28
        )
        if is_tile:
            tiles.append(bbox)
        else:
            standalone.append(bbox)

    if not tiles:
        return [], bboxes
    return tiles, standalone


def _merge_raster_bboxes_in_rows(
    bboxes: list[fitz.Rect],
    *,
    page_rect: fitz.Rect,
    gap_pt: float,
) -> list[fitz.Rect]:
    """
    Agrupa só imagens na mesma faixa horizontal (ex.: fila de cédulas).
    Não funde entre linhas — evita recorte do tamanho da página inteira.
    """
    if len(bboxes) <= 1:
        return bboxes

    groups: list[fitz.Rect] = []
    for row in _cluster_bboxes_into_rows(bboxes):
        row_sorted = sorted(row, key=lambda r: r.x0)
        current: fitz.Rect | None = None
        for bbox in row_sorted:
            if current is None:
                current = fitz.Rect(bbox)
                continue
            trial = current | bbox
            if _bboxes_same_row(current, bbox, gap_pt=gap_pt) and not _merge_would_exceed_limits(
                trial, page_rect
            ):
                current = trial
            else:
                groups.append(current)
                current = fitz.Rect(bbox)
        if current is not None:
            groups.append(current)
    return groups


def _cluster_bboxes_into_rows(bboxes: list[fitz.Rect]) -> list[list[fitz.Rect]]:
    ordered = sorted(bboxes, key=lambda r: (r.y0 + r.y1) * 0.5)
    heights = sorted(b.height for b in ordered)
    median_h = heights[len(heights) // 2] if heights else 24.0
    row_tol = max(16.0, median_h * 0.65)

    rows: list[list[fitz.Rect]] = []
    current_row: list[fitz.Rect] = [ordered[0]]
    row_center_y = (ordered[0].y0 + ordered[0].y1) * 0.5

    for bbox in ordered[1:]:
        center_y = (bbox.y0 + bbox.y1) * 0.5
        if abs(center_y - row_center_y) <= row_tol:
            current_row.append(bbox)
            row_center_y = sum((r.y0 + r.y1) * 0.5 for r in current_row) / len(current_row)
        else:
            rows.append(current_row)
            current_row = [bbox]
            row_center_y = center_y
    rows.append(current_row)
    return rows


def _bboxes_same_row(a: fitz.Rect, b: fitz.Rect, *, gap_pt: float) -> bool:
    row_tol = max(12.0, min(a.height, b.height) * 0.55)
    if abs((a.y0 + a.y1) * 0.5 - (b.y0 + b.y1) * 0.5) > row_tol:
        return False
    h_gap = max(0.0, max(b.x0 - a.x1, a.x0 - b.x1))
    return h_gap <= gap_pt


def _bbox_page_fractions(bbox: fitz.Rect, page_rect: fitz.Rect) -> tuple[float, float, float]:
    page_area = page_rect.width * page_rect.height
    if page_area <= 0:
        return 0.0, 0.0, 0.0
    area_ratio = (bbox.width * bbox.height) / page_area
    w_ratio = bbox.width / page_rect.width
    h_ratio = bbox.height / page_rect.height
    return area_ratio, w_ratio, h_ratio


def _merge_would_exceed_limits(bbox: fitz.Rect, page_rect: fitz.Rect) -> bool:
    area_ratio, w_ratio, h_ratio = _bbox_page_fractions(bbox, page_rect)
    if area_ratio > 0.24:
        return True
    if w_ratio > 0.78 or h_ratio > 0.55:
        return True
    return False


def _is_near_full_page_crop(bbox: fitz.Rect, page_rect: fitz.Rect) -> bool:
    """Recorte que cobre a maior parte da página (print da folha inteira)."""
    area_ratio, w_ratio, h_ratio = _bbox_page_fractions(bbox, page_rect)
    if w_ratio > 0.68 and h_ratio > 0.68:
        return True
    if area_ratio > 0.32:
        return True
    if w_ratio > 0.82 or h_ratio > 0.82:
        return True
    return False


def _dedupe_by_hash(images: list[ExtractedPdfImage]) -> list[ExtractedPdfImage]:
    seen: set[str] = set()
    unique: list[ExtractedPdfImage] = []
    for img in images:
        if img.content_hash in seen:
            continue
        seen.add(img.content_hash)
        unique.append(img)
    return unique
