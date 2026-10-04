"""
Read-only tools exposing companion-api's captured (warehoused) LinkedIn data.

These tools never touch Postgres directly -- they call companion-api over
HTTP (see warehouse_client.py). companion-api is an optional local sidecar;
when it is unreachable or has no matching capture, each tool returns
{"available": False, "reason": ...} rather than raising, so callers can
fall back to live scraping tools (get_company_profile, get_person_profile).
"""

import logging
from typing import Any

from fastmcp import FastMCP

from linkedin_mcp_server import warehouse_client
from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_UNAVAILABLE_REASON = "companion-api unreachable or no capture found"


def register_warehouse_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register companion-api warehouse read tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Captured Company",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"company", "warehouse"},
    )
    async def get_captured_company(slug: str) -> dict[str, Any]:
        """
        Get the most recently captured LinkedIn company page from companion-api's
        warehouse, without live browser navigation.

        companion-api is an optional local sidecar that stores prior
        companion-captured company pages (via the browser extension "capture"
        flow) in Postgres. This tool reads that cache; it does not scrape
        LinkedIn.

        Args:
            slug: LinkedIn company URL slug (the path segment after /company/).

        Returns:
            On a hit: {found: True, slug, target_name, domain, occurred_at, payload}.
            On a miss or when companion-api is unreachable:
            {available: False, reason: str}.
        """
        result = await warehouse_client.fetch_captured_company(slug)
        if result is None:
            return {"available": False, "reason": _UNAVAILABLE_REASON}
        return result

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Captured People",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"person", "warehouse"},
    )
    async def get_captured_people(
        company: str, domain: str | None = None
    ) -> dict[str, Any]:
        """
        Get companion-captured people (stakeholders) for a company from
        companion-api's warehouse, without live browser navigation.

        Args:
            company: Organisation name to match (target_name in the warehouse).
            domain: Optional company domain to match instead of/alongside name.

        Returns:
            On success: {company, domain, count, people: [...]}.
            When companion-api is unreachable: {available: False, reason: str}.
        """
        result = await warehouse_client.fetch_captured_people(
            company=company, domain=domain
        )
        if result is None:
            return {"available": False, "reason": _UNAVAILABLE_REASON}
        return result

    @mcp.tool(
        timeout=tool_timeout,
        title="List Recent Captures",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"company", "warehouse"},
    )
    async def list_recent_captures(limit: int = 20) -> dict[str, Any]:
        """
        List the most recent companion captures recorded in companion-api's
        warehouse.

        Args:
            limit: Maximum number of captures to return (default 20).

        Returns:
            On success: {count, captures: [...]}.
            When companion-api is unreachable: {available: False, reason: str}.
        """
        result = await warehouse_client.fetch_recent_captures(limit=limit)
        if result is None:
            return {"available": False, "reason": _UNAVAILABLE_REASON}
        return result
