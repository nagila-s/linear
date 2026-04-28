from typing import Any, Dict

import requests

from src.core.config import get_settings
from src.core.errors import IntegrationError


class PBExporter:
    def __init__(self) -> None:
        self.settings = get_settings()

    def export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.settings.pb_api_url:
            return {"status": "skipped", "reason": "PB_API_URL nao configurado"}
        headers = {
            "Authorization": f"Bearer {self.settings.pb_api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(self.settings.pb_api_url, json=payload, headers=headers, timeout=90)
        if response.status_code >= 400:
            raise IntegrationError(f"Exportacao PB falhou ({response.status_code}).")
        return {"status": "sent", "response": response.json()}


class AvaliaExporter:
    def __init__(self) -> None:
        self.settings = get_settings()

    def export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.settings.avalia_api_url:
            return {"status": "skipped", "reason": "AVALIA_API_URL nao configurado"}
        headers = {
            "Authorization": f"Bearer {self.settings.avalia_api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(self.settings.avalia_api_url, json=payload, headers=headers, timeout=90)
        if response.status_code >= 400:
            raise IntegrationError(f"Exportacao Avalia falhou ({response.status_code}).")
        return {"status": "sent", "response": response.json()}
