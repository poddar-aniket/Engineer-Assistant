"""
CalendarMCPServer — Google Calendar plugin.
Tools: get_today_events, get_upcoming_events, check_availability, create_event
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mcp_server.base.base_server import BaseMCPServer, ToolDefinition, ToolResult
from oauth_helper import get_google_credentials

logger = logging.getLogger(__name__)


class CalendarMCPServer(BaseMCPServer):

    def __init__(self, name: str = "calendar"):
        super().__init__(name=name)
        self._service = None

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        try:
            creds = get_google_credentials()
            self._service = build("calendar", "v3", credentials=creds)
            self._initialized = True
            logger.info("CalendarMCPServer initialized successfully.")
        except Exception as e:
            logger.error(f"CalendarMCPServer initialization failed: {e}")
            raise

    async def shutdown(self) -> None:
        self._service = None
        self._initialized = False
        logger.info("CalendarMCPServer shut down.")

    # ------------------------------------------------------------------ #
    #  Tool registry                                                       #
    # ------------------------------------------------------------------ #

    def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="get_today_events",
                description="Get all calendar events for today.",
                parameters={},
            ),
            ToolDefinition(
                name="get_upcoming_events",
                description="Get upcoming events for the next N days.",
                parameters={
                    "days": {
                        "type": "integer",
                        "description": "Number of days to look ahead (default 7).",
                        "default": 7,
                    }
                },
            ),
            ToolDefinition(
                name="check_availability",
                description="Check if a time slot is free.",
                parameters={
                    "start_time": {
                        "type": "string",
                        "description": "ISO 8601 start datetime e.g. 2025-06-16T10:00:00",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "ISO 8601 end datetime e.g. 2025-06-16T11:00:00",
                    },
                },
            ),
            ToolDefinition(
                name="create_event",
                description="Create a new calendar event (draft — shown to user before saving).",
                parameters={
                    "title": {"type": "string", "description": "Event title."},
                    "start_time": {
                        "type": "string",
                        "description": "ISO 8601 start datetime.",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "ISO 8601 end datetime.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event description.",
                        "default": "",
                    },
                    "attendees": {
                        "type": "array",
                        "description": "Optional list of attendee email addresses.",
                        "default": [],
                    },
                },
            ),
        ]

    # ------------------------------------------------------------------ #
    #  Router                                                              #
    # ------------------------------------------------------------------ #

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        self._require_init()
        handlers = {
            "get_today_events": self._get_today_events,
            "get_upcoming_events": self._get_upcoming_events,
            "check_availability": self._check_availability,
            "create_event": self._create_event,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Unknown tool: {tool_name}",
            )
        try:
            data = handler(**params)
            return ToolResult(tool_name=tool_name, success=True, data=data)
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {e}")
            return ToolResult(tool_name=tool_name, success=False, error=str(e))

    # ------------------------------------------------------------------ #
    #  Tool implementations                                                #
    # ------------------------------------------------------------------ #

    def _get_today_events(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        result = (
            self._service.events()
            .list(
                calendarId="primary",
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return self._parse_events(result.get("items", []))

    def _get_upcoming_events(self, days: int = 7) -> list[dict]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)

        result = (
            self._service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
        return self._parse_events(result.get("items", []))

    def _check_availability(self, start_time: str, end_time: str) -> dict:
        start_dt = datetime.fromisoformat(start_time).astimezone(timezone.utc)
        end_dt = datetime.fromisoformat(end_time).astimezone(timezone.utc)

        result = (
            self._service.freebusy()
            .query(
                body={
                    "timeMin": start_dt.isoformat(),
                    "timeMax": end_dt.isoformat(),
                    "items": [{"id": "primary"}],
                }
            )
            .execute()
        )
        busy_slots = result.get("calendars", {}).get("primary", {}).get("busy", [])
        return {
            "is_free": len(busy_slots) == 0,
            "busy_slots": busy_slots,
            "checked_from": start_time,
            "checked_to": end_time,
        }

    def _create_event(
        self,
        title: str,
        start_time: str,
        end_time: str,
        description: str = "",
        attendees: list[str] = [],
    ) -> dict:
        event_body = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": datetime.fromisoformat(start_time).isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": datetime.fromisoformat(end_time).isoformat(),
                "timeZone": "UTC",
            },
        }
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]

        created = (
            self._service.events()
            .insert(calendarId="primary", body=event_body)
            .execute()
        )
        return {
            "event_id": created.get("id"),
            "title": created.get("summary"),
            "start": created.get("start"),
            "end": created.get("end"),
            "link": created.get("htmlLink"),
        }

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _parse_events(self, items: list[dict]) -> list[dict]:
        events = []
        for item in items:
            start = item.get("start", {})
            end = item.get("end", {})
            events.append(
                {
                    "event_id": item.get("id"),
                    "title": item.get("summary", "(No title)"),
                    "start": start.get("dateTime") or start.get("date"),
                    "end": end.get("dateTime") or end.get("date"),
                    "location": item.get("location", ""),
                    "description": item.get("description", ""),
                    "attendees": [
                        a.get("email") for a in item.get("attendees", [])
                    ],
                    "meeting_link": item.get("hangoutLink", ""),
                    "status": item.get("status", ""),
                }
            )
        return events