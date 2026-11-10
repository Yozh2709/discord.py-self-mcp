from typing import Callable, Awaitable
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

ToolHandler = Callable[[dict], Awaitable[list[TextContent | ImageContent | EmbeddedResource]]]

class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self.handlers: dict[str, ToolHandler] = {}
        self.availability: dict[str, Callable[[], bool]] = {}

    def register(self, name: str, description: str, input_schema: dict, *, available=None):
        def decorator(func: ToolHandler):
            self.tools[name] = Tool(
                name=name,
                description=description,
                inputSchema=input_schema
            )
            self.handlers[name] = func
            if available is not None:
                self.availability[name] = available
            return func
        return decorator

    def get_tool_definitions(self) -> list[Tool]:
        checks = {}
        result = []
        for name, tool in self.tools.items():
            check = self.availability.get(name)
            if check is not None and check not in checks:
                checks[check] = check()
            if check is None or checks[check]:
                result.append(tool)
        return result

    async def call_tool(self, name: str, arguments: dict) -> list[TextContent | ImageContent | EmbeddedResource]:
        handler = self.handlers.get(name)
        if not handler:
            available_tools = ", ".join(sorted(self.handlers))
            raise ValueError(
                f"Unknown tool '{name}'. Available tools: {available_tools}"
            )
        available = self.availability.get(name)
        if available is not None and not available():
            raise RuntimeError(f"Tool '{name}' is unavailable: its required executable is not installed or configured")
        from ..bot import account_manager

        if name in {"switch_account", "list_accounts"}:
            return await handler(arguments)
        async with account_manager.gate.operation():
            return await handler(arguments)

registry = ToolRegistry()
