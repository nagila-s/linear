import logging
from typing import Any

from src.core.config import get_settings
from src.pipeline.steps.pdf_images import extract_images_from_pdf
from src.pipeline.steps.preprocess import preprocess_pdf

logger = logging.getLogger(__name__)

EXTRACT_CHECKPOINT_FILE = "extract_checkpoint.json"


def _save_extract_checkpoint(
    storage: Any,
    isbn: str,
    process_version: str,
    job_id: str,
    *,
    dpi: int,
    pages_meta: list[dict],
    figures: list[dict],
    figures_by_page: dict[int, list[dict]],
    figure_keys_by_page: dict[int, list[str]],
) -> None:
    storage.upload_json(
        isbn,
        process_version,
        job_id,
        EXTRACT_CHECKPOINT_FILE,
        {
            "dpi": dpi,
            "process_version": process_version,
            "pages": pages_meta,
            "figures": figures,
            "figures_by_page": {str(k): v for k, v in figures_by_page.items()},
            "figure_keys_by_page": {str(k): v for k, v in figure_keys_by_page.items()},
        },
    )


def _load_extract_checkpoint(
    storage: Any,
    isbn: str,
    process_version: str,
    job_id: str,
    *,
    expected_dpi: int,
) -> dict | None:
    """Reusa páginas/figuras de um retry anterior para não re-rasterizar o PDF (pico de RAM)."""
    doc = storage.download_json_if_exists(isbn, process_version, job_id, EXTRACT_CHECKPOINT_FILE)
    if not doc or not isinstance(doc, dict):
        return None
    if str(doc.get("process_version") or "") != str(process_version):
        return None
    if int(doc.get("dpi") or 0) != int(expected_dpi):
        return None
    pages_meta = doc.get("pages")
    if not isinstance(pages_meta, list) or not pages_meta:
        return None
    return doc


def _restore_from_checkpoint(storage: Any, doc: dict) -> dict:
    page_results: list[dict] = []
    for meta in doc.get("pages", []):
        if not isinstance(meta, dict):
            continue
        storage_path = str(meta.get("page_storage_path") or "").strip()
        page_number = int(meta.get("page_number") or 0)
        if not storage_path or page_number <= 0:
            continue
        page_png = storage.download_by_storage_path(storage_path)
        page_results.append(
            {
                "page_id": meta.get("page_id"),
                "page_number": page_number,
                "page_png": page_png,
                "page_storage_path": storage_path,
                "width_px": int(meta.get("width_px") or 0),
                "height_px": int(meta.get("height_px") or 0),
            }
        )

    if not page_results:
        raise ValueError("extract_checkpoint sem paginas recuperaveis.")

    figures = list(doc.get("figures") or [])
    figures_by_page_raw = doc.get("figures_by_page") or {}
    figure_keys_raw = doc.get("figure_keys_by_page") or {}
    figures_by_page: dict[int, list[dict]] = {
        int(k): v for k, v in figures_by_page_raw.items() if str(k).isdigit()
    }
    figure_keys_by_page: dict[int, list[str]] = {
        int(k): v for k, v in figure_keys_raw.items() if str(k).isdigit()
    }

    logger.info(
        "Reusando extract_checkpoint: pages=%s figures=%s (skip rasterize)",
        len(page_results),
        len(figures),
    )
    return {
        "pages": sorted(page_results, key=lambda p: int(p["page_number"])),
        "figures": figures,
        "figures_by_page": figures_by_page,
        "figure_keys_by_page": figure_keys_by_page,
    }


async def run(ctx: dict) -> dict:
    storage = ctx["storage"]
    artifacts_repo = ctx["artifacts_repo"]
    book_id = ctx["book_id"]
    isbn = ctx["isbn"]
    job_id = ctx["job_id"]
    process_version = ctx["process_version"]
    pdf_path = ctx["pdf_storage_path"]
    settings = get_settings()
    dpi = int(ctx.get("pdf_render_dpi") or settings.pdf_render_dpi)
    batch_size = int(settings.pdf_render_batch_size)

    cached = _load_extract_checkpoint(
        storage,
        isbn,
        process_version,
        job_id,
        expected_dpi=dpi,
    )
    if cached is not None:
        try:
            restored = _restore_from_checkpoint(storage, cached)
            ctx["pages"] = restored["pages"]
            ctx["figures"] = restored["figures"]
            ctx["figures_by_page"] = restored["figures_by_page"]
            ctx["figure_keys_by_page"] = restored["figure_keys_by_page"]
            return ctx
        except Exception as exc:
            logger.warning(
                "Falha ao reusar extract_checkpoint (job=%s): %s — re-extraindo.",
                job_id,
                exc,
            )

    pdf_bytes = storage.download_by_storage_path(pdf_path)
    pages = preprocess_pdf(pdf_bytes, dpi=dpi, batch_size=batch_size, keep_rgb=False)
    extracted_figures = extract_images_from_pdf(
        pdf_bytes,
        render_dpi=dpi,
        render_fallback_dpi=dpi,
    )
    # PDF em bytes já não é necessário após extract; libera referência cedo.
    del pdf_bytes

    page_results = []
    pages_meta: list[dict] = []
    page_id_by_number: dict[int, str] = {}
    for page in pages:
        page_storage_path = storage.upload_page(
            isbn=isbn,
            page_name=page.page_name,
            content=page.page_png,
            process_version=process_version,
        )
        width_px = int(page.width_px)
        height_px = int(page.height_px)
        # Garante que nenhum RGB residual fique vivo após o upload.
        if page.source_rgb_image is not None:
            try:
                page.source_rgb_image.close()
            except Exception:
                pass
            page.source_rgb_image = None

        page_id = artifacts_repo.add_page(book_id, page.page_number, page_storage_path, width_px, height_px)
        page_id_by_number[page.page_number] = str(page_id)
        page_results.append(
            {
                "page_id": page_id,
                "page_number": page.page_number,
                "page_png": page.page_png,
                "page_storage_path": page_storage_path,
                "width_px": width_px,
                "height_px": height_px,
            }
        )
        pages_meta.append(
            {
                "page_id": str(page_id),
                "page_number": page.page_number,
                "page_storage_path": page_storage_path,
                "width_px": width_px,
                "height_px": height_px,
            }
        )

    figures_by_page: dict[int, list[dict]] = {}
    figure_keys_by_page: dict[int, list[str]] = {}
    figures: list[dict] = []
    figures_by_page_counter: dict[int, int] = {}
    ordered_figures = sorted(extracted_figures, key=lambda item: (item.page_number, item.image_index))
    for item in ordered_figures:
        page_number = int(item.page_number)
        page_id = page_id_by_number.get(page_number)
        if not page_id:
            continue

        current_idx = figures_by_page_counter.get(page_number, 0) + 1
        figures_by_page_counter[page_number] = current_idx
        figure_name = f"fig{current_idx:04}.png"
        page_folder = f"p{page_number:04}"
        figure_storage_path = storage.upload_figure(
            isbn=isbn,
            page_folder=page_folder,
            figure_name=figure_name,
            content=item.image_bytes,
            process_version=process_version,
        )
        figure_id = artifacts_repo.add_figure(
            book_id=book_id,
            page_id=page_id,
            figure_index=current_idx,
            storage_path=figure_storage_path,
        )
        figure_entry = {
            "figure_id": str(figure_id),
            "figure_index": current_idx,
            "figure_key": f"fig{current_idx}",
            "page_number": page_number,
            "storage_path": figure_storage_path,
        }
        figures_by_page.setdefault(page_number, []).append(figure_entry)
        figure_keys_by_page.setdefault(page_number, []).append(figure_entry["figure_key"])
        figures.append(figure_entry)

    _save_extract_checkpoint(
        storage,
        isbn,
        process_version,
        job_id,
        dpi=dpi,
        pages_meta=pages_meta,
        figures=figures,
        figures_by_page=figures_by_page,
        figure_keys_by_page=figure_keys_by_page,
    )

    ctx["pages"] = page_results
    ctx["figures"] = figures
    ctx["figures_by_page"] = figures_by_page
    ctx["figure_keys_by_page"] = figure_keys_by_page
    return ctx
