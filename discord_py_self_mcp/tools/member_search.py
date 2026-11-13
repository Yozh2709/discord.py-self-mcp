"""Bounded live member discovery, independent of message history."""
import asyncio
from datetime import datetime, timezone
from itertools import islice
import json
import re
import unicodedata

import discord
from mcp.types import TextContent

from ..bot import client
from ..tool_utils import NOT_READY_TEXT
from .advanced_search import _integer, _snowflake
from .registry import registry

QUERY_LIMIT = 100
CACHE_SCAN_LIMIT = 10000
SEARCH_TIMEOUT = 20
QUERY_TIMEOUT = 8


def _fold(value):
    return unicodedata.normalize("NFKC", value).casefold()


def _name_key(value):
    return "".join(char for char in _fold(value) if char.isalnum())


def _probes(query):
    key = _name_key(query)
    words = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    candidates = [query]
    if words and len(words[0]) >= 2:
        candidates.append(words[0])
    candidates.extend((key[:5], key[:2]))
    result = []
    seen = set()
    for candidate in candidates:
        folded = _fold(candidate)
        if folded not in seen and len(_name_key(candidate)) >= 2:
            seen.add(folded)
            result.append(candidate)
    return result[:3]


def _match(member, query, key):
    ranks, fields = [], []
    for field, value in (
        ("username", member.name), ("nickname", getattr(member, "nick", None)),
        ("global_name", getattr(member, "global_name", None)),
        ("display_name", getattr(member, "display_name", None)),
    ):
        if not value:
            continue
        folded, normalized = _fold(value), _name_key(value)
        rank = (0 if folded == query else 1 if normalized == key else
                2 if folded.startswith(query) else 3 if normalized.startswith(key) else
                4 if query in folded else 5 if key in normalized else None)
        if rank is not None:
            fields.append(field)
            ranks.append(rank)
    return (min(ranks), fields) if ranks else None


def _row(member, match):
    return {
        "user_id": str(member.id), "username": member.name,
        "display_name": getattr(member, "display_name", member.name),
        "nickname": getattr(member, "nick", None),
        "global_name": getattr(member, "global_name", None),
        "is_member": True, "matched_fields": match[1],
        "match": ("exact", "normalized_exact", "prefix", "normalized_prefix", "contains", "normalized_contains")[match[0]],
    }


@registry.register(
    name="search_guild_members",
    description=(
        "Find CURRENT server members by username, global display name or server nickname, without searching messages. "
        "Uses live Discord Gateway prefix queries and compares names ignoring case, dots, spaces and underscores. "
        "For example, breakthezeros can discover break.the.zeros via a short prefix. "
        "At most 3 name queries (100 candidates each), plus one batched verification of matching cached candidates; "
        "no per-member HTTP requests or full member scraping. Cache-only hits are never reported as current members. "
        "Discovery is partial: no results does NOT prove absence, and normalization only applies to discovered candidates. "
        "No transliteration or historical-name lookup. Use get_guild_member for a known user ID."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "guild_id": {"type": "string", "description": "Server ID accessible to the active account."},
            "query": {"type": "string", "minLength": 2, "maxLength": 100,
                      "description": "Name or prefix; at least 2 letters/digits. Dots, spaces and underscores are ignored when comparing candidates."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "max_output_chars": {"type": "integer", "minimum": 2000, "maximum": 12000, "default": 5000},
        },
        "required": ["guild_id", "query"],
    },
)
async def search_guild_members(arguments):
    guild_id = _snowflake(arguments.get("guild_id"), "guild_id")
    query = arguments.get("query")
    if not isinstance(query, str):
        raise ValueError("query must be a name or prefix")
    query = unicodedata.normalize("NFKC", query).strip().removeprefix("@").strip()
    key = _name_key(query)
    if not 2 <= len(query) <= 100 or len(key) < 2:
        raise ValueError("query must contain at least 2 letters/digits and at most 100 characters")
    limit = _integer(arguments, "limit", 10, 1, 50)
    budget = _integer(arguments, "max_output_chars", 5000, 2000, 12000)
    if not client.is_ready():
        raise RuntimeError(NOT_READY_TEXT)
    guild = client.get_guild(guild_id)
    if guild is None:
        raise RuntimeError("Server is not available to the active account")
    folded = _fold(query)
    deadline = asyncio.get_running_loop().time() + SEARCH_TIMEOUT
    fresh, attempted, errors = {}, [], []
    request_count, verified_cache = 0, 0
    candidate_limit_reached = False

    def ranked():
        matches = [(member, match) for member in fresh.values() if (match := _match(member, folded, key)) is not None]
        return sorted(matches, key=lambda item: (item[1][0], _fold(item[0].name), item[0].id))

    async def request(**kwargs):
        nonlocal request_count
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        request_count += 1
        return await asyncio.wait_for(guild.query_members(
            **kwargs, limit=QUERY_LIMIT, presences=False, cache=False, subscribe=False,
        ), timeout=min(QUERY_TIMEOUT, remaining))

    try:
        for probe in _probes(query):
            attempted.append(probe)
            members = await request(query=probe)
            candidate_limit_reached |= len(members) >= QUERY_LIMIT
            fresh.update((member.id, member) for member in members)
            matches = ranked()
            if any(match[0] <= 1 for _, match in matches) or len(matches) >= limit:
                break

        matches = ranked()
        if not any(match[0] <= 1 for _, match in matches) and len(matches) < limit:
            # Local cache is only a discovery aid; verify all extra IDs together.
            cached = list(islice(getattr(guild, "members", ()), CACHE_SCAN_LIMIT + 1))
            candidate_limit_reached |= len(cached) > CACHE_SCAN_LIMIT
            candidates = [(member, match) for member in cached[:CACHE_SCAN_LIMIT]
                          if member.id not in fresh and (match := _match(member, folded, key)) is not None]
            candidates.sort(key=lambda item: (item[1][0], item[0].id))
            candidate_limit_reached |= len(candidates) > QUERY_LIMIT
            if candidates:
                ids = [member.id for member, _ in candidates[:QUERY_LIMIT]]
                members = await request(user_ids=ids)
                verified_cache = len(members)
                # Recheck the names from the fresh response, not stale cache names.
                fresh.update((member.id, member) for member in members if member.id in ids)
    except asyncio.TimeoutError:
        errors.append("Member query timed out; discovery is incomplete")
    except discord.DiscordException as exc:
        errors.append(f"Discord member query failed ({type(exc).__name__}); discovery is incomplete")

    matches = ranked()
    if errors and not matches:
        raise RuntimeError(errors[0])
    payload = {
        "guild_id": str(guild_id), "query": query, "source": "discord_gateway",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "queries": attempted, "gateway_requests": request_count,
        "verified_cache_candidates": verified_cache, "returned": 0,
        "search_complete": False, "candidate_limit_reached": candidate_limit_reached,
        "more_matches_known": False, "output_limited": False, "partial_failure": bool(errors),
        "note": "Bounded prefix discovery; no matches does not prove absence. Known IDs can be checked with get_guild_member.",
        "matches": [],
    }
    if errors:
        payload["errors"] = errors
    encode = lambda: json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for member, match in matches[:limit]:
        payload["matches"].append(_row(member, match))
        if len(encode()) > budget - 100:
            payload["matches"].pop()
            payload["output_limited"] = True
            break
    payload["returned"] = len(payload["matches"])
    payload["more_matches_known"] = len(matches) > payload["returned"]
    return [TextContent(type="text", text=encode())]
