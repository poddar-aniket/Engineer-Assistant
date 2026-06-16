# orchestrator/core/agent_orchestrator.py
from __future__ import annotations

import logging
from typing import Any

from mcp_server.calendar_server.server import CalendarMCPServer
from mcp_server.github_server.server import GitHubMCPServer
from mcp_server.gmail_server.server import GmailMCPServer
from orchestrator.approval.approval_manager import ApprovalManager
from orchestrator.briefing.briefing_generator import BriefingGenerator
from orchestrator.core.command_handler import CommandHandler
from orchestrator.core.gemini_client import GeminiClient
from orchestrator.drafting.action_drafter import ActionDrafter
from orchestrator.repository.action_repository import ActionRepository
from orchestrator.repository.models import Action

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(
        self,
        github: GitHubMCPServer,
        calendar: CalendarMCPServer,
        gmail: GmailMCPServer,
        gemini_client: GeminiClient,
        action_repository: ActionRepository,
    ) -> None:
        self._briefing_generator = BriefingGenerator(github, calendar, gmail, gemini_client)
        self._action_drafter = ActionDrafter(
            command_handler=CommandHandler(gemini_client),
            action_repository=action_repository,
        )
        self._approval_manager = ApprovalManager(
            action_repository=action_repository,
            calendar_server=calendar,
            gmail_server=gmail,
        )
        self._repo = action_repository

    # ------------------------------------------------------------------
    # Public API (called by FastAPI routes)
    # ------------------------------------------------------------------

    async def get_briefing(self) -> dict[str, Any]:
        briefing = await self._briefing_generator.generate()
        return briefing.to_dict()

    async def handle_command(self, user_input: str) -> dict[str, Any]:
        result = await self._action_drafter.draft_from_command(user_input)
        return {
            "success": result.success,
            "action": self._action_to_dict(result.action) if result.action else None,
            "error": result.error,
        }

    async def approve_action(self, action_id: int) -> dict[str, Any]:
        result = await self._approval_manager.approve_and_execute(action_id)
        return {
            "success": result.success,
            "action": self._action_to_dict(result.action) if result.action else None,
            "error": result.error,
        }

    def reject_action(self, action_id: int) -> dict[str, Any]:
        result = self._approval_manager.reject(action_id)
        return {
            "success": result.success,
            "action": self._action_to_dict(result.action) if result.action else None,
            "error": result.error,
        }

    def get_pending_actions(self) -> list[dict[str, Any]]:
        actions = self._repo.list_pending()
        return [self._action_to_dict(a) for a in actions]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _action_to_dict(self, action: Action) -> dict[str, Any]:
        return {
            "id": action.id,
            "action_type": action.action_type,
            "params": action.params,
            "display": action.display,
            "source": action.source,
            "status": action.status,
            "requires_approval": action.requires_approval,
            "result": action.result,
            "error": action.error,
            "created_at": action.created_at.isoformat() if action.created_at else None,
            "updated_at": action.updated_at.isoformat() if action.updated_at else None,
            "executed_at": action.executed_at.isoformat() if action.executed_at else None,
        }