"""
HTTP client for companion-api's read-only warehouse endpoints.

companion-api (Node/Express) owns all Postgres access; this MCP server never
talks to the database directly. It calls companion-api over localhost HTTP
instead.

Configuration (env vars):
    COMPANION_API_URL: Base URL for companion-api. Default: http://127.0.0.1:7100
    COMPANION_API_TOKEN: Bearer token for companion-api's auth middleware.
        Must match the token companion-api issued to its own .companion-token
        file (run `npm run issue-token` in apps/companion-api, or read the
        file directly: apps/companion-api/.companion-token).

This client fails soft: companion-api often is not running (it's an optional
local sidecar), so every function returns None on connection errors, timeouts,
or non-200 responses rather than raising. Callers should treat None as "no
cached capture available" and fall through to live scraping.
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:7100"
DEFAULT_TIMEOUT_SECONDS = 5.0


def _base_url() -> str:
    return os.environ.get("COMPANION_API_URL", DEFAULT_BASE_URL).rstrip("/")


def _token() -> str | None:
    return os.environ.get("COMPANION_API_TOKEN")


async def _get(
    path: str, *, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """GET a companion-api path. Returns parsed JSON on 200, else None."""
    token = _token()
    if not token:
        logger.debug(
            "warehouse_client: COMPANION_API_TOKEN not set; skipping companion-api call to %s",
            path,
        )
        return None

    url = f"{_base_url()}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.ConnectError:
        logger.debug(
            "warehouse_client: connection refused calling %s (companion-api down?)", url
        )
        return None
    except httpx.TimeoutException:
        logger.debug("warehouse_client: timeout calling %s", url)
        return None
    except httpx.HTTPError as e:
        logger.debug("warehouse_client: HTTP error calling %s: %s", url, e)
        return None

    if response.status_code != 200:
        logger.debug(
            "warehouse_client: non-200 (%s) from %s", response.status_code, url
        )
        return None

    try:
        return response.json()
    except ValueError:
        logger.debug("warehouse_client: non-JSON response from %s", url)
        return None


async def fetch_captured_company(slug: str) -> dict[str, Any] | None:
    """Fetch the most recent companion_capture event for a company slug.

    Returns the companion-api response dict (with a "found" key), or None if
    companion-api is unreachable. Callers should also check response["found"].
    """
    return await _get(f"/v1/companion/company/{slug}")


async def fetch_captured_people(
    company: str | None = None, domain: str | None = None
) -> dict[str, Any] | None:
    """Fetch companion-captured people (stakeholders) for a company/domain.

    Returns the companion-api response dict, or None if companion-api is
    unreachable.
    """
    params: dict[str, Any] = {}
    if company:
        params["company"] = company
    if domain:
        params["domain"] = domain
    return await _get("/v1/companion/people", params=params)


async def fetch_recent_captures(limit: int = 20) -> dict[str, Any] | None:
    """Fetch the most recent companion_capture events.

    Returns the companion-api response dict, or None if companion-api is
    unreachable.
    """
    return await _get("/v1/companion/recent", params={"limit": limit})
