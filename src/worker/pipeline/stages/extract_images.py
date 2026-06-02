from src.core.config import get_settings
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

    page_results = []
    for page in pages:
        page_storage_path = storage.upload_page(
            isbn=isbn,
            page_name=page.page_name,
            content=page.page_png,
            process_version=process_version,
        )
        width_px, height_px = page.source_rgb_image.size
        page_id = artifacts_repo.add_page(book_id, page.page_number, page_storage_path, width_px, height_px)
        page_results.append(
            {
                "page_id": page_id,
                "page_number": page.page_number,
                "page_png": page.page_png,
                "page_storage_path": page_storage_path,
            }
        )

    ctx["pages"] = page_results
    return ctx
