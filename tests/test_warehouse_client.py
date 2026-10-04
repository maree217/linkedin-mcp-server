"""Soft-fail behaviour of the companion-api warehouse client."""

import httpx
import pytest

from linkedin_mcp_server import warehouse_client


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("COMPANION_API_TOKEN", "test-token")


async def test_returns_none_without_token(monkeypatch):
    monkeypatch.delenv("COMPANION_API_TOKEN", raising=False)
    assert await warehouse_client.fetch_captured_company("acme") is None


async def test_returns_none_when_sidecar_unreachable(token, monkeypatch):
    monkeypatch.setenv("COMPANION_API_URL", "http://127.0.0.1:1")
    assert await warehouse_client.fetch_captured_company("acme") is None
    assert await warehouse_client.fetch_captured_people(company="Acme") is None
    assert await warehouse_client.fetch_recent_captures() is None


async def test_returns_none_on_non_200(token, monkeypatch):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(500))
        return real(*a, **kw)

    monkeypatch.setattr(warehouse_client.httpx, "AsyncClient", factory)
    assert await warehouse_client.fetch_captured_company("acme") is None


async def test_returns_json_on_200_with_bearer(token, monkeypatch):
    real = httpx.AsyncClient
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"found": True})

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(warehouse_client.httpx, "AsyncClient", factory)
    assert await warehouse_client.fetch_captured_company("acme") == {"found": True}
    assert seen["auth"] == "Bearer test-token"
