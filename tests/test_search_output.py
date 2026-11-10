import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from discord_py_self_mcp.tools import advanced_search, discrawl, embed, messages, threads
from discord_py_self_mcp.tools.registry import ToolRegistry, registry


def message(message_id=100, *, content="hello", guild=None, author=None, reply=None):
    return SimpleNamespace(
        id=message_id, channel=SimpleNamespace(id=10, guild=guild), guild=guild,
        author=author or SimpleNamespace(id=99, name="reader"),
        created_at=datetime(2026, 11, 8, tzinfo=timezone.utc),
        content=content, clean_content=content, embeds=[], attachments=[], reference=reply,
    )


def reference(parent_id, *, resolved=None, channel_id=10):
    return SimpleNamespace(message_id=parent_id, channel_id=channel_id, resolved=resolved)


def cached_guild():
    guild = SimpleNamespace(id=1)
    state = SimpleNamespace(store_user=lambda data: SimpleNamespace(id=int(data["id"]), name=data["username"]))
    roles = {
        1: discord.Role(guild=guild, state=state, data={"id": "1", "name": "@everyone", "position": 0, "color": 0}),
        2: discord.Role(guild=guild, state=state, data={"id": "2", "name": "Coloured role", "position": 1, "colors": {"primary_color": 0x123456}}),
        3: discord.Role(guild=guild, state=state, data={"id": "3", "name": "Moderator", "position": 5, "color": 0}),
    }
    guild.default_role = roles[1]
    guild.get_role = roles.get
    member = discord.Member(
        guild=guild, state=state,
        data={"user": {"id": "99", "username": "reader"}, "roles": ["2", "3"], "flags": 0},
    )
    guild.get_member = lambda user_id: member if user_id == 99 else None
    guild.fetch_member = AsyncMock(side_effect=AssertionError("No member HTTP requests allowed"))
    guild.fetch_roles = AsyncMock(side_effect=AssertionError("No role HTTP requests allowed"))
    return guild, member, roles


def test_cached_top_role_and_display_colour_need_no_http():
    guild, member, _ = cached_guild()
    msg = message(guild=guild)
    info = embed.author_role_info(msg, details=True)
    assert info["top_role"] == "Moderator"
    assert info["role_color"] == "#000000"
    assert info["display_color"] == "#123456"
    assert info["role_source"] == "guild_cache"
    assert 'top_role="Moderator"' in embed.format_message_line(msg)
    assert embed.serialize_message(msg)["top_role"] == "Moderator"
    assert embed.author_role_info(msg) == {"top_role": "Moderator"}
    assert "role_color" not in embed.serialize_message(msg)
    msg.author = member
    assert embed.author_role_info(msg, details=True)["role_source"] == "message_member"
    guild.fetch_member.assert_not_awaited()
    guild.fetch_roles.assert_not_awaited()


def test_uncached_member_or_partial_roles_are_explicit_and_dms_have_no_role():
    guild, member, roles = cached_guild()
    unknown = message(guild=guild, author=SimpleNamespace(id=500, name="uncached"))
    assert embed.author_role_info(unknown) == {"role_status": "uncached"}
    del roles[3]
    assert embed.author_role_info(message(guild=guild, author=member)) == {"role_status": "uncached"}
    assert embed.author_role_info(message()) == {}
    guild.fetch_member.assert_not_awaited()
    guild.fetch_roles.assert_not_awaited()


def test_default_legend_keeps_identity_roles_and_navigation_without_repeating_metadata():
    guild, _, _ = cached_guild()
    rows = [message(100 + i, guild=guild, content="short text", reply=reference(100) if i else None) for i in range(30)]
    compact = embed.MessageFormatter()
    compact_text = compact.join([compact.format(row) for row in rows])
    detailed = embed.MessageFormatter(details=True)
    detailed_text = detailed.join([detailed.format(row) for row in rows])
    assert compact_text.count("Moderator") == 1
    assert compact_text.count("reader") == 1
    assert compact_text.count("https://discord.com/channels/1/10") == 1
    assert "u1=99 reader" in compact_text and "->100:" in compact_text
    for field in ("role_color", "display_color", "top_role_id", "role_source", "timestamp=", "url="):
        assert field not in compact_text
    assert "role_color=" in detailed_text and "top_role_id=" in detailed_text
    assert len(compact_text) < len(detailed_text) / 2
    message_ids = re.findall(r"^(\d+) u1 c1 ", compact_text, re.MULTILINE)
    assert message_ids == [str(row.id) for row in rows]
    guild.fetch_member.assert_not_awaited()
    guild.fetch_roles.assert_not_awaited()


def test_later_message_member_data_can_fill_an_unknown_role_in_the_same_legend():
    guild, member, _ = cached_guild()
    guild.get_member = lambda _: None
    formatter = embed.MessageFormatter()
    first = formatter.format(message(100, guild=guild))
    assert "[role unknown]" in formatter.header()
    second = formatter.format(message(101, guild=guild, author=member))
    result = formatter.join([first, second])
    assert "[role unknown]" not in result
    assert result.count("Moderator") == 1
    assert "100 u1 c1 " in result and "101 u1 c1 " in result
    guild.fetch_member.assert_not_awaited()


class Target:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        query = kwargs.get("content")
        rows = self.rows(query) if callable(self.rows) else self.rows
        async def iterate():
            for row in rows[kwargs["offset"]:kwargs["offset"] + kwargs["limit"]]:
                yield row
        return iterate()


@pytest.fixture
def install_target(monkeypatch):
    def install(target):
        client = SimpleNamespace(get_channel=lambda _: target, get_guild=lambda _: target)
        monkeypatch.setattr(advanced_search, "client", client)
        return target
    return install


@pytest.mark.asyncio
async def test_compact_search_bound_and_offset_do_not_skip_the_first_omitted_message(install_target):
    rows = [message(index, content="x" * 2000 + " important vulnerability " + "y" * 2000) for index in range(100, 200)]
    target = install_target(Target(rows))
    args = {"channel_id": "10", "query": "vulnerability", "limit": 100, "max_output_chars": 2000}
    page = await advanced_search._search_page(args)
    assert page["output_limited"] and page["has_more"]
    assert 0 < len(page["rows"]) < 100
    assert "vulnerability" in page["rows"][0]["text"]
    result = (await advanced_search.search_messages_advanced(args))[0].text
    assert len(result) <= 2000
    assert "c1=https://discord.com/channels/" in result
    assert "output_limited=true" in result
    next_page = await advanced_search._search_page({**args, "offset": page["next_offset"]})
    assert next_page["rows"][0]["key"][1] == rows[page["next_offset"]].id
    assert target.calls[0]["limit"] == 100


@pytest.mark.asyncio
async def test_duplicate_results_advance_offsets_without_duplicate_messages(install_target):
    one, two, three = (message(index, content="x" * 1000) for index in (100, 101, 102))
    install_target(Target([one, one, two, three]))
    page = await advanced_search._search_page({"channel_id": "10", "limit": 4, "max_output_chars": 2000})
    assert len({row["key"] for row in page["rows"]}) == len(page["rows"])
    if page["has_more"]:
        assert page["next_offset"] >= len(page["rows"])


@pytest.mark.asyncio
async def test_batch_deduplicates_overlapping_queries_and_preserves_query_matches(install_target):
    install_target(Target([message(100, content="crash exploit"), message(101, content="another crash exploit")]))
    result = await advanced_search.search_messages_batch({"guild_id": "1", "queries": ["crash", "exploit"]})
    payload = json.loads(result[0].text)
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["matched_queries"] == ["crash", "exploit"]
    assert [row["returned"] for row in payload["queries"]] == [2, 2]
    assert not payload["output_limited"]


@pytest.mark.asyncio
async def test_eight_broad_queries_share_one_output_budget_with_resumable_offsets(install_target):
    def rows(query):
        return [message(1000 + int(query) * 100 + i, content="a" * 2000) for i in range(30)]
    install_target(Target(rows))
    text = (await advanced_search.search_messages_batch({
        "guild_id": "1", "queries": [str(i) for i in range(8)], "limit_per_query": 30,
        "max_output_chars": 4000, "preview_chars": 400,
    }))[0].text
    assert len(text) <= 4000
    payload = json.loads(text)
    assert payload["output_limited"]
    assert len(payload["queries"]) == 8
    assert all(row["has_more"] and row["next_offset"] is not None for row in payload["queries"])
    assert any(row["next_offset"] == 0 for row in payload["queries"])
    refs = re.findall(r"^\d+ (u\d+) (c\d+) ", "\n".join(row["message"] for row in payload["messages"]), re.MULTILINE)
    assert {ref[0] for ref in refs} == set(re.findall(r"^(u\d+)=", payload["legend"], re.MULTILINE))
    assert {ref[1] for ref in refs} == set(re.findall(r"^(c\d+)=", payload["legend"], re.MULTILINE))


@pytest.mark.asyncio
async def test_batch_uses_one_legend_across_different_queries_and_channels(install_target):
    guild, _, _ = cached_guild()
    one = message(100, guild=guild)
    two = message(200, guild=guild)
    two.channel = SimpleNamespace(id=20, guild=guild)
    two.author = SimpleNamespace(id=500, name="second-user")
    install_target(Target(lambda query: [one] if query == "first" else [two]))
    payload = json.loads((await advanced_search.search_messages_batch({
        "guild_id": "1", "queries": ["first", "second"],
    }))[0].text)
    assert "u1=99 reader" in payload["legend"]
    assert "u2=500 second-user [role unknown]" in payload["legend"]
    assert "c1=https://discord.com/channels/1/10" in payload["legend"]
    assert "c2=https://discord.com/channels/1/20" in payload["legend"]
    assert payload["messages"][0]["message"].startswith("100 u1 c1 ")
    assert payload["messages"][1]["message"].startswith("200 u2 c2 ")
    assert "role_color" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_partial_batch_errors_are_explicit_and_all_failed_batch_is_error(install_target):
    def rows(query):
        if query == "fail":
            raise RuntimeError("Unavailable")
        return [message()]
    install_target(Target(rows))
    payload = json.loads((await advanced_search.search_messages_batch({
        "channel_id": "10", "queries": ["hello", "fail"],
    }))[0].text)
    assert payload["queries"][1]["error"].endswith("Unavailable")
    assert payload["partial_failure"]
    assert len(payload["messages"]) == 1
    with pytest.raises(RuntimeError, match="All batch searches failed"):
        await advanced_search.search_messages_batch({"channel_id": "10", "queries": ["fail"]})


def context_channel(anchor, parents=None, before=(), after=()):
    by_id = {anchor.id: anchor, **(parents or {})}
    channel = SimpleNamespace(fetch_message=AsyncMock(side_effect=lambda message_id: by_id[message_id]))
    def history(**kwargs):
        rows = before if "before" in kwargs else after
        async def iterate():
            for row in rows[:kwargs["limit"]]:
                yield row
        return iterate()
    channel.history = history
    return channel


@pytest.mark.asyncio
async def test_reply_chain_follows_distant_parents_with_a_depth_limit(install_target):
    anchor = message(100, reply=reference(50))
    parent = message(50, reply=reference(20))
    grandparent = message(20, reply=reference(10))
    channel = install_target(context_channel(anchor, {50: parent, 20: grandparent}))
    text = (await advanced_search.get_message_context({
        "channel_id": "10", "message_id": "100", "before_count": 0, "after_count": 0,
    }))[0].text
    assert "REPLY ANCESTORS" in text
    assert text.index("\n20 u1 c1 ") < text.index("\n50 u1 c1 ")
    assert [call.args[0] for call in channel.fetch_message.await_args_list] == [100, 50, 20]


@pytest.mark.parametrize("cached", ["window", "resolved", "disabled"])
@pytest.mark.asyncio
async def test_reply_chain_reuses_window_or_resolved_parent_and_can_be_disabled(install_target, cached):
    parent = message(50)
    anchor = message(100, reply=reference(50, resolved=parent if cached == "resolved" else None))
    channel = install_target(context_channel(anchor, before=[parent] if cached == "window" else []))
    text = (await advanced_search.get_message_context({
        "channel_id": "10", "message_id": "100",
        **({"reply_depth": 0} if cached == "disabled" else {}),
    }))[0].text
    channel.fetch_message.assert_awaited_once_with(100)
    if cached != "disabled":
        assert "\n50 u1 c1 " in text


@pytest.mark.asyncio
async def test_reply_cycle_stops_without_extra_fetch(install_target):
    parent = message(50, reply=reference(100))
    anchor = message(100, reply=reference(50, resolved=parent))
    channel = install_target(context_channel(anchor))
    text = (await advanced_search.get_message_context({"channel_id": "10", "message_id": "100", "reply_depth": 5}))[0].text
    assert "Reply cycle stopped" in text
    channel.fetch_message.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_deleted_parent_is_not_silently_treated_as_no_reply(install_target):
    anchor = message(100, reply=reference(50))
    channel = context_channel(anchor)
    async def fetch(message_id):
        if message_id == 50:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not found"), "Unknown Message")
        return anchor
    channel.fetch_message = AsyncMock(side_effect=fetch)
    install_target(channel)
    text = (await advanced_search.get_message_context({"channel_id": "10", "message_id": "100"}))[0].text
    assert "[TARGET MESSAGE]" in text and "Reply message_id=50: not found" in text


@pytest.mark.asyncio
async def test_context_output_budget_preserves_target_and_labels_trimmed_window(install_target):
    anchor = message(100, content="anchor " * 1000)
    channel = context_channel(
        anchor, before=[message(i, content="before " * 1000) for i in range(99, 49, -1)],
        after=[message(i, content="after " * 1000) for i in range(101, 151)],
    )
    install_target(channel)
    text = (await advanced_search.get_message_context({
        "channel_id": "10", "message_id": "100", "before_count": 50, "after_count": 50,
        "max_output_chars": 3000,
    }))[0].text
    assert len(text) <= 3000
    assert "[TARGET MESSAGE]" in text and "anchor " in text
    assert "Window trimmed by output budget" in text


@pytest.mark.asyncio
async def test_context_details_are_opt_in_and_preserve_reply_navigation(install_target):
    guild, _, _ = cached_guild()
    parent = message(50, guild=guild)
    anchor = message(100, guild=guild, reply=reference(50))
    install_target(context_channel(anchor, {50: parent}))
    args = {"channel_id": "10", "message_id": "100", "before_count": 0, "after_count": 0}
    compact = (await advanced_search.get_message_context(args))[0].text
    detailed = (await advanced_search.get_message_context({**args, "details": True}))[0].text
    assert compact.count("Moderator") == 1 and "->50:" in compact
    assert "\n50 u1 c1 " in compact and "role_color" not in compact
    assert "role_color=" in detailed and "reply_to=50" in detailed
    assert "url=https://discord.com/channels/1/10/100" in detailed


@pytest.mark.parametrize("tool", ["read_messages", "search_messages", "read_thread_messages"])
@pytest.mark.asyncio
async def test_history_tools_share_one_author_legend_and_support_details(monkeypatch, tool):
    guild, _, _ = cached_guild()
    rows = [message(100, content="hello", guild=guild), message(101, content="hello again", guild=guild)]
    class Channel:
        def __init__(self):
            self.guild = guild
        def history(self, **kwargs):
            async def iterate():
                for row in rows:
                    yield row
            return iterate()
    channel = Channel()
    client = SimpleNamespace(get_channel=lambda _: channel)
    monkeypatch.setattr(messages, "client", client)
    monkeypatch.setattr(threads, "client", client)
    monkeypatch.setattr(messages.discord.abc, "Messageable", Channel)
    monkeypatch.setattr(threads.discord, "Thread", Channel)
    monkeypatch.setattr(messages, "apply_rate_limit", AsyncMock())
    module = threads if tool == "read_thread_messages" else messages
    args = {"channel_id": "10", "thread_id": "10", "query": "hello", "limit": 2}
    handler = getattr(module, tool)
    compact = (await handler(args))[0].text
    detailed = (await handler({**args, "details": True}))[0].text
    assert compact.count("Moderator") == 1 and compact.count("reader") == 1
    assert "role_color" not in compact and "role_source" not in compact
    assert "role_color=" in detailed and "message_id=100" in detailed


@pytest.mark.parametrize("tool", ["read_messages", "search_messages", "read_thread_messages", "search_messages_advanced", "search_messages_batch", "get_message_context"])
def test_all_message_read_schemas_default_to_compact(tool):
    prop = registry.tools[tool].inputSchema["properties"]["details"]
    assert prop["type"] == "boolean" and prop["default"] is False


def test_unavailable_discrawl_tools_are_not_advertised(monkeypatch):
    monkeypatch.setattr(discrawl, "_binary_exists", lambda _: False)
    names = {tool.name for tool in registry.get_tool_definitions()}
    assert not any(name.startswith("discrawl_") or name == "run_discrawl" for name in names)
    monkeypatch.setattr(discrawl, "_binary_exists", lambda _: True)
    assert "discrawl_search" in {tool.name for tool in registry.get_tool_definitions()}


@pytest.mark.asyncio
async def test_direct_call_of_unavailable_tool_is_an_error():
    custom = ToolRegistry()
    @custom.register("missing", "test", {}, available=lambda: False)
    async def handler(arguments):
        pytest.fail("unavailable handler must not run")
    with pytest.raises(RuntimeError, match="unavailable"):
        await custom.call_tool("missing", {})
