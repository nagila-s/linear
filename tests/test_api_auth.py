"""A API HTTP só responde com X-Linear-Api-Key válida (exceto /health)."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api import auth
from src.core.config import Settings


def _client(monkeypatch, *, key: str, env: str) -> TestClient:
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(linear_api_key=key, app_env=env))
    app = FastAPI(dependencies=[Depends(auth.require_api_key)])
    app.get("/health")(lambda: {"ok": True})
    app.get("/api/v1/books")(lambda: {"items": []})
    return TestClient(app)


def test_health_publico(monkeypatch):
    assert _client(monkeypatch, key="segredo", env="production").get("/health").status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-Linear-Api-Key": "errada"}])
def test_sem_chave_valida_recusa(monkeypatch, headers):
    client = _client(monkeypatch, key="segredo", env="production")
    assert client.get("/api/v1/books", headers=headers).status_code == 401


def test_chave_valida_passa(monkeypatch):
    client = _client(monkeypatch, key="segredo", env="production")
    assert client.get("/api/v1/books", headers={"X-Linear-Api-Key": "segredo"}).status_code == 200


def test_producao_sem_chave_configurada_fecha(monkeypatch):
    client = _client(monkeypatch, key="", env="production")
    assert client.get("/api/v1/books").status_code == 503


def test_dev_sem_chave_configurada_abre(monkeypatch):
    assert _client(monkeypatch, key="", env="dev").get("/api/v1/books").status_code == 200
