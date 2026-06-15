"""
Smoke test for CalendarMCPServer and GmailMCPServer.
Run: python test_calendar_gmail.py
First run will open browser for Google OAuth login.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_calendar():
    print("\n" + "=" * 50)
    print("TESTING CalendarMCPServer")
    print("=" * 50)

    from mcp_server.calendar_server.server import CalendarMCPServer

    server = CalendarMCPServer()
    await server.initialize()

    # 1. List tools
    tools = server.list_tools()
    print(f"\n  Tools registered: {[t.name for t in tools]}")

    # 2. Health check
    healthy = await server.health_check()
    print(f"  Health check: {healthy}")

    # 3. Get today's events
    result = await server.call_tool("get_today_events", {})
    if result.success:
        print(f"  Today's events: {len(result.data)} found")
        for e in result.data:
            print(f"   - {e['title']} at {e['start']}")
    else:
        print(f"❌ get_today_events failed: {result.error}")

    # 4. Get upcoming events (3 days)
    result = await server.call_tool("get_upcoming_events", {"days": 3})
    if result.success:
        print(f"  Upcoming events (3 days): {len(result.data)} found")
    else:
        print(f"❌ get_upcoming_events failed: {result.error}")

    # 5. Check availability
    result = await server.call_tool("check_availability", {
        "start_time": "2026-06-17T10:00:00",
        "end_time": "2026-06-17T11:00:00",
    })
    if result.success:
        status = "FREE  " if result.data["is_free"] else "BUSY ❌"
        print(f"  Availability check: {status}")
    else:
        print(f"❌ check_availability failed: {result.error}")

    await server.shutdown()
    print("\n  CalendarMCPServer shutdown complete.")


async def test_gmail():
    print("\n" + "=" * 50)
    print("TESTING GmailMCPServer")
    print("=" * 50)

    from mcp_server.gmail_server.server import GmailMCPServer

    server = GmailMCPServer()
    await server.initialize()

    # 1. List tools
    tools = server.list_tools()
    print(f"\n  Tools registered: {[t.name for t in tools]}")

    # 2. Health check
    healthy = await server.health_check()
    print(f"  Health check: {healthy}")

    # 3. List emails
    result = await server.call_tool("list_emails", {
        "max_results": 10,
        "query": "is:unread"
    })
    if result.success:
        data = result.data
        print(f"  Emails fetched: {data['total_fetched']}")
        print(f"   Work:      {len(data['work'])}")
        print(f"   Personal:  {len(data['personal'])}")
        print(f"   Ambiguous: {len(data['ambiguous'])}")

        # 4. Get body of first work email if any
        if data["work"]:
            first_id = data["work"][0]["email_id"]
            body_result = await server.call_tool("get_email_body", {
                "email_id": first_id
            })
            if body_result.success:
                body_preview = body_result.data["body"][:100].replace("\n", " ")
                print(f"  Email body preview: {body_preview}...")
            else:
                print(f"❌ get_email_body failed: {body_result.error}")
    else:
        print(f"❌ list_emails failed: {result.error}")

    await server.shutdown()
    print("\n  GmailMCPServer shutdown complete.")


async def main():
    await test_calendar()
    await test_gmail()
    print("\n" + "=" * 50)
    print("ALL SMOKE TESTS COMPLETE")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())