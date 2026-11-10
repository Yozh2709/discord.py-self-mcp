import json

from mcp.types import TextContent

from ..bot import account_manager
from .registry import registry


def _result(value):
    return [TextContent(type="text", text=json.dumps(value, ensure_ascii=False))]


@registry.register(
    name="list_accounts",
    description="List saved Discord account names and identities, the active account and connection status. Tokens are never returned.",
    input_schema={"type": "object", "properties": {}},
)
async def list_accounts(arguments):
    return _result(account_manager.list_accounts())


@registry.register(
    name="save_account",
    description="Validate a Discord user token and save it encrypted under an account name. Does not switch accounts. Existing names require replace=true.",
    input_schema={
        "type": "object",
        "properties": {
            "account": {"type": "string", "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,47}$"},
            "token": {"type": "string", "description": "Discord user token; stored with Windows DPAPI and never returned"},
            "replace": {"type": "boolean", "default": False},
        },
        "required": ["account", "token"],
    },
)
async def save_account(arguments):
    return _result(await account_manager.save_account(
        arguments["account"], arguments["token"], replace=arguments.get("replace", False)
    ))


@registry.register(
    name="switch_account",
    description="Switch this MCP connection to a saved Discord account without restarting the app. Waits for running commands, validates login and readiness, then returns the active Discord identity. The previous account stays connected if preparation fails.",
    input_schema={
        "type": "object",
        "properties": {"account": {"type": "string", "description": "Saved account name from list_accounts"}},
        "required": ["account"],
    },
)
async def switch_account(arguments):
    return _result(await account_manager.switch_account(arguments["account"]))
