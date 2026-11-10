import asyncio
import json
import math

import discord
from discord.http import Route
from mcp.types import TextContent

from ..bot import client
from ..tool_utils import NOT_READY_TEXT
from .advanced_search import _snowflake
from .registry import registry


@registry.register(
    name="search_forum_topics",
    description=(
        "Search a Discord forum's topic titles by keyword, including active and archived "
        "posts by default. Uses one indexed search request, not a cache scan. Returns "
        "titles, links, thread IDs, first-post previews, total matches and pagination. "
        "Read a result with read_thread_messages(thread_id) or get_message_context."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "forum_id": {"type": "string", "description": "Forum channel ID from list_channels."},
            "query": {"type": "string", "minLength": 1, "maxLength": 100, "description": "Text to search for in topic titles, such as fly."},
            "archived": {"type": "boolean", "description": "Omit for both active and archived topics; true for archived only; false for active only."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
            "offset": {"type": "integer", "minimum": 0, "maximum": 9975, "default": 0},
        },
        "required": ["forum_id", "query"],
    },
)
async def search_forum_topics(arguments: dict):
    forum_id = _snowflake(arguments.get("forum_id"), "forum_id")
    query = arguments.get("query")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
        raise ValueError("query must contain 1 to 100 characters")
    query = query.strip()
    limit = arguments.get("limit", 10)
    offset = arguments.get("offset", 0)
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError("limit must be an integer between 1 and 25")
    if type(offset) is not int or not 0 <= offset <= 9975:
        raise ValueError("offset must be an integer between 0 and 9975")
    if "archived" in arguments and type(arguments["archived"]) is not bool:
        raise ValueError("archived must be a boolean, or omit it to include both states")
    if not client.is_ready():
        raise RuntimeError(NOT_READY_TEXT)

    forum = client.get_channel(forum_id)
    if forum is None:
        forum = await client.fetch_channel(forum_id)
    if not isinstance(forum, discord.ForumChannel):
        raise ValueError("forum_id must identify a forum channel; use search_messages_advanced for message contents")

    params = {
        "name": query,
        "sort_by": "last_message_time",
        "sort_order": "desc",
        "limit": limit,
        "offset": offset,
    }
    if "archived" in arguments:
        params["archived"] = "true" if arguments["archived"] else "false"
    route = Route("GET", "/channels/{channel_id}/threads/search", channel_id=forum_id)
    # HTTPClient honors Discord's real rate-limit headers, 429s and 202 indexing
    # responses. Also handle old API responses that report indexing with HTTP 200.
    for attempt in range(3):
        data = await client.http.request(route, params=params)
        if not isinstance(data, dict):
            raise RuntimeError("Discord returned an invalid forum search response")
        if data.get("code") != 110000:
            break
        delay = float(data.get("retry_after", 2))
        if attempt == 2 or not math.isfinite(delay) or not 0 <= delay <= 10:
            raise RuntimeError("Discord's forum search index is not ready; try again later")
        await asyncio.sleep(delay)

    if not isinstance(data.get("threads"), list) or type(data.get("has_more")) is not bool:
        raise RuntimeError("Discord forum search response is missing results or pagination metadata")
    previews = {str(message.get("channel_id")): message for message in data.get("first_messages", [])}
    results = []
    guild_id = str(forum.guild.id)
    for thread in data["threads"]:
        thread_id = str(thread["id"])
        first = previews.get(thread_id, {})
        content = first.get("content") or ""
        row = {
            "title": thread["name"],
            "thread_id": thread_id,
            "forum_id": str(forum_id),
            "guild_id": guild_id,
            "url": f"https://discord.com/channels/{guild_id}/{thread_id}",
            "archived": thread.get("thread_metadata", {}).get("archived"),
            "message_count": thread.get("message_count"),
            "preview": content[:400] if first else None,
            "preview_truncated": len(content) > 400,
        }
        if first:
            row["starter_message_id"] = str(first["id"])
            row["attachment_names"] = [item.get("filename") for item in first.get("attachments", [])][:3]
        results.append(row)
    next_offset = offset + len(results)
    payload = {
        "forum_id": str(forum_id),
        "query": query,
        "total_results": data.get("total_results"),
        "returned": len(results),
        "offset": offset,
        "has_more": data["has_more"],
        "next_offset": next_offset if data["has_more"] and results and next_offset <= 9975 else None,
        "results": results,
    }
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
