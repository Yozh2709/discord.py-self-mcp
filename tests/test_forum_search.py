import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from discord_py_self_mcp.tools import forum_search


class FakeForum:
    id = 1
    guild = SimpleNamespace(id=2)
    threads = []  # Archived posts must be found even when the local cache is empty.


@pytest.fixture
def forum_client(monkeypatch):
    response = {
        "threads": [{"id": "10", "name": "fly ideas", "thread_metadata": {"archived": True}, "message_count": 5}],
        "first_messages": [{"id": "10", "channel_id": "10", "content": "A flying suggestion", "attachments": []}],
        "total_results": 1,
        "has_more": False,
    }
    client = SimpleNamespace(
        is_ready=lambda: True,
        get_channel=lambda _: FakeForum(),
        fetch_channel=AsyncMock(return_value=FakeForum()),
        http=SimpleNamespace(request=AsyncMock(return_value=response)),
    )
    monkeypatch.setattr(forum_search.discord, "ForumChannel", FakeForum)
    monkeypatch.setattr(forum_search, "client", client)
    return client, response


@pytest.mark.asyncio
async def test_search_includes_archived_posts_outside_cache_and_returns_links(forum_client):
    client, _ = forum_client
    result = await forum_search.search_forum_topics({"forum_id": "1", "query": "fly"})
    payload = json.loads(result[0].text)
    client.http.request.assert_awaited_once()
    route = client.http.request.call_args.args[0]
    assert route.method == "GET"
    assert route.url.endswith("/channels/1/threads/search")
    assert "archived" not in client.http.request.call_args.kwargs["params"]
    assert payload["total_results"] == 1
    assert payload["next_offset"] is None
    row = payload["results"][0]
    assert row["archived"] is True
    assert row["thread_id"] == row["starter_message_id"] == "10"
    assert row["url"] == "https://discord.com/channels/2/10"
    assert row["preview"] == "A flying suggestion"


@pytest.mark.asyncio
@pytest.mark.parametrize("archived,expected", [(True, "true"), (False, "false")])
async def test_archived_filter_and_pagination(forum_client, archived, expected):
    client, response = forum_client
    response.update(total_results=30, has_more=True)
    result = await forum_search.search_forum_topics({"forum_id": "1", "query": "fly", "archived": archived, "offset": 10, "limit": 1})
    params = client.http.request.call_args.kwargs["params"]
    assert params["archived"] == expected
    assert params["offset"] == 10
    assert params["limit"] == 1
    assert json.loads(result[0].text)["next_offset"] == 11


@pytest.mark.asyncio
async def test_no_results_and_preview_limit(forum_client):
    client, response = forum_client
    response["first_messages"][0]["content"] = "x" * 1000
    result = await forum_search.search_forum_topics({"forum_id": "1", "query": "fly"})
    row = json.loads(result[0].text)["results"][0]
    assert len(row["preview"]) == 400
    assert row["preview_truncated"] is True
    response.update(threads=[], first_messages=[], total_results=0)
    result = await forum_search.search_forum_topics({"forum_id": "1", "query": "missing"})
    assert json.loads(result[0].text)["results"] == []
    assert json.loads(result[0].text)["total_results"] == 0


@pytest.mark.asyncio
async def test_uncached_forum_is_fetched_once(forum_client):
    client, _ = forum_client
    client.get_channel = lambda _: None
    await forum_search.search_forum_topics({"forum_id": "1", "query": "fly"})
    client.fetch_channel.assert_awaited_once_with(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"forum_id": "bad"}, {"query": " "}, {"query": "x" * 101},
    {"limit": 26}, {"limit": True}, {"offset": -1}, {"archived": "false"},
])
async def test_invalid_parameters_never_make_search_requests(forum_client, override):
    client, _ = forum_client
    with pytest.raises(ValueError):
        await forum_search.search_forum_topics({"forum_id": "1", "query": "fly", **override})
    client.http.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_forum_channel_is_rejected(forum_client):
    client, _ = forum_client
    client.get_channel = lambda _: object()
    with pytest.raises(ValueError, match="forum channel"):
        await forum_search.search_forum_topics({"forum_id": "1", "query": "fly"})
    client.http.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_not_ready_retry_is_bounded(forum_client, monkeypatch):
    client, _ = forum_client
    client.http.request.return_value = {"code": 110000, "retry_after": 2}
    sleep = AsyncMock()
    monkeypatch.setattr(forum_search.asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError, match="index is not ready"):
        await forum_search.search_forum_topics({"forum_id": "1", "query": "fly"})
    assert client.http.request.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_api_failure_is_not_reported_as_an_empty_search(forum_client):
    client, _ = forum_client
    client.http.request.side_effect = RuntimeError("Discord access denied")
    with pytest.raises(RuntimeError, match="access denied"):
        await forum_search.search_forum_topics({"forum_id": "1", "query": "fly"})
