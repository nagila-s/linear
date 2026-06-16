from src.core.config import get_settings
from src.pipeline.steps.pdf_images import extract_images_from_pdf
from src.pipeline.steps.preprocess import preprocess_pdf


async def run(ctx: dict) -> dict:
    storage = ctx["storage"]
    artifacts_repo = ctx["artifacts_repo"]
    book_id = ctx["book_id"]
    isbn = ctx["isbn"]
    process_version = ctx["process_version"]
    pdf_path = ctx["pdf_storage_path"]
    dpi = int(ctx.get("pdf_render_dpi") or get_settings().pdf_render_dpi)

    pdf_bytes = storage.download_by_storage_path(pdf_path)
    pages = preprocess_pdf(pdf_bytes, dpi=dpi)
    extracted_figures = extract_images_from_pdf(pdf_bytes, render_dpi=dpi)

    page_results = []
    page_id_by_number: dict[int, str] = {}
    for page in pages:
        page_storage_path = storage.upload_page(
            isbn=isbn,
            page_name=page.page_name,
            content=page.page_png,
            process_version=process_version,
        )
        width_px, height_px = page.source_rgb_image.size
        page_id = artifacts_repo.add_page(book_id, page.page_number, page_storage_path, width_px, height_px)
        page_id_by_number[page.page_number] = str(page_id)
        page_results.append(
            {
                "page_id": page_id,
                "page_number": page.page_number,
                "page_png": page.page_png,
                "page_storage_path": page_storage_path,
            }
        )

    figures_by_page: dict[int, list[dict]] = {}
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
        figures_by_page.setdefault(page_number, []).append(
            {
                "figure_id": str(figure_id),
                "figure_index": current_idx,
                "figure_key": f"fig{current_idx}",
                "page_number": page_number,
                "storage_path": figure_storage_path,
            }
        )

    ctx["pages"] = page_results
    ctx["figures_by_page"] = figures_by_page
    return ctx
