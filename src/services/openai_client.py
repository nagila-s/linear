import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import APIError, BadRequestError, NotFoundError, OpenAI
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.core.config import get_settings
from src.core.errors import IntegrationError
from src.services.prompt_router import PromptRouter
from src.utils.json_codec import merge_json_fragments, parse_llm_json

logger = logging.getLogger(__name__)

_COMBINED_FIGURE_SUFFIX = (
    "\n\nRetorne JSON com as chaves page_structure e figure_contexts. "
    "page_structure deve seguir a estrutura deste prompt. "
    "figure_contexts deve ser uma lista de objetos com figure_key e context. "
    "Considere apenas estas figuras: {figure_keys}"
)

_JSON_RETRY_SUFFIX = (
    "\n\nRetorne SOMENTE JSON valido e completo. "
    'Use "texto" como string simples sempre que possivel. '
    'Escape aspas internas com \\". '
    "Nao trunque o JSON."
)

_JSON_COMPACT_SUFFIX = (
    "\n\nA pagina e densa. Priorize JSON COMPLETO e VALIDO sobre detalhe tipografico. "
    'Use sempre "texto" como string simples (nunca array de estilos). '
    "Omita campos null. Nao use markdown. Nao corte o JSON no meio."
)


class OpenAIService:
    def __init__(
        self,
        *,
        miolo_only: bool = False,
        prompt_overrides: Optional[Dict[str, str]] = None,
    ) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise IntegrationError("OPENAI_API_KEY nao configurado.")
        self.settings = settings
        self.miolo_only = bool(miolo_only)
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.prompt_router = PromptRouter(
            settings.prompts_directory,
            window_start=settings.classification_window_start,
            window_end=settings.classification_window_end,
            overrides=prompt_overrides,
        )

    @property
    def prompt_routing_enabled(self) -> bool:
        if self.miolo_only:
            return False
        return bool(self.settings.prompt_routing_enabled)

    def _linearize_max_tokens(self) -> Optional[int]:
        value = int(self.settings.linearize_max_output_tokens or 0)
        return value if value > 0 else None

    def _continue_truncated_json(
        self,
        page_png: bytes,
        partial: str,
        *,
        page_number: Optional[int] = None,
    ) -> str:
        """Pede ao modelo o JSON completo a partir de um rascunho truncado."""
        clip = partial.strip()
        if len(clip) > 60000:
            clip = clip[:2000] + "\n...\n" + clip[-50000:]
        prompt = (
            "O JSON abaixo foi TRUNCADO no meio. "
            "Reescreva o objeto JSON COMPLETO e VALIDO da pagina, "
            "preservando o conteudo ja presente e completando o que faltou. "
            "Retorne SOMENTE o JSON final (um unico objeto), sem markdown.\n\n"
            f"JSON truncado:\n{clip}"
        )
        logger.warning(
            "Continuando JSON truncado pagina=%s partial_chars=%s",
            page_number,
            len(partial),
        )
        return self._ask_vision(
            page_png,
            prompt,
            self.settings.openai_model_linearization,
            json_mode=True,
            max_output_tokens=self._linearize_max_tokens(),
        )

    def _parse_linearization_content(
        self,
        content: str,
        page_png: bytes,
        *,
        page_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            return self._extract_json(content, page_number=page_number)
        except IntegrationError:
            if not content or not content.strip():
                raise
            # Sempre tenta completar quando parece truncado ou o parse falhou com corpo parcial.
            try:
                continued = self._continue_truncated_json(
                    page_png,
                    content,
                    page_number=page_number,
                )
            except IntegrationError:
                raise
            merged = merge_json_fragments(content, continued)
            for candidate in (continued, merged, content):
                try:
                    return self._extract_json(candidate, page_number=page_number)
                except IntegrationError:
                    continue
            raise

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(IntegrationError),
        reraise=True,
    )
    def linearize_page(
        self,
        page_png: bytes,
        prompt_version: str,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
        page_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        if page_type is None:
            prompt, page_type = self._resolve_linearization(page_png, page_number, total_pages)
        else:
            prompt = self.prompt_router.get_prompt(page_type)

        attempt_prompts = (
            prompt,
            prompt + _JSON_RETRY_SUFFIX,
            prompt + _JSON_COMPACT_SUFFIX,
        )
        last_error: IntegrationError | None = None
        max_tokens = self._linearize_max_tokens()
        for attempt, extra in enumerate(attempt_prompts):
            try:
                content = self._ask_vision(
                    page_png,
                    extra,
                    self.settings.openai_model_linearization,
                    json_mode=True,
                    max_output_tokens=max_tokens,
                )
            except IntegrationError as exc:
                last_error = exc
                logger.warning(
                    "Falha na chamada OpenAI pagina=%s attempt=%s: %s",
                    page_number,
                    attempt + 1,
                    exc,
                )
                continue
            try:
                data = self._parse_linearization_content(
                    content,
                    page_png,
                    page_number=page_number,
                )
            except IntegrationError as exc:
                last_error = exc
                logger.warning(
                    "JSON invalido na pagina %s (attempt=%s); retry com prompt reforcado/compacto.",
                    page_number,
                    attempt + 1,
                )
                continue
            self._apply_page_metadata(data, page_type, prompt_version)
            if attempt > 0:
                logger.info(
                    "pagina=%s linearizada apos retry attempt=%s",
                    page_number,
                    attempt + 1,
                )
            return data

        if last_error is not None:
            raise last_error
        raise IntegrationError("Falha ao linearizar pagina.")

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(IntegrationError),
        reraise=True,
    )
    def extract_context(
        self,
        page_png: bytes,
        figure_keys: List[str],
        prompt_version: str,
    ) -> Dict[str, str]:
        prompt = (
            "Para cada figura desta pagina, gere contexto textual util para descricao acessivel. "
            f'Retorne JSON no formato {{"figures": [{{"figure_key": "...", "context": "..."}}]}}. '
            f"Considere apenas estas figuras: {figure_keys}"
        )
        content = self._ask_vision(page_png, prompt, self.settings.openai_model_context, json_mode=True)
        data = self._extract_json(content)
        figures = data.get("figures", [])
        output: Dict[str, str] = {}
        for item in figures:
            key = item.get("figure_key")
            context = item.get("context", "")
            if key:
                output[key] = context
        for key in figure_keys:
            output.setdefault(key, "")
        return output

    def resolve_page_type(
        self,
        page_png: bytes,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
    ) -> str:
        _, page_type = self._resolve_linearization(page_png, page_number, total_pages)
        return page_type

    def linearize_and_extract_context(
        self,
        page_png: bytes,
        figure_keys: List[str],
        prompt_version: str,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
        page_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        if page_type is None:
            page_type = self.resolve_page_type(
                page_png,
                page_number=page_number,
                total_pages=total_pages,
            )
        if self.prompt_router.should_skip_figure_pipeline(page_type):
            return {
                "page_structure": self.linearize_page(
                    page_png,
                    prompt_version,
                    page_number=page_number,
                    total_pages=total_pages,
                    page_type=page_type,
                ),
                "figure_contexts": {},
            }

        if not self.settings.openai_combined_mode:
            return {
                "page_structure": self.linearize_page(
                    page_png,
                    prompt_version,
                    page_number=page_number,
                    total_pages=total_pages,
                    page_type=page_type,
                ),
                "figure_contexts": self.extract_context(page_png, figure_keys, prompt_version),
            }

        prompt = self.prompt_router.get_prompt(page_type)
        combined_prompt = prompt + _COMBINED_FIGURE_SUFFIX.format(figure_keys=figure_keys)
        content = self._ask_vision(
            page_png,
            combined_prompt,
            self.settings.openai_model_linearization,
            json_mode=True,
        )
        data = self._extract_json(content, page_number=page_number)
        page_structure = data.get("page_structure")
        contexts_raw = data.get("figure_contexts", [])
        if not isinstance(page_structure, dict) or not isinstance(contexts_raw, list):
            return {
                "page_structure": self.linearize_page(
                    page_png,
                    prompt_version,
                    page_number=page_number,
                    total_pages=total_pages,
                    page_type=page_type,
                ),
                "figure_contexts": self.extract_context(page_png, figure_keys, prompt_version),
            }

        contexts: Dict[str, str] = {}
        for item in contexts_raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("figure_key", "")).strip()
            if key:
                contexts[key] = str(item.get("context", ""))
        for key in figure_keys:
            contexts.setdefault(key, "")
        self._apply_page_metadata(page_structure, page_type, prompt_version)
        return {"page_structure": page_structure, "figure_contexts": contexts}

    def _resolve_linearization(
        self,
        page_png: bytes,
        page_number: Optional[int],
        total_pages: Optional[int],
    ) -> Tuple[str, str]:
        if (
            not self.prompt_routing_enabled
            or page_number is None
            or total_pages is None
            or total_pages <= 0
        ):
            return self.prompt_router.get_prompt("conteudo"), "conteudo"

        if not self.prompt_router.should_classify(page_number, total_pages):
            page_type = "conteudo"
        else:
            classified = self._classify_page_type(page_png)
            page_type = self.prompt_router.resolve_page_type(page_number, total_pages, classified)
            logger.info(
                "page=%s/%s classified=%s routed=%s",
                page_number,
                total_pages,
                classified,
                page_type,
            )

        return self.prompt_router.get_prompt(page_type), page_type

    def _classify_page_type(self, page_png: bytes) -> str:
        content = self._ask_vision(
            page_png,
            self.prompt_router.classifier_prompt,
            self.settings.openai_model_classifier,
            max_output_tokens=self.settings.classifier_max_output_tokens,
        )
        return self.prompt_router.normalize_page_type(content)

    @staticmethod
    def _apply_page_metadata(data: Dict[str, Any], page_type: str, prompt_version: str) -> None:
        data.setdefault("tipo_pagina", page_type)
        data["prompt_version"] = prompt_version

    def _ask_vision(
        self,
        png_bytes: bytes,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        image_b64 = base64.b64encode(png_bytes).decode("utf-8")
        if self.settings.openai_prefer_responses_api:
            content = self._ask_vision_with_responses(
                image_b64,
                prompt,
                model,
                max_output_tokens=max_output_tokens,
                json_mode=json_mode,
                use_reasoning=json_mode,
            )
            if not content:
                raise IntegrationError("OpenAI retornou resposta vazia.")
            return content

        try:
            kwargs: Dict[str, Any] = {
                "model": model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": "Voce responde em JSON valido, sem markdown."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"},
                            },
                        ],
                    },
                ],
            }
            if max_output_tokens is not None:
                kwargs["max_tokens"] = max_output_tokens
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
        except (BadRequestError, NotFoundError, APIError) as exc:
            message = str(exc)
            if "not a chat model" not in message:
                raise
            content = self._ask_vision_with_responses(
                image_b64,
                prompt,
                model,
                max_output_tokens=max_output_tokens,
                json_mode=json_mode,
                use_reasoning=json_mode,
            )

        if not content:
            raise IntegrationError("OpenAI retornou resposta vazia.")
        return content

    def _reasoning_kwargs(self, *, use_reasoning: bool) -> Dict[str, Any]:
        if not use_reasoning:
            return {}
        effort = (self.settings.openai_reasoning_effort or "").strip().lower()
        if not effort or effort == "none":
            return {"reasoning": {"effort": "none"}}
        return {"reasoning": {"effort": effort}}

    def _ask_vision_with_responses(
        self,
        image_b64: str,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
        use_reasoning: bool = False,
    ) -> str:
        responses = getattr(self.client, "responses", None)
        create = getattr(responses, "create", None) if responses is not None else None
        if callable(create):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "input": [
                        {
                            "role": "system",
                            "content": [{"type": "input_text", "text": "Voce responde em JSON valido, sem markdown."}],
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": prompt},
                                {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
                            ],
                        },
                    ],
                }
                if max_output_tokens is not None:
                    kwargs["max_output_tokens"] = max_output_tokens
                if json_mode:
                    kwargs["text"] = {"format": {"type": "json_object"}}
                kwargs.update(self._reasoning_kwargs(use_reasoning=use_reasoning))
                response = create(**kwargs)
                status = str(getattr(response, "status", "") or "").lower()
                if status == "incomplete":
                    details = getattr(response, "incomplete_details", None)
                    reason = getattr(details, "reason", None) if details is not None else None
                    if isinstance(details, dict):
                        reason = details.get("reason", reason)
                    logger.warning(
                        "OpenAI responses incomplete model=%s reason=%s",
                        model,
                        reason,
                    )
                output_text = getattr(response, "output_text", None)
                if output_text:
                    return str(output_text).strip()

                output = getattr(response, "output", [])
                texts: List[str] = []
                for item in output:
                    content = getattr(item, "content", [])
                    for part in content:
                        if getattr(part, "type", "") in ("output_text", "text"):
                            text_value = getattr(part, "text", "")
                            if text_value:
                                texts.append(text_value)
                merged = "\n".join(texts).strip()
                if merged:
                    return merged
                if status == "incomplete":
                    raise IntegrationError(
                        f"OpenAI retornou resposta incompleta (reason={reason or 'unknown'})."
                    )
            except AttributeError:
                pass

        return self._ask_vision_with_responses_http(
            image_b64,
            prompt,
            model,
            max_output_tokens=max_output_tokens,
            json_mode=json_mode,
            use_reasoning=use_reasoning,
        )

    def _ask_vision_with_responses_http(
        self,
        image_b64: str,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
        use_reasoning: bool = False,
    ) -> str:
        """Chama POST /v1/responses quando o SDK OpenAI instalado nao expoe client.responses."""
        url = "https://api.openai.com/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": "Voce responde em JSON valido, sem markdown."}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
                    ],
                },
            ],
        }
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        payload.update(self._reasoning_kwargs(use_reasoning=use_reasoning))
        timeout = httpx.Timeout(600.0, connect=30.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            raw = (response.text or "").strip()
            if not raw:
                raise IntegrationError("OpenAI responses API (HTTP) retornou corpo vazio.")
            try:
                data = response.json()
            except ValueError as exc:
                raise IntegrationError(
                    f"OpenAI responses API (HTTP) retornou JSON invalido: {raw[:300]}"
                ) from exc
        status = str(data.get("status") or "").lower()
        text = self._parse_responses_api_json(data)
        if text:
            return text
        if status == "incomplete":
            details = data.get("incomplete_details") or {}
            reason = details.get("reason") if isinstance(details, dict) else None
            raise IntegrationError(
                f"OpenAI responses API incompleta (reason={reason or 'unknown'})."
            )
        raise IntegrationError("OpenAI responses API (HTTP) retornou saida vazia ou nao reconhecida.")

    @staticmethod
    def _parse_responses_api_json(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        for key in ("output_text", "text"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        out = data.get("output")
        if not isinstance(out, list):
            return ""
        parts: List[str] = []
        for block in out:
            if not isinstance(block, dict):
                continue
            content = block.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in ("output_text", "text"):
                    txt = part.get("text")
                    if isinstance(txt, str) and txt.strip():
                        parts.append(txt.strip())
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_json(
        content: str,
        *,
        page_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            return parse_llm_json(content)
        except json.JSONDecodeError as exc:
            page_hint = f" (pagina {page_number})" if page_number is not None else ""
            preview = content.strip().replace("\n", " ")[:240]
            logger.warning(
                "Falha ao parsear JSON da OpenAI%s: %s | preview=%r",
                page_hint,
                exc,
                preview,
            )
            raise IntegrationError(
                f"A IA retornou JSON invalido na linearizacao{page_hint}. "
                "Reprocesse o job; se persistir, revise o prompt da pagina."
            ) from exc
