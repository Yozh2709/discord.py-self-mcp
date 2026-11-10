import json
from datetime import timezone

import discord


def get_message_text(message: discord.Message) -> str:
    """Prefer clean content when available so mentions are readable."""
    clean_content = getattr(message, "clean_content", None)
    if clean_content:
        return clean_content
    return message.content or ""


def format_embed(embed: discord.Embed) -> str:
    """Format a Discord embed into readable text."""
    if not isinstance(embed, discord.Embed):
        return ""

    parts = []

    if embed.title:
        parts.append(f"[Title]: {embed.title}")

    if embed.author and embed.author.name:
        parts.append(f"[Author]: {embed.author.name}")

    if embed.description:
        parts.append(f"[Description]: {embed.description}")

    if embed.fields:
        for field in embed.fields:
            parts.append(f"[Field: {field.name}]: {field.value}")

    if embed.thumbnail and embed.thumbnail.url:
        parts.append(f"[Thumbnail]: {embed.thumbnail.url}")

    if embed.image and embed.image.url:
        parts.append(f"[Image]: {embed.image.url}")

    if embed.footer and embed.footer.text:
        parts.append(f"[Footer]: {embed.footer.text}")

    return "\n".join(parts)


def format_attachment(attachment: discord.Attachment, index: int | None = None) -> str:
    parts = []
    parts.append(f"[Attachment {index}]" if index is not None else "[Attachment]")
    parts.append(attachment.filename)

    if attachment.content_type:
        parts.append(f"type={attachment.content_type}")
    if attachment.size is not None:
        parts.append(f"size={attachment.size}")
    if getattr(attachment, "width", None) and getattr(attachment, "height", None):
        parts.append(f"dimensions={attachment.width}x{attachment.height}")

    parts.append(f"url={attachment.url}")
    return " ".join(parts)


def format_message_body(message: discord.Message) -> list[str]:
    parts = []
    content = get_message_text(message)
    if content:
        parts.append(content)

    for embed in message.embeds:
        embed_text = format_embed(embed)
        if embed_text:
            parts.append(f"[Embed]: {embed_text}")

    for index, attachment in enumerate(message.attachments):
        parts.append(format_attachment(attachment, index=index))

    if not parts:
        parts.append("[No content]")

    return parts


def get_reply_to_message_id(message: discord.Message):
    """Return the id of the message this one replies to, or None."""
    reference = getattr(message, "reference", None)
    return getattr(reference, "message_id", None) if reference else None


def author_role_info(message, *, details=False) -> dict:
    """Read member/role metadata already in the message or guild cache; no HTTP."""
    guild = getattr(message, "guild", None) or getattr(getattr(message, "channel", None), "guild", None)
    if guild is None:
        return {}
    author = getattr(message, "author", None)
    member = author if isinstance(author, discord.Member) else None
    source = "message_member"
    if member is None:
        get_member = getattr(guild, "get_member", None)
        member = get_member(getattr(author, "id", None)) if callable(get_member) else None
        source = "guild_cache"
    if member is None:
        return {"role_status": "uncached"}
    # A partial role cache must not incorrectly turn an unknown top role into @everyone.
    get_role = getattr(guild, "get_role", None)
    role_ids = getattr(member, "_roles", ())
    if callable(get_role) and any(get_role(role_id) is None for role_id in role_ids):
        return {"role_status": "uncached"}
    top_role = getattr(member, "top_role", None)
    if top_role is None:
        return {"role_status": "uncached"}
    if not details:
        return {"top_role": str(top_role.name)}
    role_colour = getattr(top_role, "colour", None)
    display_colour = getattr(member, "colour", None)
    return {
        "top_role": str(top_role.name),
        "top_role_id": str(top_role.id),
        "role_color": f"#{getattr(role_colour, 'value', 0):06x}",
        "display_color": f"#{getattr(display_colour, 'value', 0):06x}",
        "role_source": source,
    }


def text_preview(text: str, limit: int, query: str | None = None) -> str:
    if len(text) <= limit:
        return text
    start = 0
    if query:
        match = text.lower().find(query.lower())
        if match >= 0:
            start = max(0, match - limit // 3)
    start = min(start, max(0, len(text) - limit + 2))
    body = text[start:start + limit - 2]
    return ("…" if start else "") + body + "…"


def format_message_line(message: discord.Message, *, content_limit=None, query=None, details=False) -> str:
    author_name = message.author.name if message.author else "Unknown"
    header = f"message_id={message.id}"
    reply_to_id = get_reply_to_message_id(message)
    if reply_to_id is not None:
        header += f", reply_to={reply_to_id}"
    for key, value in author_role_info(message, details=details).items():
        header += f", {key}={json.dumps(value, ensure_ascii=False)}"
    body = " ".join(format_message_body(message))
    if content_limit is not None:
        preview = text_preview(body, content_limit, query)
        body = preview + (" [preview; use get_message_context]" if len(body) > content_limit else "")
    return f"{author_name} ({header}): " + body


DETAILS_SCHEMA = {
    "type": "boolean", "default": False,
    "description": "Full repeated metadata, role IDs, colours and message URLs. Default: compact shared author/channel legend.",
}


def detailed_output(arguments):
    value = arguments.get("details", False)
    if not isinstance(value, bool):
        raise ValueError("details must be a boolean")
    return value


class MessageFormatter:
    """A response-local legend avoids repeating author/role/channel metadata."""

    def __init__(self, *, details=False, channel_id=None, guild_id=None):
        self.details = details
        self.default_channel_id = channel_id
        self.default_guild_id = guild_id
        self.authors = {}
        self.channels = {}

    def clone(self):
        result = MessageFormatter(
            details=self.details, channel_id=self.default_channel_id, guild_id=self.default_guild_id,
        )
        result.authors = self.authors.copy()
        result.channels = self.channels.copy()
        return result

    def format(self, message, *, content_limit=None, query=None):
        channel = getattr(message, "channel", None)
        channel_id = str(getattr(channel, "id", None) or self.default_channel_id or "unknown")
        guild = getattr(message, "guild", None) or getattr(channel, "guild", None)
        guild_id = str(getattr(guild, "id", None) or getattr(channel, "_guild_id", None) or self.default_guild_id or "@me")
        base = f"https://discord.com/channels/{guild_id}/{channel_id}"
        created = getattr(message, "created_at", None)
        timestamp = created.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if created else "?"
        if self.details:
            return (
                f"channel_id={channel_id}, author_id={getattr(message.author, 'id', 'unknown')}, "
                f"timestamp={created.isoformat() if created else '?'}, url={base}/{message.id}\n"
                + format_message_line(message, content_limit=content_limit, query=query, details=True)
            )
        if channel_id not in self.channels:
            self.channels[channel_id] = (f"c{len(self.channels) + 1}", base)
        channel_ref = self.channels[channel_id][0]
        author = getattr(message, "author", None)
        user_id = getattr(author, "id", "unknown")
        key = (user_id, guild_id)
        if key not in self.authors:
            role = author_role_info(message)
            role_text = (
                f" [{json.dumps(role['top_role'], ensure_ascii=False)}]" if "top_role" in role
                else " [role unknown]" if role else ""
            )
            self.authors[key] = (
                f"u{len(self.authors) + 1}",
                f"{user_id} {getattr(author, 'name', 'Unknown')}{role_text}",
            )
        elif self.authors[key][1].endswith(" [role unknown]"):
            role = author_role_info(message)
            if "top_role" in role:
                self.authors[key] = (
                    self.authors[key][0],
                    f"{user_id} {getattr(author, 'name', 'Unknown')} [{json.dumps(role['top_role'], ensure_ascii=False)}]",
                )
        author_ref = self.authors[key][0]
        reply = get_reply_to_message_id(message)
        reply_text = f" ->{reply}" if reply is not None else ""
        body = " ".join(format_message_body(message))
        if content_limit is not None and len(body) > content_limit:
            body = text_preview(body, content_limit, query) + " [preview]"
        return f"{message.id} {author_ref} {channel_ref} {timestamp}{reply_text}: {body}"

    def header(self):
        if self.details:
            return ""
        channels = "\n".join(f"{ref}={base}" for ref, base in self.channels.values())
        authors = "\n".join(f"{ref}={name}" for ref, name in self.authors.values())
        return (
            f"channels:\n{channels}\nauthors (cached roles):\n{authors}\n"
            "rows: message_id author channel UTC_time [->reply_id]; message URL = channel URL/message_id"
        )

    def join(self, rows):
        header = self.header()
        return (header + "\n" if header and rows else "") + "\n".join(rows)


def build_search_text(message: discord.Message) -> str:
    searchable_parts = [get_message_text(message).lower()]

    for embed in message.embeds:
        embed_text = format_embed(embed)
        if embed_text:
            searchable_parts.append(embed_text.lower())

    for attachment in message.attachments:
        searchable_parts.append(attachment.filename.lower())
        if attachment.content_type:
            searchable_parts.append(attachment.content_type.lower())
        if getattr(attachment, "description", None):
            searchable_parts.append(attachment.description.lower())
        searchable_parts.append(attachment.url.lower())

    return " ".join(part for part in searchable_parts if part)


def serialize_attachment(attachment: discord.Attachment) -> dict:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "url": attachment.url,
        "content_type": attachment.content_type,
        "size": attachment.size,
        "width": getattr(attachment, "width", None),
        "height": getattr(attachment, "height", None),
        "description": getattr(attachment, "description", None),
    }


def serialize_message(message: discord.Message, *, details=False) -> dict:
    return {
        "id": message.id,
        "author": message.author.name if message.author else "Unknown",
        "content": get_message_text(message),
        "created_at": message.created_at.isoformat(),
        "reply_to": get_reply_to_message_id(message),
        **author_role_info(message, details=details),
        "attachments": [
            serialize_attachment(attachment) for attachment in message.attachments
        ],
    }
