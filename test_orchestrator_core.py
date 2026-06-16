"""
Smoke test for Day 3 — Orchestrator Core.

Tests:
1. GeminiClient initialises and generates text
2. CommandHandler parses free-text commands into DraftActions
3. BriefingGenerator assembles a full DailyBriefing from mock MCP servers

Run from project root:
    python test_orchestrator_core.py
"""

import asyncio
import logging
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimal mock MCP server for testing without real API calls
# ---------------------------------------------------------------------------

from mcp_server.base.base_server import BaseMCPServer, ToolDefinition, ToolResult


class MockMCPServer(BaseMCPServer):
    """Returns canned data so the briefing test never hits real APIs."""

    def __init__(self, name: str, responses: dict[str, Any]) -> None:
        super().__init__(name=name)
        self._responses = responses

    async def initialize(self) -> None:
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False

    def list_tools(self) -> list[ToolDefinition]:
        return []

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        if tool_name in self._responses:
            return ToolResult(tool_name=tool_name, success=True, data=self._responses[tool_name])
        return ToolResult(tool_name=tool_name, success=False, error="tool not found in mock")


# ---------------------------------------------------------------------------
# Test 1 — GeminiClient
# ---------------------------------------------------------------------------


def test_gemini_client_init() -> bool:
    logger.info("Test 1: GeminiClient initialises")
    try:
        from orchestrator.core.gemini_client import GeminiClient
        client = GeminiClient()
        client.initialize()
        logger.info("  PASS: GeminiClient initialised with model=%s",
                    __import__("config.settings", fromlist=["settings"]).settings.GEMINI_MODEL)
        return True
    except Exception as exc:
        logger.error("  FAIL: %s", exc)
        return False


def test_gemini_generate() -> bool:
    logger.info("Test 2: GeminiClient.generate() returns text")
    try:
        from orchestrator.core.gemini_client import GeminiClient
        client = GeminiClient()
        client.initialize()
        result = client.generate("Reply with exactly: hello")
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        # result is the raw response object text
        logger.info("  PASS: got response (length=%d)", len(str(result)))
        return True
    except Exception as exc:
        logger.error("  FAIL: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Test 2 — CommandHandler
# ---------------------------------------------------------------------------


def test_command_handler_schedule() -> bool:
    logger.info("Test 3: CommandHandler parses scheduling command")
    try:
        from orchestrator.core.gemini_client import GeminiClient
        from orchestrator.core.command_handler import CommandHandler

        client = GeminiClient()
        client.initialize()

        handler = CommandHandler(client)
        result = asyncio.run(handler.handle("Schedule a 1:1 with Sarah tomorrow at 3pm for 30 minutes"))

        assert result.success, f"Handler failed: {result.error}"
        assert result.draft_action is not None
        logger.info("  PASS: action_type=%s", result.draft_action.action_type)
        logger.info("  display:\n%s", result.draft_action.display)
        return True
    except Exception as exc:
        logger.error("  FAIL: %s", exc)
        return False


def test_command_handler_email() -> bool:
    logger.info("Test 4: CommandHandler parses email command")
    try:
        from orchestrator.core.gemini_client import GeminiClient
        from orchestrator.core.command_handler import CommandHandler

        client = GeminiClient()
        client.initialize()

        handler = CommandHandler(client)
        result = asyncio.run(handler.handle(
            "Send an email to john@example.com saying the PR review is done and they can merge"
        ))

        assert result.success, f"Handler failed: {result.error}"
        assert result.draft_action is not None
        assert result.draft_action.action_type in ("send_email", "create_email_draft")
        logger.info("  PASS: action_type=%s", result.draft_action.action_type)
        logger.info("  display:\n%s", result.draft_action.display)
        return True
    except Exception as exc:
        logger.error("  FAIL: %s", exc)
        return False


def test_command_handler_unknown() -> bool:
    logger.info("Test 5: CommandHandler handles unknown command gracefully")
    try:
        from orchestrator.core.gemini_client import GeminiClient
        from orchestrator.core.command_handler import CommandHandler

        client = GeminiClient()
        client.initialize()

        handler = CommandHandler(client)
        result = asyncio.run(handler.handle("Order me a pizza"))

        # Should succeed but return unknown_command action
        assert result.success or result.error is not None
        if result.draft_action:
            logger.info("  PASS: action_type=%s", result.draft_action.action_type)
        else:
            logger.info("  PASS: returned error gracefully: %s", result.error)
        return True
    except Exception as exc:
        logger.error("  FAIL: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Test 3 — BriefingGenerator with mock MCP servers
# ---------------------------------------------------------------------------


async def _run_briefing_test() -> bool:
    from orchestrator.core.gemini_client import GeminiClient
    from orchestrator.briefing.briefing_generator import BriefingGenerator

    github_mock = MockMCPServer(
        name="github",
        responses={
            "get_actionable_prs": [
                {"title": "feat: add dark mode", "html_url": "https://github.com/org/repo/pull/42"},
                {"title": "fix: null pointer in auth", "html_url": "https://github.com/org/repo/pull/43"},
            ],
            "get_ci_failures": [],
            "correlate_failure_with_commits": None,
            "get_recent_activity": [
                {"type": "PushEvent", "repo": "org/repo"},
            ],
        },
    )

    calendar_mock = MockMCPServer(
        name="calendar",
        responses={
            "get_today_events": [
                {"summary": "Team standup", "start_time": "09:00"},
                {"summary": "Sprint planning", "start_time": "14:00"},
            ],
            "get_upcoming_events": [
                {"summary": "1:1 with manager", "start_time": "2025-01-16 10:00"},
            ],
        },
    )

    gmail_mock = MockMCPServer(
        name="gmail",
        responses={
            "list_emails": {
                "work": [
                    {"subject": "PR review requested", "from": "alice@company.com", "snippet": "Please review..."},
                    {"subject": "Deploy schedule", "from": "devops@company.com", "snippet": "Deploying tonight..."},
                ],
                "personal": [
                    {"subject": "Weekend plans", "from": "friend@gmail.com"},
                ],
                "ambiguous": [],
            },
        },
    )

    await github_mock.initialize()
    await calendar_mock.initialize()
    await gmail_mock.initialize()

    client = GeminiClient()
    client.initialize()

    generator = BriefingGenerator(
        github_server=github_mock,
        calendar_server=calendar_mock,
        gmail_server=gmail_mock,
        gemini_client=client,
    )

    briefing = await generator.generate()

    assert briefing.summary, "Summary should not be empty"
    assert len(briefing.sections) > 0, "Should have at least one section"
    logger.info("  PASS: briefing generated")
    logger.info("  Sections: %s", [s.title for s in briefing.sections])
    logger.info("  Summary (first 200 chars): %s", briefing.summary[:200])
    if briefing.standup_draft:
        logger.info("  Standup draft (first 200 chars): %s", briefing.standup_draft[:200])
    if briefing.errors:
        logger.warning("  Non-fatal errors: %s", briefing.errors)

    return True


def test_briefing_generator() -> bool:
    logger.info("Test 6: BriefingGenerator produces DailyBriefing")
    try:
        return asyncio.run(_run_briefing_test())
    except Exception as exc:
        logger.error("  FAIL: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info("=" * 60)
    logger.info("Day 3 Smoke Test — Orchestrator Core")
    logger.info("=" * 60)

    tests = [
        test_gemini_client_init,
        test_gemini_generate,
        test_command_handler_schedule,
        test_command_handler_email,
        test_command_handler_unknown,
        test_briefing_generator,
    ]

    results = []
    for test in tests:
        results.append(test())
        logger.info("")

    passed = sum(results)
    total = len(results)

    logger.info("=" * 60)
    logger.info("Results: %d/%d passed", passed, total)
    logger.info("=" * 60)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()