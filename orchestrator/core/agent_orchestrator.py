# orchestrator/core/agent_orchestrator.py
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mcp_server.base.base_server import ToolResult
from mcp_server.calendar_server.server import CalendarMCPServer
from mcp_server.github_server.server import GitHubMCPServer
from mcp_server.gmail_server.server import GmailMCPServer
from orchestrator.approval.approval_manager import ApprovalManager
from orchestrator.briefing.briefing_generator import BriefingGenerator
from orchestrator.core.command_handler import CommandHandler, DraftAction
from orchestrator.core.gemini_client import GeminiClient
from orchestrator.drafting.action_drafter import ActionDrafter
from orchestrator.repository.action_repository import ActionRepository
from orchestrator.repository.correction_repository import CorrectionRepository
from orchestrator.repository.models import Action
from orchestrator.personalization.engine import PersonalizationEngine
from orchestrator.personalization.strategies import RecencyStrategy

logger = logging.getLogger(__name__)

# TODO: replace with config.settings.LOCAL_TIMEZONE if that value differs
LOCAL_TZ = ZoneInfo("Asia/Kolkata")

# Strips zero-width/invisible unicode characters often present in marketing email snippets
_INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u034f\u061c\u200e\u200f\u2060-\u206f]")


class AgentOrchestrator:
    def __init__(
        self,
        github: GitHubMCPServer,
        calendar: CalendarMCPServer,
        gmail: GmailMCPServer,
        gemini_client: GeminiClient,
        action_repository: ActionRepository,
        correction_repository: CorrectionRepository | None = None,
    ) -> None:
        personalization_engine = (
            PersonalizationEngine(RecencyStrategy(correction_repository))
            if correction_repository
            else None
        )
        self._correction_repo = correction_repository
        self._github = github
        self._calendar = calendar
        self._gmail = gmail
        self._briefing_generator = BriefingGenerator(github, calendar, gmail, gemini_client)
        self._action_drafter = ActionDrafter(
            command_handler=CommandHandler(gemini_client, personalization_engine),
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

    async def check_ci_failures(self) -> ToolResult:
        return await self._github.call_tool("get_ci_failures", {})

    async def get_briefing(self) -> dict[str, Any]:
        briefing = await self._briefing_generator.generate()
        return briefing.to_dict()

    async def handle_command(self, user_input: str) -> dict[str, Any]:
        result = await self._action_drafter.draft_from_command(user_input)

        if not result.success:
            return {"success": False, "action": None, "error": result.error}

        # Read-only action — execute directly via MCP, skip DB entirely
        if result.action is None and result.draft_action is not None:
            draft = result.draft_action
            tool_result = await self._execute_read_only(draft)
            formatted_result = self._format_read_only_result(
                draft.action_type,
                tool_result.data if tool_result.success else None,
            )
            return {
                "success": True,
                "action": None,
                "read_only_result": formatted_result,
                "read_only_type": draft.action_type,
                "read_only_display": draft.display,
                "error": tool_result.error if not tool_result.success else None,
            }

        return {
            "success": True,
            "action": self._action_to_dict(result.action) if result.action else None,
            "error": None,
        }

    async def approve_action(self, action_id: int) -> dict[str, Any]:
        result = await self._approval_manager.approve_and_execute(action_id)
        return {
            "success": result.success,
            "action": self._action_to_dict(result.action) if result.action else None,
            "error": result.error,
        }

    async def _execute_read_only(self, draft: DraftAction) -> ToolResult:
        """Execute a read-only action directly via MCP without persisting to DB."""
        params = draft.params

        if draft.action_type == "get_todays_schedule":
            result = await self._calendar.call_tool("get_today_events", {})
            logger.info(
                "get_today_events result: success=%s data=%s error=%s",
                result.success, result.data, result.error,
            )
            return result

        if draft.action_type == "check_availability":
            from orchestrator.approval.approval_manager import ApprovalManager
            start = ApprovalManager._combine_date_time_utc(
                self._approval_manager, params["date"], params["start_time"]
            )
            end = ApprovalManager._combine_date_time_utc(
                self._approval_manager, params["date"], params["end_time"]
            )
            result = await self._calendar.call_tool("check_availability", {
                "start_time": start,
                "end_time": end,
            })
            logger.info(
                "check_availability result: success=%s data=%s error=%s",
                result.success, result.data, result.error,
            )
            return result

        if draft.action_type == "summarise_emails":
            result = await self._gmail.call_tool("list_emails", {
                "max_results": params.get("max_count", 10),
                "query": params.get("filter_topic", "") or params.get("filter_sender", ""),
            })
            logger.info(
                "list_emails result: success=%s data=%s error=%s",
                result.success, result.data, result.error,
            )
            return result

        return ToolResult(success=False, error=f"Unknown read-only action: {draft.action_type}")

    def reject_action(self, action_id: int) -> dict[str, Any]:
        result = self._approval_manager.reject(action_id)
        return {
            "success": result.success,
            "action": self._action_to_dict(result.action) if result.action else None,
            "error": result.error,
        }

    def store_correction(
        self,
        action_type: str,
        original: str,
        corrected: str,
        user_note: str | None = None,
    ) -> dict[str, Any]:
        if not self._correction_repo:
            return {"success": False, "error": "Correction repository not configured"}
        correction = self._correction_repo.create(
            action_type=action_type,
            original=original,
            corrected=corrected,
            user_note=user_note,
        )
        return {"success": True, "correction_id": correction.id}

    def get_pending_actions(self) -> list[dict[str, Any]]:
        actions = self._repo.list_pending()
        return [self._action_to_dict(a) for a in actions]

    def get_corrections(self) -> list[dict[str, Any]]:
        if not self._correction_repo:
            return []
        corrections = self._correction_repo.list_all()
        return [
            {
                "id": c.id,
                "action_type": c.action_type,
                "original": c.original,
                "corrected": c.corrected,
                "user_note": c.user_note,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in corrections
        ]

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

    def _fmt_time(self, iso_str: str) -> str:
        """Convert an ISO timestamp (with offset, including 'Z') to a friendly local time, e.g. '2:30 PM'."""
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_local = dt.astimezone(LOCAL_TZ)
        formatted = dt_local.strftime("%I:%M %p")
        return formatted.lstrip("0") if not formatted.startswith("0:") else formatted

    def _clean_text(self, text: str, max_len: int = 100) -> str:
        """Strip invisible unicode junk and truncate for display."""
        if not text:
            return ""
        cleaned = _INVISIBLE_CHARS_RE.sub("", text).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rstrip() + "..."
        return cleaned

    def _format_read_only_result(self, action_type: str, data: Any) -> Any:
        """Turn a raw MCP tool result into a human-friendly string for display."""
        if data is None:
            return data

        if action_type == "get_todays_schedule":
            events = data
            if not events:
                return "You have no events scheduled today."
            lines = []
            for ev in events:
                start = self._fmt_time(ev["start"])
                end = self._fmt_time(ev["end"])
                line = f"{start} - {end}: {ev.get('title', 'Untitled event')}"
                if ev.get("location"):
                    line += f" ({ev['location']})"
                lines.append(line)
            return "\n".join(lines)

        if action_type == "check_availability":
            if data.get("is_free"):
                return "You're free during that time."
            events = data.get("conflicting_events") or []
            if events:
                lines = ["You're busy during that time. Conflicts with:"]
                for ev in events:
                    start = self._fmt_time(ev["start"])
                    end = self._fmt_time(ev["end"])
                    lines.append(f"  - {ev.get('title', 'Untitled event')} ({start} - {end})")
                return "\n".join(lines)
            slots = data.get("busy_slots") or []
            if not slots:
                return "You're busy during that time."
            conflicts = ", ".join(
                f"{self._fmt_time(s['start'])} - {self._fmt_time(s['end'])}" for s in slots
            )
            return f"You're busy during that time. Conflicts: {conflicts}"

        if action_type == "summarise_emails":
            total = data.get("total_fetched", 0)
            if not total:
                return "No emails found."
            lines = [f"Fetched {total} recent emails:"]
            for category in ("work", "personal", "ambiguous"):
                emails = data.get(category) or []
                if not emails:
                    continue
                label = category.capitalize()
                lines.append(f"\n{label} ({len(emails)}):")
                for e in emails:
                    sender = self._clean_text(e.get("sender", ""), max_len=50)
                    subject = self._clean_text(e.get("subject", ""), max_len=80)
                    snippet = self._clean_text(e.get("snippet", ""), max_len=120)
                    lines.append(f"  - {sender}: {subject}")
                    if snippet:
                        lines.append(f"      {snippet}")
            return "\n".join(lines)

        return data