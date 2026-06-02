import base64
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
from openai import APIError, BadRequestError, NotFoundError, OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import get_settings
from src.core.errors import IntegrationError


class OpenAIService:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise IntegrationError("OPENAI_API_KEY nao configurado.")
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.linearization_prompt = self._load_linearization_prompt()

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3), reraise=True)
    def linearize_page(self, page_png: bytes, prompt_version: str) -> Dict[str, Any]:
        content = self._ask_vision(page_png, self.linearization_prompt, self.settings.openai_model_linearization)
        data = self._extract_json(content)
        data["prompt_version"] = prompt_version
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
            f"Retorne JSON no formato {{\"figures\": [{{\"figure_key\": \"...\", \"context\": \"...\"}}]}}. "
            f"Considere apenas estas figuras: {figure_keys}"
        )
        content = self._ask_vision(page_png, prompt, self.settings.openai_model_context)
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
    ) -> Dict[str, Any]:
        prompt = (
            "Retorne JSON com page_structure e figure_contexts. "
            "page_structure deve conter a linearizacao da pagina. "
            "figure_contexts deve ser uma lista de objetos com figure_key e context. "
            f"Use apenas estas figuras: {figure_keys}"
        )
        if not self.settings.openai_combined_mode:
            return {
                "page_structure": self.linearize_page(page_png, prompt_version),
                "figure_contexts": self.extract_context(page_png, figure_keys, prompt_version),
            }

        content = self._ask_vision(page_png, prompt, self.settings.openai_model_linearization)
        data = self._extract_json(content)
        page_structure = data.get("page_structure")
        contexts_raw = data.get("figure_contexts", [])
        if not isinstance(page_structure, dict) or not isinstance(contexts_raw, list):
            # Fallback automatico para chamadas separadas se a saida vier ruim/invalida.
            return {
                "page_structure": self.linearize_page(page_png, prompt_version),
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
        page_structure["prompt_version"] = prompt_version
        return {"page_structure": page_structure, "figure_contexts": contexts}

    def _ask_vision(self, png_bytes: bytes, prompt: str, model: str) -> str:
        image_b64 = base64.b64encode(png_bytes).decode("utf-8")
        if self.settings.openai_prefer_responses_api:
            content = self._ask_vision_with_responses(image_b64, prompt, model)
            if not content:
                raise IntegrationError("OpenAI retornou resposta vazia.")
            return content

        try:
            response = self.client.chat.completions.create(
                model=model,
                temperature=0.1,
                messages=[
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
            )
            content = response.choices[0].message.content
        except (BadRequestError, NotFoundError, APIError) as exc:
            message = str(exc)
            if "not a chat model" not in message:
                raise
            content = self._ask_vision_with_responses(image_b64, prompt, model)

        if not content:
            raise IntegrationError("OpenAI retornou resposta vazia.")
        return content

    def _ask_vision_with_responses(self, image_b64: str, prompt: str, model: str) -> str:
        responses = getattr(self.client, "responses", None)
        create = getattr(responses, "create", None) if responses is not None else None
        if callable(create):
            try:
                response = create(
                    model=model,
                    input=[
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
            except AttributeError:
                pass

        return self._ask_vision_with_responses_http(image_b64, prompt, model)

    def _ask_vision_with_responses_http(self, image_b64: str, prompt: str, model: str) -> str:
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

    def _load_linearization_prompt(self) -> str:
        fallback = (
            "Estruture semanticamente esta pagina para leitura acessivel. "
            "Retorne somente JSON com blocos ordenados e referencias de figuras."
        )
        raw_path = (self.settings.linearization_prompt_file or "").strip()
        if not raw_path:
            return fallback
        prompt_path = Path(raw_path)
        if not prompt_path.exists():
            return fallback
        content = prompt_path.read_text(encoding="utf-8").strip()
        return content or fallback

    @staticmethod
    def _extract_json(content: str) -> Dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                return json.loads(cleaned[start : end + 1])
            raise IntegrationError("Nao foi possivel extrair JSON valido da resposta OpenAI.")
