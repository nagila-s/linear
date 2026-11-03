from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BBox:
    """Retângulo com origem no canto superior esquerdo."""

    x: float
    y: float
    width: float
    height: float

    @property
    def x0(self) -> float:
        return self.x

    @property
    def y0(self) -> float:
        return self.y

    @property
    def x1(self) -> float:
        return self.x + self.width

    @property
    def y1(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def cx(self) -> float:
        return self.x + self.width / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.height / 2.0

    @property
    def aspect_ratio(self) -> float:
        short = min(self.width, self.height)
        long = max(self.width, self.height)
        if short <= 0:
            return float("inf")
        return long / short

    def padded(self, pad: float, max_w: float, max_h: float) -> BBox:
        x0 = max(0.0, self.x - pad)
        y0 = max(0.0, self.y - pad)
        x1 = min(max_w, self.x1 + pad)
        y1 = min(max_h, self.y1 + pad)
        return BBox(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0))

    def scaled(self, sx: float, sy: float | None = None) -> BBox:
        sy = sx if sy is None else sy
        return BBox(self.x * sx, self.y * sy, self.width * sx, self.height * sy)

    def intersection(self, other: BBox) -> BBox | None:
        x0 = max(self.x0, other.x0)
        y0 = max(self.y0, other.y0)
        x1 = min(self.x1, other.x1)
        y1 = min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return BBox(x0, y0, x1 - x0, y1 - y0)

    def intersects(self, other: BBox) -> bool:
        return self.intersection(other) is not None

    def iou(self, other: BBox) -> float:
        inter = self.intersection(other)
        if inter is None:
            return 0.0
        union = self.area + other.area - inter.area
        return inter.area / union if union else 0.0

    def coverage_of(self, other: BBox) -> float:
        """Fração da área de `other` que está dentro deste bbox."""
        inter = self.intersection(other)
        if inter is None or other.area <= 0:
            return 0.0
        return inter.area / other.area

    def union(self, other: BBox) -> BBox:
        x0 = min(self.x0, other.x0)
        y0 = min(self.y0, other.y0)
        x1 = max(self.x1, other.x1)
        y1 = max(self.y1, other.y1)
        return BBox(x0, y0, x1 - x0, y1 - y0)

    def gap(self, other: BBox) -> tuple[float, float]:
        dx = 0.0 if self.intersects(other) else max(0.0, max(self.x0, other.x0) - min(self.x1, other.x1))
        dy = 0.0 if self.intersects(other) else max(0.0, max(self.y0, other.y0) - min(self.y1, other.y1))
        return dx, dy

    def overlap_ratio_x(self, other: BBox) -> float:
        overlap = min(self.x1, other.x1) - max(self.x0, other.x0)
        denom = min(self.width, other.width)
        if denom <= 0:
            return 0.0
        return max(0.0, overlap) / denom

    def overlap_ratio_y(self, other: BBox) -> float:
        overlap = min(self.y1, other.y1) - max(self.y0, other.y0)
        denom = min(self.height, other.height)
        if denom <= 0:
            return 0.0
        return max(0.0, overlap) / denom

    def as_xywh_int(self) -> tuple[int, int, int, int]:
        x = max(0, int(round(self.x)))
        y = max(0, int(round(self.y)))
        w = max(0, int(round(self.width)))
        h = max(0, int(round(self.height)))
        return x, y, w, h

    def to_dict(self) -> dict[str, float]:
        return {
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "width": round(self.width, 2),
            "height": round(self.height, 2),
        }


def merge_nearby(boxes: list[BBox], gap: float) -> list[BBox]:
    """Une regiões próximas (painéis a/b/c, figura + legenda gráfica)."""
    if not boxes:
        return []
    remaining = list(boxes)
    changed = True
    while changed:
        changed = False
        nxt: list[BBox] = []
        used = [False] * len(remaining)
        for i, a in enumerate(remaining):
            if used[i]:
                continue
            acc = a
            for j, b in enumerate(remaining):
                if i == j or used[j]:
                    continue
                if _should_merge(acc, b, gap):
                    acc = acc.union(b)
                    used[j] = True
                    changed = True
            used[i] = True
            nxt.append(acc)
        remaining = nxt
    return remaining


def _should_merge(a: BBox, b: BBox, gap: float) -> bool:
    if a.iou(b) > 0.08 or a.coverage_of(b) >= 0.55 or b.coverage_of(a) >= 0.55:
        return True
    dx, dy = a.gap(b)
    close = dx <= gap and dy <= gap
    aligned_row = a.overlap_ratio_y(b) >= 0.35 and dx <= gap * 1.4
    aligned_col = a.overlap_ratio_x(b) >= 0.35 and dy <= gap * 1.4
    return close and (aligned_row or aligned_col or (dx + dy) <= gap)
