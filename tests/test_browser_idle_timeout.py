"""Tests for the idle-close watchdog in linkedin_mcp_server.drivers.browser.

Uses a fake browser and a tiny LINKEDIN_BROWSER_IDLE_SECONDS timeout so the
timer logic is exercised in milliseconds with no real LinkedIn/network
traffic involved.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from linkedin_mcp_server.drivers import browser as browser_module

IDLE_SECONDS = 0.05
SETTLE = IDLE_SECONDS * 3


@pytest.fixture(autouse=True)
def _tiny_idle_timeout(monkeypatch):
    monkeypatch.setenv(browser_module.IDLE_SECONDS_ENV_VAR, str(IDLE_SECONDS))


def _fake_browser() -> MagicMock:
    browser = MagicMock()
    browser.close = AsyncMock()
    return browser


async def test_idle_timeout_closes_browser_after_last_call():
    browser_module._browser = _fake_browser()

    async with browser_module.track_tool_call():
        pass

    assert browser_module._browser is not None  # not closed immediately
    await asyncio.sleep(SETTLE)
    assert browser_module._browser is None


async def test_idle_timer_never_fires_mid_call():
    fake = _fake_browser()
    browser_module._browser = fake

    async with browser_module.track_tool_call():
        # Longer than the idle timeout, but the call is still in-flight.
        await asyncio.sleep(SETTLE)
        assert browser_module._browser is fake
        fake.close.assert_not_awaited()

    # Countdown restarts only once the call has finished.
    assert browser_module._browser is fake


async def test_new_call_resets_the_idle_countdown():
    browser_module._browser = _fake_browser()

    async with browser_module.track_tool_call():
        pass
    await asyncio.sleep(IDLE_SECONDS / 2)
    assert browser_module._browser is not None

    # A second tool call arrives before the timeout elapses; this must cancel
    # the pending close and restart the countdown from this call's end.
    async with browser_module.track_tool_call():
        pass
    await asyncio.sleep(IDLE_SECONDS / 2)
    assert browser_module._browser is not None

    await asyncio.sleep(SETTLE)
    assert browser_module._browser is None


async def test_manual_close_browser_cancels_pending_idle_timer():
    browser_module._browser = _fake_browser()

    async with browser_module.track_tool_call():
        pass
    assert browser_module._idle_task is not None

    await browser_module.close_browser()

    assert browser_module._idle_task is None
    assert browser_module._browser is None


async def test_relaunch_after_idle_close_is_lazy(monkeypatch):
    """The next tool call after an idle-close must relaunch exactly like
    after close_session -- i.e. get_or_create_browser() sees ``_browser is
    None`` and builds a fresh one."""
    browser_module._browser = _fake_browser()

    async with browser_module.track_tool_call():
        pass
    await asyncio.sleep(SETTLE)
    assert browser_module._browser is None

    relaunched = _fake_browser()

    async def fake_get_or_create_browser(headless: bool | None = None):
        browser_module._browser = relaunched
        return relaunched

    monkeypatch.setattr(
        browser_module, "get_or_create_browser", fake_get_or_create_browser
    )

    async with browser_module.track_tool_call():
        result = await browser_module.get_or_create_browser()

    assert result is relaunched
    assert browser_module._browser is relaunched
