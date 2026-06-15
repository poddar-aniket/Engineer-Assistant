import asyncio
from mcp_server.github_server.server import GitHubMCPServer
from dotenv import load_dotenv
load_dotenv()


async def test():
    s = GitHubMCPServer()

    await s.initialize()

    print("=== TOOLS ===")
    for t in s.list_tools():
        print(t.name)

    print("\n=== HEALTH CHECK ===")
    print(await s.health_check())

    await s.shutdown()


asyncio.run(test())