"""Tests for warehouse-backed cache helpers and tool annotations."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from linkedin_mcp_server import warehouse_client
from linkedin_mcp_server.tools import person as person_module
from linkedin_mcp_server.tools.person import _find_cached_person
from linkedin_mcp_server.tools.warehouse import register_warehouse_tools
from linkedin_mcp_server.warehouse_client import _capture_age_hours


def _recent(*names: str) -> dict:
    return {"captures": [{"target_name": n, "domain": f"{n}.com"} for n in names]}


def _people(*urls: str) -> dict:
    return {
        "people": [
            {
                "linkedin_url": u,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            }
            for u in urls
        ]
    }


@pytest.fixture
def patch_wh(monkeypatch):
    def _apply(recent, people):
        monkeypatch.setattr(
            warehouse_client, "fetch_recent_captures", AsyncMock(return_value=recent)
        )
        monkeypatch.setattr(
            warehouse_client, "fetch_captured_people", AsyncMock(return_value=people)
        )

    return _apply


async def test_exact_username_match_rejects_prefix(patch_wh):
    patch_wh(_recent("acme"), _people("https://www.linkedin.com/in/bobby-smith/"))
    assert await _find_cached_person("bob", 24) is None


async def test_exact_username_match_hits_case_insensitive(patch_wh):
    patch_wh(_recent("acme"), _people("https://www.linkedin.com/in/Bob/"))
    hit = await _find_cached_person("bob", 24)
    assert hit is not None
    assert hit["source"] == "companion_capture"


async def test_lookup_timeout_returns_none(patch_wh, monkeypatch):
    patch_wh(_recent("acme"), _people("https://www.linkedin.com/in/bob/"))

    async def slow(**_kw):
        await asyncio.sleep(5)

    monkeypatch.setattr(warehouse_client, "fetch_captured_people", slow)
    monkeypatch.setattr(person_module, "_CACHE_LOOKUP_TIMEOUT_SECONDS", 0.05)
    assert await _find_cached_person("bob", 24) is None


def test_capture_age_fresh_and_old():
    fresh = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
    fresh_age = _capture_age_hours(fresh)
    old_age = _capture_age_hours(old)
    assert fresh_age is not None and fresh_age < 0.1
    assert old_age is not None and 199 < old_age < 201
    assert _capture_age_hours(None) is None
    assert _capture_age_hours("garbage") is None


async def test_warehouse_tool_annotations():
    mcp = FastMCP("t")
    register_warehouse_tools(mcp)
    tools = await mcp.list_tools()
    assert len(tools) == 3
    for t in tools:
        assert t.annotations is not None
        assert t.annotations.readOnlyHint is True
        assert t.annotations.openWorldHint is False
