import logging
from dataclasses import dataclass, field
from typing import Any

from mcp_server.base.base_server import BaseMCPServer
from orchestrator.core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BriefingSection:
    title: str
    content: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DailyBriefing:
    summary: str
    sections: list[BriefingSection] = field(default_factory=list)
    standup_draft: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "sections": [
                {"title": s.title, "content": s.content} for s in self.sections
            ],
            "standup_draft": self.standup_draft,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# BriefingGenerator
# ---------------------------------------------------------------------------


class BriefingGenerator:
    """
    Collects data from GitHub, Calendar, and Gmail MCP servers, then
    uses Gemini to produce a concise, actionable morning briefing.

    Usage:
        generator = BriefingGenerator(github, calendar, gmail, gemini_client)
        briefing  = await generator.generate()
    """

    def __init__(
        self,
        github_server: BaseMCPServer,
        calendar_server: BaseMCPServer,
        gmail_server: BaseMCPServer,
        gemini_client: GeminiClient,
    ) -> None:
        self._github = github_server
        self._calendar = calendar_server
        self._gmail = gmail_server
        self._gemini = gemini_client

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def generate(self) -> DailyBriefing:
        """Fetch all data, build the briefing, return a DailyBriefing."""
        errors: list[str] = []

        # 1. Fetch raw data from each MCP server concurrently-ish
        #    (sequential here — parallel would need asyncio.gather;
        #     kept sequential to stay under RPM limit easily)
        github_data = await self._fetch_github(errors)
        calendar_data = await self._fetch_calendar(errors)
        gmail_data = await self._fetch_gmail(errors)

        # 2. Build individual sections with Gemini summaries
        sections: list[BriefingSection] = []

        if github_data:
            sections.append(self._build_github_section(github_data))

        if calendar_data:
            sections.append(self._build_calendar_section(calendar_data))

        if gmail_data:
            sections.append(await self._build_gmail_section(gmail_data, errors))

        # 3. Generate overall summary + standup draft via Gemini
        summary, standup = self._generate_summary_and_standup(
            github_data, calendar_data, gmail_data, errors
        )

        return DailyBriefing(
            summary=summary,
            sections=sections,
            standup_draft=standup,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    async def _fetch_github(self, errors: list[str]) -> dict[str, Any]:
        data: dict[str, Any] = {}

        pr_result = await self._github.call_tool("get_actionable_prs", {})
        if pr_result.success:
            if isinstance(pr_result.data, dict):
                data["prs"] = pr_result.data.get("prs", [])
            else:
                data["prs"] = pr_result.data or []
        else:
            errors.append(f"GitHub PRs: {pr_result.error}")

        ci_result = await self._github.call_tool("get_ci_failures", {})
        if ci_result.success:
            failures_list = []
            if isinstance(ci_result.data, dict):
                failures_list = ci_result.data.get("failures", [])
            elif isinstance(ci_result.data, list):
                failures_list = ci_result.data

            data["ci_failures"] = failures_list
            # Correlate each failure with commits
            correlated = []
            for failure in failures_list:
                run_id = failure.get("id") or failure.get("run_id")
                if run_id:
                    corr = await self._github.call_tool(
                        "correlate_failure_with_commits",
                        {"run_id": run_id},
                    )
                    if corr.success:
                        correlated.append(corr.data)
            data["ci_correlations"] = correlated
        else:
            errors.append(f"GitHub CI: {ci_result.error}")

        activity_result = await self._github.call_tool("get_recent_activity", {})
        if activity_result.success:
            data["recent_activity"] = activity_result.data
        else:
            errors.append(f"GitHub activity: {activity_result.error}")

        return data

    async def _fetch_calendar(self, errors: list[str]) -> dict[str, Any]:
        data: dict[str, Any] = {}

        today_result = await self._calendar.call_tool("get_today_events", {})
        if today_result.success:
            data["today_events"] = today_result.data
        else:
            errors.append(f"Calendar today: {today_result.error}")

        upcoming_result = await self._calendar.call_tool(
            "get_upcoming_events", {"days": 2}
        )
        if upcoming_result.success:
            data["upcoming_events"] = upcoming_result.data
        else:
            errors.append(f"Calendar upcoming: {upcoming_result.error}")

        return data

    async def _fetch_gmail(self, errors: list[str]) -> dict[str, Any]:
        data: dict[str, Any] = {}

        email_result = await self._gmail.call_tool(
            "list_emails", {"max_results": 20}
        )
        if email_result.success:
            emails = email_result.data or {}
            data["work_emails"] = emails.get("work", [])
            data["personal_emails"] = emails.get("personal", [])
            data["ambiguous_emails"] = emails.get("ambiguous", [])
        else:
            errors.append(f"Gmail: {email_result.error}")

        return data

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_github_section(self, data: dict[str, Any]) -> BriefingSection:
        prs = data.get("prs") or []
        ci = data.get("ci_failures") or []
        correlations = data.get("ci_correlations") or []

        lines: list[str] = []

        if prs:
            lines.append(f"PRs needing attention ({len(prs)}):")
            for pr in prs[:5]:  # cap display at 5
                title = pr.get("title", "untitled")
                url = pr.get("url") or pr.get("html_url", "")
                lines.append(f"  - {title}  {url}")
        else:
            lines.append("No PRs need immediate attention.")

        if ci:
            lines.append(f"\nCI failures ({len(ci)}):")
            for i, failure in enumerate(ci[:3]):
                name = failure.get("name") or failure.get("workflow_name", "unknown")
                lines.append(f"  - {name}")
                if i < len(correlations) and correlations[i]:
                    commit = correlations[i]
                    sha = str(commit.get("sha", ""))[:7]
                    msg = commit.get("message", "")
                    lines.append(f"    -> likely cause: commit {sha} '{msg}'")
        else:
            lines.append("\nAll CI checks passing.")

        return BriefingSection(
            title="GitHub",
            content="\n".join(lines),
            raw=data,
        )

    def _build_calendar_section(self, data: dict[str, Any]) -> BriefingSection:
        today = data.get("today_events") or []
        upcoming = data.get("upcoming_events") or []

        lines: list[str] = []

        if today:
            lines.append(f"Today ({len(today)} events):")
            for event in today:
                start = event.get("start_time") or event.get("start", "")
                title = event.get("summary") or event.get("title", "untitled")
                lines.append(f"  {start}  {title}")
        else:
            lines.append("No events scheduled today.")

        if upcoming:
            lines.append(f"\nUpcoming (next 2 days):")
            for event in upcoming[:3]:
                date = event.get("date") or event.get("start_time", "")
                title = event.get("summary") or event.get("title", "untitled")
                lines.append(f"  {date}  {title}")

        return BriefingSection(
            title="Calendar",
            content="\n".join(lines),
            raw=data,
        )

    async def _build_gmail_section(
        self, data: dict[str, Any], errors: list[str]
    ) -> BriefingSection:
        work = data.get("work_emails") or []
        ambiguous = data.get("ambiguous_emails") or []

        lines: list[str] = []

        if work:
            lines.append(f"Work emails ({len(work)}):")
            for email in work[:5]:
                subject = email.get("subject", "(no subject)")
                sender = email.get("from") or email.get("sender", "unknown")
                lines.append(f"  - [{sender}] {subject}")
        else:
            lines.append("No work emails.")

        # Tier-2 Gemini classification for ambiguous emails
        if ambiguous:
            classified = await self._classify_ambiguous_emails(ambiguous, errors)
            tier2_work = [e for e in classified if e.get("tier2_label") == "work"]
            if tier2_work:
                lines.append(f"\nAdditional work-relevant emails ({len(tier2_work)}):")
                for email in tier2_work[:3]:
                    subject = email.get("subject", "(no subject)")
                    sender = email.get("from") or email.get("sender", "unknown")
                    lines.append(f"  - [{sender}] {subject}")

        return BriefingSection(
            title="Email",
            content="\n".join(lines),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Tier-2 email classification via Gemini
    # ------------------------------------------------------------------

    async def _classify_ambiguous_emails(
        self, emails: list[dict[str, Any]], errors: list[str]
    ) -> list[dict[str, Any]]:
        """
        Send batches of ambiguous emails to Gemini for work/personal classification.
        Batches of up to 5 to stay within RPM limits.
        """
        BATCH_SIZE = 5
        classified: list[dict[str, Any]] = []

        for i in range(0, len(emails), BATCH_SIZE):
            batch = emails[i : i + BATCH_SIZE]
            prompt = self._build_classification_prompt(batch)
            try:
                response_text = self._gemini.generate(prompt)
                labels = self._parse_classification_response(response_text, len(batch))
                for email, label in zip(batch, labels):
                    email["tier2_label"] = label
                    classified.append(email)
            except Exception as exc:
                errors.append(f"Tier-2 email classification: {exc}")
                # Mark as ambiguous so we don't silently drop them
                for email in batch:
                    email["tier2_label"] = "ambiguous"
                    classified.append(email)

        return classified

    @staticmethod
    def _build_classification_prompt(emails: list[dict[str, Any]]) -> str:
        lines = [
            "Classify each email as exactly 'work' or 'personal'. "
            "Reply with one label per line in the same order, nothing else.\n"
        ]
        for i, email in enumerate(emails, 1):
            subject = email.get("subject", "")
            sender = email.get("from") or email.get("sender", "")
            snippet = email.get("snippet", "")
            lines.append(f"{i}. From: {sender} | Subject: {subject} | Snippet: {snippet}")
        return "\n".join(lines)

    @staticmethod
    def _parse_classification_response(text: str, expected: int) -> list[str]:
        labels: list[str] = []
        for line in text.strip().splitlines():
            line = line.strip().lower()
            if "work" in line:
                labels.append("work")
            elif "personal" in line:
                labels.append("personal")
        # Pad with 'ambiguous' if Gemini returned fewer lines than expected
        while len(labels) < expected:
            labels.append("ambiguous")
        return labels[:expected]

    # ------------------------------------------------------------------
    # Overall summary + standup via Gemini
    # ------------------------------------------------------------------

    def _generate_summary_and_standup(
        self,
        github_data: dict[str, Any],
        calendar_data: dict[str, Any],
        gmail_data: dict[str, Any],
        errors: list[str],
    ) -> tuple[str, str]:
        prompt = self._build_briefing_prompt(github_data, calendar_data, gmail_data)
        try:
            response_text = self._gemini.generate(prompt)
            return self._parse_briefing_response(response_text)
        except Exception as exc:
            errors.append(f"Gemini briefing summary: {exc}")
            return "Briefing summary unavailable.", ""

    @staticmethod
    def _build_briefing_prompt(
        github: dict[str, Any],
        calendar: dict[str, Any],
        gmail: dict[str, Any],
    ) -> str:
        prs = github.get("prs") or []
        ci = github.get("ci_failures") or []
        activity = github.get("recent_activity") or []
        events = calendar.get("today_events") or []
        work_emails = gmail.get("work_emails") or []

        return f"""You are an engineer's AI assistant. Based on the data below, write:
1. A short summary (3-5 sentences) of the most important things to act on today.
2. A standup draft (what I did yesterday, what I plan today, any blockers) — keep it concise and professional.

Separate the two sections with exactly this delimiter on its own line: ---STANDUP---

DATA:
- Open PRs needing attention: {len(prs)} ({', '.join(p.get('title','') for p in prs[:3])})
- CI failures: {len(ci)}
- Recent GitHub activity: {len(activity)} events
- Calendar events today: {len(events)} ({', '.join(e.get('summary','') or e.get('title','') for e in events[:3])})
- Important work emails: {len(work_emails)}

Write only the two sections — no headings, no bullet points, no extra commentary."""

    @staticmethod
    def _parse_briefing_response(text: str) -> tuple[str, str]:
        delimiter = "---STANDUP---"
        if delimiter in text:
            parts = text.split(delimiter, 1)
            return parts[0].strip(), parts[1].strip()
        # If delimiter missing, treat whole text as summary
        return text.strip(), ""