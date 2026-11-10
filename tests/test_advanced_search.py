import asyncio
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from discord_py_self_mcp.tools import advanced_search
from discord_py_self_mcp import tool_utils
from discord_py_self_mcp.rate_limiter import RateLimiter


class SearchTarget:
    def __init__(self, rows=()):
        self.rows = rows
        self.kwargs = None

    def search(self, **kwargs):
        self.kwargs = kwargs

        async def results():
            for row in self.rows:
                yield row

        return results()


def fake_message(message_id):
    return SimpleNamespace(
        id=message_id, channel=SimpleNamespace(id=1), author=SimpleNamespace(id=99, name="reader"),
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        content=f"message {message_id}", clean_content="", embeds=[], attachments=[], reference=None,
    )


@pytest.fixture
def setup_search(monkeypatch):
    target = SearchTarget([fake_message(123)])
    client = SimpleNamespace(
        get_channel=lambda _: target,
        get_guild=lambda _: target,
        fetch_channel=AsyncMock(return_value=target),
        fetch_guild=AsyncMock(return_value=target),
    )
    limiter = AsyncMock()
    monkeypatch.setattr(advanced_search, "client", client)
    monkeypatch.setattr(tool_utils, "rate_limiter", SimpleNamespace(is_enabled=lambda: True, wait_if_needed=limiter))
    return target, client, limiter


@pytest.mark.asyncio
async def test_combines_author_dates_and_text_using_native_search(setup_search):
    target, _, limiter = setup_search
    result = await advanced_search.search_messages_advanced({
        "channel_id": "1", "query": "release", "author_id": "99",
        "after": "2026-10-01", "before": "2026-11-01T03:00:00+03:00",
        "offset": 25, "limit": 25, "oldest_first": True,
    })
    assert target.kwargs["authors"][0].id == 99
    assert target.kwargs["after"] == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert target.kwargs["before"] == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert target.kwargs["content"] == "release"
    assert target.kwargs["offset"] == 25
    assert target.kwargs["limit"] == 25
    assert target.kwargs["oldest_first"] is True
    limiter.assert_not_awaited()
    assert "123 u1 c1 2026-11-01" in result[0].text
    assert "u1=99 reader" in result[0].text


@pytest.mark.asyncio
async def test_server_search_can_omit_text_and_page_results(setup_search):
    target, _, _ = setup_search
    result = await advanced_search.search_messages_advanced({
        "guild_id": "1", "author_id": "99", "limit": 1,
    })
    assert "content" not in target.kwargs
    assert "offset=1" in result[0].text
    assert "c1=https://discord.com/channels/1/1" in result[0].text
    assert "123 u1 c1 " in result[0].text


@pytest.mark.asyncio
async def test_uncached_channel_and_message_id_bounds(setup_search):
    target, client, _ = setup_search
    client.get_channel = lambda _: None
    await advanced_search.search_messages_advanced({
        "channel_id": "1", "after": "100", "before": "200",
    })
    client.fetch_channel.assert_awaited_once_with(1)
    assert target.kwargs["after"].id == 100
    assert target.kwargs["before"].id == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("args,error", [
    ({}, "exactly one"),
    ({"channel_id": "1", "guild_id": "2"}, "exactly one"),
    ({"channel_id": "0"}, "positive 64-bit"),
    ({"channel_id": "1", "author_id": "@someone"}, "author_id"),
    ({"channel_id": "1", "after": "yesterday"}, "after must be"),
    ({"channel_id": "1", "after": "2026-02-30"}, "after must be"),
    ({"channel_id": "1", "after": "2026-11-01", "before": "2026-10-01"}, "earlier"),
    ({"channel_id": "1", "offset": -1}, "offset must be"),
    ({"channel_id": "1", "offset": True}, "offset must be"),
])
async def test_invalid_filters_fail_before_search(setup_search, args, error):
    target, _, limiter = setup_search
    with pytest.raises(RuntimeError, match=error):
        await advanced_search.search_messages_advanced(args)
    assert target.kwargs is None
    limiter.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_failure_is_reported_without_silent_history_scan(setup_search):
    target, _, _ = setup_search

    def fail(**kwargs):
        raise RuntimeError("Search unavailable")

    target.search = fail
    with pytest.raises(RuntimeError, match="Error in native Discord search: Search unavailable"):
        await advanced_search.search_messages_advanced({"channel_id": "1"})


@pytest.mark.asyncio
async def test_empty_search_is_explicit(setup_search):
    target, _, _ = setup_search
    target.rows = []
    result = await advanced_search.search_messages_advanced({"channel_id": "1"})
    assert "returned=0, total_results=unknown" in result[0].text
    assert "No messages returned on this page." in result[0].text


@pytest.mark.asyncio
async def test_last_page_stays_within_discord_search_window(setup_search):
    target, _, _ = setup_search
    await advanced_search.search_messages_advanced({
        "channel_id": "1", "offset": 9975, "limit": 200,
    })
    assert target.kwargs["limit"] == 25


def context_target(target):
    target.fetch_message = AsyncMock(return_value=fake_message(102))
    target.history_calls = []

    def history(**kwargs):
        target.history_calls.append(kwargs)
        # Discord returns the nearest preceding messages newest first, and
        # the nearest following messages oldest first with these parameters.
        ids = [101, 100] if "before" in kwargs else [103, 104]

        async def results():
            for message_id in ids[:kwargs["limit"]]:
                yield fake_message(message_id)

        return results()

    target.history = history
    return target


@pytest.mark.asyncio
async def test_context_returns_nearest_neighbors_in_chronological_order(setup_search):
    target, _, limiter = setup_search
    context_target(target)
    result = await advanced_search.get_message_context({
        "channel_id": "1", "message_id": "102", "before_count": 2, "after_count": 2,
    })
    text = result[0].text
    ids = re.findall(r"^(\d+) u\d+ c\d+ ", text, re.MULTILINE)
    assert ids == [str(i) for i in range(100, 105)]
    assert text.count("[TARGET MESSAGE]") == 1
    assert "[TARGET MESSAGE]\n102 u1 c1" in text
    target.fetch_message.assert_awaited_once_with(102)
    assert target.history_calls[0] == {"limit": 2, "before": target.fetch_message.return_value, "oldest_first": False}
    assert target.history_calls[1] == {"limit": 2, "after": target.fetch_message.return_value, "oldest_first": True}
    limiter.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_zero_counts_only_fetches_target(setup_search):
    target, _, limiter = setup_search
    context_target(target)
    result = await advanced_search.get_message_context({
        "channel_id": "1", "message_id": "102", "before_count": 0, "after_count": 0,
    })
    assert target.history_calls == []
    limiter.assert_not_awaited()
    assert "0 before, target, 0 after" in result[0].text


@pytest.mark.asyncio
async def test_context_fetches_uncached_channel_and_reports_available_counts(setup_search):
    target, client, _ = setup_search
    context_target(target)
    client.get_channel = lambda _: None
    result = await advanced_search.get_message_context({"channel_id": "1", "message_id": "102"})
    client.fetch_channel.assert_awaited_once_with(1)
    assert [kwargs["limit"] for kwargs in target.history_calls] == [10, 10]
    assert "2 before, target, 2 after" in result[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("override,error", [
    ({"before_count": -1}, "before_count"),
    ({"after_count": 51}, "after_count"),
    ({"before_count": True}, "before_count"),
    ({"message_id": "bad"}, "message_id"),
])
async def test_context_rejects_invalid_counts_and_ids(setup_search, override, error):
    target, _, limiter = setup_search
    context_target(target)
    args = {"channel_id": "1", "message_id": "102", **override}
    with pytest.raises(RuntimeError, match=error):
        await advanced_search.get_message_context(args)
    target.fetch_message.assert_not_awaited()
    limiter.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(404, "not found"), (403, "Access denied")])
async def test_context_reports_deleted_or_inaccessible_anchor(setup_search, status, expected):
    target, _, _ = setup_search
    context_target(target)
    response = SimpleNamespace(status=status, reason="Unavailable")
    error_type = advanced_search.discord.NotFound if status == 404 else advanced_search.discord.Forbidden
    target.fetch_message.side_effect = error_type(response, "Unavailable")
    with pytest.raises(RuntimeError, match=expected):
        await advanced_search.get_message_context({"channel_id": "1", "message_id": "102"})
    assert target.history_calls == []


@pytest.mark.asyncio
async def test_search_and_context_work_during_a_full_write_cooldown(setup_search, monkeypatch):
    target, _, _ = setup_search
    context_target(target)
    limiter = RateLimiter()
    limiter._action_timestamps = [time.time()] * 5
    limiter._cooldown_until = time.time() + 60
    monkeypatch.setattr(tool_utils, "rate_limiter", limiter)

    for _ in range(3):
        search = await asyncio.wait_for(
            advanced_search.search_messages_advanced({"channel_id": "1", "query": "release"}),
            timeout=0.5,
        )
        context = await asyncio.wait_for(
            advanced_search.get_message_context({"channel_id": "1", "message_id": "102"}),
            timeout=0.5,
        )
        assert "Native Discord search: returned=1" in search[0].text
        assert "[TARGET MESSAGE]" in context[0].text

    assert len(limiter._action_timestamps) == 5
    assert limiter.get_cooldown_remaining() > 50
