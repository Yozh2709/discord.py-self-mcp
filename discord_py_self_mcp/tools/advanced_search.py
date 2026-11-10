import asyncio
from datetime import datetime, timezone
import json

import discord
from mcp.types import TextContent

from ..bot import client
from ..tool_utils import normalize_history_limit
from .embed import DETAILS_SCHEMA, MessageFormatter, detailed_output, get_reply_to_message_id
from .registry import registry


def _snowflake(value: object, name: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{name} must be a Discord ID")
    number = int(value)
    if not 0 < number < 2**64:
        raise ValueError(f"{name} must be a positive 64-bit Discord ID")
    return number


def _date_bound(value: object, name: str):
    if value is None:
        return None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return discord.Object(id=_snowflake(value, name))
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be YYYY-MM-DD, an ISO 8601 timestamp, or a message ID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD, an ISO 8601 timestamp, or a message ID") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bound_id(bound) -> int:
    if isinstance(bound, datetime):
        return discord.utils.time_snowflake(bound)
    return bound.id


def _integer(arguments, name, default, low, high):
    value = arguments.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


SEARCH_OUTPUT_SCHEMA = {
    "preview_chars": {"type": "integer", "minimum": 80, "maximum": 800, "default": 240},
    "max_output_chars": {"type": "integer", "minimum": 2000, "maximum": 16000, "default": 3500},
    "details": DETAILS_SCHEMA,
}


SEARCH_TOOL = dict(
    name="search_messages_advanced",
    description=(
        "Search Discord's indexed history by text, author and date range. "
        "Provide exactly one of channel_id or guild_id. Filters can be combined. "
        "Returns bounded previews with a shared author/role/channel legend and no colours by default. "
        "Full repeated metadata require details=true; roles use no member lookups. "
        "For multiple terms use search_messages_batch to deduplicate and share an output budget. "
        "Read a useful hit with get_message_context to expand its text and reply chain."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "channel_id": {
                "type": "string",
                "description": "Search this channel, DM, or thread; omit guild_id.",
            },
            "guild_id": {
                "type": "string",
                "description": "Search all accessible channels in this server; omit channel_id.",
            },
            "query": {
                "type": "string",
                "description": "Optional text. Omit to search only by author or dates. Use separate fields for filters.",
            },
            "author_id": {"type": "string", "description": "Only messages from this user ID."},
            "after": {
                "type": "string",
                "description": "Exclusive lower bound: YYYY-MM-DD, ISO 8601 timestamp, or message ID. Dates and timestamps without a timezone use UTC.",
            },
            "before": {
                "type": "string",
                "description": "Exclusive upper bound, same formats as after. To include a whole day, use the following day's date.",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            "offset": {
                "type": "integer", "minimum": 0, "maximum": 9975, "default": 0,
                "description": "Search-result offset for pagination; Discord limits deep search offsets.",
            },
            "oldest_first": {"type": "boolean", "default": False},
            **SEARCH_OUTPUT_SCHEMA,
        },
    },
)
async def _search_page(arguments: dict):
    try:
        channel_id = arguments.get("channel_id")
        guild_id = arguments.get("guild_id")
        if (channel_id is None) == (guild_id is None):
            raise ValueError("Provide exactly one of channel_id or guild_id")
        scope_name = "channel_id" if channel_id is not None else "guild_id"
        scope_id = _snowflake(channel_id if channel_id is not None else guild_id, scope_name)
        query = arguments.get("query")
        if query is not None and not isinstance(query, str):
            raise ValueError("query must be a string")
        author = arguments.get("author_id")
        author_id = _snowflake(author, "author_id") if author is not None else None
        after = _date_bound(arguments.get("after"), "after")
        before = _date_bound(arguments.get("before"), "before")
        if after is not None and before is not None and _bound_id(after) >= _bound_id(before):
            raise ValueError("after must be earlier than before")
        offset = arguments.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= 9975:
            raise ValueError("offset must be an integer between 0 and 9975")
        oldest_first = arguments.get("oldest_first", False)
        if not isinstance(oldest_first, bool):
            raise ValueError("oldest_first must be a boolean")
        limit = min(normalize_history_limit(arguments.get("limit")), 10000 - offset)
        preview_chars = _integer(arguments, "preview_chars", 240, 80, 800)
        max_output_chars = _integer(arguments, "max_output_chars", 3500, 2000, 16000)
        details = detailed_output(arguments)

        if channel_id is not None:
            target = client.get_channel(scope_id)
            if target is None:
                target = await client.fetch_channel(scope_id)
        else:
            target = client.get_guild(scope_id)
            if target is None:
                target = await client.fetch_guild(scope_id)
        if not callable(getattr(target, "search", None)):
            raise ValueError("This channel or server does not support native message search")

        kwargs = {"limit": limit, "offset": offset, "oldest_first": oldest_first}
        if query:
            kwargs["content"] = query
        if author_id is not None:
            kwargs["authors"] = [discord.Object(id=author_id)]
        if after is not None:
            kwargs["after"] = after
        if before is not None:
            kwargs["before"] = before

        # discord.py-self handles Discord's HTTP rate-limit headers and 429s.
        # Reads must not share the additional local cooldown used for writes.
        rows = []
        seen = set()
        scanned = 0
        characters = 0
        output_limited = False
        formatter = MessageFormatter(
            details=details, channel_id=scope_id if channel_id is not None else None,
            guild_id=scope_id if guild_id is not None else None,
        )
        async for message in target.search(**kwargs):
            key = (message.channel.id, message.id)
            if key in seen:
                scanned += 1
                continue
            candidate = formatter.clone()
            row = candidate.format(message, content_limit=preview_chars, query=query)
            needed = len(row) + len(candidate.header())
            if not rows and needed > max_output_chars - 512:
                smaller = max(40, preview_chars - (needed - max_output_chars + 512))
                row = candidate.format(message, content_limit=smaller, query=query)
            if characters + len(row) + len(candidate.header()) + 1 > max_output_chars - 512:
                if not rows:
                    raise ValueError("Result metadata exceeds max_output_chars; increase the output budget")
                output_limited = True
                break
            seen.add(key)
            formatter = candidate
            rows.append({"key": key, "text": row, "message": message, "offset_after": offset + scanned + 1})
            characters += len(row) + 1
            scanned += 1
        more = (output_limited or scanned == limit) and offset + scanned <= 9975
        return {
            "rows": rows, "offset": offset, "has_more": more,
            "next_offset": offset + scanned if more else None,
            "output_limited": output_limited, "preview_chars": preview_chars,
            "legend": formatter.header(),
        }
    except Exception as exc:
        raise RuntimeError(f"Error in native Discord search: {exc}") from None


@registry.register(**SEARCH_TOOL)
async def search_messages_advanced(arguments: dict):
    page = await _search_page(arguments)
    if not page["rows"]:
        return [TextContent(type="text", text="No matching messages found by native Discord search.")]
    header = (
        f"Native Discord search: {len(page['rows'])} result(s), offset={page['offset']}. "
        f"has_more={str(page['has_more']).lower()}, next_offset={page['next_offset']}, "
        f"output_limited={str(page['output_limited']).lower()}, preview_chars={page['preview_chars']}."
    )
    sections = [header, page["legend"], *(row["text"] for row in page["rows"])]
    return [TextContent(type="text", text="\n".join(section for section in sections if section))]


@registry.register(
    name="search_messages_batch",
    description=(
        "Search multiple terms with the same server/channel, author and date filters. "
        "Shares one bounded output budget, deduplicates messages and labels matching queries. "
        "Use this instead of printing many separate search responses. Open useful hits with "
        "get_message_context, including reply ancestors; each query has its own next_offset."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **{key: value for key, value in SEARCH_TOOL["input_schema"]["properties"].items()
               if key not in {"query", "limit", "preview_chars", "max_output_chars"}},
            "queries": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
            "limit_per_query": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
            "preview_chars": {"type": "integer", "minimum": 80, "maximum": 400, "default": 160},
            "max_output_chars": {"type": "integer", "minimum": 4000, "maximum": 20000, "default": 10000},
        },
        "required": ["queries"],
    },
)
async def search_messages_batch(arguments):
    queries = arguments.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 8:
        raise ValueError("queries must contain 1-8 search strings")
    if any(not isinstance(query, str) or not query.strip() or len(query) > 200 for query in queries):
        raise ValueError("Each query must contain 1-200 characters")
    queries = list(dict.fromkeys(query.strip() for query in queries))
    limit = _integer(arguments, "limit_per_query", 10, 1, 30)
    preview = _integer(arguments, "preview_chars", 160, 80, 400)
    budget = _integer(arguments, "max_output_chars", 10000, 4000, 20000)
    details = detailed_output(arguments)
    scope = {key: value for key, value in arguments.items()
             if key in SEARCH_TOOL["input_schema"]["properties"] and key not in {"preview_chars", "max_output_chars"}}
    pages = await asyncio.gather(*[
        _search_page({**scope, "query": query, "limit": limit, "preview_chars": preview})
        for query in queries
    ], return_exceptions=True)
    summaries = [
        {"query": query, "returned": 0, "has_more": False, "next_offset": None,
         **({"error": str(page)[:120]} if isinstance(page, Exception) else {})}
        for query, page in zip(queries, pages)
    ]
    if all(isinstance(page, Exception) for page in pages):
        raise RuntimeError("All batch searches failed: " + "; ".join(row["error"] for row in summaries))
    payload = {
        "queries": summaries, "messages": [], "output_limited": False,
        "partial_failure": any(isinstance(page, Exception) for page in pages), "legend": "",
    }
    formatter = MessageFormatter(details=details, channel_id=arguments.get("channel_id"), guild_id=arguments.get("guild_id"))
    by_key = {}
    blocked = set()
    encode = lambda: json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encode()) > budget - 512:
        raise ValueError("Query and error metadata exceed max_output_chars; shorten queries or increase the budget")
    max_rows = max((len(page["rows"]) for page in pages if not isinstance(page, Exception)), default=0)
    for index in range(max_rows):
        for query_index, (query, page) in enumerate(zip(queries, pages)):
            if isinstance(page, Exception) or query_index in blocked or index >= len(page["rows"]):
                continue
            row = page["rows"][index]
            existing = by_key.get(row["key"])
            candidate = None
            previous_legend = payload["legend"]
            if existing is None:
                candidate = formatter.clone()
                message_text = candidate.format(row["message"], content_limit=preview, query=query)
                record = {"matched_queries": [query], "message": message_text}
                payload["messages"].append(record)
                payload["legend"] = candidate.header()
            else:
                record = existing
                record["matched_queries"].append(query)
            if len(encode()) > budget - 512:
                if existing is None:
                    payload["messages"].pop()
                    payload["legend"] = previous_legend
                else:
                    record["matched_queries"].pop()
                blocked.add(query_index)
                payload["output_limited"] = True
                continue
            by_key[row["key"]] = record
            if candidate is not None:
                formatter = candidate
            summaries[query_index]["returned"] += 1
            summaries[query_index]["next_offset"] = row["offset_after"]
    for index, (summary, page) in enumerate(zip(summaries, pages)):
        if isinstance(page, Exception):
            continue
        if index in blocked:
            summary["has_more"] = True
            if summary["next_offset"] is None:
                summary["next_offset"] = page["offset"]
        else:
            summary["has_more"] = page["has_more"]
            summary["next_offset"] = page["next_offset"]
        payload["output_limited"] |= page["output_limited"]
    text = encode()
    if len(text) > budget:
        raise RuntimeError("Batch metadata exceed the output budget; retry with fewer queries")
    return [TextContent(type="text", text=text)]


@registry.register(
    name="get_message_context",
    description=(
        "Read a found message and nearby conversation in its channel, DM or thread. "
        "Use channel_id and message_id from a search result. Returns messages from "
        "all authors in chronological order and marks the target message. "
        "Also follows up to reply_depth parent messages (default 2, maximum 5), "
        "reusing resolved references and the window before fetching missing parents. "
        "Roles come only from message data or the guild cache."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel, DM or thread ID from a search result."},
            "message_id": {"type": "string", "description": "ID of the message to expand."},
            "before_count": {"type": "integer", "minimum": 0, "maximum": 50, "default": 10},
            "after_count": {"type": "integer", "minimum": 0, "maximum": 50, "default": 10},
            "reply_depth": {"type": "integer", "minimum": 0, "maximum": 5, "default": 2},
            "message_chars": {"type": "integer", "minimum": 100, "maximum": 8000, "default": 1000},
            "max_output_chars": {"type": "integer", "minimum": 3000, "maximum": 30000, "default": 12000},
            "details": DETAILS_SCHEMA,
        },
        "required": ["channel_id", "message_id"],
    },
)
async def get_message_context(arguments: dict):
    try:
        channel_id = _snowflake(arguments.get("channel_id"), "channel_id")
        message_id = _snowflake(arguments.get("message_id"), "message_id")
        counts = {}
        for name in ("before_count", "after_count"):
            count = arguments.get(name, 10)
            if type(count) is not int or not 0 <= count <= 50:
                raise ValueError(f"{name} must be an integer between 0 and 50")
            counts[name] = count
        reply_depth = _integer(arguments, "reply_depth", 2, 0, 5)
        budget = _integer(arguments, "max_output_chars", 12000, 3000, 30000)
        message_chars = min(_integer(arguments, "message_chars", 1000, 100, 8000), max(100, budget - 2400))
        details = detailed_output(arguments)

        channel = client.get_channel(channel_id)
        if channel is None:
            channel = await client.fetch_channel(channel_id)
        if not callable(getattr(channel, "fetch_message", None)) or not callable(getattr(channel, "history", None)):
            raise ValueError("This channel does not support message history")

        anchor = await channel.fetch_message(message_id)
        preceding = []
        following = []
        if counts["before_count"]:
            async for message in channel.history(limit=counts["before_count"], before=anchor, oldest_first=False):
                preceding.append(message)
        if counts["after_count"]:
            async for message in channel.history(limit=counts["after_count"], after=anchor, oldest_first=True):
                following.append(message)

        window = [*reversed(preceding), anchor, *following]
        known = {message.id: message for message in window}
        parents = []
        notes = []
        current = anchor
        seen = {anchor.id}
        for _ in range(reply_depth):
            parent_id = get_reply_to_message_id(current)
            if parent_id is None:
                break
            if parent_id in seen:
                notes.append(f"Reply cycle stopped at message_id={parent_id}.")
                break
            seen.add(parent_id)
            reference = current.reference
            parent = known.get(parent_id)
            if parent is None:
                resolved = getattr(reference, "resolved", None)
                if isinstance(resolved, discord.DeletedReferencedMessage):
                    notes.append(f"Reply message_id={parent_id}: deleted.")
                    break
                if getattr(resolved, "id", None) == parent_id:
                    parent = resolved
            parent_channel = getattr(reference, "channel_id", None) or channel_id
            if parent is None and parent_channel != channel_id:
                notes.append(f"Reply message_id={parent_id} is in channel_id={parent_channel}; open that channel separately.")
                break
            if parent is None:
                try:
                    parent = await channel.fetch_message(parent_id)
                except discord.NotFound:
                    notes.append(f"Reply message_id={parent_id}: not found or deleted.")
                    break
                except discord.Forbidden:
                    notes.append(f"Reply message_id={parent_id}: access denied.")
                    break
                except discord.HTTPException:
                    notes.append(f"Reply message_id={parent_id}: Discord could not return the parent.")
                    break
            if parent.id not in known:
                parents.append(parent)
                known[parent.id] = parent
            current = parent
        formatter = MessageFormatter(
            details=details, channel_id=channel_id,
            guild_id=getattr(getattr(channel, "guild", None), "id", None),
        )
        target_row = "[TARGET MESSAGE]\n" + formatter.format(anchor, content_limit=message_chars)
        remaining = budget - 1200 - len(target_row) - len(formatter.header())
        parent_rows = []
        for parent in parents:
            candidate = formatter.clone()
            row = candidate.format(parent, content_limit=message_chars)
            cost = len(row) + 2 + len(candidate.header()) - len(formatter.header())
            if cost <= remaining:
                parent_rows.append(row)
                remaining -= cost
                formatter = candidate
            else:
                notes.append(f"Reply message_id={parent.id} omitted by output budget; open it directly.")
        chosen_before = []
        chosen_after = []
        for index in range(max(len(preceding), len(following))):
            for source, chosen in ((preceding, chosen_before), (following, chosen_after)):
                if index < len(source):
                    candidate = formatter.clone()
                    row = candidate.format(source[index], content_limit=message_chars)
                    cost = len(row) + 2 + len(candidate.header()) - len(formatter.header())
                    if cost <= remaining:
                        chosen.append(row)
                        remaining -= cost
                        formatter = candidate
        rows = [*reversed(chosen_before), target_row, *chosen_after]
        header = (
            f"Message context: {len(chosen_before)} before, target, {len(chosen_after)} after. "
            "Chronological order; all authors included."
        )
        if len(chosen_before) < len(preceding) or len(chosen_after) < len(following):
            header += " Window trimmed by output budget; increase max_output_chars or request a smaller window."
        if parent_rows:
            rows.append("[REPLY ANCESTORS; oldest first]\n" + "\n\n".join(reversed(parent_rows)))
        if notes:
            rows.append("\n".join(notes))
        legend = formatter.header()
        return [TextContent(type="text", text=header + ("\n" + legend if legend else "") + "\n\n" + "\n\n".join(rows))]
    except discord.NotFound:
        raise RuntimeError("Message or channel not found; it may have been deleted.") from None
    except discord.Forbidden:
        raise RuntimeError("Access denied to this message or channel history.") from None
    except Exception as exc:
        raise RuntimeError(f"Error reading message context: {exc}") from None
