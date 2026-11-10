import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from discord_py_self_mcp.tools import advanced_search
from discord_py_self_mcp.tools.search_metadata import SearchMetadata


def response(total, ids=(), **extra):
    return {
        "total_results": total,
        "messages": [[{"id": str(message_id), "channel_id": "10"}] for message_id in ids],
        **extra,
    }


def destination(monkeypatch, replies, kind="guild", *, content="text"):
    http = SimpleNamespace(
        search_guild=AsyncMock(side_effect=replies),
        search_channel=AsyncMock(side_effect=replies),
    )
    state = SimpleNamespace(http=http, user=SimpleNamespace(nsfw_allowed=None))
    guild = discord.Guild.__new__(discord.Guild)
    guild.id, guild._state = 1, state
    channel_type = discord.DMChannel if kind == "dm" else discord.TextChannel
    channel = channel_type.__new__(channel_type)
    channel.id, channel._state = 10, state
    if kind != "dm":
        channel.guild = guild
    state._get_guild_channel = lambda data: (channel, guild if kind != "dm" else None)
    state.create_message = lambda *, channel, data, search_result: SimpleNamespace(
        id=int(data["id"]), channel=channel,
        author=SimpleNamespace(id=99, name="reader"),
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        content=content, clean_content="", embeds=[], attachments=[], reference=None,
        total_results=search_result["total_results"],
    )
    # No members are needed to render role metadata.
    guild._members = {}
    client = SimpleNamespace(get_guild=lambda _: guild, get_channel=lambda _: channel)
    monkeypatch.setattr(advanced_search, "client", client)
    return guild, channel, state, http


@pytest.mark.parametrize("kind", ["guild", "channel", "dm"])
@pytest.mark.asyncio
async def test_total_from_same_sdk_request_for_guild_channel_and_dm(monkeypatch, kind):
    guild, channel, state, http = destination(monkeypatch, [response(137, [100])], kind)
    args = {"guild_id": "1"} if kind == "guild" else {"channel_id": "10"}
    page = await advanced_search._search_page({**args, "limit": 1, "query": "text"})
    assert page["returned"] == 1 and page["total_results"] == 137
    assert page["has_more"] and page["next_offset"] == 1
    endpoint = http.search_channel if kind == "dm" else http.search_guild
    assert endpoint.await_count == 1
    params = endpoint.await_args.args[1]
    assert params["limit"] == 1 and params["content"] == "text"
    if kind == "channel":
        assert params["channel_id"] == [10]
    assert guild._state is state and channel._state is state
    assert state.http is http  # No shared client/state/HTTP monkeypatch.


@pytest.mark.asyncio
async def test_output_budget_does_not_replace_total_with_returned_count(monkeypatch):
    _, _, _, http = destination(monkeypatch, [response(137, range(100, 125))], content="x" * 2000)
    page = await advanced_search._search_page({
        "guild_id": "1", "limit": 100, "preview_chars": 400, "max_output_chars": 2000,
    })
    assert page["total_results"] == 137
    assert 0 < page["returned"] < 25
    assert page["output_limited"]
    assert page["next_offset"] == page["returned"]
    http.search_guild.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_total_survives_sdk_snowflake_pagination(monkeypatch):
    _, _, _, http = destination(monkeypatch, [
        response(137, range(200, 175, -1)),
        response(112, range(175, 170, -1)),
    ])
    page = await advanced_search._search_page({
        "guild_id": "1", "limit": 30, "preview_chars": 80, "max_output_chars": 16000,
    })
    assert page["returned"] == 30 and page["total_results"] == 137
    assert http.search_guild.await_count == 2
    assert http.search_guild.await_args_list[1].args[1]["max_id"] == 176


@pytest.mark.parametrize("offset,total", [(0, 0), (200, 137)])
@pytest.mark.asyncio
async def test_empty_pages_retain_actual_count_without_a_second_request(monkeypatch, offset, total):
    _, _, _, http = destination(monkeypatch, [response(total)])
    result = (await advanced_search.search_messages_advanced({"guild_id": "1", "offset": offset}))[0].text
    assert f"returned=0, total_results={total}" in result
    assert "has_more=false" in result and "next_offset=None" in result
    assert "channels:" not in result
    http.search_guild.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_but_incomplete_page_does_not_claim_zero_matches(monkeypatch):
    destination(monkeypatch, [response(137)])
    page = await advanced_search._search_page({"guild_id": "1"})
    assert page["returned"] == 0 and page["total_results"] == 137
    assert page["has_more"] and page["search_incomplete"]
    assert page["next_offset"] is None  # No non-advancing pagination loop.


@pytest.mark.asyncio
async def test_total_beyond_discord_search_window_is_not_reported_as_exhausted_results(monkeypatch):
    destination(monkeypatch, [response(20000, range(100, 125))])
    page = await advanced_search._search_page({
        "guild_id": "1", "offset": 9975, "limit": 25, "max_output_chars": 16000,
    })
    assert page["total_results"] == 20000 and page["returned"] == 25
    assert page["has_more"] and page["search_window_exhausted"]
    assert page["next_offset"] is None


@pytest.mark.asyncio
async def test_indexing_totals_are_marked_partial(monkeypatch):
    destination(monkeypatch, [response(137, [100], doing_deep_historical_index=True)])
    result = (await advanced_search.search_messages_advanced({"guild_id": "1", "limit": 1}))[0].text
    assert "total_results=137" in result and "total_results_partial=true" in result


@pytest.mark.asyncio
async def test_parallel_batch_totals_are_isolated_and_never_summed(monkeypatch):
    _, _, state, http = destination(monkeypatch, [])
    started = 0
    both = asyncio.Event()
    async def request(guild_id, params):
        nonlocal started
        started += 1
        if started == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=1)
        return response(137 if params["content"] == "first" else 42, [100])
    http.search_guild.side_effect = request
    payload = json.loads((await advanced_search.search_messages_batch({
        "guild_id": "1", "queries": ["first", "second"], "limit_per_query": 1,
    }))[0].text)
    assert [row["total_results"] for row in payload["queries"]] == [137, 42]
    assert [row["returned"] for row in payload["queries"]] == [1, 1]
    assert len(payload["messages"]) == 1
    assert "total_results" not in payload  # Overlapping queries have no combined total.
    assert http.search_guild.await_count == 2
    assert state.http is http


@pytest.mark.asyncio
async def test_batch_global_output_budget_retains_counts_and_resumable_offsets(monkeypatch):
    _, _, _, http = destination(monkeypatch, [])
    async def request(guild_id, params):
        first = 100 if params["content"] == "first" else 200
        return response(137, range(first, first + 10))
    http.search_guild.side_effect = request
    payload = json.loads((await advanced_search.search_messages_batch({
        "guild_id": "1", "queries": ["first", "second"], "limit_per_query": 10, "max_output_chars": 4000,
    }))[0].text)
    assert [row["total_results"] for row in payload["queries"]] == [137, 137]
    for row in payload["queries"]:
        assert row["has_more"] and row["next_offset"] == row["returned"]


@pytest.mark.parametrize("value", [None, True, -1, "137"])
def test_missing_or_invalid_totals_are_not_invented(value):
    metadata = SearchMetadata()
    metadata.capture_response({"total_results": value})
    assert metadata.total_results is None
