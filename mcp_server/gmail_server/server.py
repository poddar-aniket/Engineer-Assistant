"""
GmailMCPServer — Gmail plugin.
Tools: list_emails, get_email_body, send_email, create_draft
Tier-1 heuristic filter applied automatically on list_emails.
"""

from __future__ import annotations

import base64
import logging
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mcp_server.base.base_server import BaseMCPServer, ToolDefinition, ToolResult
from mcp_server.gmail_server.tier1_filter import filter_emails
from oauth_helper import get_google_credentials

logger = logging.getLogger(__name__)


class GmailMCPServer(BaseMCPServer):

    def __init__(self, name: str = "gmail"):
        super().__init__(name=name)
        self._service = None

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        try:
            creds = get_google_credentials()
            self._service = build("gmail", "v1", credentials=creds)
            self._initialized = True
            logger.info("GmailMCPServer initialized successfully.")
        except Exception as e:
            logger.error(f"GmailMCPServer initialization failed: {e}")
            raise

    async def shutdown(self) -> None:
        self._service = None
        self._initialized = False
        logger.info("GmailMCPServer shut down.")

    # ------------------------------------------------------------------ #
    #  Tool registry                                                       #
    # ------------------------------------------------------------------ #

    def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="list_emails",
                description="List recent emails with Tier-1 classification applied.",
                parameters={
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of emails to fetch (default 20).",
                        "default": 20,
                    },
                    "query": {
                        "type": "string",
                        "description": "Gmail search query e.g. 'is:unread' (default 'is:unread').",
                        "default": "is:unread",
                    },
                },
            ),
            ToolDefinition(
                name="get_email_body",
                description="Get the full body of a specific email by ID.",
                parameters={
                    "email_id": {
                        "type": "string",
                        "description": "Gmail message ID.",
                    }
                },
            ),
            ToolDefinition(
                name="send_email",
                description="Send an email (shown as draft card for approval before sending).",
                parameters={
                    "to": {"type": "string", "description": "Recipient email address."},
                    "subject": {"type": "string", "description": "Email subject."},
                    "body": {"type": "string", "description": "Plain text email body."},
                },
            ),
            ToolDefinition(
                name="create_draft",
                description="Save an email as a Gmail draft without sending.",
                parameters={
                    "to": {"type": "string", "description": "Recipient email address."},
                    "subject": {"type": "string", "description": "Email subject."},
                    "body": {"type": "string", "description": "Plain text email body."},
                },
            ),
        ]

    # ------------------------------------------------------------------ #
    #  Router                                                              #
    # ------------------------------------------------------------------ #

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        self._require_init()
        handlers = {
            "list_emails": self._list_emails,
            "get_email_body": self._get_email_body,
            "send_email": self._send_email,
            "create_draft": self._create_draft,
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

    def _list_emails(
        self, max_results: int = 20, query: str = "is:unread"
    ) -> dict:
        result = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = result.get("messages", [])
        emails = []
        for msg in messages:
            meta = self._get_email_metadata(msg["id"])
            if meta:
                emails.append(meta)

        # Apply Tier-1 filter
        classified = filter_emails(emails)
        return {
            "total_fetched": len(emails),
            "work": classified["work"],
            "personal": classified["personal"],
            "ambiguous": classified["ambiguous"],
        }

    def _get_email_metadata(self, email_id: str) -> dict | None:
        try:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=email_id, format="metadata",
                     metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            return {
                "email_id": email_id,
                "sender": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            }
        except HttpError as e:
            logger.warning(f"Could not fetch metadata for {email_id}: {e}")
            return None

    def _get_email_body(self, email_id: str) -> dict:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=email_id, format="full")
            .execute()
        )
        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        body = self._extract_body(msg.get("payload", {}))
        return {
            "email_id": email_id,
            "sender": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body,
        }

    def _send_email(self, to: str, subject: str, body: str) -> dict:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            self._service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return {
            "email_id": sent.get("id"),
            "status": "sent",
            "to": to,
            "subject": subject,
        }

    def _create_draft(self, to: str, subject: str, body: str) -> dict:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = (
            self._service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
        return {
            "draft_id": draft.get("id"),
            "status": "draft_created",
            "to": to,
            "subject": subject,
        }

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain text body from email payload."""
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Multipart — recurse into parts
        for part in payload.get("parts", []):
            result = self._extract_body(part)
            if result:
                return result

        return ""