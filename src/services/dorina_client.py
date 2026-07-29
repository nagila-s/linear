from typing import Any, Dict

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import get_settings
from src.core.errors import IntegrationError

# Recortes grandes às vezes incluem texto da página ao redor/abaixo da figura.
_DORINA_IMAGE_SCOPE_INSTRUCTION = (
    "Descreva APENAS o que está visível na imagem enviada (a figura/ilustração em si). "
    "Ignore e NÃO transcreva texto de parágrafo, exercício, legenda de página, número de página "
    "ou qualquer conteúdo do livro que apareça ao redor ou abaixo da imagem por causa do recorte. "
    "Se houver texto que faça parte da própria figura (rótulos, balões, títulos dentro da arte), "
    "aí sim inclua na descrição."
)


class DorinaService:
    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.dorina_api_url:
            raise IntegrationError("DORINA_API_URL nao configurado.")
        if not self.settings.dorina_api_key:
            raise IntegrationError("DORINA_API_KEY nao configurado.")

    @staticmethod
    def _compose_context(context: str) -> str:
        base = (context or "").strip()
        if not base:
            return _DORINA_IMAGE_SCOPE_INSTRUCTION
        return f"{base}\n\n{_DORINA_IMAGE_SCOPE_INSTRUCTION}"

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def describe_figure(
        self,
        image_url: str,
        isbn: str,
        context: str,
        prompt_version: str,
        image_id: int = 0,
        document_id: int = 0,
    ) -> Dict[str, Any]:
        key_header = self.settings.dorina_api_key_header.strip() or "Authorization"
        headers = {
            key_header: self.settings.dorina_api_key,
            "accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "data": {
                "imageId": image_id,
                "documentId": document_id,
                "url": image_url,
                "braille": self.settings.dorina_braille,
                "documentType": self.settings.dorina_document_type,
                "context": self._compose_context(context),
            }
        }
        try:
            response = requests.post(
                self.settings.dorina_api_url,
                json=payload,
                headers=headers,
                timeout=self.settings.dorina_timeout_seconds,
            )
        except requests.Timeout as exc:
            raise IntegrationError("Dorina timeout_transient_error") from exc
        except (requests.ConnectionError, ConnectionResetError, OSError) as exc:
            raise IntegrationError(f"Dorina connection_transient_error: {exc}") from exc
        except requests.RequestException as exc:
            raise IntegrationError("Dorina network_transient_error") from exc
        if response.status_code >= 400:
            if response.status_code >= 500:
                raise IntegrationError(f"Dorina upstream_5xx_error ({response.status_code}): {response.text[:500]}")
            raise IntegrationError(f"Dorina upstream_4xx_error ({response.status_code}): {response.text[:500]}")
        raw = (response.text or "").strip()
        if not raw:
            raise IntegrationError("Dorina respondeu com corpo vazio.")
        try:
            data = response.json()
        except ValueError as exc:
            raise IntegrationError(
                f"Dorina respondeu JSON invalido: {raw[:300]}"
            ) from exc
        if not isinstance(data, dict):
            raise IntegrationError(f"Dorina resposta invalida: {str(data)[:300]}")
        if data.get("error"):
            raise IntegrationError(f"Dorina error: {str(data.get('error'))[:500]}")
        description = str(
            data.get("description") or data.get("texto") or data.get("caption") or ""
        ).strip()
        data["description"] = description
        return data
