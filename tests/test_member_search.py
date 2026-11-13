import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from discord_py_self_mcp.tools import member_search
from discord_py_self_mcp.tools.registry import registry


def member(user_id=77, name="example.member", nick=None, global_name=None):
    return SimpleNamespace(id=user_id, name=name, nick=nick, global_name=global_name,
                           display_name=nick or global_name or name)


@pytest.fixture
def setup(monkeypatch):
    guild = SimpleNamespace(members=[], query_members=AsyncMock(return_value=[]))
    client = SimpleNamespace(is_ready=lambda: True, get_guild=lambda _: guild)
    monkeypatch.setattr(member_search, "client", client)
    return client, guild


async def search(**kwargs):
    result = await member_search.search_guild_members({"guild_id": "1", "query": "examplemember", **kwargs})
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_dotless_name_discovers_uncached_dotted_username(setup):
    _, guild = setup
    async def query(**kwargs):
        return [member()] if kwargs.get("query") == "examp" else []
    guild.query_members.side_effect = query
    result = await search()
    assert result["matches"][0]["username"] == "example.member"
    assert result["matches"][0]["match"] == "normalized_exact"
    assert result["matches"][0]["is_member"] is True
    assert result["queries"] == ["examplemember", "examp"]
    assert result["gateway_requests"] == 2
    assert result["search_complete"] is False
    for call in guild.query_members.await_args_list:
        assert call.kwargs["presences"] is False
        assert call.kwargs["cache"] is False
        assert call.kwargs["subscribe"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "nick", "global_name"])
async def test_matches_all_name_fields_case_and_punctuation(setup, field):
    _, guild = setup
    candidate = member(name="unrelated", nick="Server Name", global_name="Display Name")
    setattr(candidate, field, "ExAmPlE_Member")
    guild.query_members.return_value = [candidate]
    result = await search(query="@EXAMPLE member")
    assert result["matches"][0]["user_id"] == "77"
    assert result["matches"][0]["match"] == "normalized_exact"
    assert result["gateway_requests"] == 1


@pytest.mark.asyncio
async def test_cached_candidates_are_verified_in_one_batch(setup):
    _, guild = setup
    guild.members = [member(77), member(78, "example_member")]
    async def query(**kwargs):
        if "user_ids" in kwargs:
            assert kwargs["user_ids"] == [77, 78]
            return [member(77)]  # The second cached user has left.
        return []
    guild.query_members.side_effect = query
    result = await search()
    assert [row["user_id"] for row in result["matches"]] == ["77"]
    assert result["verified_cache_candidates"] == 1
    assert result["gateway_requests"] == 4


@pytest.mark.asyncio
async def test_stale_cache_name_is_rechecked_after_live_verification(setup):
    _, guild = setup
    guild.members = [member()]
    async def query(**kwargs):
        return [member(name="renamed.person")] if "user_ids" in kwargs else []
    guild.query_members.side_effect = query
    result = await search()
    assert result["matches"] == []
    assert result["search_complete"] is False


@pytest.mark.asyncio
async def test_empty_query_result_never_means_absent(setup):
    result = await search()
    assert result["returned"] == 0
    assert result["search_complete"] is False
    assert "is_member" not in result


@pytest.mark.asyncio
async def test_deduplicates_ranks_exact_and_bounds_output(setup):
    _, guild = setup
    exact = member(80, "examplemember")
    guild.query_members.return_value = [member(77, "examplemember_more"), exact, exact, member(81, "unrelated")]
    result = await search(limit=1)
    assert [row["user_id"] for row in result["matches"]] == ["80"]
    assert result["more_matches_known"] is True


@pytest.mark.asyncio
async def test_candidate_cap_and_output_budget_are_reported(setup):
    _, guild = setup
    guild.query_members.return_value = [member(i, "examplemember_" + "x" * 70 + str(i)) for i in range(1, 101)]
    result = await search(limit=50, max_output_chars=2000)
    assert result["candidate_limit_reached"] is True
    assert result["output_limited"] is True
    assert result["more_matches_known"] is True
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= 2000


@pytest.mark.asyncio
async def test_timeout_is_mcp_error_without_stale_candidates(setup):
    _, guild = setup
    guild.members = [member()]
    guild.query_members.side_effect = asyncio.TimeoutError
    with pytest.raises(RuntimeError, match="timed out"):
        await search()


@pytest.mark.asyncio
async def test_partial_results_survive_later_query_timeout(setup):
    _, guild = setup
    guild.query_members.side_effect = [[member(name="examplemember_more")], asyncio.TimeoutError]
    result = await search()
    assert result["partial_failure"] is True
    assert result["matches"][0]["is_member"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "@", ". _", "x", None, 10, "x" * 101])
async def test_invalid_names_never_request_members(setup, query):
    _, guild = setup
    with pytest.raises(ValueError):
        await search(query=query)
    guild.query_members.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_guild_and_not_ready_fail_before_gateway(setup):
    client, guild = setup
    client.is_ready = lambda: False
    with pytest.raises(RuntimeError):
        await search()
    client.is_ready = lambda: True
    client.get_guild = lambda _: None
    with pytest.raises(RuntimeError):
        await search()
    guild.query_members.assert_not_awaited()


def test_schema_registered_without_provider_union():
    schema = registry.tools["search_guild_members"].inputSchema
    assert schema["required"] == ["guild_id", "query"]
    assert "anyOf" not in schema
