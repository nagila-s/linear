import asyncio
import re
from typing import Any

from src.core.config import get_settings

CHECKPOINT_FILE = "linear_checkpoint.json"
DESCRIPTIONS_CHECKPOINT_FILE = "descriptions_checkpoint.json"


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


def _load_descriptions_checkpoint(
    storage: Any,
    isbn: str,
    process_version: str,
    job_id: str,
    prompt_version: str,
) -> dict[str, dict[str, Any]]:
    doc = storage.download_json_if_exists(isbn, process_version, job_id, DESCRIPTIONS_CHECKPOINT_FILE)
    if not doc or not isinstance(doc, dict):
        return {}
    if str(doc.get("prompt_version")) != str(prompt_version):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in doc.get("descriptions", []):
        if not isinstance(item, dict):
            continue
        figure_id = str(item.get("figure_id") or "").strip()
        if figure_id:
            out[figure_id] = item
    return out


def _save_descriptions_checkpoint(
    storage: Any,
    isbn: str,
    process_version: str,
    job_id: str,
    prompt_version: str,
    descriptions_by_figure: dict[str, dict[str, Any]],
) -> None:
    ordered = sorted(
        descriptions_by_figure.values(),
        key=lambda item: (int(item.get("page_number", 0)), str(item.get("figure_key", ""))),
    )
    storage.upload_json(
        isbn,
        process_version,
        job_id,
        DESCRIPTIONS_CHECKPOINT_FILE,
        {"prompt_version": prompt_version, "descriptions": ordered},
    )


def _extract_image_refs_and_captions(content: Any) -> tuple[set[str], dict[str, str]]:
    refs: set[str] = set()
    captions: dict[str, str] = {}
    fig_pattern = re.compile(r"^fig\d+$", re.IGNORECASE)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            image_id = str(node.get("id") or "").strip()
            if fig_pattern.match(image_id):
                image_id = image_id.lower()
                refs.add(image_id)
                legend = node.get("legenda")
                if legend is not None:
                    legend_text = str(legend).strip()
                    if legend_text:
                        captions[image_id] = legend_text

            refs_list = node.get("referencias_visuais")
            if isinstance(refs_list, list):
                for ref in refs_list:
                    ref_text = str(ref).strip().lower()
                    if fig_pattern.match(ref_text):
                        refs.add(ref_text)

            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(content)
    return refs, captions


async def run(ctx: dict) -> dict:
    openai = ctx["openai"]
    dorina = ctx["dorina"]
    artifacts_repo = ctx["artifacts_repo"]
    storage = ctx["storage"]
    prompt_version = ctx["prompt_version"]
    settings = get_settings()
    dorina_prompt_version = settings.dorina_prompt_version
    signed_url_ttl = int(settings.dorina_signed_url_expires_seconds)
    isbn = ctx["isbn"]
    job_id = ctx["job_id"]
    process_version = ctx["process_version"]
    concurrency = max(1, int(ctx.get("linearize_page_concurrency") or 4))

    pages = ctx.get("pages", [])
    figures_by_page = ctx.get("figures_by_page", {})
    pages_done: dict[int, dict[str, Any]] = await asyncio.to_thread(
        _load_linear_checkpoint,
        storage,
        isbn,
        process_version,
        job_id,
        prompt_version,
    )
    descriptions_done: dict[str, dict[str, Any]] = await asyncio.to_thread(
        _load_descriptions_checkpoint,
        storage,
        isbn,
        process_version,
        job_id,
        dorina_prompt_version,
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

        refs, captions = _extract_image_refs_and_captions(page_structure)
        page_figures = sorted(
            figures_by_page.get(page_number, []),
            key=lambda item: int(item.get("figure_index") or 0),
        )
        selected = [fig for fig in page_figures if str(fig.get("figure_key", "")).lower() in refs]
        page_descriptions: list[dict[str, Any]] = []
        for fig in selected:
            figure_id = str(fig.get("figure_id") or "").strip()
            if not figure_id:
                continue
            if figure_id in descriptions_done:
                page_descriptions.append(descriptions_done[figure_id])
                continue

            image_url = await asyncio.to_thread(
                storage.signed_url_for_storage_path,
                str(fig.get("storage_path") or ""),
                signed_url_ttl,
            )
            figure_key = str(fig.get("figure_key") or "").lower()
            caption_context = captions.get(figure_key, "")
            try:
                dorina_payload = await dorina.describe(
                    image_url=image_url,
                    context=caption_context,
                    prompt_version=dorina_prompt_version,
                )
            except Exception as exc:
                description_item = {
                    "figure_id": figure_id,
                    "figure_key": figure_key,
                    "page_number": page_number,
                    "prompt_version": dorina_prompt_version,
                    "context": caption_context,
                    "payload": {"error": str(exc)},
                    "description": "",
                    "status": "failed",
                }
                descriptions_done[figure_id] = description_item
                page_descriptions.append(description_item)
                continue
            description_item = {
                "figure_id": figure_id,
                "figure_key": figure_key,
                "page_number": page_number,
                "prompt_version": dorina_prompt_version,
                "context": caption_context,
                "payload": dorina_payload,
                "description": str(dorina_payload.get("description") or dorina_payload.get("texto") or ""),
                "status": "ok",
            }
            await asyncio.to_thread(
                artifacts_repo.save_description,
                figure_id,
                dorina_prompt_version,
                dorina_payload,
            )
            descriptions_done[figure_id] = description_item
            page_descriptions.append(description_item)

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
            if page_descriptions:
                await asyncio.to_thread(
                    _save_descriptions_checkpoint,
                    storage,
                    isbn,
                    process_version,
                    job_id,
                    dorina_prompt_version,
                    descriptions_done,
                )

    pending = [p for p in pages if int(p["page_number"]) not in pages_done]
    if pending:
        await asyncio.gather(*[process_page(p) for p in pending])

    linearized_pages = [pages_done[n] for n in sorted(pages_done)]
    ctx["linearized_pages"] = linearized_pages
    ctx["descriptions"] = sorted(
        descriptions_done.values(),
        key=lambda item: (int(item.get("page_number", 0)), str(item.get("figure_key", ""))),
    )
    ctx["described_count"] = len(linearized_pages)
    ctx["failed_count"] = sum(1 for item in ctx["descriptions"] if str(item.get("status")) == "failed")
    return ctx
