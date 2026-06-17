# test_agent_orchestrator.py
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

from orchestrator.core.agent_orchestrator import AgentOrchestrator
from orchestrator.repository.models import Action, ActionStatus

logging.basicConfig(level=logging.INFO)


def _make_mock_action(action_id: int = 1, status: str = ActionStatus.PENDING.value) -> Action:
    action = MagicMock(spec=Action)
    action.id = action_id
    action.action_type = "schedule_meeting"
    action.params = {"title": "Standup", "date": "2026-06-18", "start_time": "09:00", "end_time": "09:30", "attendees": ""}
    action.display = "Schedule Standup on 2026-06-18 at 09:00"
    action.source = "command"
    action.status = status
    action.requires_approval = True
    action.result = None
    action.error = None
    action.created_at = None
    action.updated_at = None
    action.executed_at = None
    return action


def _make_orchestrator() -> AgentOrchestrator:
    github = MagicMock()
    calendar = MagicMock()
    gmail = MagicMock()
    gemini_client = MagicMock()
    action_repo = MagicMock()
    return AgentOrchestrator(
        github=github,
        calendar=calendar,
        gmail=gmail,
        gemini_client=gemini_client,
        action_repository=action_repo,
    )


async def test_get_briefing() -> None:
    orch = _make_orchestrator()
    mock_briefing = MagicMock()
    mock_briefing.to_dict.return_value = {"summary": "All good", "sections": [], "errors": []}
    orch._briefing_generator.generate = AsyncMock(return_value=mock_briefing)

    result = await orch.get_briefing()
    assert result["summary"] == "All good"
    print("PASS test_get_briefing")


async def test_handle_command_success() -> None:
    orch = _make_orchestrator()
    mock_action = _make_mock_action()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.action = mock_action
    mock_result.error = None
    orch._action_drafter.draft_from_command = AsyncMock(return_value=mock_result)

    result = await orch.handle_command("schedule standup tomorrow at 9am")
    assert result["success"] is True
    assert result["action"]["id"] == 1
    assert result["error"] is None
    print("PASS test_handle_command_success")


async def test_handle_command_failure() -> None:
    orch = _make_orchestrator()
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.action = None
    mock_result.error = "Could not parse command"
    orch._action_drafter.draft_from_command = AsyncMock(return_value=mock_result)

    result = await orch.handle_command("do something weird")
    assert result["success"] is False
    assert result["action"] is None
    assert result["error"] == "Could not parse command"
    print("PASS test_handle_command_failure")


async def test_approve_action_success() -> None:
    orch = _make_orchestrator()
    mock_action = _make_mock_action(status=ActionStatus.EXECUTED.value)
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.action = mock_action
    mock_result.error = None
    orch._approval_manager.approve_and_execute = AsyncMock(return_value=mock_result)

    result = await orch.approve_action(1)
    assert result["success"] is True
    assert result["action"]["status"] == ActionStatus.EXECUTED.value
    print("PASS test_approve_action_success")


async def test_reject_action() -> None:
    orch = _make_orchestrator()
    mock_action = _make_mock_action(status=ActionStatus.REJECTED.value)
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.action = mock_action
    mock_result.error = None
    orch._approval_manager.reject = MagicMock(return_value=mock_result)

    result = orch.reject_action(1)
    assert result["success"] is True
    assert result["action"]["status"] == ActionStatus.REJECTED.value
    print("PASS test_reject_action")


async def test_get_pending_actions() -> None:
    orch = _make_orchestrator()
    orch._repo.list_pending = MagicMock(return_value=[_make_mock_action(), _make_mock_action(action_id=2)])

    result = orch.get_pending_actions()
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["id"] == 2
    print("PASS test_get_pending_actions")