#!/usr/bin/env python
"""
Extrai imagens de um PDF de livro didático e gera um .docx só com as figuras.

Uso:
  python scripts/pdf_images_to_docx.py entrada.pdf -o saida.docx
  python scripts/pdf_images_to_docx.py entrada.pdf --export-png ./figuras
  python scripts/pdf_images_to_docx.py entrada.pdf --pages 1-10   # teste rápido
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.images_to_docx import build_docx_from_images
from src.pipeline.steps.pdf_images import ExtractedPdfImage, iter_extract_images_from_pdf


def _log(msg: str, *, quiet: bool) -> None:
    if not quiet:
        print(msg, file=sys.stderr, flush=True)


def _parse_pages(value: str | None) -> tuple[int, int | None]:
    if not value:
        return 1, None
    raw = value.strip()
    if "-" in raw:
        start_s, end_s = raw.split("-", 1)
        return int(start_s), int(end_s)
    page = int(raw)
    return page, page


def _format_eta(elapsed: float, done: int, total: int) -> str:
    if done <= 0:
        return "calculando..."
    remaining = total - done
    per_page = elapsed / done
    eta_s = per_page * remaining
    if eta_s < 60:
        return f"{eta_s:.0f}s"
    return f"{eta_s / 60:.1f} min"


def _export_png(img: ExtractedPdfImage, export_dir: Path) -> Path:
    name = f"p{img.page_number:04d}_i{img.image_index:03d}_{img.kind}.png"
    path = export_dir / name
    path.write_bytes(img.image_bytes)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrai figuras de um PDF (embutidas, vetoriais e recortes) e monta um Word."
    )
    parser.add_argument("pdf", type=Path, help="Caminho do PDF de entrada")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Arquivo .docx de saída (padrão: <nome_do_pdf>_imagens.docx)",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Título do documento Word (padrão: nome do arquivo PDF)",
    )
    parser.add_argument(
        "--pages",
        default=None,
        metavar="N ou N-M",
        help="Processar só um intervalo de páginas (ex: 1-20). Útil para testar.",
    )
    parser.add_argument(
        "--min-width",
        type=int,
        default=0,
        help="Largura mínima em pixels (0 = sem filtro; padrão: 0)",
    )
    parser.add_argument(
        "--min-height",
        type=int,
        default=0,
        help="Altura mínima em pixels (0 = sem filtro; padrão: 0)",
    )
    parser.add_argument(
        "--mode",
        choices=("balanced", "full", "compact"),
        default="balanced",
        help=(
            "balanced (padrão): agrupa cédulas/ícones repetidos, mantém figuras grandes, "
            "inclui vetores (operações) e remove duplicatas exatas; "
            "full: tudo separado + vetores; compact: só raster agrupado (v2)"
        ),
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Forçar remoção de imagens com mesmo conteúdo (ligado por padrão em balanced)",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Não remover duplicatas exatas (só em --mode balanced)",
    )
    parser.add_argument(
        "--no-merge-nearby",
        action="store_true",
        help="Não agrupar tiles repetidos na mesma linha (ex.: cédulas)",
    )
    parser.add_argument(
        "--merge-min-count",
        type=int,
        default=5,
        metavar="N",
        help="Mínimo de rasters na página para ativar agrupamento (padrão: 5)",
    )
    parser.add_argument(
        "--merge-gap-pt",
        type=float,
        default=14.0,
        help="Distância máxima em pontos entre imagens para fundir no mesmo recorte (padrão: 14)",
    )
    parser.add_argument(
        "--include-page-fallback",
        action="store_true",
        help="Se a página não tiver figura raster, salvar a página inteira como imagem",
    )
    parser.add_argument(
        "--vector-clusters",
        action="store_true",
        help="Forçar vetores (operações/tabelas desenhadas); ligado por padrão em balanced e full",
    )
    parser.add_argument(
        "--no-vector-clusters",
        action="store_true",
        help="Não incluir agrupamentos vetoriais (desliga operações matemáticas desenhadas)",
    )
    parser.add_argument(
        "--no-filter-decorative",
        action="store_true",
        help="Desliga filtro de quadrados azuis/cinzas e blocos decorativos pequenos",
    )
    parser.add_argument(
        "--render-dpi",
        type=int,
        default=150,
        help="DPI para recortes e fallback de página (padrão: 150)",
    )
    parser.add_argument(
        "--export-png",
        type=Path,
        default=None,
        help="Pasta para salvar cada figura como PNG (gravado página a página)",
    )
    parser.add_argument(
        "--no-page-caption",
        action="store_true",
        help="Não incluir legenda 'Página N' antes de cada imagem no Word",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Sem mensagens de progresso",
    )
    args = parser.parse_args()
    quiet = args.quiet

    if args.mode == "balanced":
        merge_nearby = not args.no_merge_nearby
        merge_tiles_only = True
        include_vectors = not args.no_vector_clusters
        use_dedupe = not args.no_dedupe
    elif args.mode == "full":
        merge_nearby = False
        merge_tiles_only = False
        include_vectors = not args.no_vector_clusters
        use_dedupe = args.dedupe
    else:  # compact
        merge_nearby = not args.no_merge_nearby
        merge_tiles_only = False
        include_vectors = args.vector_clusters and not args.no_vector_clusters
        use_dedupe = args.dedupe

    if args.dedupe:
        use_dedupe = True
    if args.vector_clusters:
        include_vectors = True
    if args.no_vector_clusters:
        include_vectors = False

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        print(f"Arquivo não encontrado: {pdf_path}", file=sys.stderr)
        return 1
    if pdf_path.suffix.lower() != ".pdf":
        print("O arquivo de entrada precisa ser .pdf", file=sys.stderr)
        return 1

    output_path = args.output or pdf_path.with_name(f"{pdf_path.stem}_imagens.docx")
    output_path = output_path.resolve()
    page_start, page_end = _parse_pages(args.pages)

    pdf_size_mb = pdf_path.stat().st_size / (1024 * 1024)
    _log(f"PDF: {pdf_path.name} ({pdf_size_mb:.1f} MB)", quiet=quiet)
    if args.pages:
        _log(f"Intervalo de paginas: {page_start}" + (f"-{page_end}" if page_end else ""), quiet=quiet)
    _log(f"Modo: {args.mode}", quiet=quiet)
    if include_vectors:
        _log("Vetores: ligado (operacoes/tabelas desenhadas)", quiet=quiet)
    else:
        _log("Vetores: desligado", quiet=quiet)
    if merge_nearby:
        kind = "tiles repetidos (cédulas/ícones)" if merge_tiles_only else "todos os rasters próximos"
        _log(
            f"Agrupamento: {kind}, >= {args.merge_min_count}/pagina, gap {args.merge_gap_pt}pt",
            quiet=quiet,
        )
    else:
        _log("Agrupamento: desligado (cada raster separado)", quiet=quiet)
    if use_dedupe:
        _log("Deduplicacao de imagens identicas: ligada", quiet=quiet)
    if args.no_filter_decorative:
        _log("Filtro decorativo DESLIGADO", quiet=quiet)

    t_read = time.perf_counter()
    _log("Lendo arquivo PDF...", quiet=quiet)
    pdf_bytes = pdf_path.read_bytes()
    if not pdf_bytes:
        print("PDF vazio.", file=sys.stderr)
        return 1
    _log(f"Leitura concluida em {time.perf_counter() - t_read:.1f}s", quiet=quiet)

    export_dir = args.export_png.resolve() if args.export_png else None
    if export_dir:
        export_dir.mkdir(parents=True, exist_ok=True)
        _log(f"PNGs serao gravados em: {export_dir}", quiet=quiet)

    fallback_dpi = args.render_dpi if args.include_page_fallback else 0
    images: list[ExtractedPdfImage] = []
    total_figures = 0
    total_skipped = 0
    pages_done = 0
    pages_in_job = 0
    kind_totals: Counter[str] = Counter()
    t_extract = time.perf_counter()

    def on_page_done(
        page_number: int,
        total: int,
        page_items: list[ExtractedPdfImage],
        elapsed: float,
        skipped: int,
    ) -> None:
        nonlocal total_figures, total_skipped, pages_done, pages_in_job
        pages_in_job = total
        pages_done += 1
        total_figures += len(page_items)
        total_skipped += skipped
        for item in page_items:
            kind_totals[item.kind] += 1

        kinds = ", ".join(f"{k}={v}" for k, v in sorted(Counter(i.kind for i in page_items).items()))
        kinds_part = f" ({kinds})" if kinds else ""
        skip_part = f", {skipped} ignorada(s)" if skipped else ""
        slow = " [lento]" if elapsed > 3.0 else ""
        eta = _format_eta(time.perf_counter() - t_extract, pages_done, total)
        _log(
            f"  [{pages_done}/{total}] pag {page_number}: "
            f"+{len(page_items)} figura(s){kinds_part}{skip_part} | total {total_figures} | "
            f"{elapsed:.1f}s{slow} | restante ~{eta}",
            quiet=quiet,
        )

    _log("Extraindo figuras...", quiet=quiet)
    for img in iter_extract_images_from_pdf(
        pdf_bytes,
        min_width_px=args.min_width,
        min_height_px=args.min_height,
        render_dpi=args.render_dpi,
        render_fallback_dpi=fallback_dpi,
        merge_nearby_rasters=merge_nearby,
        merge_tiles_only=merge_tiles_only,
        merge_min_count=args.merge_min_count,
        merge_gap_pt=args.merge_gap_pt,
        include_vector_clusters=include_vectors,
        filter_decorative=not args.no_filter_decorative,
        page_start=page_start,
        page_end=page_end,
        on_page_done=on_page_done,
    ):
        images.append(img)
        if export_dir:
            _export_png(img, export_dir)

    extract_elapsed = time.perf_counter() - t_extract
    if not images:
        print(
            "Nenhuma figura encontrada. Tente --include-page-fallback ou --vector-clusters, ou outro --pages.",
            file=sys.stderr,
        )
        return 2

    if use_dedupe:
        from src.pipeline.steps.pdf_images import _dedupe_by_hash

        before = len(images)
        images = _dedupe_by_hash(images)
        _log(f"Deduplicacao: {before} -> {len(images)} figuras", quiet=quiet)

    _log(
        f"Extracao: {len(images)} figura(s) em {pages_in_job} pagina(s), {extract_elapsed:.1f}s "
        f"({kind_totals.get('raster', 0)} raster, {kind_totals.get('vector', 0)} vetor, "
        f"{kind_totals.get('page', 0)} pagina inteira; {total_skipped} candidatos ignorados)",
        quiet=quiet,
    )

    if export_dir:
        _log(f"PNGs em: {export_dir}", quiet=quiet)

    total_images = len(images)
    progress_every = 1 if total_images <= 30 else 10 if total_images <= 200 else 25
    t_docx = time.perf_counter()
    t_insert_start = t_docx
    t_save_start = 0.0
    last_save_ping = 0.0

    def on_docx_progress(current: int, total: int, phase: str) -> None:
        nonlocal t_insert_start, t_save_start, last_save_ping
        if phase == "iniciando":
            _log(f"Word: montando com {total} imagem(ns)...", quiet=quiet)
            t_insert_start = time.perf_counter()
            return
        if phase == "inserindo":
            pct = int(100 * current / total) if total else 100
            elapsed = time.perf_counter() - t_insert_start
            eta = _format_eta(elapsed, current, total)
            _log(
                f"  Word inserindo: {current}/{total} ({pct}%) | restante ~{eta}",
                quiet=quiet,
            )
            return
        if phase == "salvando":
            now = time.perf_counter()
            if t_save_start == 0:
                t_save_start = now
                _log(
                    f"  Word gravando .docx ({total} imagens embutidas) — pode levar varios minutos...",
                    quiet=quiet,
                )
                last_save_ping = now
            elif now - last_save_ping >= 8:
                _log(f"  Word ainda gravando... ({now - t_save_start:.0f}s)", quiet=quiet)
                last_save_ping = now
            return
        if phase == "concluido":
            _log(f"  Word montado em {time.perf_counter() - t_docx:.1f}s", quiet=quiet)

    title = args.title or pdf_path.stem
    docx_bytes = build_docx_from_images(
        images,
        title=title,
        include_page_caption=not args.no_page_caption,
        on_progress=on_docx_progress,
        progress_every=progress_every,
        save_heartbeat_seconds=8.0,
    )
    _log("Gravando arquivo no disco...", quiet=quiet)
    output_path.write_bytes(docx_bytes)
    docx_mb = len(docx_bytes) / (1024 * 1024)
    _log(f"Concluido em {extract_elapsed + (time.perf_counter() - t_docx):.1f}s no total", quiet=quiet)

    print(f"OK: {len(images)} figura(s) -> {output_path} ({docx_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
