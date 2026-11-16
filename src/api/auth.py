"""Autenticação da API HTTP por chave compartilhada com o BFF do Next.js.

Toda rota exige o header ``X-Linear-Api-Key`` igual a ``LINEAR_API_KEY``,
exceto ``/health`` (healthcheck do ALB/ECS). Sem chave configurada, a API só
fica aberta com ``APP_ENV=dev``; em qualquer outro ambiente ela recusa tudo.
"""

import hmac

from fastapi import HTTPException, Request

from src.core.config import get_settings

API_KEY_HEADER = "X-Linear-Api-Key"
PUBLIC_PATHS = frozenset({"/health"})


def auth_disabled_for_dev() -> bool:
    settings = get_settings()
    return not settings.linear_api_key and settings.app_env == "dev"


def require_api_key(request: Request) -> None:
    if request.url.path in PUBLIC_PATHS:
        return
    expected = get_settings().linear_api_key
    if not expected:
        if auth_disabled_for_dev():
            return
        raise HTTPException(status_code=503, detail="API sem LINEAR_API_KEY configurada.")
    provided = request.headers.get(API_KEY_HEADER, "")
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Chave da API ausente ou inválida.")
