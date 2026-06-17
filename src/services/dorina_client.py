from typing import Any, Dict

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import get_settings
from src.core.errors import IntegrationError


class DorinaService:
    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.dorina_api_url:
            raise IntegrationError("DORINA_API_URL nao configurado.")
        if not self.settings.dorina_api_key:
            raise IntegrationError("DORINA_API_KEY nao configurado.")

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3), reraise=True)
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
            }
        }
        if context.strip():
            payload["data"]["context"] = context.strip()
        try:
            response = requests.post(
                self.settings.dorina_api_url,
                json=payload,
                headers=headers,
                timeout=self.settings.dorina_timeout_seconds,
            )
        except requests.Timeout as exc:
            raise IntegrationError("Dorina timeout_transient_error") from exc
        except requests.RequestException as exc:
            raise IntegrationError("Dorina network_transient_error") from exc
        if response.status_code >= 400:
            if response.status_code >= 500:
                raise IntegrationError(f"Dorina upstream_5xx_error ({response.status_code}): {response.text[:500]}")
            raise IntegrationError(f"Dorina upstream_4xx_error ({response.status_code}): {response.text[:500]}")
        data = response.json()
        if not isinstance(data, dict):
            raise IntegrationError(f"Dorina resposta invalida: {str(data)[:300]}")
        if data.get("error"):
            raise IntegrationError(f"Dorina error: {str(data.get('error'))[:500]}")
        description = str(
            data.get("description") or data.get("texto") or data.get("caption") or ""
        ).strip()
        data["description"] = description
        return data
