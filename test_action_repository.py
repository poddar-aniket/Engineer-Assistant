"""
Smoke test for orchestrator/repository/action_repository.py and
orchestrator/repository/models.py.

Uses an isolated in-memory SQLite database -- never touches the real
engineer_assistant.db. Run directly: python test_action_repository.py
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from orchestrator.repository.action_repository import (
    ActionNotFoundError,
    ActionRepository,
    InvalidActionStateError,
)
from orchestrator.repository.models import ActionStatus, Base

results: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    results.append((name, condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_create_action():
    db = make_session()
    repo = ActionRepository(db)
    action = repo.create(
        action_type="schedule_meeting",
        params={"title": "Sync", "duration_minutes": 30},
        display="Schedule 'Sync' for 30 minutes",
        source="command",
    )
    check("create_action returns Action with id", action.id is not None)
    check("create_action defaults to pending", action.status == ActionStatus.PENDING.value)
    check("create_action sets created_at", action.created_at is not None)
    db.close()


def test_get_existing_and_missing():
    db = make_session()
    repo = ActionRepository(db)
    created = repo.create("send_email", {"to": "a@b.com"}, "Send email to a@b.com")
    fetched = repo.get(created.id)
    check("get returns matching action", fetched is not None and fetched.id == created.id)
    check("get returns None for missing id", repo.get(999999) is None)
    db.close()


def test_list_pending():
    db = make_session()
    repo = ActionRepository(db)
    repo.create("schedule_meeting", {}, "Action 1")
    repo.create("send_email", {}, "Action 2")
    check("list_pending returns all pending actions", len(repo.list_pending()) == 2)
    db.close()


def test_approve_then_execute():
    db = make_session()
    repo = ActionRepository(db)
    action = repo.create("add_calendar_event", {}, "Add event")
    approved = repo.mark_approved(action.id)
    check("mark_approved sets status to approved", approved.status == ActionStatus.APPROVED.value)
    executed = repo.mark_executed(action.id, result={"event_id": "abc123"})
    check("mark_executed sets status to executed", executed.status == ActionStatus.EXECUTED.value)
    check("mark_executed stores result", executed.result == {"event_id": "abc123"})
    check("mark_executed sets executed_at", executed.executed_at is not None)
    db.close()


def test_reject():
    db = make_session()
    repo = ActionRepository(db)
    action = repo.create("send_email", {}, "Send email")
    rejected = repo.mark_rejected(action.id)
    check("mark_rejected sets status to rejected", rejected.status == ActionStatus.REJECTED.value)
    db.close()


def test_mark_failed():
    db = make_session()
    repo = ActionRepository(db)
    action = repo.create("create_event", {}, "Create event")
    repo.mark_approved(action.id)
    failed = repo.mark_failed(action.id, error="Calendar API timeout")
    check("mark_failed sets status to failed", failed.status == ActionStatus.FAILED.value)
    check("mark_failed stores error message", failed.error == "Calendar API timeout")
    db.close()


def test_invalid_transitions_raise():
    db = make_session()
    repo = ActionRepository(db)
    action = repo.create("send_email", {}, "Send email")
    repo.mark_approved(action.id)

    raised_double_approve = False
    try:
        repo.mark_approved(action.id)
    except InvalidActionStateError:
        raised_double_approve = True
    check("approving an already-approved action raises", raised_double_approve)

    action2 = repo.create("send_email", {}, "Send email 2")
    raised_execute_without_approval = False
    try:
        repo.mark_executed(action2.id, result={})
    except InvalidActionStateError:
        raised_execute_without_approval = True
    check("executing a pending action raises", raised_execute_without_approval)
    db.close()


def test_not_found_raises():
    db = make_session()
    repo = ActionRepository(db)
    raised = False
    try:
        repo.mark_approved(999999)
    except ActionNotFoundError:
        raised = True
    check("acting on missing action raises ActionNotFoundError", raised)
    db.close()


def test_delete():
    db = make_session()
    repo = ActionRepository(db)
    action = repo.create("send_email", {}, "Send email")
    check("delete returns True for existing action", repo.delete(action.id) is True)
    check("action no longer retrievable after delete", repo.get(action.id) is None)
    check("delete returns False for missing action", repo.delete(999999) is False)
    db.close()


def main():
    for test in [
        test_create_action,
        test_get_existing_and_missing,
        test_list_pending,
        test_approve_then_execute,
        test_reject,
        test_mark_failed,
        test_invalid_transitions_raise,
        test_not_found_raises,
        test_delete,
    ]:
        test()

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()