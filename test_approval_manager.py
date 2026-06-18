"""
Smoke test for orchestrator/approval/approval_manager.py.

Uses FakeMCPServer stand-ins for CalendarMCPServer/GmailMCPServer (no real
Google API calls) and an isolated in-memory SQLite database (no real
engineer_assistant.db). A fixed timezone is passed directly into
ApprovalManager rather than relying on settings.LOCAL_TIMEZONE, so this
test suite runs standalone regardless of what's configured in .env.

Run directly: python test_approval_manager.py
"""

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mcp_server.base.base_server import ToolResult
from orchestrator.approval.approval_manager import ApprovalManager
from orchestrator.repository.action_repository import ActionRepository
from orchestrator.repository.models import ActionStatus, Base

TEST_TIMEZONE = "Asia/Kolkata"  # fixed UTC+5:30, no DST -- deterministic for assertions

results: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    results.append((name, condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")


def make_repo() -> ActionRepository:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return ActionRepository(Session())


def expected_utc_iso(date_str: str, time_str: str) -> str:
    local_dt = datetime.fromisoformat(f"{date_str}T{time_str}:00").replace(tzinfo=ZoneInfo(TEST_TIMEZONE))
    return local_dt.astimezone(timezone.utc).isoformat()


class FakeMCPServer:
    """Minimal stand-in for a BaseMCPServer subclass. Records every call
    and returns a pre-set ToolResult -- no real network calls."""

    def __init__(self, result: ToolResult | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._result = result

    async def call_tool(self, tool_name: str, params: dict) -> ToolResult:
        self.calls.append((tool_name, params))
        return self._result


async def test_schedule_meeting_exact_timezone_math():
    repo = make_repo()
    action = repo.create(
        "schedule_meeting",
        {
            "title": "Sync",
            "date": "2026-06-18",
            "start_time": "15:00",
            "end_time": "15:30",
            "attendees": "a@b.com, c@d.com",
        },
        "Schedule meeting: 'Sync'",
    )
    calendar = FakeMCPServer(ToolResult(tool_name="create_event", success=True, data={"event_id": "abc123"}))
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    check("schedule_meeting result is success", result.success is True)
    check("schedule_meeting action ends up executed", result.action.status == ActionStatus.EXECUTED.value)
    tool_name, params = calendar.calls[-1]
    check("schedule_meeting calls create_event", tool_name == "create_event")
    check("15:00 IST converts to 09:30 UTC", params["start_time"] == "2026-06-18T09:30:00+00:00")
    check("end time converts correctly too", params["end_time"] == "2026-06-18T10:00:00+00:00")
    check("attendees string is split into a list", params["attendees"] == ["a@b.com", "c@d.com"])
    check("description defaults to empty string", params["description"] == "")
    check("no gmail calls were made", len(gmail.calls) == 0)


async def test_add_calendar_event_maps_notes_to_description():
    repo = make_repo()
    action = repo.create(
        "add_calendar_event",
        {"title": "Dentist", "date": "2026-07-01", "start_time": "09:00", "end_time": "10:00", "notes": "Bring x-rays"},
        "Add calendar event: 'Dentist'",
    )
    calendar = FakeMCPServer(ToolResult(tool_name="create_event", success=True, data={"event_id": "e2"}))
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    tool_name, params = calendar.calls[-1]
    check("add_calendar_event result is success", result.success is True)
    check("add_calendar_event calls create_event", tool_name == "create_event")
    check("'notes' maps to 'description'", params["description"] == "Bring x-rays")
    check("personal events have no attendees", params["attendees"] == [])
    check("start_time matches expected UTC conversion", params["start_time"] == expected_utc_iso("2026-07-01", "09:00"))


async def test_check_availability_translation():
    repo = make_repo()
    action = repo.create(
        "check_availability",
        {"date": "2026-07-02", "start_time": "10:00", "end_time": "11:00"},
        "Check availability on 2026-07-02",
    )
    calendar = FakeMCPServer(ToolResult(tool_name="check_availability", success=True, data={"is_free": True}))
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    tool_name, params = calendar.calls[0]
    check("check_availability result is success", result.success is True)
    check("check_availability calls the right tool", tool_name == "check_availability")
    check("start_time matches expected UTC conversion", params["start_time"] == expected_utc_iso("2026-07-02", "10:00"))
    check("result data is stored on the action", result.action.result == {"is_free": True})


async def test_get_todays_schedule_needs_no_params():
    repo = make_repo()
    action = repo.create("get_todays_schedule", {}, "Fetch and display today's calendar schedule")
    calendar = FakeMCPServer(ToolResult(tool_name="get_today_events", success=True, data=[]))
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    tool_name, params = calendar.calls[0]
    check("get_todays_schedule result is success", result.success is True)
    check("get_todays_schedule calls get_today_events", tool_name == "get_today_events")
    check("get_todays_schedule passes no params", params == {})


async def test_send_email_drops_unsupported_cc():
    repo = make_repo()
    action = repo.create(
        "send_email",
        {"to": "x@y.com", "subject": "Hi", "body": "Hello", "cc": "z@y.com"},
        "Send email to: x@y.com",
    )
    calendar = FakeMCPServer()
    gmail = FakeMCPServer(ToolResult(tool_name="send_email", success=True, data={"email_id": "m1", "status": "sent"}))
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    tool_name, params = gmail.calls[0]
    check("send_email result is success", result.success is True)
    check("send_email calls the right tool", tool_name == "send_email")
    check("cc is not forwarded (gmail server doesn't support it)", "cc" not in params)
    check("to/subject/body are forwarded correctly", params == {"to": "x@y.com", "subject": "Hi", "body": "Hello"})
    check("no calendar calls were made", len(calendar.calls) == 0)


async def test_create_email_draft_passthrough():
    repo = make_repo()
    action = repo.create(
        "create_email_draft",
        {"to": "a@b.com", "subject": "Draft", "body": "Body text"},
        "Create email draft to: a@b.com",
    )
    calendar = FakeMCPServer()
    gmail = FakeMCPServer(ToolResult(tool_name="create_draft", success=True, data={"draft_id": "d1"}))
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    tool_name, params = gmail.calls[0]
    check("create_email_draft result is success", result.success is True)
    check("create_email_draft calls create_draft", tool_name == "create_draft")
    check("params pass through unchanged", params == {"to": "a@b.com", "subject": "Draft", "body": "Body text"})


async def test_mcp_failure_marks_action_failed():
    repo = make_repo()
    action = repo.create("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"}, "Send email to: a@b.com")
    calendar = FakeMCPServer()
    gmail = FakeMCPServer(ToolResult(tool_name="send_email", success=False, error="SMTP quota exceeded"))
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    check("MCP failure makes ApprovalResult unsuccessful", result.success is False)
    check("error message is carried through", result.error == "SMTP quota exceeded")
    check("action ends up marked failed, not executed", result.action.status == ActionStatus.FAILED.value)


async def test_unmapped_action_type_marks_failed_without_calling_mcp():
    repo = make_repo()
    action = repo.create("summarise_emails", {"max_count": 5}, "Summarise up to 5 emails")
    calendar = FakeMCPServer()
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(action.id)

    check("unmapped action_type is not successful", result.success is False)
    check("unmapped action_type action ends up failed", result.action.status == ActionStatus.FAILED.value)
    check("no calendar calls were made", len(calendar.calls) == 0)
    check("no gmail calls were made", len(gmail.calls) == 0)


async def test_reject_never_touches_mcp_servers():
    repo = make_repo()
    action = repo.create("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"}, "Send email to: a@b.com")
    calendar = FakeMCPServer()
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = manager.reject(action.id)

    check("reject result is success", result.success is True)
    check("rejected action has rejected status", result.action.status == ActionStatus.REJECTED.value)
    check("no calendar calls were made", len(calendar.calls) == 0)
    check("no gmail calls were made", len(gmail.calls) == 0)


async def test_approve_nonexistent_action_does_not_raise():
    repo = make_repo()
    calendar = FakeMCPServer()
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = await manager.approve_and_execute(999999)

    check("approving a missing action returns failure, not an exception", result.success is False)
    check("error message mentions the missing action", "999999" in (result.error or ""))


async def test_reject_an_already_approved_action_fails():
    repo = make_repo()
    action = repo.create("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"}, "Send email to: a@b.com")
    repo.mark_approved(action.id)
    calendar = FakeMCPServer()
    gmail = FakeMCPServer()
    manager = ApprovalManager(repo, calendar, gmail, local_timezone=TEST_TIMEZONE)

    result = manager.reject(action.id)

    check("rejecting an already-approved action fails", result.success is False)


async def main():
    tests = [
        test_schedule_meeting_exact_timezone_math,
        test_add_calendar_event_maps_notes_to_description,
        test_check_availability_translation,
        test_get_todays_schedule_needs_no_params,
        test_send_email_drops_unsupported_cc,
        test_create_email_draft_passthrough,
        test_mcp_failure_marks_action_failed,
        test_unmapped_action_type_marks_failed_without_calling_mcp,
        test_reject_never_touches_mcp_servers,
        test_approve_nonexistent_action_does_not_raise,
        test_reject_an_already_approved_action_fails,
    ]
    for test in tests:
        await test()

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())