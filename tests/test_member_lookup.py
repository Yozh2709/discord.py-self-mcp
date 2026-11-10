from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from discord_py_self_mcp.tools import member_lookup, permissions


@pytest.fixture
def member_client(monkeypatch):
    member = SimpleNamespace(
        id=77, name="example_member", display_name="Server Alias", nick="Server Alias",
        joined_at=datetime(2023, 1, 16, tzinfo=timezone.utc), bot=False, roles=[],
        guild_permissions=discord.Permissions(0),
    )
    guild = SimpleNamespace(get_member=lambda _: None, fetch_member=AsyncMock(return_value=member), channels=[])
    client = SimpleNamespace(is_ready=lambda: True, get_guild=lambda _: guild, fetch_guild=AsyncMock(return_value=guild))
    monkeypatch.setattr(member_lookup, "client", client)
    monkeypatch.setattr(permissions, "client", client)
    return client, guild, member


def api_error(status, code):
    response = SimpleNamespace(status=status, reason="Unavailable")
    cls = discord.NotFound if status == 404 else discord.Forbidden if status == 403 else discord.HTTPException
    return cls(response, {"code": code, "message": "Unavailable"})


@pytest.mark.asyncio
async def test_uncached_member_is_confirmed_by_api(member_client):
    _, guild, _ = member_client
    result = await member_lookup.get_guild_member({"guild_id": "1", "user_id": "77"})
    payload = json.loads(result[0].text)
    assert payload["is_member"] is True
    assert payload["status"] == "present"
    assert payload["username"] == "example_member"
    assert payload["source"] == "discord_api"
    guild.fetch_member.assert_awaited_once_with(77)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,expected", [(404, 10007, False), (404, 10004, None), (403, 50001, None), (500, 0, None)])
async def test_only_unknown_member_means_absence(member_client, status, code, expected):
    _, guild, member = member_client
    guild.get_member = lambda _: member  # Deliberately stale cache entry.
    guild.fetch_member.side_effect = api_error(status, code)
    result = await member_lookup.get_guild_member({"guild_id": "1", "user_id": "77"})
    payload = json.loads(result[0].text)
    assert payload["is_member"] is expected
    assert payload["status"] == ("absent" if expected is False else "unknown")
    guild.fetch_member.assert_awaited_once_with(77)


@pytest.mark.asyncio
async def test_permissions_inspection_fetches_an_uncached_member(member_client):
    _, guild, _ = member_client
    result = await permissions.inspect_effective_permissions({"guild_id": "1", "target_id": "77", "target_type": "member"})
    payload = json.loads(result[0].text)
    assert payload["is_member"] is True
    assert payload["member_source"] == "discord_api"
    guild.fetch_member.assert_awaited_once_with(77)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,expected", [(404, 10007, False), (403, 50001, None)])
async def test_permissions_inspection_does_not_trust_a_stale_cache(member_client, status, code, expected):
    _, guild, member = member_client
    guild.get_member = lambda _: member
    guild.fetch_member.side_effect = api_error(status, code)
    result = await permissions.inspect_effective_permissions({"guild_id": "1", "target_id": "77", "target_type": "member"})
    payload = json.loads(result[0].text)
    assert payload["is_member"] is expected
    assert payload["membership_status"] == ("absent" if expected is False else "unknown")


@pytest.mark.asyncio
async def test_inaccessible_guild_does_not_mean_absence(member_client):
    client, guild, _ = member_client
    client.get_guild = lambda _: None
    client.fetch_guild.side_effect = api_error(403, 50001)
    result = await member_lookup.get_guild_member({"guild_id": "1", "user_id": "77"})
    assert json.loads(result[0].text)["is_member"] is None
    guild.fetch_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_user_id_never_queries_api(member_client):
    _, guild, _ = member_client
    with pytest.raises(ValueError):
        await member_lookup.get_guild_member({"guild_id": "1", "user_id": "example_member"})
    guild.fetch_member.assert_not_awaited()
