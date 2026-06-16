from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import settings
from mcp_server.base.base_server import BaseMCPServer, ToolResult
from mcp_server.calendar_server.server import CalendarMCPServer
from mcp_server.gmail_server.server import GmailMCPServer
from orchestrator.repository.action_repository import (
    ActionNotFoundError,
    ActionRepository,
    InvalidActionStateError,
)
from orchestrator.repository.models import Action

logger = logging.getLogger(__name__)


@dataclass
class ApprovalResult:
    success: bool
    action: Action | None = None
    error: str | None = None


class ApprovalManager:
    """
    Executes an approved Action by translating its generic params (filled
    in by Gemini via COMMAND_TOOLS) into the exact shape the relevant MCP
    server tool expects, then calling it. Rejections never touch an MCP
    server at all.
    """

    def __init__(
        self,
        action_repository: ActionRepository,
        calendar_server: CalendarMCPServer,
        gmail_server: GmailMCPServer,
        local_timezone: str | None = None,
    ) -> None:
        self._repo = action_repository
        self._calendar = calendar_server
        self._gmail = gmail_server
        self._local_tz = ZoneInfo(local_timezone or settings.LOCAL_TIMEZONE)
        self._translators = {
            "schedule_meeting": self._translate_schedule_meeting,
            "add_calendar_event": self._translate_add_calendar_event,
            "check_availability": self._translate_check_availability,
            "get_todays_schedule": self._translate_get_todays_schedule,
            "send_email": self._translate_send_email,
            "create_email_draft": self._translate_create_email_draft,
        }

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def approve_and_execute(self, action_id: int) -> ApprovalResult:
        """
        Mark the action approved, translate + execute it via the right MCP
        server, then mark it executed or failed based on the outcome.
        Never raises.
        """
        try:
            action = self._repo.mark_approved(action_id)
        except (ActionNotFoundError, InvalidActionStateError) as exc:
            return ApprovalResult(success=False, error=str(exc))

        translator = self._translators.get(action.action_type)
        if translator is None:
            error = f"No execution mapping yet for action_type '{action.action_type}'"
            logger.error(error)
            failed = self._repo.mark_failed(action_id, error=error)
            return ApprovalResult(success=False, action=failed, error=error)

        try:
            server, tool_name, tool_params = translator(action.params)
        except Exception as exc:
            error = f"Failed to translate params for '{action.action_type}': {exc}"
            logger.error(error)
            failed = self._repo.mark_failed(action_id, error=error)
            return ApprovalResult(success=False, action=failed, error=error)

        tool_result: ToolResult = await server.call_tool(tool_name, tool_params)

        if tool_result.success:
            executed = self._repo.mark_executed(action_id, result=tool_result.data)
            return ApprovalResult(success=True, action=executed)

        failed = self._repo.mark_failed(action_id, error=tool_result.error)
        return ApprovalResult(success=False, action=failed, error=tool_result.error)

    def reject(self, action_id: int) -> ApprovalResult:
        """Reject a pending action. No MCP server is ever called."""
        try:
            action = self._repo.mark_rejected(action_id)
            return ApprovalResult(success=True, action=action)
        except (ActionNotFoundError, InvalidActionStateError) as exc:
            return ApprovalResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Translators: action_type's generic Gemini params -> (server, tool, params)
    # ------------------------------------------------------------------

    def _combine_date_time_utc(self, date_str: str, time_str: str) -> str:
        """
        Combine YYYY-MM-DD / HH:MM strings (as Gemini fills them via
        COMMAND_TOOLS, assumed to be in self._local_tz) into a single
        timezone-aware UTC ISO 8601 string, e.g. "2026-06-18T09:30:00+00:00".

        The explicit +00:00 offset matters: CalendarMCPServer.create_event
        treats a naive string as already-UTC and just labels it so, while
        check_availability calls .astimezone(utc) on it -- which, for a
        NAIVE datetime, assumes the server PROCESS's local timezone rather
        than UTC. An explicit offset makes both behave correctly regardless
        of what timezone the machine running this code is set to.
        """
        local_dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
        local_dt = local_dt.replace(tzinfo=self._local_tz)
        return local_dt.astimezone(timezone.utc).isoformat()

    def _translate_schedule_meeting(self, params: dict[str, Any]) -> tuple[BaseMCPServer, str, dict]:
        start = self._combine_date_time_utc(params["date"], params["start_time"])
        end = self._combine_date_time_utc(params["date"], params["end_time"])
        attendees_raw = params.get("attendees", "")
        attendees = [a.strip() for a in attendees_raw.split(",") if a.strip()] if attendees_raw else []
        return self._calendar, "create_event", {
            "title": params["title"],
            "start_time": start,
            "end_time": end,
            "description": params.get("description", ""),
            "attendees": attendees,
        }

    def _translate_add_calendar_event(self, params: dict[str, Any]) -> tuple[BaseMCPServer, str, dict]:
        start = self._combine_date_time_utc(params["date"], params["start_time"])
        end = self._combine_date_time_utc(params["date"], params["end_time"])
        return self._calendar, "create_event", {
            "title": params["title"],
            "start_time": start,
            "end_time": end,
            "description": params.get("notes", ""),
            "attendees": [],
        }

    def _translate_check_availability(self, params: dict[str, Any]) -> tuple[BaseMCPServer, str, dict]:
        start = self._combine_date_time_utc(params["date"], params["start_time"])
        end = self._combine_date_time_utc(params["date"], params["end_time"])
        return self._calendar, "check_availability", {"start_time": start, "end_time": end}

    def _translate_get_todays_schedule(self, params: dict[str, Any]) -> tuple[BaseMCPServer, str, dict]:
        return self._calendar, "get_today_events", {}

    def _translate_send_email(self, params: dict[str, Any]) -> tuple[BaseMCPServer, str, dict]:
        # NOTE: GmailMCPServer.send_email has no 'cc' parameter -- any cc
        # Gemini filled in (COMMAND_TOOLS allows it) is intentionally
        # dropped here rather than forwarded and crashing the call.
        return self._gmail, "send_email", {
            "to": params["to"],
            "subject": params["subject"],
            "body": params["body"],
        }

    def _translate_create_email_draft(self, params: dict[str, Any]) -> tuple[BaseMCPServer, str, dict]:
        return self._gmail, "create_draft", {
            "to": params["to"],
            "subject": params["subject"],
            "body": params["body"],
        }