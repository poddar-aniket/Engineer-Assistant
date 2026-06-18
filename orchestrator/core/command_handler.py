from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo
from config.settings import settings
from orchestrator.core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas — what Gemini can choose to call
# ---------------------------------------------------------------------------

COMMAND_TOOLS = [
    {
        "name": "schedule_meeting",
        "description": "Schedule a new calendar event or meeting.",
        "parameters": {
            "title": {"type": "string", "description": "Title of the meeting"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "start_time": {"type": "string", "description": "Start time in HH:MM 24h format"},
            "end_time": {"type": "string", "description": "End time in HH:MM 24h format"},
            "attendees": {"type": "string", "description": "Comma-separated email addresses of attendees"},
            "description": {"type": "string", "description": "Optional meeting description or agenda"},
        },
        "required": ["title", "date", "start_time", "end_time"],
    },
    {
        "name": "send_email",
        "description": "Send an email to one or more recipients.",
        "parameters": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Full email body text"},
            "cc": {"type": "string", "description": "Optional CC email addresses, comma-separated"},
        },
        "required": ["to", "subject", "body"],
    },
    {
        "name": "create_email_draft",
        "description": "Create an email draft without sending it.",
        "parameters": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Full email body text"},
        },
        "required": ["to", "subject", "body"],
    },
    {
        "name": "check_availability",
        "description": "Check calendar availability for a given date and time range.",
        "parameters": {
            "date": {"type": "string", "description": "Date to check in YYYY-MM-DD format"},
            "start_time": {"type": "string", "description": "Start of window in HH:MM 24h format"},
            "end_time": {"type": "string", "description": "End of window in HH:MM 24h format"},
        },
        "required": ["date", "start_time", "end_time"],
    },
    {
        "name": "add_calendar_event",
        "description": "Add a personal calendar event or reminder (no attendees).",
        "parameters": {
            "title": {"type": "string", "description": "Event title"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "start_time": {"type": "string", "description": "Start time in HH:MM 24h format"},
            "end_time": {"type": "string", "description": "End time in HH:MM 24h format"},
            "notes": {"type": "string", "description": "Optional notes for the event"},
        },
        "required": ["title", "date", "start_time", "end_time"],
    },
    {
        "name": "summarise_emails",
        "description": "Summarise recent emails from inbox, optionally filtered by sender or topic.",
        "parameters": {
            "filter_sender": {"type": "string", "description": "Optional sender email or name to filter by"},
            "filter_topic": {"type": "string", "description": "Optional topic or keyword to filter by"},
            "max_count": {"type": "integer", "description": "Maximum number of emails to summarise"},
        },
        "required": [],
    },
    {
        "name": "get_todays_schedule",
        "description": "Retrieve and display today's calendar events.",
        "parameters": {},
        "required": [],
    },
    {
        "name": "unknown_command",
        "description": "Use this when the user request does not match any supported action.",
        "parameters": {
            "reason": {"type": "string", "description": "Brief explanation of why the command is not supported"},
        },
        "required": ["reason"],
    },
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DraftAction:
    """
    A parsed, human-readable draft of what the assistant intends to do.
    Nothing is executed until the user approves it (Day 4 approval layer).
    """

    action_type: str          # e.g. "schedule_meeting", "send_email"
    params: dict[str, Any]    # raw args from Gemini
    display: str              # human-readable summary shown to the user
    requires_approval: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "params": self.params,
            "display": self.display,
            "requires_approval": self.requires_approval,
            "metadata": self.metadata,
        }


@dataclass
class CommandResult:
    success: bool
    draft_action: DraftAction | None = None
    error: str | None = None
    raw_command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "draft_action": self.draft_action.to_dict() if self.draft_action else None,
            "error": self.error,
            "raw_command": self.raw_command,
        }


# ---------------------------------------------------------------------------
# CommandHandler
# ---------------------------------------------------------------------------


class CommandHandler:
    """
    Interprets a free-text user command using Gemini function-calling
    and returns a DraftAction ready for user approval.

    Nothing is executed here — execution happens in the Day 4 approval layer.

    Usage:
        handler = CommandHandler(gemini_client)
        result  = await handler.handle("Schedule a 1:1 with Sarah tomorrow at 3pm")
    """
    READ_ONLY_ACTIONS = {"summarise_emails", "get_todays_schedule", "check_availability"}

    def __init__(
        self,
        gemini_client: GeminiClient,
        personalization_engine=None,
    ) -> None:
        self._gemini = gemini_client
        self._personalization = personalization_engine

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def handle(self, user_command: str) -> CommandResult:
        """
        Parse a free-text command and return a CommandResult with a DraftAction.
        Always returns a CommandResult — never raises.
        """
        if not user_command or not user_command.strip():
            return CommandResult(
                success=False,
                error="Empty command received.",
                raw_command=user_command,
            )

        try:
            prompt = self._build_prompt(user_command)
            if self._personalization:
                action_hint = "general"
                prompt = self._personalization.build_personalized_prompt(
                    base_prompt=prompt,
                    action_type=action_hint,
                )
            fc = self._gemini.function_call(prompt, COMMAND_TOOLS)
            action_type = fc.get("name", "general")
            if self._personalization and action_type not in ("unknown_command", "general"):
                refined_prompt = self._personalization.build_personalized_prompt(
                    base_prompt=prompt,
                    action_type=action_type,
                )
                if refined_prompt != prompt:
                    fc = self._gemini.function_call(refined_prompt, COMMAND_TOOLS)
            draft = self._build_draft_action(fc, user_command)
            return CommandResult(
                success=True,
                draft_action=draft,
                raw_command=user_command,
            )
        except Exception as exc:
            logger.error("CommandHandler failed for '%s': %s", user_command, exc)
            return CommandResult(
                success=False,
                error=str(exc),
                raw_command=user_command,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(user_command: str) -> str:
        today_str = datetime.now(ZoneInfo(settings.LOCAL_TIMEZONE)).strftime("%Y-%m-%d")
        return f"""You are an AI assistant for a software engineer.
    The user has typed the following command:

    "{user_command}"

    Choose the most appropriate function to call based on what the user wants to do.
    Fill in all required parameters. Infer reasonable values from context where possible.
    Today's date is {today_str}. Use this as the reference point when the user says
    "today", "tomorrow", "next Monday", or any other relative date expression.
    Use ISO date format (YYYY-MM-DD) for dates, 24-hour HH:MM for times.
    When converting times with AM/PM, follow these examples exactly:
    "4 AM" -> "04:00", "9 AM" -> "09:00", "12 PM" -> "12:00",
    "5 PM" -> "17:00", "11 PM" -> "23:00", "12 AM" -> "00:00".
    IMPORTANT: For schedule_meeting and add_calendar_event, you MUST provide both
    "start_time" and "end_time" as separate HH:MM fields. Never use "time" or
    "duration_minutes" as substitutes.
    If the command does not match any supported action, call unknown_command."""

    def _build_draft_action(
        self, fc: dict[str, Any], raw_command: str
    ) -> DraftAction:
        name = fc.get("name", "unknown_command")
        args = fc.get("args", {})

        display = self._format_display(name, args, raw_command)
        logger.info("action_type=%s requires_approval check: READ_ONLY_ACTIONS=%s", name, self.READ_ONLY_ACTIONS)
        requires_approval = (
            name != "unknown_command"
            and name not in self.READ_ONLY_ACTIONS
        )

        return DraftAction(
            action_type=name,
            params=args,
            display=display,
            requires_approval=requires_approval,
        )

    @staticmethod
    def _format_display(
        action_type: str, args: dict[str, Any], raw_command: str
    ) -> str:
        """Produce a clear human-readable summary of the draft action."""

        if action_type == "schedule_meeting":
            title = args.get("title", "meeting")
            date = args.get("date", "unknown date")
            start = args.get("start_time", "")
            end = args.get("end_time", "")
            attendees = args.get("attendees", "")
            time_str = f"{start} - {end}" if start and end else ""
            attendee_str = f" with {attendees}" if attendees else ""
            return (
                f"Schedule meeting: '{title}'{attendee_str}\n"
                f"  Date: {date}  {time_str}"
            )

        if action_type == "send_email":
            to = args.get("to", "unknown")
            subject = args.get("subject", "(no subject)")
            body_preview = (args.get("body", "")[:80] + "...") if len(args.get("body", "")) > 80 else args.get("body", "")
            return (
                f"Send email to: {to}\n"
                f"  Subject: {subject}\n"
                f"  Body preview: {body_preview}"
            )

        if action_type == "create_email_draft":
            to = args.get("to", "unknown")
            subject = args.get("subject", "(no subject)")
            return f"Create email draft to: {to}\n  Subject: {subject}"

        if action_type == "check_availability":
            date = args.get("date", "unknown date")
            start = args.get("start_time", "")
            end = args.get("end_time", "")
            return f"Check availability on {date} from {start} to {end}"

        if action_type == "add_calendar_event":
            title = args.get("title", "event")
            date = args.get("date", "unknown date")
            start = args.get("start_time", "")
            end = args.get("end_time", "")
            return f"Add calendar event: '{title}'\n  Date: {date}  {start} - {end}"

        if action_type == "summarise_emails":
            parts = []
            if args.get("filter_sender"):
                parts.append(f"from {args['filter_sender']}")
            if args.get("filter_topic"):
                parts.append(f"about '{args['filter_topic']}'")
            filter_str = " ".join(parts) if parts else "recent inbox"
            count = args.get("max_count", 10)
            return f"Summarise up to {count} emails ({filter_str})"

        if action_type == "get_todays_schedule":
            return "Fetch and display today's calendar schedule"

        if action_type == "unknown_command":
            reason = args.get("reason", "Command not recognised")
            return f"Cannot process command: {reason}\n  Original: \"{raw_command}\""

        # Fallback for any future actions
        return f"Action: {action_type}\n  Args: {args}"