import asyncio
import logging
from orchestrator.core.mcp_registry import MCPRegistry
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)


async def main():
    registry = MCPRegistry()
    await registry.initialize_all()

    print("\n   Loaded plugins:", registry.list_names())

    dummy = registry.get("dummy")

    ping = await dummy.call_tool("ping", {})
    print("   ping:", ping)

    echo = await dummy.call_tool("echo", {"message": "hello contract"})
    print("   echo:", echo)

    health = await registry.health_check()
    print("   health:", health)

    await registry.shutdown_all()
    print("   shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())