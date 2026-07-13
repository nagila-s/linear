import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import APIError, BadRequestError, NotFoundError, OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import get_settings
from src.core.errors import IntegrationError
from src.services.prompt_router import PromptRouter
from src.utils.json_codec import parse_llm_json

logger = logging.getLogger(__name__)

_COMBINED_FIGURE_SUFFIX = (
    "\n\nRetorne JSON com as chaves page_structure e figure_contexts. "
    "page_structure deve seguir a estrutura deste prompt. "
    "figure_contexts deve ser uma lista de objetos com figure_key e context. "
    "Considere apenas estas figuras: {figure_keys}"
)


class OpenAIService:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise IntegrationError("OPENAI_API_KEY nao configurado.")
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.prompt_router = PromptRouter(
            settings.prompts_directory,
            window_start=settings.classification_window_start,
            window_end=settings.classification_window_end,
        )

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3), reraise=True)
    def linearize_page(
        self,
        page_png: bytes,
        prompt_version: str,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
    ) -> Dict[str, Any]:
        prompt, page_type = self._resolve_linearization(page_png, page_number, total_pages)
        content = self._ask_vision(
            page_png,
            prompt,
            self.settings.openai_model_linearization,
            json_mode=True,
        )
        data = self._extract_json(content, page_number=page_number)
        self._apply_page_metadata(data, page_type, prompt_version)
        return data

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3), reraise=True)
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

    def linearize_and_extract_context(
        self,
        page_png: bytes,
        figure_keys: List[str],
        prompt_version: str,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not self.settings.openai_combined_mode:
            return {
                "page_structure": self.linearize_page(
                    page_png,
                    prompt_version,
                    page_number=page_number,
                    total_pages=total_pages,
                ),
                "figure_contexts": self.extract_context(page_png, figure_keys, prompt_version),
            }

        prompt, page_type = self._resolve_linearization(page_png, page_number, total_pages)
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
            not self.settings.prompt_routing_enabled
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
            )

        if not content:
            raise IntegrationError("OpenAI retornou resposta vazia.")
        return content

    def _ask_vision_with_responses(
        self,
        image_b64: str,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
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
                response = create(**kwargs)
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
            except AttributeError:
                pass

        return self._ask_vision_with_responses_http(
            image_b64,
            prompt,
            model,
            max_output_tokens=max_output_tokens,
            json_mode=json_mode,
        )

    def _ask_vision_with_responses_http(
        self,
        image_b64: str,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
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
        timeout = httpx.Timeout(600.0, connect=30.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        text = self._parse_responses_api_json(data)
        if not text:
            raise IntegrationError("OpenAI responses API (HTTP) retornou saida vazia ou nao reconhecida.")
        return text

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
