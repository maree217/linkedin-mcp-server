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
        title="Get Post Comments",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"feed", "scraping"},
        exclude_args=["extractor"],
    )
    async def get_post_comments(
        post_url: Annotated[str, Field(min_length=1)],
        ctx: Context,
        max_comments: Annotated[int, Field(ge=1, le=300)] = 100,
        max_scrolls: Annotated[int, Field(ge=1, le=40)] = 15,
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        """
        Get the list of commenters on a specific LinkedIn post.

        Navigates to the post permalink, expands the comment thread (clicking
        "Load more comments" and scrolling), and returns each commenter's
        name, headline, profile URL, and comment text. READ-only.

        This is the reverse of get_person_profile(sections="comments"), which
        returns one person's own comment history; this returns everyone who
        commented on one post.

        Args:
            post_url: Permalink of the post — a
                /feed/update/urn:li:activity:... or /posts/<slug> URL.
            max_comments: Stop once this many distinct comments are collected
                (1-300, default 100).
            max_scrolls: Max "Load more comments" + scroll iterations
                (1-40, default 15). Raise for posts with hundreds of comments.

        Returns:
            Dict with url, comment_count, and comments (list of
            {name, headline, profile_url, text}). On rate limit returns a
            dict with error="rate_limit".
        """
        try:
            extractor = extractor or await get_ready_extractor(
                ctx, tool_name="get_post_comments"
            )
            logger.info(
                "Scraping post comments (max_comments=%d, max_scrolls=%d)",
                max_comments,
                max_scrolls,
            )

            await ctx.report_progress(
                progress=0, total=100, message="Loading post comments"
            )

            result = await extractor.get_post_comments(
                post_url,
                max_comments=max_comments,
                max_scrolls=max_scrolls,
            )

            await ctx.report_progress(progress=100, total=100, message="Complete")

            return result

        except AuthenticationError as e:
            try:
                await handle_auth_error(e, ctx)
            except Exception as relogin_exc:
                raise_tool_error(relogin_exc, "get_post_comments")
        except Exception as e:
            raise_tool_error(e, "get_post_comments")

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
        visibility: Annotated[str, Field(pattern="^(anyone|connections)$")] = "anyone",
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

    @mcp.tool(
        timeout=tool_timeout,
        title="Comment On Post",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"feed", "actions"},
        exclude_args=["extractor"],
    )
    async def comment_on_post(
        post_url: Annotated[str, Field(min_length=1)],
        text: Annotated[str, Field(min_length=1, max_length=1250)],
        confirm_comment: bool,
        ctx: Context,
        reply_to_profile: Annotated[str | None, Field()] = None,
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        """
        Publish a comment (or threaded reply) on a specific LinkedIn post.

        This is a WRITE operation gated on confirm_comment: with
        confirm_comment=False (the safe default to preview) the comment box is
        opened and the text entered, but nothing is published — a dry run
        returning status="confirmation_required". Set confirm_comment=True to
        actually publish the comment.

        On a real publish the write is verified end-to-end: commented=True is
        returned only once the comment is observed in the thread, never merely
        because the submit button was clicked. If the submit fires but the
        comment cannot be confirmed, status="comment_unconfirmed" is returned
        (commented=False) — check before retrying to avoid a duplicate.

        Args:
            post_url: Permalink of the post to comment on — e.g. the
                /feed/update/urn:li:activity:... or /posts/<slug> URLs that
                get_feed returns under references["feed"].
            text: The comment body (1-1250 characters; 1250 is LinkedIn's
                comment limit).
            confirm_comment: Must be True to publish. False does a dry run.
            ctx: FastMCP context for progress reporting.
            reply_to_profile: Optional — a commenter's /in/ URL or bare
                username. When set, the text is posted as a threaded reply
                under that person's comment rather than as a top-level comment.
                The target comment must already be loaded on the post; call
                get_post_comments first to surface it.

        Returns:
            Dict with url, status, message, and commented (bool). Statuses:
            "commented", "confirmation_required", "comment_unconfirmed",
            "comment_box_unavailable", "comment_button_unavailable",
            "reply_target_unresolved", "reply_target_unavailable".
        """
        try:
            extractor = extractor or await get_ready_extractor(
                ctx, tool_name="comment_on_post"
            )
            logger.info(
                "Commenting on post (confirm_comment=%s, length=%d, reply=%s)",
                confirm_comment,
                len(text),
                bool(reply_to_profile),
            )

            await ctx.report_progress(
                progress=0, total=100, message="Opening comment box"
            )

            result = await extractor.comment_on_post(
                post_url,
                text,
                confirm_comment=confirm_comment,
                reply_to_profile=reply_to_profile,
            )

            await ctx.report_progress(progress=100, total=100, message="Complete")

            return result

        except AuthenticationError as e:
            try:
                await handle_auth_error(e, ctx)
            except Exception as relogin_exc:
                raise_tool_error(relogin_exc, "comment_on_post")
        except Exception as e:
            raise_tool_error(e, "comment_on_post")  # NoReturn

    @mcp.tool(
        timeout=tool_timeout,
        title="React To Post",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"feed", "actions"},
        exclude_args=["extractor"],
    )
    async def react_to_post(
        post_url: Annotated[str, Field(min_length=1)],
        confirm_react: bool,
        ctx: Context,
        reaction: Annotated[
            str,
            Field(pattern="^(like|celebrate|support|love|insightful|funny)$"),
        ] = "like",
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        """
        React (like / celebrate / support / love / insightful / funny) to a post.

        This is a WRITE operation gated on confirm_react: with
        confirm_react=False (the safe default to preview) the react control is
        located and its readiness reported, but no reaction is applied — a dry
        run returning status="confirmation_required". Set confirm_react=True to
        actually react.

        Idempotent-safe: if the post already carries the requested reaction it
        is a no-op returning status="already_reacted". On a real react the write
        is verified — reacted=True is returned only once the toggle reads as
        pressed, never merely because it was clicked.

        Args:
            post_url: Permalink of the post to react to — e.g. the
                /feed/update/urn:li:activity:... or /posts/<slug> URLs that
                get_feed returns under references["feed"].
            confirm_react: Must be True to apply the reaction. False does a dry
                run.
            ctx: FastMCP context for progress reporting.
            reaction: One of like (default), celebrate, support, love,
                insightful, funny.

        Returns:
            Dict with url, status, message, and reacted (bool). Statuses:
            "reacted", "already_reacted", "confirmation_required",
            "invalid_reaction", "react_control_unavailable",
            "reaction_unavailable", "reaction_unconfirmed".
        """
        try:
            extractor = extractor or await get_ready_extractor(
                ctx, tool_name="react_to_post"
            )
            logger.info(
                "Reacting to post (confirm_react=%s, reaction=%s)",
                confirm_react,
                reaction,
            )

            await ctx.report_progress(
                progress=0, total=100, message="Locating react control"
            )

            result = await extractor.react_to_post(
                post_url,
                reaction=reaction,
                confirm_react=confirm_react,
            )

            await ctx.report_progress(progress=100, total=100, message="Complete")

            return result

        except AuthenticationError as e:
            try:
                await handle_auth_error(e, ctx)
            except Exception as relogin_exc:
                raise_tool_error(relogin_exc, "react_to_post")
        except Exception as e:
            raise_tool_error(e, "react_to_post")  # NoReturn
