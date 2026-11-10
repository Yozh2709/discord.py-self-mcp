from datetime import datetime, timezone
import json

import discord
from mcp.types import TextContent

from ..bot import client
from ..tool_utils import NOT_READY_TEXT
from .advanced_search import _snowflake
from .registry import registry


async def fetch_member_status(guild, user_id: int):
    """Return member/status/error using Discord, never a cache-only conclusion."""
    try:
        member = await guild.fetch_member(user_id)
    except discord.NotFound as exc:
        if exc.code == 10007:  # Unknown Member, not Unknown Guild or Unknown User.
            return None, "absent", None
        return None, "unknown", f"Discord returned HTTP {exc.status}, code {exc.code}; membership could not be verified"
    except discord.Forbidden:
        return None, "unknown", "Access denied; membership could not be verified"
    except discord.HTTPException as exc:
        return None, "unknown", f"Discord returned HTTP {exc.status}, code {exc.code}; membership could not be verified"
    if member is None:
        return None, "unknown", "Discord returned no member data"
    return member, "present", None


@registry.register(
    name="get_guild_member",
    description=(
        "Check a user's CURRENT server membership by user ID, querying Discord's API "
        "even if the member is cached. Returns present, absent or unknown and is_member "
        "true, false or null. Only Discord Unknown Member (10007) means absent; access "
        "errors mean unknown. Historical messages and cache misses do not prove current membership."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "guild_id": {"type": "string", "description": "Server ID."},
            "user_id": {"type": "string", "description": "Stable user ID, for example author_id from search results."},
        },
        "required": ["guild_id", "user_id"],
    },
)
async def get_guild_member(arguments: dict):
    guild_id = _snowflake(arguments.get("guild_id"), "guild_id")
    user_id = _snowflake(arguments.get("user_id"), "user_id")
    if not client.is_ready():
        raise RuntimeError(NOT_READY_TEXT)
    payload = {
        "guild_id": str(guild_id),
        "user_id": str(user_id),
        "source": "discord_api",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    guild = client.get_guild(guild_id)
    if guild is None:
        try:
            guild = await client.fetch_guild(guild_id)
        except discord.HTTPException as exc:
            payload.update(status="unknown", is_member=None, error=f"Cannot access server: HTTP {exc.status}, Discord code {exc.code}")
            return [TextContent(type="text", text=json.dumps(payload))]

    member, status, error = await fetch_member_status(guild, user_id)
    payload.update(status=status, is_member=True if status == "present" else False if status == "absent" else None)
    if error:
        payload["error"] = error
    if member is not None:
        joined_at = getattr(member, "joined_at", None)
        payload.update(
            username=member.name,
            display_name=getattr(member, "display_name", member.name),
            nickname=getattr(member, "nick", None),
            joined_at=joined_at.isoformat() if joined_at else None,
            bot=getattr(member, "bot", False),
            role_ids=[str(role.id) for role in getattr(member, "roles", [])],
        )
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
