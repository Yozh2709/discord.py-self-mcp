<p align="center">
  <img src="./logo.png" alt="discord-py-self-mcp" width="100">
</p>

<h1 align="center">discord-py-self-mcp</h1>

<p align="center">
  comprehensive discord selfbot mcp server for full user autonomy.
</p>

<p align="center">
  <a href="https://github.com/Microck/discord.py-self-mcp/releases"><img src="https://img.shields.io/github/v/release/Microck/discord.py-self-mcp?display_name=tag&style=flat-square&label=release&color=000000" alt="release"></a>
  <a href="https://www.npmjs.com/package/discord-selfbot-mcp"><img src="https://flat.badgen.net/npm/dt/discord-selfbot-mcp?label=downloads&color=000000" alt="npm downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-mit-000000?style=flat-square" alt="license"></a>
</p>

<p align="center">
<video src="https://github.com/user-attachments/assets/d7d9fc9f-c466-49c0-a666-05bed2fa8ca9
" controls preload="auto" width="100%" style="border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 800px;"></video>
</p>

---

## this fork

Fork of [Microck/discord.py-self-mcp](https://github.com/Microck/discord.py-self-mcp)
with indexed and batch search, reply context, forum search, saved accounts and
switching, mutual friends/servers, verified membership, member name search, required typing duration
and compact message output. Saved accounts use Windows DPAPI.

[Инструкция на русском](README-FORK-RU.md)

Install this fork from source on Windows:

~~~powershell
git clone --branch codex/discord-mcp-enhancements https://github.com/Yozh2709/discord.py-self-mcp.git
cd discord.py-self-mcp
python -m venv .venv
.venv\Scripts\python.exe -m pip install .
~~~

Configure your MCP client to run the checkout's Python with
args: -m discord_py_self_mcp.main and a DISCORD_TOKEN environment variable.
The saved profile selected through switch_account is reused on future starts.
The npm package and release links below refer to the upstream project.
This fork has not been published as a separate npm package.

`search_guild_members(guild_id, query)` discovers current members by username,
global name or server nickname without searching message history. Name comparison
ignores case and punctuation; bounded Gateway prefix queries can discover dotted
usernames from a dotless query. Matching cache candidates are verified together,
with no per-member HTTP calls. Discovery is partial, so no matches never proves
absence. Use `get_guild_member` when the user ID is known.

## quick start

this is a local mcp server (stdio transport). your mcp client spawns it as a process, and you provide secrets (like `DISCORD_TOKEN`) via the client's `env`/`environment` config.

manual run:

```bash
DISCORD_TOKEN="your_discord_token_here" python3 -m discord_py_self_mcp.main
```

> **important:** automating user accounts is against the Discord ToS. use this at your own risk.

---

### overview

discord-py-self-mcp acts as a bridge between your ai assistant (Claude Code, OpenCode, Codex, etc) and your personal discord account. unlike standard bots, this "selfbot" runs as you; allowing your ai to read your dms, reply to friends, manage your servers, and interact with buttons/menus just like a human user.

built on the <a href="https://github.com/dolfies/discord.py-self">discord.py-self</a> library by dolfies.

---

### quick installation

paste this into your llm agent session:

```
Install and configure discord-selfbot-mcp by following the instructions here:
https://raw.githubusercontent.com/Microck/discord.py-self-mcp/refs/heads/master/INSTALL.md
```

**npm (recommended)**

```bash
npm install -g discord-selfbot-mcp
discord-selfbot-mcp-setup
```

---

### manual installation

**prerequisites**:
- python 3.10+
- `uv` (recommended) or `pip`
- **voice support (linux only)**: `libffi-dev` (or `libffi-devel`), `python-dev` (e.g. `python3-dev`)

**install**:

```bash
uv tool install git+https://github.com/Microck/discord.py-self-mcp.git
# or
pip install git+https://github.com/Microck/discord.py-self-mcp.git
```

> **note**: voice dependencies (PyNaCl) are included by default. on linux, ensure system packages are installed first.

---

### npm installation (node.js wrapper)

**prerequisites**:
- node.js 18+
- python 3.10+

**install**:

```bash
npm install -g discord-selfbot-mcp
```

the npm package is a wrapper that uses the underlying python implementation.

---

### how it works (setup wizard)

run the interactive setup script to extract your token and generate the mcp config json (it can also write to common client config files and creates a backup before editing).

```bash
# if using npm
discord-selfbot-mcp-setup

# if using python (uv/pip)
python3 -m discord_py_self_mcp.setup
```

1. **extract token**: grabs your token from an open browser session (playwright) or via manual entry
2. **generate config**: prints the mcp configuration json (and can write it to your client config)
3. **configure**: paste the config into your mcp client settings

---

### manual configuration

for the default `stdio` transport, configure the server as a local command and pass the token via `env` (not `url`/`headers`).

examples:
- `mcp.example.json`
- `mcp.python.example.json`
- `.env.example`

**npm wrapper (recommended)**:

```json
{
  "mcpServers": {
    "discord-py-self": {
      "command": "discord-selfbot-mcp",
      "env": {
        "DISCORD_TOKEN": "${DISCORD_TOKEN}"
      }
    }
  }
}
```

**python (uv tool)**:

```json
{
  "mcpServers": {
    "discord-py-self": {
      "command": "uv",
      "args": ["tool", "run", "discord-py-self-mcp"],
      "env": {
        "DISCORD_TOKEN": "${DISCORD_TOKEN}"
      }
    }
  }
}
```

**python (pip / venv)**:

```json
{
  "mcpServers": {
    "discord-py-self": {
      "command": "python3",
      "args": ["-m", "discord_py_self_mcp.main"],
      "env": {
        "DISCORD_TOKEN": "${DISCORD_TOKEN}"
      }
    }
  }
}
```

> if your client does not expand `${DISCORD_TOKEN}`, replace it with the literal token value.

### streamable HTTP transport

The default transport is stdio. For clients or local services that need a
persistent endpoint, start the same MCP server with Streamable HTTP instead:

```bash
python3 -m discord_py_self_mcp.main --transport streamable-http --host 127.0.0.1 --port 7781
```

This exposes the MCP endpoint at `http://127.0.0.1:7781/mcp`. The listener is
localhost-only by default; place an authenticated reverse proxy or tunnel in
front of it if remote access is required. `MCP_TRANSPORT`, `MCP_HOST`, and
`MCP_PORT` provide equivalent environment-based configuration.

---

### features

powered by the robust `discord.py-self` library.

| category | tools | description |
|----------|-------|-------------|
| **system** | 2 | get_user_info, list_guilds |
| **accounts** | 3 | list_accounts, save_account, switch_account |
| **messages** | 9 | send_message, read_messages, search_messages, search_messages_advanced, search_messages_batch, get_message_context, edit_message, delete_message, get_message_attachments |
| **forum search** | 1 | search_forum_topics |
| **member lookup** | 1 | get_guild_member |
| **mutuals** | 1 | get_user_mutuals |
| **channels** | 3 | create_channel, delete_channel, list_channels (bulk and compact summary modes) |
| **dms** | 2 | list_dm_channels, list_unread_dms |
| **pings** | 2 | list_pings, mark_message_read |
| **voice** | 2 | join_voice_channel, leave_voice_channel |
| **relationships** | 4 | list_friends, send_friend_request, add_friend, remove_friend |
| **presence** | 2 | set_status, set_activity |
| **interactions** | 8 | send_slash_command, click_button, select_menu, submit_modal, list_ephemeral_messages, list_application_commands, send_user_command, send_message_command |
| **threads** | 5 | create_thread, send_thread_message, list_active_threads, read_thread_messages, archive_thread |
| **members** | 5 | kick_member, ban_member, unban_member, add_role, remove_role |
| **roles** | 6 | list_roles, get_role, create_role, edit_role, delete_role, reorder_roles |
| **permissions** | 7 | set_role_permissions, get_channel_permissions, set_channel_permissions, patch_channel_permissions, remove_channel_permissions, set_category_permissions, inspect_effective_permissions |
| **invites** | 3 | create_invite, list_invites, delete_invite |
| **profile** | 1 | edit_profile |
| **server folders** | 6 | list_server_folders, create_server_folder, move_server_to_folder, rename_server_folder, reorder_server_folders, apply_server_folder_layout |
| **server discovery** | 3 | get_server_overviews, sample_server_content, analyze_server_sidebar |
| **reactions** | 2 | add_reaction, remove_reaction |
| **discrawl** | 7 | run_discrawl, discrawl_doctor, discrawl_status, discrawl_sync, discrawl_search, discrawl_messages, discrawl_mentions |

### roles and permissions

`list_roles` returns every role as JSON (id, name, color, position, permission
bitfield) sorted highest-first. Run it before any restructuring — `position` is
guild-wide, so moving one role reindexes the others and the dump is your only
way back.

`create_role` and `edit_role` take `color` as a hex string (`#5865F2`) or an
integer, and `permissions` as either a raw bitfield string or a list of flag
names (`["manage_roles", "kick_members"]`). `edit_role` only touches the fields
you pass. `reorder_roles` moves several roles in one call and falls back to
sequential edits when the bulk endpoint is unavailable.

Role edits are bounded by hierarchy: your account cannot change a role at or
above your own highest role. Discord answers that with a bare 403, so these
tools check position locally first and say which role is blocking. Guild owners
are exempt.

`set_channel_permissions` replaces an overwrite wholesale, so any flag you do
not pass is lost. When an overwrite already exists and you only mean to change
one flag, use `patch_channel_permissions` — it takes a map of flag to
true/false/null and leaves everything else in that entry untouched. Because a
wholesale write with neither `allow` nor `deny` would quietly wipe the entry,
both setters require at least one of the two and reject a flag listed in both;
`remove_channel_permissions` is the way to drop an overwrite on purpose.

Role moves are checked twice before anything is sent: the role must sit below
your own highest role, and so must the position you are moving it to. Both are
compared with discord's own role ordering rather than raw position numbers,
since positions can tie and are broken by id.

For channel access, `set_channel_permissions` writes one overwrite and
`set_category_permissions` writes the category plus, by default, every channel
inside it (`sync_children: false` to skip). `inspect_effective_permissions`
resolves a role or member against every channel and reports what they can
actually see — useful for checking a change landed the way you meant.

Flag names are accepted in either spelling on input, but the `allowed` /
`denied` lists in JSON output use discord.py-self's canonical names — so
`view_channel` comes back as `read_messages`.

### native search with author and date filters (local patch)

`search_messages_advanced` uses Discord's indexed search. Provide exactly one of
`channel_id` (channel, DM, or thread) or `guild_id` (server). Combine optional
`query`, `author_id`, `after`, and `before`; omit `query` to filter only by author
and dates. This is a separate tool; `search_messages` keeps its original behavior.

Example: messages from one author during October 2026:

```json
{
  "channel_id": "123456789012345678",
  "author_id": "987654321098765432",
  "query": "release",
  "after": "2026-10-01",
  "before": "2026-11-01",
  "limit": 50,
  "offset": 0
}
```

Date bounds are exclusive. `YYYY-MM-DD` means midnight UTC; ISO 8601 timestamps
without a timezone also use UTC. Message IDs can be used instead of dates.
Set `oldest_first: true` for chronological order. Increase `offset` by the number
of results returned to get the next page. The default result limit is 50, maximum
200; offsets are bounded to 9975 and the last page is capped at 10000 results.
Split a larger search into smaller date ranges.

Search covers history indexed by Discord, subject to the account's permissions
and Discord's search availability. API errors are reported; the tool does not
silently substitute a limited recent-history scan. The patch requires the
project's existing `discord.py-self==2.1.0` dependency. Offline tests exercise
filter forwarding, UTC conversion, pagination, validation and error handling;
live-account behavior has not been tested.

`get_message_context` expands a search result using its `channel_id` and
`message_id`. It fetches the target message and the nearest messages before and
after it through channel history, including all authors. Results are chronological
and the target is marked `[TARGET MESSAGE]`. Each side defaults to 10 messages,
with `before_count` and `after_count` independently configurable from 0 to 50.
Fewer rows are returned if history ends or no more accessible messages exist.
Deleted or inaccessible target messages produce an explicit error.

```json
{
  "channel_id": "123456789012345678",
  "message_id": "123456789012345679",
  "before_count": 10,
  "after_count": 10
}
```

Advanced search results include channel IDs, author IDs and timestamps so the
client can expand any hit directly, including hits from a server-wide search.

Advanced search and message context rely on discord.py-self's handling of
Discord's HTTP rate-limit headers and 429 responses. They do not use the extra
local action cooldown, so reading is not blocked by the local write budget.

### mutual servers and friends (local patch)

get_user_mutuals returns servers and friends shared with a user relative to the
active saved account. The response identifies both the target and viewer.

~~~json
{"user_id": "123456789012345678"}
~~~

The tool makes one profile request with mutual guild/friend flags. Server names
come from the guild cache; an uncached name is null, without an extra lookup.
There are no per-guild/member/friend fetches or extra local read cooldown.
Use include_guilds=false or include_friends=false to skip an unneeded category.

Each list has status, count, items and next_offset. available means Discord
exposed a list; partial includes available_count when the reported friend total
differs from the exposed list. count_only means only a friend count was exposed,
and unavailable means the requested data were missing. A masked profile is
labelled limited and its totals are unknown. not_requested marks an excluded
category. Missing or restricted data never imply zero mutuals. HTTP access
failures are MCP errors, including 404 responses that cannot distinguish a
missing user from an inaccessible profile.

limit defaults to 20 entries per list, within a shared max_output_chars budget
(default 6000). Continue by passing the corresponding next_offset value as
guild_offset or friend_offset. Each continuation fetches a fresh profile;
offsets paginate entries exposed by Discord, not hidden entries.

### compact search, reply chains and cached roles (local patch)

search_messages_advanced returns previews of up to preview_chars characters
(default 240) within max_output_chars (default 3500). Even when limit is large,
the response may contain fewer messages to stay inside that budget. Follow
next_offset with the same filters, rather than assuming limit messages were
returned. returned is the number shown; total_results is Discord's reported
matching count for the original filters. It is not capped by limit or the text
budget. The count is captured from the same first search response, including
empty pages, with no extra count request. Later SDK pages can narrow the date
range; their counts do not overwrite the original total.

has_more uses the total when available, otherwise it is conservative. A missing
counter is unknown (null in batch JSON), not an inferred zero. Indexing counts
are marked total_results_partial. If the 10,000-result search window is reached,
search_window_exhausted is set; narrow the date range to continue. An empty page
with remaining matches is marked search_incomplete instead of claiming no
matches. Previews retain IDs, reply IDs and a shared channel/author legend.
Open relevant hits with get_message_context to read more.

For several terms, use search_messages_batch:

~~~json
{
  "guild_id": "123456789012345678",
  "queries": ["vulnerability", "193367", "crash"],
  "limit_per_query": 10,
  "max_output_chars": 10000
}
~~~

The batch shares an output budget, deduplicates messages across queries and
labels matched_queries. Each query reports returned, total_results, has_more,
next_offset and any error. Totals can overlap and must not be summed across
queries. Continue an individual query with search_messages_advanced and that
query's next_offset. partial_failure marks a batch with some failed queries;
failure of all queries is an MCP error.

get_message_context follows reply parents up to reply_depth (default 2, maximum
5). It reuses the requested window and already resolved references before
fetching missing parents. reply_depth=0 disables extra parent fetches.
Deleted and inaccessible parents are labelled. Neighbouring messages remain in
chronological order; additional ancestors have their own section.
Context text is bounded by max_output_chars (default 12000) and message_chars
(default 1000); the target is always retained and trimmed windows are labelled.

History, thread reads, both search tools and context default to a shared legend.
Each channel URL and each author's ID, username and highest role name appear
once. Rows contain the message ID, author/channel references, UTC time and an
optional ->reply_id. Append the message ID to its channel URL to get a jump link.
For batch searches the legend is shared across all queries. Output budgets
include the legend; omitted rows do not leave unused author/channel references.

Colours, role IDs, cache-source fields and repeated full message URLs are
omitted by default. Set details=true for the full per-message metadata format.
In detailed mode role_color describes the highest role and display_color comes
from the highest coloured role. Normal JSON serialization keeps only the role
name/status alongside existing message fields.

Role metadata uses only the message and guild caches: no member/role fetches.
Missing data appear as [role unknown] in the legend; DMs omit roles.
Cached roles describe available member state, not historical rank.

Native-search and context failures now produce MCP isError=true. Unavailable
discrawl tools are hidden from discovery, and direct failures are MCP errors.

### forum topic search

Use the read-only MCP tool search_forum_topics to search forum topic titles
through Discord's indexed thread-search API. It includes active and archived
topics by default and does not scan the local active-thread cache.

Example: search a suggestions forum for fly:

~~~json
{
  "forum_id": "123456789012345678",
  "query": "fly",
  "limit": 10,
  "offset": 0
}
~~~

The JSON result contains titles, Discord links, thread IDs, archive status,
first-post previews (up to 400 characters), total_results, has_more and
next_offset. Use read_thread_messages with a returned thread_id to read replies.
The search targets titles, not every message's contents.

Omit archived to include both states, or pass true/false to filter. limit is 1–25,
offset is 0–9975. Pass next_offset with the same query for the following page.
Discord's own rate limits apply; there is no additional local action cooldown.
Index-not-ready retries are bounded, and failures are reported as MCP errors.

### current server membership

Use get_guild_member with guild_id and user_id to check current membership.
It always queries Discord's API, even when an older member object is cached.
The response includes source=discord_api, checked_at and one of:

- present / is_member=true: Discord returned the member, with username, server
  nickname and join date.
- absent / is_member=false: Discord returned Unknown Member (code 10007).
- unknown / is_member=null: access was denied or Discord could not verify the
  member. Unknown Guild, HTTP 403 and other API failures never mean absent.

Messages found in history prove historical activity, not current membership.
An empty local member cache proves neither absence nor departure.
inspect_effective_permissions now refreshes member targets from the API too;
use get_guild_member when permissions are not needed.

### saved accounts and switching (local patch)

The MCP tools list_accounts, save_account and switch_account manage named
Discord user accounts. On the first successful startup, the existing
DISCORD_TOKEN is saved as main. Windows DPAPI encrypts saved tokens for the
current Windows user; no token is included in tool responses.

Use save_account with account, token and optional replace=true to update an
existing profile. Discord validates the token before saving. Saving does not
change the active connection. Use list_accounts to see profile names, Discord
identities, connection status and the active profile.

To switch to a saved profile:

~~~json
{"account": "work"}
~~~

Call switch_account with these arguments. It waits for running commands to
finish, connects a fresh Discord client and checks its identity and readiness
before replacing the old connection. A failed preparation keeps the previous
account active. Cached messages, channels, members and modals are isolated
between accounts; concurrent reads remain supported.

The selected profile is reused on the next MCP startup, ahead of the legacy
DISCORD_TOKEN fallback. Set DISCORD_ACCOUNT to select a particular saved profile
at startup, or DISCORD_ACCOUNTS_FILE to choose the encrypted account file.
The default file is under LocalAppData/discord-self-mcp/accounts.json.
Switching changes this running MCP server. Other clients sharing that server
use the same active account.

Reconnect MCP once after installing this change to load the new tools.
Subsequent account switches do not require an app restart.
Saved profiles in this build require Windows; the separate CLI daemon does
not share the MCP server's active connection.

### required typing duration before sending (local patch)

send_message and send_thread_message require an explicit typing_seconds
number greater than 0 and at most 60. Fractions are supported; there is no default.
This covers messages and replies in channels, DMs, group DMs and existing threads.

~~~json
{
  "channel_id": "123456789012345678",
  "content": "Hello!",
  "typing_seconds": 3
}
~~~

After any local message cooldown, the tool starts Discord's typing indicator,
keeps refreshing it while waiting for the chosen duration, then sends.
Missing or invalid durations fail before looking up the destination or sending.
If typing cannot start, the message is not sent. The confirmation includes the
chosen duration. For the CLI, --typing-seconds is required too.
Creating a new forum topic remains a separate create_thread operation: the
destination thread does not exist yet, so it cannot show a typing indicator.

Reconnect the MCP server after upgrading so clients reload the required input.

### direct messages

`list_dm_channels` enumerates your open 1:1 and group DM channels so you can
discover a `channel_id` instead of needing to know it in advance. Each row is
`<channel_id> - [dm|group] <recipient display> (id=<user_id>) [BOT]`. Optional
args: `include_groups` (default `true`) and `name_contains` (case-insensitive
filter on recipient name/handle), e.g. find the DM with a person by name and
feed the id straight into `read_messages` / `send_message`.

### server discovery and folders

`analyze_server_sidebar` is the recommended first step when organizing a large
server list. It returns the current folder layout alongside each server's
description, member count, permissions, and a compact channel summary. Set
`include_recent_messages: true` to sample high-signal channels such as
announcements, general, FAQ, and updates; likely ticket and log channels are
skipped by default.

Use `get_server_overviews` for selected servers or `sample_server_content` when
you only need message evidence. `list_channels` also accepts `guild_ids` and a
`mode: "summary"` option, which collapses repeated ticket-style channels unless
`include_repetitive` is set.

For writes, use `apply_server_folder_layout` to create, rename, recolor, and
move several folders in one settings update. First call it with `dry_run: true`;
the response lists each creation, rename, recolor, move, and empty folder that
would be removed. Servers omitted from the request stay in their current place.
The service logs each settings write by operation count and data version, never
message content or account secrets.

### slash commands

`send_slash_command` invokes an application command in a channel or DM. Pass
`application_id` (the bot's user/application ID) for reliable resolution; in a DM
with a bot it is inferred automatically. The command and any options are
resolved from the application's registered command list
(`GET /applications/{id}/commands`), which works for ordinary guild-installed
bots whose commands the per-channel `/` search index does not return. Subcommands
are space-separated in `command_name` (e.g. `"config set"`). Example:

```json
{
  "channel_id": "123456789012345678",
  "command_name": "remind",
  "application_id": "987654321098765432",
  "options": { "text": "stand up", "when": "in 10 minutes" }
}
```

### context menu commands

`list_application_commands` shows everything a channel offers — slash commands
plus the user and message commands that live in the right-click "Apps" menu:

```json
{ "channel_id": "123456789012345678", "kind": "all" }
```

invoke them with `send_user_command` (targets a user) or
`send_message_command` (targets a message):

```json
{
  "channel_id": "123456789012345678",
  "user_id": "987654321098765432",
  "command_name": "Report User"
}
```

a name is only matched within its own kind, so a user command never satisfies
`send_message_command`. pass `application_id` when two apps register the same
name.

### modals

when a button or slash command opens a modal, `click_button` reports the
modal's `custom_id` and its fields instead of a bare "Button clicked". feed
those into `submit_modal`:

```json
{
  "custom_id": "auth_profile:ABC123",
  "values": { "profile_username": "your_username" }
}
```

pending modals are held for the session (up to 16 at a time) and are consumed
on submit. a modal is put back when the submit is rejected — unknown field
ids, missing required fields, or a failed send before anything reached
discord — so you can fix the values and retry without clicking the button
again. once the answers have been sent the entry stays consumed, because a
second attempt would submit the interaction twice. discord expires the
underlying interaction after roughly 15 minutes; if that happens, click the
button again.

### ephemeral replies

most bots answer a click or a slash command with an ephemeral reply — the
private "only you can see this" message. discord never persists those, so
`read_messages` cannot see them and `fetch_message` returns 404. they do
arrive over the gateway, so `list_ephemeral_messages` reads them out of the
cache and `click_button` / `select_menu` fall back to the cache when the REST
fetch 404s. that makes multi-step flows reachable:

    click_button(panel)                -> bot replies ephemerally
    list_ephemeral_messages(channel)   -> message_id + its buttons
    click_button(that message_id, ...) -> next ephemeral step

only replies received while this server was connected are cached.

### discrawl integration

Use `run_discrawl` to execute local `discrawl` commands directly from MCP.
Use typed tools for common operations (`discrawl_sync`, `discrawl_search`, `discrawl_messages`, etc.) when you want structured params.
By default this MCP uses the Microck fork at `../discrawl-self/bin/discrawl`:
`https://github.com/Microck/discrawl-self`. It does not silently fall back to a
global `discrawl` from `PATH`; set `DISCRAWL_BIN` or the tool `binary` argument
when you intentionally want another executable.

Example tool call payload:

```json
{
  "command": "sync",
  "args": ["--guild", "1234567890", "--since", "2026-03-01T00:00:00Z"],
  "config_path": "~/.discrawl/config.toml"
}
```

Typed tool payload example:

```json
{
  "tool": "discrawl_sync",
  "args": {
    "guild": "1234567890",
    "since": "2026-03-01T00:00:00Z",
    "full": true,
    "config_path": "~/.discrawl/config.toml"
  }
}
```

Optional env var:

- `DISCRAWL_BIN` - custom path to discrawl executable. This overrides the default Microck fork lookup.

### attachment access

Use `get_message_attachments` when a message contains files or images you need to inspect directly.
It returns attachment metadata for the target message and can stream image/file content back through MCP outputs.

### comparison

| feature | discord-py-self-mcp | discord.py-self (Lib) | Maol-1997 | codebyyassine | elyxlz |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **read messages** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **send messages** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **list guilds** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **list channels** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **get user info** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **search messages** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **create channels** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **delete channels** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **edit messages** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **delete messages** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **join voice** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **manage friends** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **manage threads** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **slash commands** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **click buttons** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **select menus** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **submit modals** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **ephemeral replies** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **context menu commands** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **kick/ban** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **invites** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **profile edit** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **setup wizard** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **captcha solver** | ✅ | ❌ | ❌ | ❌ | ❌ |

✅ = supported

❌ = not supported

🚧 = planned / in progress

---

### captcha solving (experimental)

automatically solves hCaptchas when encountered (e.g., joining servers, dms).
built upon [QIN2DIM/hcaptcha-challenger](https://github.com/QIN2DIM/hcaptcha-challenger) - an AI-powered hCaptcha solver using vision models.

> **warning**: this feature is experimental. use at your own risk.

**requirements:**
1. **Gemini API Key**: Required for AI vision. Get from [Google AI Studio](https://aistudio.google.com/app/apikey). Set `GEMINI_API_KEY` in your mcp client `env`.
2. **Playwright**: Required for browser automation.
   ```bash
   playwright install chromium --with-deps
   ```

**optional:**
- `CAPTCHA_PROXY`: proxy url for solving hCaptcha challenges.
- `TEMP_DIR`: Directory for temporary model files (default: `/tmp/hcaptcha`)

---

### rate limiting (recommended)

built-in rate limiting to prevent account bans. configurable via environment variables.

**configuration:**

| variable | default | description |
|----------|---------|-------------|
| `RATE_LIMIT_ENABLED` | `true` | Enable/disable rate limiting |
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | `10` | Max messages per minute |
| `RATE_LIMIT_MESSAGES_PER_SECOND` | `1` | Max messages per second |
| `RATE_LIMIT_ACTIONS_PER_MINUTE` | `5` | Max actions (joins, etc.) per minute |
| `RATE_LIMIT_COOLDOWN` | `60` | Cooldown duration when limit hit (seconds) |

> rate limiting is enabled by default to reduce ban risk. Only disable it if you are deliberately taking responsibility for raw Discord API pacing yourself.

---

### troubleshooting

| problem | solution |
|---------|----------|
| **token invalid** | run the setup script again to extract a fresh one |
| **missing dependencies** | ensure `uv` or `pip` installed all requirements |
| **playwright error** | run `playwright install chromium` |
| **audioop error** | ensure `audioop-lts` is installed if using python 3.13+ |
| **camoufox missing** | run `python -m camoufox fetch` |
| **voice error** | install `libffi-dev` (linux) or ensure PyNaCl built correctly |

---

### project structure

```
discord_py_self_mcp/
├── bot.py
├── main.py
├── setup.py
├── rate_limiter.py
├── tool_utils.py
├── cli_runtime.py
├── logging_utils.py
├── captcha/
│   └── solver.py
└── tools/
    ├── channels.py
    ├── dms.py
    ├── discrawl.py
    ├── embed.py
    ├── guilds.py
    ├── interactions.py
    ├── invites.py
    ├── members.py
    ├── messages.py
    ├── permissions.py
    ├── presence.py
    ├── profile.py
    ├── reactions.py
    ├── registry.py
    ├── relationships.py
    ├── roles.py
    ├── threads.py
    └── voice.py
```

---

### skill cli mode (optional)

in addition to the mcp server, this package also provides a **skill/cli mode** for command-line usage with a persistent daemon. this is useful for scripts or when you need faster execution without the mcp protocol overhead.

**quick start**:
```bash
# install (same package)
npm install -g discord-selfbot-mcp

# create .env file
echo "DISCORD_TOKEN=***" > .env

# use skill mode (from package directory)
python3 scripts/dcli.py send-message --channel 123 --content "Hello!" --typing-seconds 3
```

**key commands**:
```bash
python3 scripts/dcli.py daemon start     # start the daemon
python3 scripts/dcli.py daemon status    # check daemon status
python3 scripts/dcli.py send-message --channel CHANNEL_ID --content "Hello" --typing-seconds 3
python3 scripts/dcli.py list-guilds
python3 scripts/dcli.py read-messages --channel CHANNEL_ID --limit 20
python3 scripts/dcli.py get-message-attachments --channel CHANNEL_ID --message MESSAGE_ID
python3 scripts/dcli.py get-message-attachments --channel CHANNEL_ID --message MESSAGE_ID --download --output-dir ./attachments
```

**when to use skill mode**:
- command-line scripting
- faster execution (persistent connection)
- automation tasks
- when mcp is not needed

see [SKILL.md](SKILL.md) for detailed documentation.

---

### license

this project is licensed under the [mit license](./LICENSE).

---

### contributing

issues and pull requests are welcome at [github.com/Microck/discord.py-self-mcp](https://github.com/Microck/discord.py-self-mcp).

1. fork the repository
2. create a feature branch (`git checkout -b feature/my-feature`)
3. commit your changes (`git commit -m 'add my feature'`)
4. push to the branch (`git push origin feature/my-feature`)
5. open a pull request

please ensure tests pass (`pytest`) before submitting.
