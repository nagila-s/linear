"""Pipeline síncrono para a área de testes de prompts.

Diferente do worker de produção, este fluxo NÃO usa fila, banco (jobs/books/figures)
nem checkpoints. Ele processa um PDF pequeno na hora, chamando OpenAI e Dorina
diretamente, e devolve o JSON final. Serve para experimentar prompts sem afetar o
pipeline principal nem os prompts do sistema.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from src.pipeline.steps.pdf_images import extract_images_from_pdf
from src.pipeline.steps.preprocess import preprocess_pdf
from src.services.dorina_client import DorinaService
from src.services.openai_client import OpenAIService
from src.services.prompt_router import PromptRouter, sanitize_prompt_overrides
from src.services.storage import StorageService
from src.worker.pipeline.stages.describe import (
    _apply_descriptions_to_content,
    _build_dorina_context,
    _extract_image_refs_and_captions,
    _resolve_targets,
)

logger = logging.getLogger(__name__)

MAX_TEST_PAGES = 30


def run_test_linearization(
    pdf_bytes: bytes,
    *,
    prompt_overrides: Optional[Dict[str, str]] = None,
    miolo_only: bool = False,
    isbn: str = "teste",
    dpi: Optional[int] = None,
) -> Dict[str, Any]:
    settings = StorageService().settings
    overrides = sanitize_prompt_overrides(prompt_overrides or {})
    render_dpi = int(dpi or settings.pdf_render_dpi)
    run_id = uuid.uuid4().hex[:12]
    test_version = f"test-{run_id}"
    prompt_version = "test"
    dorina_prompt_version = settings.dorina_prompt_version
    signed_url_ttl = int(settings.dorina_signed_url_expires_seconds)

    openai = OpenAIService(miolo_only=miolo_only, prompt_overrides=overrides or None)
    storage = StorageService()

    pages = preprocess_pdf(
        pdf_bytes,
        dpi=render_dpi,
        batch_size=int(settings.pdf_render_batch_size),
        keep_rgb=False,
    )
    if len(pages) > MAX_TEST_PAGES:
        raise ValueError(
            f"PDF de teste tem {len(pages)} páginas; o limite da área de testes é {MAX_TEST_PAGES}. "
            "Use um recorte menor."
        )
    total_pages = len(pages)

    extracted = extract_images_from_pdf(
        pdf_bytes,
        render_dpi=render_dpi,
        render_fallback_dpi=render_dpi,
    )
    figures_by_page: Dict[int, List[dict]] = {}
    figure_keys_by_page: Dict[int, List[str]] = {}
    counter: Dict[int, int] = {}
    for item in sorted(extracted, key=lambda i: (i.page_number, i.image_index)):
        page_number = int(item.page_number)
        idx = counter.get(page_number, 0) + 1
        counter[page_number] = idx
        figure_name = f"fig{idx:04}.png"
        page_folder = f"p{page_number:04}"
        storage_path = storage.upload_figure(
            isbn=isbn,
            page_folder=page_folder,
            figure_name=figure_name,
            content=item.image_bytes,
            process_version=test_version,
        )
        entry = {
            "figure_id": None,
            "figure_index": idx,
            "figure_key": f"fig{idx}",
            "page_number": page_number,
            "storage_path": storage_path,
        }
        figures_by_page.setdefault(page_number, []).append(entry)
        figure_keys_by_page.setdefault(page_number, []).append(entry["figure_key"])

    dorina: Optional[DorinaService] = None
    linearized_pages: List[dict] = []
    all_descriptions: List[dict] = []
    contexts: Dict[str, str] = {}

    for page in pages:
        page_number = int(page.page_number)
        figure_keys = figure_keys_by_page.get(page_number, [])
        page_type = openai.resolve_page_type(
            page.page_png,
            page_number=page_number,
            total_pages=total_pages,
        )
        wants_figures = (
            miolo_only or PromptRouter.supports_figure_description(page_type)
        ) and bool(figure_keys)

        if wants_figures:
            combined = openai.linearize_and_extract_context(
                page.page_png,
                figure_keys,
                prompt_version,
                page_number=page_number,
                total_pages=total_pages,
                page_type=page_type,
            )
            page_structure = combined["page_structure"]
            page_contexts = combined.get("figure_contexts", {}) or {}
        else:
            page_structure = openai.linearize_page(
                page.page_png,
                prompt_version,
                page_number=page_number,
                total_pages=total_pages,
                page_type=page_type,
            )
            page_contexts = {}

        for key, ctx_text in page_contexts.items():
            if ctx_text:
                contexts[key] = ctx_text

        describe_ok = miolo_only or PromptRouter.supports_figure_description(
            str(page_structure.get("tipo_pagina") or "conteudo")
        )
        if describe_ok:
            refs, captions = _extract_image_refs_and_captions(page_structure)
            for ref, legend in captions.items():
                contexts.setdefault(ref, legend)
            targets = _resolve_targets(refs, figures_by_page.get(page_number, []), {})
            if targets and dorina is None:
                dorina = DorinaService()
            descriptions_by_key: Dict[str, str] = {}
            for target in targets:
                figure_key = str(target["figure_key"])
                caption_context = _build_dorina_context(figure_key, captions, page_contexts)
                try:
                    image_url = storage.signed_url_for_storage_path(
                        str(target["storage_path"]), signed_url_ttl
                    )
                    payload = dorina.describe_figure(  # type: ignore[union-attr]
                        image_url=image_url,
                        isbn=isbn,
                        context=caption_context,
                        prompt_version=dorina_prompt_version,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "test-run page=%s figure=%s dorina_failed: %s",
                        page_number,
                        figure_key,
                        exc,
                    )
                    all_descriptions.append(
                        {
                            "figure_key": figure_key,
                            "page_number": page_number,
                            "context": caption_context,
                            "description": "",
                            "status": "failed",
                            "error": str(exc)[:400],
                        }
                    )
                    continue

                description_text = str(
                    payload.get("description")
                    or payload.get("texto")
                    or payload.get("caption")
                    or ""
                ).strip()
                if description_text:
                    descriptions_by_key[figure_key.lower()] = description_text
                all_descriptions.append(
                    {
                        "figure_key": figure_key,
                        "page_number": page_number,
                        "context": caption_context,
                        "description": description_text,
                        "status": "ok" if description_text else "failed",
                    }
                )
            if descriptions_by_key:
                _apply_descriptions_to_content(page_structure, descriptions_by_key)

        linearized_pages.append(
            {"page_number": page_number, "content": page_structure}
        )

    described_ok = sum(1 for d in all_descriptions if d["status"] == "ok")
    dorina_failed = sum(1 for d in all_descriptions if d["status"] == "failed")

    return {
        "isbn": isbn,
        "test_run": True,
        "run_id": run_id,
        "job_type": "linearizar",
        "prompt_version": prompt_version,
        "process_version": test_version,
        "dpi": render_dpi,
        "miolo_only": miolo_only,
        "prompt_overrides": sorted(overrides.keys()),
        "pages": linearized_pages,
        "image_context": [
            {"figure_key": key, "context": value}
            for key, value in sorted(contexts.items())
        ],
        "descriptions": all_descriptions,
        "stats": {
            "pages": total_pages,
            "figures": sum(len(v) for v in figures_by_page.values()),
            "described_ok": described_ok,
            "dorina_failed": dorina_failed,
        },
    }
