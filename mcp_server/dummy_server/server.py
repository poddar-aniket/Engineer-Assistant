import logging
from typing import Any
from mcp_server.base import BaseMCPServer, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class DummyMCPServer(BaseMCPServer):

    async def initialize(self) -> None:
        logger.info("[DummyServer] initialize() called.")
        self._initialized = True

    async def shutdown(self) -> None:
        logger.info("[DummyServer] shutdown() called.")
        self._initialized = False

    def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(name="echo", description="Echoes input back.",
                           parameters={"message": {"type": "string", "required": True}}),
            ToolDefinition(name="ping", description="Returns pong.", parameters={}),
        ]

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        self._require_init()
        match tool_name:
            case "echo":
                return ToolResult(tool_name=tool_name, success=True,
                                  data={"echo": params.get("message", "")})
            case "ping":
                return ToolResult(tool_name=tool_name, success=True,
                                  data={"response": "pong"})
            case _:
                return ToolResult(tool_name=tool_name, success=False,
                                  error=f"Unknown tool: '{tool_name}'")