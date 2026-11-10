"""Bounded mutual-server/friend results from a single Discord profile request."""

import asyncio
from datetime import datetime, timezone
import json

import discord
from mcp.types import TextContent

from ..bot import account_manager, client
from ..tool_utils import NOT_READY_TEXT
from .advanced_search import _integer, _snowflake
from .registry import registry


def _section(rows, *, enabled, limited, reported_count=None):
    if not enabled:
        status, count = "not_requested", None
    elif limited:
        status, count = "limited", None
    elif rows is None:
        status = "count_only" if reported_count is not None else "unavailable"
        count = reported_count
    else:
        count = len(rows) if reported_count is None else reported_count
        status = "partial" if count != len(rows) else "available"
        if count < len(rows):
            count = None
    section = {"status": status, "count": count, "items": [], "next_offset": None}
    if rows is not None and status in {"partial", "limited"}:
        section["available_count"] = len(rows)
    return section


def _guild_row(guild):
    cached = client.get_guild(guild.id)
    return {"id": str(guild.id), "name": getattr(cached, "name", None)}


def _friend_row(user):
    row = {"id": str(user.id), "name": user.name}
    display = getattr(user, "global_name", None)
    if display and display != user.name:
        row["display_name"] = display
    return row


@registry.register(
    name="get_user_mutuals",
    description=(
        "Get mutual servers and mutual friends with a user relative to the ACTIVE Discord account. "
        "Uses one profile API request; guild names use cache only, with no per-member/server requests. "
        "Returns bounded lists, counts and separate continuation offsets. Missing/private data are "
        "marked unavailable/limited, never assumed to mean zero; profile access errors are MCP errors."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "User ID, for example an author ID from chat."},
            "include_guilds": {"type": "boolean", "default": True},
            "include_friends": {"type": "boolean", "default": True},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20,
                      "description": "Maximum entries per list."},
            "guild_offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
            "friend_offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
            "max_output_chars": {"type": "integer", "minimum": 2000, "maximum": 16000, "default": 6000},
        },
        "required": ["user_id"],
    },
)
async def get_user_mutuals(arguments):
    user_id = _snowflake(arguments.get("user_id"), "user_id")
    include_guilds = arguments.get("include_guilds", True)
    include_friends = arguments.get("include_friends", True)
    if not isinstance(include_guilds, bool) or not isinstance(include_friends, bool):
        raise ValueError("include_guilds and include_friends must be booleans")
    if not include_guilds and not include_friends:
        raise ValueError("Enable include_guilds or include_friends")
    limit = _integer(arguments, "limit", 20, 1, 100)
    guild_offset = _integer(arguments, "guild_offset", 0, 0, 10000)
    friend_offset = _integer(arguments, "friend_offset", 0, 0, 10000)
    budget = _integer(arguments, "max_output_chars", 6000, 2000, 16000)
    if not client.is_ready():
        raise RuntimeError(NOT_READY_TEXT)
    viewer = {"account": account_manager.active_account, "id": str(client.user.id)}
    try:
        profile = await asyncio.wait_for(client.fetch_user_profile(
            user_id,
            with_mutual_guilds=include_guilds,
            with_mutual_friends=include_friends,
            with_mutual_friends_count=include_friends,
        ), timeout=30)
    except discord.NotFound as exc:
        raise RuntimeError(
            f"Profile unavailable to the active account (HTTP {exc.status}, code {exc.code}); "
            "the user may be missing or inaccessible. Mutuals are unknown."
        ) from None
    except discord.Forbidden as exc:
        raise RuntimeError(
            f"Discord denied profile access (HTTP {exc.status}, code {exc.code}); mutuals are unknown."
        ) from None
    except discord.HTTPException as exc:
        raise RuntimeError(f"Discord profile request failed (HTTP {exc.status}, code {exc.code}); mutuals are unknown.") from None
    except asyncio.TimeoutError:
        raise RuntimeError("Discord profile request timed out; mutuals are unknown.") from None
    if str(profile.id) != str(user_id):
        raise RuntimeError("Discord returned a different user profile; mutuals could not be verified.")
    limited = bool(getattr(profile, "_blocked", False))
    guilds = getattr(profile, "mutual_guilds", None) if include_guilds else None
    friends = getattr(profile, "mutual_friends", None) if include_friends else None
    friend_count = getattr(profile, "mutual_friends_count", None) if include_friends else None
    if friend_count is not None and (type(friend_count) is not int or friend_count < 0):
        raise RuntimeError("Discord returned an invalid mutual friend count.")
    payload = {
        "user": {"id": str(profile.id), "name": profile.name},
        "viewer": viewer,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guilds": _section(guilds, enabled=include_guilds, limited=limited),
        "friends": _section(friends, enabled=include_friends, limited=limited, reported_count=friend_count),
        "output_limited": False,
    }
    if limited:
        payload["profile_visibility"] = "limited"
    encode = lambda: json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encode()) > budget - 256:
        raise RuntimeError("Profile metadata exceeds the output budget.")
    sections = [
        (payload["guilds"], guilds, guild_offset, _guild_row),
        (payload["friends"], friends, friend_offset, _friend_row),
    ]
    blocked = set()
    for index in range(limit):
        for section_index, (section, rows, offset, render) in enumerate(sections):
            if rows is None or section_index in blocked or offset + index >= len(rows):
                continue
            section["items"].append(render(rows[offset + index]))
            if len(encode()) > budget - 256:
                section["items"].pop()
                blocked.add(section_index)
                payload["output_limited"] = True
    for section, rows, offset, _ in sections:
        next_offset = offset + len(section["items"])
        if rows is not None and next_offset < len(rows):
            section["next_offset"] = next_offset
    text = encode()
    if len(text) > budget:
        raise RuntimeError("Mutual profile data exceed the output budget; increase max_output_chars.")
    return [TextContent(type="text", text=text)]
