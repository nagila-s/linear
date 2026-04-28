import asyncio


async def run(ctx: dict) -> dict:
    openai = ctx["openai"]
    dorina = ctx["dorina"]
    storage = ctx["storage"]
    artifacts_repo = ctx["artifacts_repo"]
    prompt_version = ctx["prompt_version"]
    isbn = ctx["isbn"]

    pages = ctx.get("pages", [])
    figures = ctx.get("figures", [])
    figure_keys_by_page = ctx.get("figure_keys_by_page", {})
    figure_id_by_key = {f["figure_key"]: f["figure_id"] for f in figures}
    figure_path_by_key = {f["figure_key"]: f["figure_storage_path"] for f in figures}

    linearized_pages = []
    contexts = {}
    descriptions = []
    failures = 0

    for page in pages:
        page_number = page["page_number"]
        figure_keys = figure_keys_by_page.get(page_number, [])
        combined = await asyncio.to_thread(
            openai.linearize_and_extract_context,
            page["page_png"],
            figure_keys,
            prompt_version,
        )
        page_structure = combined["page_structure"]
        page_contexts = combined["figure_contexts"]
        contexts.update(page_contexts)
        linearized_pages.append(
            {
                "page_number": page_number,
                "content": page_structure,
                "figure_refs": figure_keys,
            }
        )
        for key, context in page_contexts.items():
            figure_id = figure_id_by_key.get(key)
            if figure_id:
                artifacts_repo.save_context(figure_id, context, prompt_version)

    for figure in figures:
        figure_key = figure["figure_key"]
        figure_id = figure["figure_id"]
        context = contexts.get(figure_key, "")
        storage_path = figure_path_by_key[figure_key]
        try:
            signed_url = storage.signed_url_for_storage_path(
                storage_path,
                expires_in=storage.settings.dorina_signed_url_expires_seconds,
            )
            description_payload = await asyncio.to_thread(
                dorina.describe_figure,
                signed_url,
                isbn,
                context,
                prompt_version,
            )
            artifacts_repo.save_description(figure_id, prompt_version, description_payload)
            descriptions.append(
                {
                    "figure_key": figure_key,
                    "figure_id": figure_id,
                    **description_payload,
                }
            )
        except Exception:
            failures += 1

    ctx["linearized_pages"] = linearized_pages
    ctx["contexts"] = contexts
    ctx["descriptions"] = descriptions
    ctx["described_count"] = len(descriptions)
    ctx["failed_count"] = failures
    return ctx
