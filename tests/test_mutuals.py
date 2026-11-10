import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from discord_py_self_mcp.tools import mutuals
from discord_py_self_mcp.tools.registry import registry


@pytest.fixture
def setup_mutuals(monkeypatch):
    profile = SimpleNamespace(
        id=77, name="target", _blocked=False,
        mutual_guilds=[SimpleNamespace(id=11), SimpleNamespace(id=22)],
        mutual_friends=[
            SimpleNamespace(id=101, name="first", global_name="First Friend"),
            SimpleNamespace(id=102, name="second", global_name=None),
        ],
        mutual_friends_count=2,
    )
    guilds = {11: SimpleNamespace(name="First server"), 22: SimpleNamespace(name="Second server")}
    client = SimpleNamespace(
        is_ready=lambda: True, user=SimpleNamespace(id=1),
        fetch_user_profile=AsyncMock(return_value=profile), get_guild=guilds.get,
        fetch_guild=AsyncMock(side_effect=AssertionError("No per-guild HTTP requests")),
        fetch_user=AsyncMock(side_effect=AssertionError("No per-friend HTTP requests")),
    )
    manager = SimpleNamespace(active_account="main")
    monkeypatch.setattr(mutuals, "client", client)
    monkeypatch.setattr(mutuals, "account_manager", manager)
    return client, profile, guilds, manager


async def get(**kwargs):
    response = await mutuals.get_user_mutuals({"user_id": "77", **kwargs})
    return json.loads(response[0].text)


@pytest.mark.asyncio
async def test_mutuals_use_one_profile_request_and_identify_active_account(setup_mutuals):
    client, _, _, _ = setup_mutuals
    payload = await get()
    assert payload["user"] == {"id": "77", "name": "target"}
    assert payload["viewer"] == {"account": "main", "id": "1"}
    assert payload["guilds"]["count"] == payload["friends"]["count"] == 2
    assert payload["guilds"]["items"][0] == {"id": "11", "name": "First server"}
    assert payload["friends"]["items"][0] == {"id": "101", "name": "first", "display_name": "First Friend"}
    assert payload["guilds"]["status"] == payload["friends"]["status"] == "available"
    client.fetch_user_profile.assert_awaited_once_with(
        77, with_mutual_guilds=True, with_mutual_friends=True, with_mutual_friends_count=True,
    )
    client.fetch_guild.assert_not_awaited()
    client.fetch_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_cached_guild_name_does_not_trigger_an_extra_request(setup_mutuals):
    client, _, guilds, _ = setup_mutuals
    del guilds[11]
    payload = await get()
    assert payload["guilds"]["items"][0] == {"id": "11", "name": None}
    client.fetch_guild.assert_not_awaited()


@pytest.mark.parametrize("group,flag", [("guilds", "include_guilds"), ("friends", "include_friends")])
@pytest.mark.asyncio
async def test_unrequested_data_are_not_fetched_or_reported_as_empty(setup_mutuals, group, flag):
    client, _, _, _ = setup_mutuals
    payload = await get(**{flag: False})
    assert payload[group]["status"] == "not_requested" and payload[group]["count"] is None
    options = client.fetch_user_profile.await_args.kwargs
    assert options["with_mutual_guilds" if group == "guilds" else "with_mutual_friends"] is False
    if group == "friends":
        assert options["with_mutual_friends_count"] is False


@pytest.mark.asyncio
async def test_empty_visible_lists_mean_zero_but_missing_lists_mean_unknown(setup_mutuals):
    _, profile, _, _ = setup_mutuals
    profile.mutual_guilds = profile.mutual_friends = []
    profile.mutual_friends_count = 0
    empty = await get()
    assert empty["guilds"]["count"] == empty["friends"]["count"] == 0
    assert empty["guilds"]["status"] == empty["friends"]["status"] == "available"
    profile.mutual_guilds = profile.mutual_friends = None
    profile.mutual_friends_count = None
    missing = await get()
    assert missing["guilds"]["status"] == missing["friends"]["status"] == "unavailable"
    assert missing["guilds"]["count"] is missing["friends"]["count"] is None


@pytest.mark.asyncio
async def test_visible_count_without_friend_list_is_explicit(setup_mutuals):
    _, profile, _, _ = setup_mutuals
    profile.mutual_friends = None
    profile.mutual_friends_count = 7
    friends = (await get())["friends"]
    assert friends["status"] == "count_only" and friends["count"] == 7
    assert friends["items"] == [] and friends["next_offset"] is None


@pytest.mark.asyncio
async def test_partial_friend_list_does_not_claim_all_reported_friends_are_listed(setup_mutuals):
    _, profile, _, _ = setup_mutuals
    profile.mutual_friends_count = 10
    friends = (await get())["friends"]
    assert friends["status"] == "partial" and friends["count"] == 10
    assert friends["available_count"] == len(friends["items"]) == 2
    assert friends["next_offset"] is None  # The API exposed only two entries.


@pytest.mark.asyncio
async def test_limited_profile_does_not_turn_hidden_lists_into_zero_mutuals(setup_mutuals):
    _, profile, _, _ = setup_mutuals
    profile._blocked = True
    profile.mutual_guilds = profile.mutual_friends = []
    profile.mutual_friends_count = 0
    payload = await get()
    assert payload["profile_visibility"] == "limited"
    assert payload["guilds"]["status"] == payload["friends"]["status"] == "limited"
    assert payload["guilds"]["count"] is payload["friends"]["count"] is None


@pytest.mark.asyncio
async def test_pagination_keeps_totals_and_does_not_skip_entries(setup_mutuals):
    first = await get(limit=1)
    assert first["guilds"]["next_offset"] == first["friends"]["next_offset"] == 1
    second = await get(limit=1, guild_offset=1, friend_offset=1)
    assert second["guilds"]["items"][0]["id"] == "22"
    assert second["friends"]["items"][0]["id"] == "102"
    assert second["guilds"]["next_offset"] is second["friends"]["next_offset"] is None
    assert second["guilds"]["count"] == second["friends"]["count"] == 2
    beyond = await get(guild_offset=99, friend_offset=99)
    assert beyond["guilds"]["items"] == beyond["friends"]["items"] == []
    assert beyond["guilds"]["count"] == beyond["friends"]["count"] == 2


@pytest.mark.asyncio
async def test_output_budget_is_shared_and_offsets_resume_at_first_omitted_item(setup_mutuals):
    client, profile, guilds, _ = setup_mutuals
    profile.mutual_guilds = [SimpleNamespace(id=i) for i in range(1000, 1100)]
    guilds.update({i: SimpleNamespace(name=str(i) + "s" * 96) for i in range(1000, 1100)})
    profile.mutual_friends = [
        SimpleNamespace(id=i, name="n" * 32, global_name="d" * 32) for i in range(2000, 2100)
    ]
    profile.mutual_friends_count = 100
    raw = await mutuals.get_user_mutuals({"user_id": "77", "limit": 100, "max_output_chars": 2000})
    assert len(raw[0].text) <= 2000
    payload = json.loads(raw[0].text)
    assert payload["output_limited"]
    for group, start in (("guilds", 1000), ("friends", 2000)):
        section = payload[group]
        assert section["items"]
        assert section["next_offset"] == len(section["items"])
        assert [item["id"] for item in section["items"]] == [
            str(i) for i in range(start, start + len(section["items"]))
        ]
    client.fetch_guild.assert_not_awaited()
    client.fetch_user.assert_not_awaited()


@pytest.mark.parametrize("args", [
    {"user_id": "unknown"}, {"user_id": "0"},
    {"include_guilds": False, "include_friends": False}, {"include_friends": 1},
    {"limit": True}, {"limit": 0}, {"guild_offset": -1}, {"friend_offset": "1"},
    {"max_output_chars": 100},
])
@pytest.mark.asyncio
async def test_invalid_arguments_fail_before_profile_request(setup_mutuals, args):
    client, _, _, _ = setup_mutuals
    with pytest.raises(ValueError):
        await mutuals.get_user_mutuals({"user_id": "77", **args})
    client.fetch_user_profile.assert_not_awaited()


@pytest.mark.parametrize("status,code", [(404, 10013), (403, 50001), (500, 0)])
@pytest.mark.asyncio
async def test_profile_errors_mean_unknown_not_no_mutuals(setup_mutuals, status, code):
    client, _, _, _ = setup_mutuals
    cls = discord.NotFound if status == 404 else discord.Forbidden if status == 403 else discord.HTTPException
    client.fetch_user_profile.side_effect = cls(
        SimpleNamespace(status=status, reason="Unavailable"),
        {"code": code, "message": "Unavailable"},
    )
    with pytest.raises(RuntimeError, match="unknown"):
        await get()
    client.fetch_guild.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_and_not_ready_are_explicit(setup_mutuals):
    client, _, _, _ = setup_mutuals
    client.fetch_user_profile.side_effect = asyncio.TimeoutError()
    with pytest.raises(RuntimeError, match="timed out"):
        await get()
    client.fetch_user_profile.reset_mock()
    client.is_ready = lambda: False
    with pytest.raises(RuntimeError, match="not ready"):
        await get()
    client.fetch_user_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_profile_identity_is_rejected(setup_mutuals):
    _, profile, _, _ = setup_mutuals
    profile.id = 78
    with pytest.raises(RuntimeError, match="different user profile"):
        await get()


def test_tool_schema_exposes_only_a_required_user_id():
    schema = registry.tools["get_user_mutuals"].inputSchema
    assert schema["required"] == ["user_id"]
    assert schema["properties"]["limit"]["default"] == 20
