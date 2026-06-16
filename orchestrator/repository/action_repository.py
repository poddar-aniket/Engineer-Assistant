from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from orchestrator.repository.models import Action, ActionStatus


class ActionNotFoundError(Exception):
    """Raised when an action_id does not exist."""


class InvalidActionStateError(Exception):
    """Raised when a status transition is attempted from an invalid state."""


class ActionRepository:
    """Pure persistence layer for Action records. No knowledge of
    DraftAction, MCP servers, or Gemini -- that glue lives in
    ActionDrafter and ApprovalManager."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        action_type: str,
        params: dict,
        display: str,
        source: str = "command",
        requires_approval: bool = True,
    ) -> Action:
        action = Action(
            action_type=action_type,
            params=params,
            display=display,
            source=source,
            requires_approval=requires_approval,
            status=ActionStatus.PENDING.value,
        )
        self.db.add(action)
        self.db.commit()
        self.db.refresh(action)
        return action

    def get(self, action_id: int) -> Action | None:
        return self.db.get(Action, action_id)

    def list_pending(self) -> list[Action]:
        return (
            self.db.query(Action)
            .filter(Action.status == ActionStatus.PENDING.value)
            .order_by(Action.created_at.asc())
            .all()
        )

    def list_all(self, status: str | None = None, limit: int = 50) -> list[Action]:
        query = self.db.query(Action)
        if status is not None:
            query = query.filter(Action.status == status)
        return query.order_by(Action.created_at.desc()).limit(limit).all()

    def _get_or_raise(self, action_id: int) -> Action:
        action = self.get(action_id)
        if action is None:
            raise ActionNotFoundError(f"No action found with id={action_id}")
        return action

    def mark_approved(self, action_id: int) -> Action:
        action = self._get_or_raise(action_id)
        if action.status != ActionStatus.PENDING.value:
            raise InvalidActionStateError(
                f"Cannot approve action {action_id} from status '{action.status}'"
            )
        action.status = ActionStatus.APPROVED.value
        self.db.commit()
        self.db.refresh(action)
        return action

    def mark_rejected(self, action_id: int) -> Action:
        action = self._get_or_raise(action_id)
        if action.status != ActionStatus.PENDING.value:
            raise InvalidActionStateError(
                f"Cannot reject action {action_id} from status '{action.status}'"
            )
        action.status = ActionStatus.REJECTED.value
        self.db.commit()
        self.db.refresh(action)
        return action

    def mark_executed(self, action_id: int, result: dict | None = None) -> Action:
        action = self._get_or_raise(action_id)
        if action.status != ActionStatus.APPROVED.value:
            raise InvalidActionStateError(
                f"Cannot mark action {action_id} executed from status '{action.status}'"
            )
        action.status = ActionStatus.EXECUTED.value
        action.result = result
        action.executed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(action)
        return action

    def mark_failed(self, action_id: int, error: str) -> Action:
        action = self._get_or_raise(action_id)
        if action.status != ActionStatus.APPROVED.value:
            raise InvalidActionStateError(
                f"Cannot mark action {action_id} failed from status '{action.status}'"
            )
        action.status = ActionStatus.FAILED.value
        action.error = error
        self.db.commit()
        self.db.refresh(action)
        return action

    def delete(self, action_id: int) -> bool:
        action = self.get(action_id)
        if action is None:
            return False
        self.db.delete(action)
        self.db.commit()
        return True