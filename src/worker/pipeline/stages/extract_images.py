from src.pipeline.steps.preprocess import extract_figures_from_page, preprocess_pdf


async def run(ctx: dict) -> dict:
    storage = ctx["storage"]
    artifacts_repo = ctx["artifacts_repo"]
    book_id = ctx["book_id"]
    isbn = ctx["isbn"]
    process_version = ctx["process_version"]
    pdf_path = ctx["pdf_storage_path"]

    pdf_bytes = storage.download_by_storage_path(pdf_path)
    pages = preprocess_pdf(pdf_bytes)

    page_results = []
    figure_results = []
    figure_map = {}

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

        page_figures = extract_figures_from_page(page)
        page_keys = []
        for fig in page_figures:
            figure_storage_path = storage.upload_figure(
                isbn=isbn,
                page_folder=fig.page_folder,
                figure_name=fig.figure_name,
                content=fig.figure_png,
                process_version=process_version,
            )
            figure_id = artifacts_repo.add_figure(book_id, page_id, fig.figure_index, figure_storage_path)
            figure_results.append(
                {
                    "figure_id": figure_id,
                    "figure_key": fig.figure_key,
                    "figure_index": fig.figure_index,
                    "page_number": fig.page_number,
                    "figure_storage_path": figure_storage_path,
                }
            )
            page_keys.append(fig.figure_key)
        figure_map[page.page_number] = page_keys

    ctx["pages"] = page_results
    ctx["figures"] = figure_results
    ctx["figure_keys_by_page"] = figure_map
    return ctx
