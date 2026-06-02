import asyncio
from typing import Any

CHECKPOINT_FILE = "linear_checkpoint.json"


def _load_linear_checkpoint(
    storage: Any,
    isbn: str,
    process_version: str,
    job_id: str,
    prompt_version: str,
) -> dict[int, dict[str, Any]]:
    doc = storage.download_json_if_exists(isbn, process_version, job_id, CHECKPOINT_FILE)
    if not doc or not isinstance(doc, dict):
        return {}
    if str(doc.get("prompt_version")) != str(prompt_version):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for item in doc.get("pages", []):
        if not isinstance(item, dict):
            continue
        pn = item.get("page_number")
        if isinstance(pn, int) and pn > 0:
            out[pn] = item
    return out


def _save_linear_checkpoint(
    storage: Any,
    isbn: str,
    process_version: str,
    job_id: str,
    prompt_version: str,
    pages_by_num: dict[int, dict[str, Any]],
) -> None:
    ordered = [pages_by_num[n] for n in sorted(pages_by_num)]
    storage.upload_json(
        isbn,
        process_version,
        job_id,
        CHECKPOINT_FILE,
        {"prompt_version": prompt_version, "pages": ordered},
    )


async def run(ctx: dict) -> dict:
    openai = ctx["openai"]
    storage = ctx["storage"]
    prompt_version = ctx["prompt_version"]
    isbn = ctx["isbn"]
    job_id = ctx["job_id"]
    process_version = ctx["process_version"]
    concurrency = max(1, int(ctx.get("linearize_page_concurrency") or 4))

    pages = ctx.get("pages", [])
    pages_done: dict[int, dict[str, Any]] = await asyncio.to_thread(
        _load_linear_checkpoint,
        storage,
        isbn,
        process_version,
        job_id,
        prompt_version,
    )

    sem = asyncio.Semaphore(concurrency)
    ck_lock = asyncio.Lock()

    async def process_page(page: dict) -> None:
        page_number = int(page["page_number"])
        async with sem:
            page_structure = await asyncio.to_thread(
                openai.linearize_page,
                page["page_png"],
                prompt_version,
            )
        linear_entry = {
            "page_number": page_number,
            "content": page_structure,
        }
        async with ck_lock:
            pages_done[page_number] = linear_entry
            await asyncio.to_thread(
                _save_linear_checkpoint,
                storage,
                isbn,
                process_version,
                job_id,
                prompt_version,
                pages_done,
            )

    pending = [p for p in pages if int(p["page_number"]) not in pages_done]
    if pending:
        await asyncio.gather(*[process_page(p) for p in pending])

    linearized_pages = [pages_done[n] for n in sorted(pages_done)]
    ctx["linearized_pages"] = linearized_pages
    ctx["described_count"] = len(linearized_pages)
    ctx["failed_count"] = 0
    return ctx
