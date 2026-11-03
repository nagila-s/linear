from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf
import numpy as np

from .geometry import BBox
from .models import TextBlock


def open_document(source: str | Path | bytes) -> pymupdf.Document:
    if isinstance(source, (str, Path)):
        return pymupdf.open(str(source))
    return pymupdf.open(stream=source, filetype="pdf")


def render_page(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return np.ascontiguousarray(arr)


def page_scale(page: pymupdf.Page, raster: np.ndarray) -> tuple[float, float]:
    height, width = raster.shape[:2]
    rect = page.rect
    sx = width / rect.width if rect.width else 1.0
    sy = height / rect.height if rect.height else 1.0
    return sx, sy


def pdf_bbox_to_px(bbox: BBox, sx: float, sy: float) -> BBox:
    return bbox.scaled(sx, sy)


def px_bbox_to_pdf(bbox: BBox, sx: float, sy: float) -> BBox:
    return bbox.scaled(1.0 / sx if sx else 1.0, 1.0 / sy if sy else 1.0)


def page_text(page: pymupdf.Page) -> dict:
    """`get_text("dict")` da página, com blocos de imagem. É caro: extraia uma vez por página."""
    return page.get_text("dict")


def load_text_blocks(page: pymupdf.Page, text: dict | None = None) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    raw = text if text is not None else page_text(page)
    index = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        x0, y0, x1, y1 = block["bbox"]
        parts: list[str] = []
        for line in block.get("lines", []):
            line_text = " ".join(span.get("text", "") for span in line.get("spans", []))
            if line_text.strip():
                parts.append(line_text.strip())
        text = " ".join(parts).strip()
        if not text:
            continue
        blocks.append(
            TextBlock(
                bbox=BBox(x0, y0, x1 - x0, y1 - y0),
                text=text,
                index=index,
            )
        )
        index += 1
    return blocks


def running_text_lines(page: pymupdf.Page, min_words: int = 5, text: dict | None = None) -> list[BBox]:
    """Linhas de texto corrido (frase, não rótulo)."""
    lines: list[BBox] = []
    raw = text if text is not None else page_text(page)
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if len(text.split()) >= min_words:
                x0, y0, x1, y1 = line["bbox"]
                lines.append(BBox(x0, y0, x1 - x0, y1 - y0))
    return lines


@dataclass(frozen=True, slots=True)
class NativeImage:
    bbox: BBox
    xref: int
    has_alpha: bool
    # Área visível antes de aparar a transparência; os filtros de tamanho usam esta.
    extent: BBox | None = None


def native_image_bboxes(page: pymupdf.Page, text: dict | None = None) -> list[BBox]:
    return [image.bbox for image in native_images(page, text)]


def native_images(page: pymupdf.Page, text: dict | None = None) -> list[NativeImage]:
    """Posição visível de cada imagem.

    `get_image_rects` devolve o retângulo em que a imagem foi posicionada,
    antes do recorte. No livro, esse retângulo costuma ser maior que a foto:
    o que sobra é margem, e o texto da página aparece por cima. O bbox de
    imagem do texto da página já é a interseção com o clipping path — a área
    que o leitor vê.

    Imagem recortada por transparência (SMask: o celular, o mascote) tem o
    retângulo inteiro transparente em volta do desenho. Quando há texto nessa
    parte transparente, o bbox fica só na parte opaca, senão o recorte leva o
    texto que está atrás. Sem texto ali, o bbox não muda: os limiares de
    tamanho foram calibrados com o retângulo cheio.
    """
    raw = text if text is not None else page_text(page)
    clips = _painted_image_boxes(page, raw)
    lines = _line_boxes(raw)
    sheet = _rect_bbox(page.rect)
    found: list[NativeImage] = []
    seen: set[tuple[float, float, float, float]] = set()
    opaque_cache: dict[int, tuple[float, float, float, float] | None] = {}
    for info in page.get_images(full=True):
        xref, smask = info[0], info[1]
        width, height = int(info[2]), int(info[3])
        try:
            rects = page.get_image_rects(xref, transform=True)
        except (ValueError, RuntimeError):
            continue
        if smask and smask not in opaque_cache:
            opaque_cache[smask] = _opaque_unit_box(page.parent, smask)
        opaque = opaque_cache.get(smask) if smask else None
        for rect, matrix in rects:
            placement = BBox(rect.x0, rect.y0, rect.width, rect.height)
            on_sheet = placement.intersection(sheet)
            # Mais da metade fora da folha: é a outra página de uma imagem em página dupla.
            if on_sheet is None or on_sheet.area < 0.5 * placement.area:
                continue
            box = _visible_image_box(placement, width, height, clips).intersection(sheet)
            extent = box
            if box is not None and opaque is not None:
                trimmed = box.intersection(_unit_box_on_page(opaque, matrix))
                if trimmed is not None and _text_behind(box, trimmed, lines):
                    box = trimmed
            if box is None:
                continue
            key = (round(box.x0, 1), round(box.y0, 1), round(box.x1, 1), round(box.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            found.append(NativeImage(bbox=box, xref=xref, has_alpha=bool(smask), extent=extent))
    return found


_OPAQUE_ALPHA = 16


def _line_boxes(text: dict) -> list[BBox]:
    boxes: list[BBox] = []
    for block in text.get("blocks", []):
        for line in block.get("lines", []):
            if any(span.get("text", "").strip() for span in line.get("spans", [])):
                x0, y0, x1, y1 = line["bbox"]
                boxes.append(BBox(x0, y0, x1 - x0, y1 - y0))
    return boxes


def _text_behind(box: BBox, opaque: BBox, lines: list[BBox]) -> bool:
    """Alguma linha de texto está dentro da imagem, mas fora da parte opaca."""
    return any(box.coverage_of(line) >= 0.5 and opaque.coverage_of(line) < 0.5 for line in lines)


def _opaque_unit_box(doc: pymupdf.Document, smask: int) -> tuple[float, float, float, float] | None:
    """Parte opaca da máscara, em coordenadas 0..1 da imagem (origem no topo)."""
    try:
        pix = pymupdf.Pixmap(doc, smask)
    except (ValueError, RuntimeError):
        return None
    if pix.width < 1 or pix.height < 1:
        return None
    alpha = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
    rows = np.flatnonzero((alpha > _OPAQUE_ALPHA).any(axis=1))
    cols = np.flatnonzero((alpha > _OPAQUE_ALPHA).any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    return (
        cols[0] / pix.width,
        rows[0] / pix.height,
        (cols[-1] + 1) / pix.width,
        (rows[-1] + 1) / pix.height,
    )


def _unit_box_on_page(unit: tuple[float, float, float, float], matrix: pymupdf.Matrix) -> BBox:
    u0, v0, u1, v1 = unit
    corners = [pymupdf.Point(u, v) * matrix for u, v in ((u0, v0), (u1, v0), (u0, v1), (u1, v1))]
    xs = [p.x for p in corners]
    ys = [p.y for p in corners]
    return BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def vector_figure_bboxes(page: pymupdf.Page, text: dict | None = None) -> list[BBox]:
    """Figuras desenhadas em vetor: mapas, gráficos e ilustrações de traço.

    No raster, o mapa é indistinguível de tabela (moldura, paralelos e
    meridianos) ou de moldura vazia (mar liso, litoral fino). No PDF ele é
    inconfundível: centenas de traçados, contornos longos, várias cores.

    O limite vem do clipping path: o conteúdo do mapa é recortado pela
    moldura, então o recorte mais externo que os traçados têm em comum é a
    borda da figura. Recortes internos (hachura, encarte) ficam dentro dela.
    Desenhos sem recorte são agrupados por proximidade. Em seguida entra o
    que encosta na borda e é estreito — aba de título, traço da moldura —,
    mas não a caixa de destaque ao lado nem o fio que liga o mapa a uma foto.
    """
    page_area = float(page.rect.width * page.rect.height)
    clipped, free = _drawings_by_clip(page, page_area)
    if sum(len(paths) for _, paths in clipped) + len(free) < _VECTOR_MIN_PATHS:
        return []

    groups: list[tuple[BBox, list[dict]]] = []
    for _, paths in clipped:
        box = _union_visible(paths)
        if box is not None:
            groups.append((box, list(paths)))
    groups = _absorb_contained(groups)

    loose = [d for d in free if not any(d["_visible"].intersects(box) for box, _ in groups)]
    if len(loose) >= _VECTOR_MIN_PATHS:
        sheet = _rect_bbox(page.rect)
        for rect in page.cluster_drawings(drawings=loose):
            box = _rect_bbox(rect).intersection(sheet)
            if box is not None:
                groups.append((box, [d for d in loose if rect.contains(d["rect"])]))
        groups = _absorb_contained(groups)

    everything = [d for _, paths in clipped for d in paths] + free
    drawn = [
        _with_attachments(box, everything)
        for box, paths in groups
        if box.width >= 48 and box.height >= 48 and _looks_like_vector_figure(paths)
    ]
    if not drawn:
        return []
    spans = _text_spans(page, text)
    outside = [span for span in spans if not any(box.coverage_of(span[0]) >= 0.5 for box in drawn)]
    return [box for box in drawn if _text_is_labels(box, spans, outside)]


_VECTOR_MIN_PATHS = 40
_VECTOR_MIN_LONG_PATHS = 10
_VECTOR_MIN_FILLS = 3


def _drawings_by_clip(page: pymupdf.Page, page_area: float) -> tuple[list[tuple[BBox, list[dict]]], list[dict]]:
    """Separa os traçados pelo clipping path mais externo que os recorta.

    Cada traçado ganha `_visible`: o retângulo dele cortado por todos os
    recortes ativos — o que de fato aparece na página.
    """
    by_clip: dict[tuple[float, float, float, float], list[dict]] = {}
    free: list[dict] = []
    stack: dict[int, BBox] = {}
    sheet = _rect_bbox(page.rect)
    for entry in page.get_drawings(extended=True):
        kind = entry.get("type")
        level = int(entry.get("level", 0))
        if kind in ("clip", "group"):
            stack = {lvl: box for lvl, box in stack.items() if lvl < level}
            scissor = entry.get("scissor") if kind == "clip" else None
            if scissor is not None:
                stack[level] = _rect_bbox(scissor)
            continue
        rect = entry.get("rect")
        if rect is None or rect.width * rect.height >= 0.4 * page_area:
            continue
        clips = [box for lvl, box in sorted(stack.items()) if lvl < level]
        visible = _rect_bbox(rect).intersection(sheet)
        for clip in clips:
            visible = visible.intersection(clip) if visible is not None else None
        if visible is None:
            continue
        entry["_visible"] = visible
        frames = [clip for clip in clips if clip.area < 0.6 * page_area]
        if frames:
            key = frames[0]
            by_clip.setdefault((key.x0, key.y0, key.x1, key.y1), []).append(entry)
        else:
            free.append(entry)
    clipped = [(BBox(x0, y0, x1 - x0, y1 - y0), paths) for (x0, y0, x1, y1), paths in by_clip.items()]
    return clipped, free


def _absorb_contained(groups: list[tuple[BBox, list[dict]]]) -> list[tuple[BBox, list[dict]]]:
    """O recorte de dentro (a moldura dupla, o encarte) pertence à figura que o contém."""
    ordered = sorted(groups, key=lambda item: item[0].area, reverse=True)
    out: list[tuple[BBox, list[dict]]] = []
    for box, paths in ordered:
        for i, (outer, outer_paths) in enumerate(out):
            if outer.coverage_of(box) >= 0.85:
                out[i] = (outer, outer_paths + paths)
                break
        else:
            out.append((box, paths))
    return out


def _looks_like_vector_figure(paths: list[dict]) -> bool:
    if len(paths) < _VECTOR_MIN_PATHS:
        return False
    if sum(1 for d in paths if len(d.get("items") or ()) >= 8) < _VECTOR_MIN_LONG_PATHS:
        return False
    fills = {tuple(round(c, 2) for c in d["fill"]) for d in paths if d.get("fill")}
    return len(fills) >= _VECTOR_MIN_FILLS


def _text_spans(page: pymupdf.Page, text: dict | None = None) -> list[tuple[BBox, float, int]]:
    spans: list[tuple[BBox, float, int]] = []
    raw = text if text is not None else page_text(page)
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = len(span.get("text", "").strip())
                if chars:
                    x0, y0, x1, y1 = span["bbox"]
                    spans.append((BBox(x0, y0, x1 - x0, y1 - y0), float(span["size"]), chars))
    return spans


def _dominant_size(spans: list[tuple[BBox, float, int]]) -> float:
    weight: dict[float, int] = {}
    for _, size, chars in spans:
        key = round(size * 2) / 2
        weight[key] = weight.get(key, 0) + chars
    return max(weight, key=weight.get)


def _text_is_labels(
    box: BBox,
    spans: list[tuple[BBox, float, int]],
    outside: list[tuple[BBox, float, int]],
) -> bool:
    """O texto de um mapa ou diagrama é rótulo: menor que o corpo da página.

    Quadro de seção, página reduzida do livro do aluno e balão de exercício
    também são desenhos com muitos traçados, mas guardam texto corrido no
    tamanho do corpo (ou maior que as notas em volta).
    """
    inside = [span for span in spans if box.coverage_of(span[0]) >= 0.5]
    chars = sum(span[2] for span in inside)
    if chars < _LABEL_FREE_CHARS:
        return True
    if sum(span[2] for span in outside) < _BODY_MIN_CHARS:
        return False
    body = _dominant_size(outside)
    large = sum(span[2] for span in inside if span[1] >= 0.85 * body)
    return _dominant_size(inside) <= 0.8 * body and large <= 0.15 * chars


_LABEL_FREE_CHARS = 20
_BODY_MIN_CHARS = 150


def _with_attachments(box: BBox, drawings: list[dict]) -> BBox:
    """Inclui o que encosta na figura e não a alarga: aba de título, traço da moldura.

    Também entra o quadro preenchido pequeno pousado sobre a borda da figura,
    como a legenda do mapa, que costuma vir num recorte próprio. Linhas sem
    preenchimento (fios que ligam o mapa a uma foto) ficam de fora. Por fim, a
    moldura que envolve a figura com pouca folga, com o título dentro dela.
    """
    grown = box
    reach = 3.0
    for d in drawings:
        other = d["_visible"]
        if other.area <= 0 or box.coverage_of(other) >= 0.95:
            continue
        near = BBox(box.x0 - reach, box.y0 - reach, box.width + 2 * reach, box.height + 2 * reach)
        if not near.intersects(other):
            continue
        within_x = other.x0 >= box.x0 - reach and other.x1 <= box.x1 + reach
        within_y = other.y0 >= box.y0 - reach and other.y1 <= box.y1 + reach
        if within_x and other.height <= 0.12 * box.height + reach:
            grown = grown.union(other)
        elif within_y and other.width <= 0.12 * box.width + reach:
            grown = grown.union(other)
        elif d.get("fill") is not None and other.area <= 0.25 * box.area:
            inter = box.intersection(other)
            if inter is not None and inter.area >= 0.1 * other.area:
                grown = grown.union(other)
    frames = [
        d["_visible"]
        for d in drawings
        if d["_visible"].coverage_of(grown) >= 0.98 and grown.area >= 0.7 * d["_visible"].area
    ]
    if frames:
        grown = grown.union(max(frames, key=lambda frame: frame.area))
    return grown


def _union_visible(drawings: list[dict]) -> BBox | None:
    acc: BBox | None = None
    for d in drawings:
        box = d["_visible"]
        acc = box if acc is None else acc.union(box)
    return acc


def _rect_bbox(rect) -> BBox:
    return BBox(rect.x0, rect.y0, rect.x1 - rect.x0, rect.y1 - rect.y0)


def _painted_image_boxes(page: pymupdf.Page, text: dict | None = None) -> list[tuple[int, int, BBox]]:
    painted: list[tuple[int, int, BBox]] = []
    raw = text if text is not None else page_text(page)
    for block in raw.get("blocks", []):
        if block.get("type") != 1:
            continue
        x0, y0, x1, y1 = block["bbox"]
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        painted.append(
            (int(block.get("width") or 0), int(block.get("height") or 0), BBox(x0, y0, x1 - x0, y1 - y0))
        )
    return painted


def _visible_image_box(
    placement: BBox,
    width: int,
    height: int,
    painted: list[tuple[int, int, BBox]],
) -> BBox:
    contained: list[BBox] = []
    for pw, ph, clip in painted:
        if pw != width or ph != height:
            continue
        if placement.coverage_of(clip) < 0.75:
            continue
        contained.append(clip)
    if not contained:
        return placement
    shrunk = [clip for clip in contained if placement.area * 0.12 <= clip.area <= placement.area * 0.98]
    chosen = min(shrunk, key=lambda clip: clip.area) if shrunk else max(contained, key=lambda clip: clip.area)
    return placement.intersection(chosen) or placement
