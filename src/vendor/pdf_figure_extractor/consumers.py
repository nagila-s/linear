"""Adaptadores da extração para os formatos que os sistemas de destino esperam.

`DocumentExtraction` é rico de propósito: traz bbox, legenda, âncora e ordem de
leitura. Cada consumidor a jusante quer um recorte diferente disso, e nenhum
quer o objeto inteiro. Manter a tradução aqui evita que cada integração invente
o seu próprio dicionário a partir dos modelos.

O extrator entrega pixels, identidade e posição. Upload, `figure_id` e
`storage_path` de objeto no bucket são do consumidor — ele é quem conhece o
ISBN, a versão do processo e o storage.
"""

from __future__ import annotations

import hashlib

from .models import Anchor, DocumentExtraction, ExtractedFigure

FIGURE_FORMAT = "png"


def as_avalia_images(
    result: DocumentExtraction,
    *,
    book_id: str,
    project_id: str | None = None,
) -> list[dict]:
    """Os dez campos que o Avalia monta em `_append_image`.

    `storage_path` segue `{book_id}/p{página}_i{índice}.png`, índice 0-based
    na página. `source_key` é a chave de rastreabilidade da origem (indexada
    em `idx_images_source_key`); aqui deriva do bbox e da fonte, estável entre
    execuções no mesmo PDF. `needs_convert` fica sempre falso porque este
    extrator só entrega PNG.
    """
    items: list[dict] = []
    for figure, index in _indexed_by_page(result, start=0):
        items.append(
            {
                "book_id": book_id,
                "project_id": project_id,
                "page_number": figure.page,
                "image_index": index,
                "format": FIGURE_FORMAT,
                "raw_bytes": figure.png_bytes,
                "storage_path": f"{book_id}/p{figure.page}_i{index}.png",
                "needs_convert": False,
                "content_hash": hashlib.sha256(figure.png_bytes).hexdigest(),
                "source_key": _source_key(figure),
            }
        )
    return items


def as_linear_figures(result: DocumentExtraction) -> list[dict]:
    """O que o Linear precisa para persistir uma figura, sem assumir o storage.

    `figure_key` é `fig{n}` 1-based reiniciando por página — o mesmo contrato
    da migração `test_figures_key_per_page`. `image_bytes` vão para o upload,
    que o Linear faz. `figure_id` e `storage_path` não saem daqui: o Linear
    os atribui depois de gravar no bucket. `bbox` / `width_px` / `height_px`
    (tamanho do PNG entregue) preenchem colunas que a tabela `test_figures` já tem e hoje ficam vazias.
    `caption` e `anchor` são contexto determinístico do PDF, para quem quiser
    usar no lugar da chamada de LLM por página.
    """
    return [
        {
            "figure_key": f"fig{index}",
            "page_number": figure.page,
            "figure_index": index,
            "image_bytes": figure.png_bytes,
            "content_hash": hashlib.sha256(figure.png_bytes).hexdigest(),
            "bbox": figure.bbox.to_dict(),
            "width_px": _png_size(figure.png_bytes)[0],
            "height_px": _png_size(figure.png_bytes)[1],
            "caption": figure.caption,
            "anchor": _anchor_payload(figure.anchor),
            "source": figure.source,
        }
        for figure, index in _indexed_by_page(result, start=1)
    ]


def _png_size(png: bytes) -> tuple[int, int]:
    """Largura e altura do PNG entregue, lidas do cabeçalho IHDR."""
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def _source_key(figure: ExtractedFigure) -> str:
    box = figure.bbox
    return (
        f"pdf:p{figure.page}:{figure.source}:{figure.id}:"
        f"x{int(box.x)}y{int(box.y)}w{int(box.width)}h{int(box.height)}"
    )


def _anchor_payload(anchor: Anchor | None) -> dict | None:
    if anchor is None:
        return None
    return {
        "text": anchor.text,
        "bbox": anchor.bbox.to_dict(),
        "block_index": anchor.block_index,
    }


def _indexed_by_page(
    result: DocumentExtraction,
    *,
    start: int,
) -> list[tuple[ExtractedFigure, int]]:
    """Numera as figuras reiniciando a contagem em cada página."""
    counters: dict[int, int] = {}
    out: list[tuple[ExtractedFigure, int]] = []
    for figure in result.figures:
        index = counters.get(figure.page, start)
        counters[figure.page] = index + 1
        out.append((figure, index))
    return out
