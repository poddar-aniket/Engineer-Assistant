"""
Smoke test for orchestrator/drafting/action_drafter.py.

Uses a FakeCommandHandler (no real Gemini calls) and an isolated in-memory
SQLite database (no real engineer_assistant.db). Run directly:
python test_action_drafter.py
"""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from orchestrator.core.command_handler import CommandResult, DraftAction
from orchestrator.drafting.action_drafter import ActionDrafter
from orchestrator.repository.action_repository import ActionRepository
from orchestrator.repository.models import ActionStatus, Base

results: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    results.append((name, condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")


def make_repo() -> ActionRepository:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return ActionRepository(Session())


class FakeCommandHandler:
    """Stand-in for CommandHandler -- same handle() signature, no real
    Gemini calls, so ActionDrafter can be tested in isolation."""

    def __init__(self, result: CommandResult) -> None:
        self._result = result

    async def handle(self, user_command: str) -> CommandResult:
        return self._result


class RaisingRepository(ActionRepository):
    """ActionRepository whose create() always raises, to confirm
    ActionDrafter wraps persistence failures instead of propagating them."""

    def create(self, *args, **kwargs):
        raise RuntimeError("simulated database failure")


async def test_successful_command_persists_action():
    fake_draft = DraftAction(
        action_type="schedule_meeting",
        params={"title": "Sync", "date": "2026-06-18", "start_time": "15:00", "end_time": "15:30"},
        display="Schedule meeting: 'Sync'\n  Date: 2026-06-18  15:00 - 15:30",
        requires_approval=True,
    )
    handler = FakeCommandHandler(CommandResult(success=True, draft_action=fake_draft, raw_command="schedule a sync"))
    repo = make_repo()
    drafter = ActionDrafter(handler, repo)

    result = await drafter.draft_from_command("schedule a sync")

    check("successful command returns success=True", result.success is True)
    check("successful command produces a persisted Action", result.action is not None)
    check("persisted action has correct action_type", result.action.action_type == "schedule_meeting")
    check("persisted action defaults to pending status", result.action.status == ActionStatus.PENDING.value)
    check("persisted action source is 'command'", result.action.source == "command")


async def test_command_handler_failure_is_not_persisted():
    handler = FakeCommandHandler(CommandResult(success=False, error="Gemini timed out", raw_command="do something"))
    repo = make_repo()
    drafter = ActionDrafter(handler, repo)

    result = await drafter.draft_from_command("do something")

    check("handler failure returns success=False", result.success is False)
    check("handler failure carries the error message through", result.error == "Gemini timed out")
    check("handler failure produces no persisted action", result.action is None)
    check("nothing was written to the repository", len(repo.list_all()) == 0)


async def test_unknown_command_is_not_persisted():
    unknown_draft = DraftAction(
        action_type="unknown_command",
        params={"reason": "Not a supported action"},
        display='Cannot process command: Not a supported action\n  Original: "make me a sandwich"',
        requires_approval=False,
    )
    handler = FakeCommandHandler(
        CommandResult(success=True, draft_action=unknown_draft, raw_command="make me a sandwich")
    )
    repo = make_repo()
    drafter = ActionDrafter(handler, repo)

    result = await drafter.draft_from_command("make me a sandwich")

    check("unknown_command returns success=False", result.success is False)
    check("unknown_command still carries draft_action for display purposes", result.draft_action is not None)
    check("unknown_command produces no persisted action", result.action is None)
    check("nothing was written to the repository", len(repo.list_all()) == 0)


async def test_repository_failure_is_caught():
    fake_draft = DraftAction(
        action_type="send_email",
        params={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
        display="Send email to: a@b.com",
        requires_approval=True,
    )
    handler = FakeCommandHandler(CommandResult(success=True, draft_action=fake_draft, raw_command="email a@b.com"))

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    repo = RaisingRepository(Session())
    drafter = ActionDrafter(handler, repo)

    result = await drafter.draft_from_command("email a@b.com")

    check("repository failure returns success=False", result.success is False)
    check("repository failure surfaces the error", result.error == "simulated database failure")
    check("repository failure produces no persisted action", result.action is None)


async def main():
    await test_successful_command_persists_action()
    await test_command_handler_failure_is_not_persisted()
    await test_unknown_command_is_not_persisted()
    await test_repository_failure_is_caught()

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())