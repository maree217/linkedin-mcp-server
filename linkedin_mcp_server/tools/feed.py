"""
LinkedIn feed scraping tool.

Fetches posts from the authenticated user's LinkedIn home feed using
innerText extraction. Scrolls until the requested number of post
permalinks have been observed in SDUI pagination responses — a
locale-independent progress signal, since the feed DOM exposes no
stable per-post container selector.
"""

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error
from linkedin_mcp_server.scraping.extractor import _RATE_LIMITED_MSG
from linkedin_mcp_server.scraping.link_metadata import Reference

logger = logging.getLogger(__name__)


def register_feed_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register feed-related tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Feed",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"feed", "scraping"},
        exclude_args=["extractor"],
    )
    async def get_feed(
        ctx: Context,
        num_posts: Annotated[int, Field(ge=1, le=50)] = 10,
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        """
        Get posts from the authenticated user's LinkedIn feed.

        Args:
            ctx: FastMCP context for progress reporting
            num_posts: Number of posts to fetch (1-50, default 10).
                       Posts are loaded in batches of ~5 as the page scrolls,
                       so the actual count may slightly exceed the target.

        Returns:
            Dict with url, sections (name -> raw text), and optional keys:
            - references["feed"]: list of {kind: "feed_post", url, ...}
              entries. URLs are relative paths and may carry either
              ``/feed/update/<urn>/`` (DOM-anchor-derived) or
              ``/posts/<slug>`` (SDUI-derived) shape — both are valid
              LinkedIn permalinks.
            - section_errors: present when the feed is rate-limited or
              extraction fails.

            Truncated posts are not auto-expanded; full text for any post
            is reachable via its permalink in references["feed"]. The LLM
            should parse sections["feed"] for post bodies.
        """
        try:
            extractor = extractor or await get_ready_extractor(
                ctx, tool_name="get_feed"
            )
            logger.info("Scraping feed (num_posts=%d)", num_posts)

            await ctx.report_progress(
                progress=0, total=100, message="Starting feed scrape"
            )

            extracted = await extractor.extract_feed(num_posts=num_posts)

            url = "https://www.linkedin.com/feed/"
            sections: dict[str, str] = {}
            references: dict[str, list[Reference]] = {}
            section_errors: dict[str, dict[str, Any]] = {}
            if extracted.text and extracted.text != _RATE_LIMITED_MSG:
                sections["feed"] = extracted.text
                if extracted.references:
                    references["feed"] = extracted.references
            elif extracted.text == _RATE_LIMITED_MSG:
                section_errors["feed"] = {
                    "error_type": "rate_limit",
                    "error_message": extracted.text,
                }
            elif extracted.error:
                section_errors["feed"] = extracted.error

            await ctx.report_progress(progress=100, total=100, message="Complete")

            result: dict[str, Any] = {"url": url, "sections": sections}
            if references:
                result["references"] = references
            if section_errors:
                result["section_errors"] = section_errors
            return result

        except AuthenticationError as e:
            try:
                await handle_auth_error(e, ctx)
            except Exception as relogin_exc:
                raise_tool_error(relogin_exc, "get_feed")
        except Exception as e:
            raise_tool_error(e, "get_feed")

    @mcp.tool(
        timeout=tool_timeout,
        title="Create Post",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"feed", "actions"},
        exclude_args=["extractor"],
    )
    async def create_post(
        text: Annotated[str, Field(min_length=1, max_length=3000)],
        confirm_post: bool,
        ctx: Context,
        visibility: Annotated[
            str, Field(pattern="^(anyone|connections)$")
        ] = "anyone",
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        """
        Publish a short text post to the authenticated user's LinkedIn feed.

        This is a WRITE operation. It is gated on confirm_post: with
        confirm_post=False (the safe default to preview) the share composer is
        opened and the text entered, but the post is NOT published — a dry run
        that returns status="confirmation_required". Set confirm_post=True to
        actually publish.

        Note: this creates a standard feed POST, not a long-form ARTICLE.
        LinkedIn's article composer (/pulse) is not automatable here — draft
        articles externally and paste them into LinkedIn yourself.

        Args:
            text: The post body (1-3000 characters; 3000 is LinkedIn's limit).
            confirm_post: Must be True to publish. False does a dry run.
            ctx: FastMCP context for progress reporting.
            visibility: Audience for the post — "anyone" (public, default) or
                "connections". Applied best-effort; LinkedIn's current default
                audience is used if the selector is unavailable.

        Returns:
            Dict with url, status, message, and posted (bool). Statuses:
            "posted", "confirmation_required", "composer_unavailable",
            "post_button_unavailable".
        """
        try:
            extractor = extractor or await get_ready_extractor(
                ctx, tool_name="create_post"
            )
            logger.info(
                "Creating feed post (confirm_post=%s, visibility=%s, length=%d)",
                confirm_post,
                visibility,
                len(text),
            )

            await ctx.report_progress(
                progress=0, total=100, message="Opening share composer"
            )

            result = await extractor.create_post(
                text,
                confirm_post=confirm_post,
                visibility=visibility,
            )

            await ctx.report_progress(progress=100, total=100, message="Complete")

            return result

        except AuthenticationError as e:
            try:
                await handle_auth_error(e, ctx)
            except Exception as relogin_exc:
                raise_tool_error(relogin_exc, "create_post")
        except Exception as e:
            raise_tool_error(e, "create_post")  # NoReturn
