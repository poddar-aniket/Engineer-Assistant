"""
seed_mock_data.py

Populates the actions and corrections tables with a few fake rows so
the Pending Actions and Corrections pages in the Streamlit UI have
something to show, without needing real GitHub/Calendar/Gmail activity.

Run from the repo root, after `alembic upgrade head` has created the
schema:

    python seed_mock_data.py

Safe to re-run -- each run just adds another batch of rows. If you
want a clean slate first, delete engineer_copilot.db and re-run
`alembic upgrade head` before seeding.

NOTE: this assumes `params` and `result` are SQLAlchemy JSON columns
(per the project's model notes) so plain dicts are passed in directly.
If your `params` column is actually a Text/String column instead,
swap the dict literals below for `json.dumps(...)`.
"""

from datetime import datetime, timezone

from orchestrator.repository.database import SessionLocal
from orchestrator.repository.models import Action, ActionStatus
from orchestrator.repository.correction_models import Correction


def seed_actions(session):
    mock_actions = [
        {
            "action_type": "schedule_meeting",
            "params": {
                "title": "Sprint planning",
                "date": "2026-06-18",
                "time": "10:00",
                "duration_minutes": 30,
                "attendees": ["teammate@example.com"],
            },
            "display": "Schedule 'Sprint planning' on 2026-06-18 at 10:00 with teammate@example.com",
            "source": "command",
            "status": ActionStatus.PENDING,
            "requires_approval": True,
        },
        {
            "action_type": "send_email",
            "params": {
                "to": "manager@example.com",
                "subject": "Status update",
                "body": "Quick update on this week's progress on the migration ticket.",
            },
            "display": "Send email to manager@example.com: 'Status update'",
            "source": "command",
            "status": ActionStatus.PENDING,
            "requires_approval": True,
        },
        {
            "action_type": "create_email_draft",
            "params": {
                "to": "vendor@example.com",
                "subject": "Re: contract renewal",
                "body": "Thanks for the update -- let me confirm with the team and circle back.",
            },
            "display": "Draft email to vendor@example.com: 'Re: contract renewal'",
            "source": "command",
            "status": ActionStatus.PENDING,
            "requires_approval": True,
        },
        {
            "action_type": "add_calendar_event",
            "params": {
                "title": "1:1 with mentor",
                "date": "2026-06-19",
                "time": "15:00",
            },
            "display": "Add '1:1 with mentor' on 2026-06-19 at 15:00",
            "source": "email_extraction",
            "status": ActionStatus.EXECUTED,
            "requires_approval": True,
            "executed_at": datetime.now(timezone.utc),
        },
        {
            "action_type": "send_email",
            "params": {
                "to": "old-lead@example.com",
                "subject": "Quick question",
                "body": "Hey, do you have five minutes today?",
            },
            "display": "Send email to old-lead@example.com: 'Quick question'",
            "source": "command",
            "status": ActionStatus.REJECTED,
            "requires_approval": True,
        },
    ]

    for data in mock_actions:
        action = Action(
            action_type=data["action_type"],
            params=data["params"],
            display=data["display"],
            source=data["source"],
            status=data["status"],
            requires_approval=data["requires_approval"],
            executed_at=data.get("executed_at"),
        )
        session.add(action)

    print(f"Added {len(mock_actions)} mock actions.")


def seed_corrections(session):
    mock_corrections = [
        {
            "action_type": "send_email",
            "original": "Hey, just checking in on the thing",
            "corrected": "Hi -- following up on the API migration ticket. Any blockers on your end?",
            "user_note": "Always name the specific ticket/topic, never say 'the thing'",
        },
        {
            "action_type": "schedule_meeting",
            "original": "Meeting at 9am",
            "corrected": "Meeting at 10am",
            "user_note": "I never take meetings before 10am",
        },
        {
            "action_type": "send_email",
            "original": "Best,\nAlex",
            "corrected": "Thanks,\nAlex",
            "user_note": "Prefer 'Thanks' as a sign-off over 'Best'",
        },
    ]

    for data in mock_corrections:
        correction = Correction(
            action_type=data["action_type"],
            original=data["original"],
            corrected=data["corrected"],
            user_note=data["user_note"],
        )
        session.add(correction)

    print(f"Added {len(mock_corrections)} mock corrections.")


def main():
    session = SessionLocal()
    try:
        seed_actions(session)
        seed_corrections(session)
        session.commit()
        print("Done. Refresh the Streamlit UI to see the new rows.")
    except Exception as exc:
        session.rollback()
        print(f"Seeding failed, rolled back: {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()