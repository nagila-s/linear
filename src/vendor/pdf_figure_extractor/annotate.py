from __future__ import annotations

import re
from typing import Callable, TypeVar

from .geometry import BBox
from .models import Anchor, TextBlock

T = TypeVar("T")

CAPTION_RE = re.compile(
    r"^\s*(figura|fig\.?|foto|gr[aá]fico|mapa|ilustra[cç][aã]o|fonte)\b",
    re.IGNORECASE,
)


def find_caption(figure: BBox, blocks: list[TextBlock], page_height: float) -> str | None:
    best: tuple[float, str] | None = None
    slack = max(56.0, page_height * 0.08)
    for block in blocks:
        if not CAPTION_RE.search(block.text):
            continue
        if figure.overlap_ratio_x(block.bbox) < 0.2 and block.bbox.overlap_ratio_x(figure) < 0.2:
            continue
        below = 0 <= (block.bbox.y0 - figure.y1) <= slack
        above = 0 <= (figure.y0 - block.bbox.y1) <= slack * 0.6
        if not (below or above):
            continue
        dist = abs(block.bbox.y0 - figure.y1) if below else abs(figure.y0 - block.bbox.y1)
        if best is None or dist < best[0]:
            best = (dist, block.text)
    return best[1] if best else None


def _is_inside_or_label(figure: BBox, block: TextBlock) -> bool:
    if figure.coverage_of(block.bbox) >= 0.4:
        return True
    if figure.intersection(block.bbox) and figure.coverage_of(block.bbox) >= 0.2:
        return True
    near_below = 0 <= (block.bbox.y0 - figure.y1) <= 28 and figure.overlap_ratio_x(block.bbox) >= 0.25
    if near_below and len(block.text) < 40:
        return True
    return False


def column_gutter(
    blocks: list[TextBlock],
    page_width: float,
    page_height: float | None = None,
) -> float | None:
    """X do vão entre duas colunas, ou None quando a página é de coluna única.

    Livro didático em duas colunas se lê a coluna esquerda inteira e depois a
    direita. A figura do fim da esquerda vem antes da figura do topo da direita,
    mesmo quando esta está mais acima na página.
    """
    if page_width <= 0:
        return None
    limit = page_width * 0.46
    body: list[TextBlock] = []
    for block in blocks:
        box = block.bbox
        if box.width < 28 or box.width > limit or box.height < 8:
            continue
        if page_height:
            if box.y0 < page_height * 0.07 or box.y0 > page_height * 0.94:
                continue
        body.append(block)
    if len(body) < 2:
        return None

    best: tuple[float, float] | None = None
    candidates = {round(block.bbox.x0, 1) for block in body} | {round(block.bbox.x1, 1) for block in body}
    for raw in candidates:
        if not page_width * 0.28 <= raw <= page_width * 0.72:
            continue
        left: list[TextBlock] = []
        right: list[TextBlock] = []
        cross = 0
        for block in body:
            if block.bbox.x1 <= raw + 4:
                left.append(block)
            elif block.bbox.x0 >= raw - 4:
                right.append(block)
            else:
                cross += 1
        if not left or not right or cross > 2:
            continue
        if len(left) + len(right) < 4 and cross:
            continue
        left_h = sum(block.bbox.height for block in left)
        right_h = sum(block.bbox.height for block in right)
        min_h = (page_height or max(block.bbox.y1 for block in body)) * 0.15
        if left_h < min_h or right_h < min_h:
            continue
        gap = min(block.bbox.x0 for block in right) - max(block.bbox.x1 for block in left)
        if gap < 6:
            continue
        gutter = max(block.bbox.x1 for block in left) + gap / 2.0
        if not page_width * 0.28 <= gutter <= page_width * 0.72:
            continue
        score = left_h + right_h + gap * 4 - cross * 400
        if best is None or score > best[0]:
            best = (score, gutter)
    return best[1] if best else None


def column_of(bbox: BBox, gutter: float | None) -> int:
    """0 = coluna esquerda (ou página de coluna única), 1 = direita."""
    if gutter is None:
        return 0
    left = max(0.0, min(bbox.x1, gutter) - bbox.x0)
    right = max(0.0, bbox.x1 - max(bbox.x0, gutter))
    if left > 0 and right > 0 and min(left, right) >= 0.25 * bbox.width:
        return 0 if bbox.x0 < gutter else 1
    return 0 if left >= right else 1


def reading_ordered(items: list[T], box_of: Callable[[T], BBox], gutter: float | None) -> list[T]:
    """Coluna por coluna; dentro da coluna, fileira por fileira, da esquerda para a direita.

    Duas figuras lado a lado formam uma fileira mesmo que uma comece mais
    acima: a foto alta à direita não passa na frente da que está à esquerda.
    """
    by_column: dict[int, list[T]] = {}
    for item in items:
        by_column.setdefault(column_of(box_of(item), gutter), []).append(item)
    ordered: list[T] = []
    for column in sorted(by_column):
        ordered.extend(_rows_left_to_right(by_column[column], box_of))
    return ordered


def _rows_left_to_right(items: list[T], box_of: Callable[[T], BBox]) -> list[T]:
    rows: list[list[T]] = []
    for item in sorted(items, key=lambda it: (round(box_of(it).y0, 1), box_of(it).x0)):
        box = box_of(item)
        for row in rows:
            if any(_side_by_side(box, box_of(other)) for other in row):
                row.append(item)
                break
        else:
            rows.append([item])
    return [item for row in rows for item in sorted(row, key=lambda it: box_of(it).x0)]


def _side_by_side(a: BBox, b: BBox) -> bool:
    shared_x = min(a.x1, b.x1) - max(a.x0, b.x0)
    apart = shared_x <= max(4.0, 0.25 * min(a.width, b.width))
    return apart and a.overlap_ratio_y(b) >= 0.5


def find_anchor(
    figure: BBox,
    blocks: list[TextBlock],
    *,
    page_width: float | None = None,
    page_height: float | None = None,
) -> Anchor | None:
    """Bloco de texto anterior na ordem de leitura — ponto de inserção no Braille."""
    gutter = column_gutter(blocks, page_width, page_height) if page_width else None
    pool = blocks
    if gutter is not None:
        col = column_of(figure, gutter)
        same = [block for block in blocks if _in_column(block.bbox, gutter, col)]
        pool = same or blocks
    ordered = sorted(pool, key=lambda b: (round(b.bbox.y0, 1), b.bbox.x0))
    previous: TextBlock | None = None
    for block in ordered:
        if CAPTION_RE.search(block.text):
            continue
        if _is_inside_or_label(figure, block):
            continue
        if block.bbox.y1 <= figure.cy or (
            block.bbox.y1 <= figure.y1 + 8 and block.bbox.cy < figure.y0
        ):
            previous = block
        elif previous is not None:
            break
    if previous is None and ordered:
        for block in ordered:
            if _is_inside_or_label(figure, block):
                continue
            if CAPTION_RE.search(block.text):
                continue
            previous = block
            break
    if previous is None:
        return None
    return Anchor(text=previous.text, bbox=previous.bbox, block_index=previous.index)


def _in_column(bbox: BBox, gutter: float, column: int) -> bool:
    left = max(0.0, min(bbox.x1, gutter) - bbox.x0)
    right = max(0.0, bbox.x1 - max(bbox.x0, gutter))
    if left > 0 and right > 0 and min(left, right) >= 0.25 * max(bbox.width, 1):
        return False
    return column_of(bbox, gutter) == column


def reading_order_for(
    figure: BBox,
    figures: list[BBox],
    blocks: list[TextBlock] | None = None,
    page_width: float | None = None,
    page_height: float | None = None,
) -> int:
    gutter = column_gutter(blocks, page_width, page_height) if blocks and page_width else None
    ordered = reading_ordered(figures, lambda b: b, gutter)
    for i, bbox in enumerate(ordered, start=1):
        if bbox is figure or bbox.iou(figure) > 0.9:
            return i
    return 1
