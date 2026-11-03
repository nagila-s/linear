from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import pymupdf

from .annotate import CAPTION_RE, column_gutter, find_anchor, find_caption, reading_ordered
from .detect import RawRegion, detect_visual_regions
from .filters import keep_region
from .geometry import BBox, merge_nearby
from .models import (
    DocumentExtraction,
    ExtractedFigure,
    ExtractOptions,
    PageExtraction,
    PageImages,
)
from .pdf_ops import (
    load_text_blocks,
    native_images,
    open_document,
    page_scale,
    page_text,
    pdf_bbox_to_px,
    render_page,
    running_text_lines,
    vector_figure_bboxes,
)

logger = logging.getLogger(__name__)


def extract_figures(
    pdf: str | Path | bytes,
    *,
    page_images: PageImages | None = None,
    options: ExtractOptions | None = None,
    source_name: str | None = None,
) -> DocumentExtraction:
    """Extrai figuras de um PDF didático.

    As duas fontes entram em estágios diferentes: os XObjects dão a posição
    **no PDF**, antes de qualquer raster, e a detecção por bordas corre **no
    raster da página**. O PNG, porém, é sempre o recorte do raster — tanto
    para XObject quanto para figura vetorial — porque é ali que a figura
    aparece como o leitor a vê, já sem o texto ao redor.

    Se o pipeline de livros já transformou a página em imagem, passe
    `page_images` (página 1-based → RGB) para não rasterizar de novo.
    """
    if isinstance(pdf, (str, Path)):
        source_name = source_name or Path(pdf).name
    doc = open_document(pdf)
    try:
        pages_out = list(_iter_document(doc, page_images, options or ExtractOptions()))
        return DocumentExtraction(
            source_name=source_name,
            page_count=doc.page_count,
            figures=[figure for page in pages_out for figure in page.figures],
            pages=pages_out,
        )
    finally:
        doc.close()


def iter_pages(
    pdf: str | Path | bytes,
    *,
    page_images: PageImages | None = None,
    options: ExtractOptions | None = None,
) -> Iterator[PageExtraction]:
    """Uma página por vez, para quem grava as figuras à medida que saem.

    `extract_figures` guarda os PNGs do livro inteiro em memória; aqui só os
    da página corrente.
    """
    doc = open_document(pdf)
    try:
        yield from _iter_document(doc, page_images, options or ExtractOptions())
    finally:
        doc.close()


def _iter_document(doc, page_images: PageImages | None, options: ExtractOptions) -> Iterator[PageExtraction]:
    """Uma página com defeito vira página sem figura e com `error`; o livro segue."""
    wanted = set(options.pages) if options.pages else None
    for index, page in enumerate(doc, start=1):
        if wanted is not None and index not in wanted:
            continue
        try:
            yield _extract_page(page, index, page_images, options)
        except Exception as exc:  # noqa: BLE001 — uma página não derruba o livro
            logger.exception("Falha ao extrair figuras da página %s", index)
            yield PageExtraction(
                page=index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                raster_width=0,
                raster_height=0,
                error=f"{type(exc).__name__}: {exc}",
            )


def _extract_page(page, page_number: int, page_images: PageImages | None, options: ExtractOptions) -> PageExtraction:
    text = page_text(page)
    text_blocks = load_text_blocks(page, text)
    raster = _page_raster(page, page_number, page_images, options.dpi)
    sx, sy = page_scale(page, raster)
    page_w, page_h = float(page.rect.width), float(page.rect.height)

    def passes(region: RawRegion, structural: bool) -> bool:
        ok, _, _ = keep_region(
            region, raster, text_blocks, page_w, page_h, sx, sy, options, native=structural
        )
        return ok

    structure: list[RawRegion] = []
    rescued: list[RawRegion] = []
    backdrops: list[BBox] = []
    if options.use_native:
        lines = running_text_lines(page, text=text)
        images = []
        for image in native_images(page, text):
            # Recorte com transparência é desenho solto (personagem, objeto), não fundo.
            if not image.has_alpha and _is_backdrop(image.bbox, lines, page_w * page_h, options.full_page_ratio):
                backdrops.append(image.bbox)
            else:
                images.append(_raw(image.bbox, "pdf_xobject", sx, sy, extent=image.extent, xref=image.xref))
        # As fatias de uma imagem cortada só passam no tamanho mínimo depois de juntas.
        images = _join_tiles(images)
        kept_images = [region for region in images if passes(region, True)]
        rescued = _rescue_row_siblings(images, kept_images, options, page_w * page_h)
        small = replace(options, min_area_ratio=options.grid_min_area_ratio, min_side_pt=options.grid_min_side_pt)
        rescued += _rescue_grids(
            [region for region in images if not any(region is other for other in kept_images + rescued)],
            lambda region: keep_region(region, raster, text_blocks, page_w, page_h, sx, sy, small, native=True)[0],
            options.merge_gap_pt,
            page_w * page_h,
        )
        kept_images += rescued
        vectors = [_raw(bbox, "pdf_vector", sx, sy) for bbox in vector_figure_bboxes(page, text)]
        vectors = [region for region in vectors if passes(region, True)]
        structure = _combine_structure(_group_images(kept_images), vectors)

    visual: list[RawRegion] = []
    if options.use_visual:
        known = [region.bbox for region in structure]
        found = detect_visual_regions(
            raster, text_blocks, page_w, page_h, sx, sy, options, known=known + backdrops
        )
        visual = [region for region in found if passes(region, False)]
        visual = _merge_regions(visual, options.merge_gap_pt)
        visual = _merge_by_shared_caption(visual, text_blocks, page_h)
        visual = _merge_aligned_panels(visual, text_blocks, page_w, page_h)
        visual = [
            region
            for region in visual
            if not _already_known(region.bbox, known + backdrops, options.merge_gap_pt)
            and not _wraps_known(region.bbox, known)
        ]

    accepted: list[tuple[RawRegion, float]] = []
    for region in structure + visual:
        region.bbox_px = pdf_bbox_to_px(region.bbox, sx, sy)
        structural = region.source != "visual_edges"
        ok, conf, _ = keep_region(
            region, raster, text_blocks, page_w, page_h, sx, sy, options, native=structural
        )
        if ok:
            accepted.append((region, conf))
        elif any(region is sibling for sibling in rescued):
            accepted.append((region, 0.6))

    body_text = [
        block
        for block in text_blocks
        if not any(region.bbox.coverage_of(block.bbox) >= 0.5 for region, _ in accepted)
    ]
    gutter = column_gutter(body_text, page_w, page_h)
    extracted: list[ExtractedFigure] = []
    for region, conf in reading_ordered(accepted, lambda item: item[0].bbox, gutter):
        crop = _pad_avoiding_text(region.bbox, options.crop_padding_pt, text_blocks, page_w, page_h)
        png = _render_crop(page, crop, options)
        if png is None:
            continue
        order_index = len(extracted) + 1
        caption = find_caption(region.bbox, text_blocks, page_h)
        anchor = find_anchor(region.bbox, text_blocks, page_width=page_w, page_height=page_h)
        if caption:
            conf = min(0.98, conf + 0.08)
        fig_id = f"p{page_number}-f{order_index}"
        source = region.source
        extracted.append(
            ExtractedFigure(
                id=fig_id,
                page=page_number,
                page_width=page_w,
                page_height=page_h,
                bbox=region.bbox,
                bbox_px=region.bbox_px,
                png_bytes=png,
                source=source,
                confidence=conf,
                caption=caption,
                anchor=anchor,
                reading_order=order_index,
                file_name=f"page-{page_number:03d}-fig-{order_index:02d}.png",
            )
        )

    return PageExtraction(
        page=page_number,
        width=page_w,
        height=page_h,
        raster_width=int(raster.shape[1]),
        raster_height=int(raster.shape[0]),
        figures=extracted,
        text_blocks=text_blocks,
    )


def _page_raster(page, page_number: int, page_images: PageImages | None, dpi: int) -> np.ndarray:
    if page_images and page_number in page_images:
        return _as_rgb(page_images[page_number], page_number)
    return render_page(page, dpi)


def _as_rgb(img: np.ndarray, page_number: int) -> np.ndarray:
    """Aceita RGB ou escala de cinza e devolve RGB contíguo (H, W, 3).

    O Linear rasteriza em cinza por padrão para conter memória. A detecção
    visual já opera em cinza (`detect.py` converte RGB→GRAY), então o recorte
    e as bordas continuam válidos. O que se perde é cor no PNG entregue e no
    palpite de fundo (`_background_color` usa os cantos): em cinza os três
    canais são iguais, e uma figura colorida sobre fundo colorido fica mais
    difícil de separar. Não inventamos cor — só repetimos o canal único.
    """
    arr = np.ascontiguousarray(img)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.ndim == 3 and arr.shape[2] >= 3:
        arr = arr[:, :, :3]
    else:
        raise ValueError(
            f"page_images[{page_number}] precisa ser RGB (H, W, 3) ou cinza (H, W); "
            f"recebido shape={getattr(img, 'shape', None)}"
        )
    return np.ascontiguousarray(arr)


def _merge_regions(regions: list[RawRegion], gap: float) -> list[RawRegion]:
    if not regions:
        return []
    boxes = [r.bbox for r in regions]
    merged_boxes = merge_nearby(boxes, gap)
    result: list[RawRegion] = []
    used = [False] * len(regions)
    for box in merged_boxes:
        members: list[RawRegion] = []
        for i, region in enumerate(regions):
            if used[i]:
                continue
            if box.iou(region.bbox) > 0.15 or box.coverage_of(region.bbox) >= 0.7:
                members.append(region)
                used[i] = True
        if not members:
            continue
        sources = {m.source for m in members}
        if sources == {"pdf_xobject"}:
            source = "pdf_xobject"
        elif "pdf_xobject" in sources and "visual_edges" in sources:
            source = "hybrid"
        else:
            source = "visual_edges"
        fill = max(m.fill_ratio for m in members)
        inner = max(m.inner_std for m in members)
        # bbox_px is filled later by caller via region; keep a dummy scaled later
        result.append(
            RawRegion(
                bbox=box,
                bbox_px=_union_px(members, box),
                source=source,
                fill_ratio=fill,
                inner_std=inner,
            )
        )
    return result


def _merge_by_shared_caption(
    regions: list[RawRegion],
    text_blocks: list,
    page_height: float,
) -> list[RawRegion]:
    """Une painéis (a)(b) que compartilham a mesma legenda 'Figura N'."""
    if len(regions) < 2:
        return regions
    slack = max(64.0, page_height * 0.09)
    consumed = [False] * len(regions)
    out: list[RawRegion] = []
    captions = [b for b in text_blocks if CAPTION_RE.search(b.text)]
    for caption in captions:
        members_idx = [
            i
            for i, region in enumerate(regions)
            if not consumed[i]
            and 0 <= (caption.bbox.y0 - region.bbox.y1) <= slack
            and region.bbox.overlap_ratio_x(caption.bbox) >= 0.15
        ]
        if len(members_idx) < 2:
            continue
        acc = regions[members_idx[0]]
        box = acc.bbox
        sources = {acc.source}
        fill = acc.fill_ratio
        inner = acc.inner_std
        for i in members_idx:
            consumed[i] = True
            box = box.union(regions[i].bbox)
            sources.add(regions[i].source)
            fill = max(fill, regions[i].fill_ratio)
            inner = max(inner, regions[i].inner_std)
        source = "hybrid" if len(sources) > 1 else next(iter(sources))
        out.append(RawRegion(bbox=box, bbox_px=acc.bbox_px, source=source, fill_ratio=fill, inner_std=inner))
    for i, region in enumerate(regions):
        if not consumed[i]:
            out.append(region)
    return out


def _merge_aligned_panels(
    regions: list[RawRegion],
    text_blocks: list,
    page_width: float,
    page_height: float,
) -> list[RawRegion]:
    """Une painéis lado a lado (a/b) quando há legenda de figura abaixo da fileira."""
    if len(regions) < 2:
        return regions
    slack = max(64.0, page_height * 0.09)
    captions = [b for b in text_blocks if CAPTION_RE.search(b.text)]
    used = [False] * len(regions)
    out: list[RawRegion] = []
    for i, a in enumerate(regions):
        if used[i]:
            continue
        group = [i]
        for j, b in enumerate(regions):
            if j == i or used[j]:
                continue
            if a.bbox.overlap_ratio_y(b.bbox) < 0.55:
                continue
            taller = max(a.bbox.height, b.bbox.height)
            shorter = min(a.bbox.height, b.bbox.height)
            if taller <= 0 or shorter / taller < 0.7:
                continue
            dx, _ = a.bbox.gap(b.bbox)
            if dx <= page_width * 0.35:
                group.append(j)
        if len(group) >= 2:
            box = regions[group[0]].bbox
            for idx in group[1:]:
                box = box.union(regions[idx].bbox)
            caption_below = any(0 <= (cap.bbox.y0 - box.y1) <= slack for cap in captions)
            if caption_below:
                acc = regions[group[0]]
                sources = {acc.source}
                fill = acc.fill_ratio
                inner = acc.inner_std
                for idx in group:
                    used[idx] = True
                    box = box.union(regions[idx].bbox)
                    sources.add(regions[idx].source)
                    fill = max(fill, regions[idx].fill_ratio)
                    inner = max(inner, regions[idx].inner_std)
                source = "hybrid" if len(sources) > 1 else next(iter(sources))
                out.append(
                    RawRegion(bbox=box, bbox_px=acc.bbox_px, source=source, fill_ratio=fill, inner_std=inner)
                )
                continue
        used[i] = True
        out.append(a)
    return out


def _raw(
    bbox: BBox,
    source: str,
    sx: float,
    sy: float,
    extent: BBox | None = None,
    xref: int | None = None,
) -> RawRegion:
    return RawRegion(
        bbox=bbox,
        bbox_px=pdf_bbox_to_px(bbox, sx, sy),
        source=source,
        fill_ratio=1.0,
        inner_std=0.0,
        extent=extent if extent is not None and extent != bbox else None,
        xref=xref,
    )


def _rescue_grids(
    leftovers: list[RawRegion],
    passes_small: Callable[[RawRegion], bool],
    gap: float,
    page_area: float,
) -> list[RawRegion]:
    """Imagens pequenas que formam grade: cédulas, fotos de animais lado a lado.

    Sozinha, uma imagem abaixo da área mínima é ícone ou mascote. Duas ou mais
    do mesmo tamanho, alinhadas em fileira ou coluna, são o conteúdo do
    exercício. Quando a grade repete a mesma imagem (mesmo xref: as cédulas)
    ou as imagens se encostam formando um mosaico (o labirinto de casinhas),
    vira uma figura só; quando são imagens diferentes e separadas (os animais,
    que o exercício cita um a um), cada uma é uma figura.

    Agrupa antes de filtrar: a peça do mosaico sozinha não passa nem no
    limite reduzido, o mosaico inteiro passa.
    """
    small = [region for region in leftovers if region.bbox.area < 0.25 * page_area]
    parent = list(range(len(small)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(small):
        for j in range(i + 1, len(small)):
            if _touching(a.bbox, small[j].bbox) or _grid_neighbours(a.bbox, small[j].bbox, gap):
                parent[root(j)] = root(i)

    groups: dict[int, list[RawRegion]] = {}
    for i, region in enumerate(small):
        groups.setdefault(root(i), []).append(region)

    rescued: list[RawRegion] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        xrefs = [member.xref for member in members]
        copies = None not in xrefs and len(set(xrefs)) < len(members)
        mosaic = any(_touching(a.bbox, b.bbox) for i, a in enumerate(members) for b in members[i + 1 :])
        if copies or mosaic:
            merged = members[0]
            for member in members[1:]:
                merged = _absorb(merged, member, "pdf_xobject")
            if passes_small(merged):
                rescued.append(merged)
        else:
            kept = [member for member in members if passes_small(member)]
            if len(kept) >= 2:
                rescued.extend(kept)
    return rescued


def _touching(a: BBox, b: BBox, tol: float = 6.0) -> bool:
    """Encostadas (até `tol` pt de vão) e lado a lado ou uma sobre a outra."""
    dx, dy = a.gap(b)
    return max(dx, dy) <= tol and (a.overlap_ratio_x(b) >= 0.5 or a.overlap_ratio_y(b) >= 0.5)


def _grid_neighbours(a: BBox, b: BBox, gap: float) -> bool:
    """Mesmo tamanho (±15%) e vizinhas na mesma fileira ou coluna."""
    if abs(a.width - b.width) > 0.15 * max(a.width, b.width):
        return False
    if abs(a.height - b.height) > 0.15 * max(a.height, b.height):
        return False
    dx, dy = a.gap(b)
    same_row = a.overlap_ratio_y(b) >= 0.8 and dx <= max(gap, 1.5 * min(a.width, b.width))
    same_column = a.overlap_ratio_x(b) >= 0.8 and dy <= max(gap, 1.5 * min(a.height, b.height))
    return same_row or same_column


def _rescue_row_siblings(
    images: list[RawRegion],
    kept: list[RawRegion],
    options: ExtractOptions,
    page_area: float,
) -> list[RawRegion]:
    """Foto um pouco abaixo da área mínima entra se faz fileira com uma foto aceita.

    Numa sequência de fotos lado a lado, a mais estreita pode não alcançar a
    área mínima. O limiar existe para barrar ícones e mascotes, que não vêm
    alinhados, com a mesma altura, ao lado de uma foto de verdade.
    """
    floor = 0.6 * options.min_area_ratio * page_area
    rescued: list[RawRegion] = []
    for region in images:
        box = region.bbox
        if region in kept or box.area < floor or min(box.width, box.height) < options.min_side_pt:
            continue
        for sibling in kept:
            same_height = abs(sibling.bbox.height - box.height) <= 0.06 * sibling.bbox.height
            dx, _ = sibling.bbox.gap(box)
            if same_height and box.overlap_ratio_y(sibling.bbox) >= 0.9 and dx <= options.merge_gap_pt:
                rescued.append(region)
                break
    return rescued


def _is_backdrop(box: BBox, lines: list[BBox], page_area: float, full_page_ratio: float) -> bool:
    """Imagem grande com texto corrido impresso por cima é fundo de diagramação.

    É a arte de fundo da página do aluno reduzida no manual do professor, ou
    o fundo branco atrás de foto e legenda. Foto com legenda sobreposta é
    menor e carrega uma ou duas linhas, não um parágrafo. O fundo da página
    inteira fica de fora: já é descartado e não pode esconder o que está nela.
    """
    if not 0.4 * page_area <= box.area < full_page_ratio * page_area:
        return False
    return sum(1 for line in lines if box.coverage_of(line) >= 0.9) >= 3


def _group_images(images: list[RawRegion]) -> list[RawRegion]:
    """Cada imagem embutida é uma figura. Só se juntam a contida e a fatiada.

    Fotos vizinhas são figuras diferentes, por mais perto que estejam. Juntam-se
    apenas a imagem dentro de outra (selo, ícone sobre a foto) e as faixas de
    uma mesma imagem cortada em pedaços, que encostam de borda a borda.
    """
    ordered = sorted(images, key=lambda region: region.bbox.area, reverse=True)
    groups: list[RawRegion] = []
    for region in ordered:
        for i, group in enumerate(groups):
            if group.bbox.coverage_of(region.bbox) >= 0.85 or _are_tiles(group.bbox, region.bbox):
                groups[i] = _absorb(group, region, group.source)
                break
        else:
            groups.append(region)
    return groups


def _join_tiles(images: list[RawRegion]) -> list[RawRegion]:
    """Junta as faixas de uma imagem fatiada, que encostam de borda a borda.

    Cada faixa sozinha costuma ficar abaixo do tamanho mínimo; juntas, são a
    figura. Só fatias: imagem contida em outra continua separada até depois do
    filtro, para não sumir dentro de um fundo que o filtro descarta.
    """
    out = list(images)
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                if _are_tiles(out[i].bbox, out[j].bbox):
                    out[i] = _absorb(out[i], out[j], out[i].source)
                    del out[j]
                    changed = True
                    break
            if changed:
                break
    return out


def _are_tiles(a: BBox, b: BBox, tol: float = 1.5) -> bool:
    dx, dy = a.gap(b)
    same_columns = abs(a.x0 - b.x0) <= tol and abs(a.x1 - b.x1) <= tol
    same_rows = abs(a.y0 - b.y0) <= tol and abs(a.y1 - b.y1) <= tol
    return (same_columns and dy <= tol) or (same_rows and dx <= tol)


def _combine_structure(images: list[RawRegion], vectors: list[RawRegion]) -> list[RawRegion]:
    """Mapa vetorial e imagem embutida que se sobrepõem são a mesma figura.

    O caso típico é o mapa com o minimapa-múndi de localização, que é uma
    imagem colada sobre a moldura e às vezes sai um pouco para fora dela.
    Desenho que abriga duas ou mais fotos é quadro de diagramação (sumário,
    página reduzida), não figura: ficam as fotos.
    """
    out = [
        vector
        for vector in vectors
        if sum(1 for image in images if vector.bbox.coverage_of(image.bbox) >= 0.6) < 2
    ]
    for image in images:
        for i, vector in enumerate(out):
            inside = vector.bbox.coverage_of(image.bbox)
            overlay = image.bbox.coverage_of(vector.bbox)
            if inside >= 0.6 or overlay >= 0.85:
                out[i] = _absorb(vector, image, "hybrid")
                break
        else:
            out.append(image)
    return out


def _absorb(base: RawRegion, other: RawRegion, source: str) -> RawRegion:
    box = base.bbox.union(other.bbox)
    return RawRegion(bbox=box, bbox_px=base.bbox_px.union(other.bbox_px), source=source, fill_ratio=1.0, inner_std=0.0)


def _already_known(box: BBox, known: list[BBox], gap: float) -> bool:
    """Resto da figura estrutural que a detecção visual ainda enxergou na borda."""
    for other in known:
        grown = BBox(other.x0 - gap, other.y0 - gap, other.width + 2 * gap, other.height + 2 * gap)
        if grown.coverage_of(box) >= 0.6:
            return True
    return False


def _wraps_known(box: BBox, known: list[BBox]) -> bool:
    """Região visual em volta de figura já conhecida é a diagramação dela (quadro, coluna)."""
    return any(box.coverage_of(other) >= 0.85 for other in known)


def _union_px(members: list[RawRegion], box: BBox) -> BBox:
    acc = members[0].bbox_px
    for m in members[1:]:
        acc = acc.union(m.bbox_px)
    if acc.area <= 0:
        return members[0].bbox_px
    return acc


def _pad_avoiding_text(
    bbox: BBox,
    pad: float,
    blocks: list,
    page_w: float,
    page_h: float,
) -> BBox:
    """Folga em volta da figura, sem alcançar o texto que está logo ao lado."""
    x0 = max(0.0, bbox.x0 - pad)
    y0 = max(0.0, bbox.y0 - pad)
    x1 = min(page_w, bbox.x1 + pad)
    y1 = min(page_h, bbox.y1 + pad)
    for block in blocks:
        other = block.bbox
        if bbox.coverage_of(other) >= 0.35:
            continue
        if other.y0 >= bbox.y1 - 0.5 and bbox.overlap_ratio_x(other) >= 0.15:
            y1 = min(y1, other.y0)
        if other.y1 <= bbox.y0 + 0.5 and bbox.overlap_ratio_x(other) >= 0.15:
            y0 = max(y0, other.y1)
        if other.x0 >= bbox.x1 - 0.5 and bbox.overlap_ratio_y(other) >= 0.15:
            x1 = min(x1, other.x0)
        if other.x1 <= bbox.x0 + 0.5 and bbox.overlap_ratio_y(other) >= 0.15:
            x0 = max(x0, other.x1)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return bbox
    return BBox(x0, y0, x1 - x0, y1 - y0)


def _render_crop(page, crop: BBox, options: ExtractOptions) -> bytes | None:
    """PNG da figura renderizado do PDF, em cor, na resolução que a figura pede.

    O raster da página serve à detecção e pode vir em cinza e em dpi baixo do
    pipeline. Para a IA que descreve a figura, a figura pequena sobe de dpi até
    o lado maior chegar a `crop_min_long_px`; a grande desce até `crop_max_long_px`.
    Recorte vazio não vira figura.
    """
    if crop.width < 1 or crop.height < 1:
        return None
    long_pt = max(crop.width, crop.height)
    dpi = max(float(options.dpi), 72.0 * options.crop_min_long_px / long_pt)
    dpi = min(dpi, float(options.crop_max_dpi), 72.0 * options.crop_max_long_px / long_pt)
    rect = pymupdf.Rect(crop.x0, crop.y0, crop.x1, crop.y1) & page.rect
    if rect.is_empty:
        return None
    pix = page.get_pixmap(dpi=max(1, int(round(dpi))), clip=rect, alpha=False, colorspace=pymupdf.csRGB)
    if pix.width < 2 or pix.height < 2:
        return None
    return pix.tobytes("png")
