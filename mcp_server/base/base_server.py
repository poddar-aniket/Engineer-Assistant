from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None

    def __repr__(self) -> str:
        status = "OK" if self.success else f"ERR({self.error})"
        return f"ToolResult({self.tool_name}, {status})"


class BaseMCPServer(ABC):
    def __init__(self, name: str):
        self.name = name
        self._initialized: bool = False

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    def list_tools(self) -> list[ToolDefinition]: ...

    @abstractmethod
    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> ToolResult: ...

    async def health_check(self) -> bool:
        return self._initialized

    def _require_init(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                f"Plugin '{self.name}' used before initialize() was called."
            )

    def __repr__(self) -> str:
        status = "ready" if self._initialized else "uninitialized"
        return f"{self.__class__.__name__}(name={self.name!r}, status={status})"