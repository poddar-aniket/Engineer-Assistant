from __future__ import annotations

import logging
from dataclasses import dataclass

from orchestrator.core.command_handler import CommandHandler, DraftAction
from orchestrator.repository.action_repository import ActionRepository
from orchestrator.repository.models import Action

logger = logging.getLogger(__name__)


@dataclass
class DraftResult:
    """
    Outcome of attempting to turn a free-text command (or, later, any other
    source) into a persisted, approvable Action. Always returned, never
    raised.
    """

    success: bool
    action: Action | None = None
    draft_action: DraftAction | None = None
    error: str | None = None


class ActionDrafter:
    """
    Glue layer between CommandHandler (parses free text into a DraftAction)
    and ActionRepository (persists it). Knows nothing about Gemini's
    function-calling internals or SQLAlchemy session management -- just
    bridges the two.
    """

    def __init__(self, command_handler: CommandHandler, action_repository: ActionRepository) -> None:
        self._command_handler = command_handler
        self._repo = action_repository

    async def draft_from_command(self, user_command: str) -> DraftResult:
        """
        Parse a free-text command via CommandHandler and persist the
        resulting DraftAction as a pending Action. If the command could not
        be parsed into a supported action (unknown_command), or the handler
        itself failed, nothing is persisted -- the reason comes back in
        DraftResult.error instead.
        """
        result = await self._command_handler.handle(user_command)

        if not result.success:
            return DraftResult(success=False, error=result.error)

        draft = result.draft_action
        if draft is None:
            return DraftResult(success=False, error="CommandHandler returned no draft action.")

        if not draft.requires_approval:
            # e.g. unknown_command -- nothing actionable to persist
            return DraftResult(success=False, draft_action=draft, error=draft.display)

        try:
            action = self._persist(draft, source="command")
        except Exception as exc:
            logger.error("ActionDrafter failed to persist draft for '%s': %s", user_command, exc)
            return DraftResult(success=False, draft_action=draft, error=str(exc))

        return DraftResult(success=True, action=action, draft_action=draft)

    def _persist(self, draft: DraftAction, source: str) -> Action:
        return self._repo.create(
            action_type=draft.action_type,
            params=draft.params,
            display=draft.display,
            source=source,
            requires_approval=draft.requires_approval,
        )