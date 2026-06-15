"""
GitHubMCPServer — Day 1 plugin
Tools:
  1. get_actionable_prs             — PRs needing the user's attention
  2. get_ci_failures                — failed workflow runs across watched repos
  3. correlate_failure_with_commits — links a failed run to likely causative commits
  4. get_recent_activity            — user's pushes/merges for standup generation
"""

from __future__ import annotations

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from github import Github, GithubException, Auth

# ---------------------------------------------------------------------------
# Make sure the project root is importable regardless of how the file is run
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp_server.base.base_server import BaseMCPServer, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class GitHubMCPServer(BaseMCPServer):
    """MCP plugin that exposes GitHub data as callable tools."""

    def __init__(self, name: str = "github") -> None:
        super().__init__(name=name)
        self._client: Github | None = None
        self._authenticated_user = None

    # ---------------------------------------------------------------- lifecycle

    async def initialize(self) -> None:
        """Validate PAT and create GitHub client. Fails fast on bad token."""
        token = os.getenv("GITHUB_PAT")
        if not token:
            raise RuntimeError(
                "GITHUB_PAT environment variable is not set. "
                "Add it to your .env file."
            )

        self._client = Github(auth=Auth.Token(token))

        try:
            self._authenticated_user = self._client.get_user()
            _ = self._authenticated_user.login  # forces actual API call
        except GithubException as exc:
            raise RuntimeError(
                f"GitHub authentication failed (status {exc.status}): {exc.data}"
            ) from exc

        self._initialized = True
        logger.info(
            "GitHubMCPServer initialised — authenticated as '%s'",
            self._authenticated_user.login,
        )

    async def shutdown(self) -> None:
        if self._client:
            self._client.close()
        self._initialized = False
        logger.info("GitHubMCPServer shut down.")

    async def health_check(self) -> bool:
        if not self._initialized or not self._client:
            return False
        try:
            _ = self._authenticated_user.login
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------- tool registry

    def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="get_actionable_prs",
                description=(
                    "Returns open pull requests that need the authenticated user's "
                    "attention: PRs where they are a requested reviewer, PRs they "
                    "authored that have new review comments, and PRs that are ready "
                    "to merge. Optionally filter by a specific repo."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": (
                                "Full repo name (owner/repo). "
                                "If omitted, scans all repos the user has access to."
                            ),
                        },
                        "max_prs": {
                            "type": "integer",
                            "description": "Maximum PRs to return (default 20).",
                            "default": 20,
                        },
                    },
                    "required": [],
                },
            ),
            ToolDefinition(
                name="get_ci_failures",
                description=(
                    "Returns recent failed GitHub Actions workflow runs across the "
                    "user's repositories. Each result includes the repo, workflow "
                    "name, branch, commit SHA, and a link to the run logs."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": (
                                "Full repo name (owner/repo). "
                                "If omitted, scans all repos the user has access to."
                            ),
                        },
                        "hours_back": {
                            "type": "integer",
                            "description": "How many hours back to look (default 24).",
                            "default": 24,
                        },
                        "max_failures": {
                            "type": "integer",
                            "description": "Maximum failures to return (default 10).",
                            "default": 10,
                        },
                    },
                    "required": [],
                },
            ),
            ToolDefinition(
                name="correlate_failure_with_commits",
                description=(
                    "Given a failed workflow run ID and repo, returns the commits "
                    "pushed to the branch in the 2 hours before the run started. "
                    "These are the most likely candidates that caused the failure."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "Full repo name (owner/repo).",
                        },
                        "run_id": {
                            "type": "integer",
                            "description": "The GitHub Actions workflow run ID.",
                        },
                        "window_minutes": {
                            "type": "integer",
                            "description": (
                                "How many minutes before the run to look for commits "
                                "(default 120)."
                            ),
                            "default": 120,
                        },
                    },
                    "required": ["repo_name", "run_id"],
                },
            ),
            ToolDefinition(
                name="get_recent_activity",
                description=(
                    "Returns the authenticated user's recent GitHub activity: "
                    "commits pushed, PRs opened/merged, and issues closed. "
                    "Ideal for generating a daily standup summary."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "hours_back": {
                            "type": "integer",
                            "description": "How many hours back to look (default 24).",
                            "default": 24,
                        },
                        "repo_name": {
                            "type": "string",
                            "description": (
                                "Limit to a specific repo (owner/repo). "
                                "If omitted, scans all repos."
                            ),
                        },
                    },
                    "required": [],
                },
            ),
        ]

    # ---------------------------------------------------------------- dispatch

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        self._require_init()

        dispatch = {
            "get_actionable_prs": self._get_actionable_prs,
            "get_ci_failures": self._get_ci_failures,
            "correlate_failure_with_commits": self._correlate_failure_with_commits,
            "get_recent_activity": self._get_recent_activity,
        }

        handler = dispatch.get(tool_name)
        if handler is None:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                data=None,
                error=f"Unknown tool: '{tool_name}'",
            )

        try:
            data = handler(**params)
            return ToolResult(tool_name=tool_name, success=True, data=data, error=None)
        except GithubException as exc:
            logger.error("GitHub API error in %s: %s", tool_name, exc)
            return ToolResult(
                tool_name=tool_name,
                success=False,
                data=None,
                error=f"GitHub API error (status {exc.status}): {exc.data}",
            )
        except Exception as exc:
            logger.exception("Unexpected error in %s", tool_name)
            return ToolResult(
                tool_name=tool_name,
                success=False,
                data=None,
                error=str(exc),
            )

    # ================================================================ TOOL IMPLEMENTATIONS

    # ---------------------------------------------------------------- tool 1

    def _get_actionable_prs(
        self,
        repo_name: str | None = None,
        max_prs: int = 20,
    ) -> dict[str, Any]:
        """PRs needing the user's attention."""
        user_login = self._authenticated_user.login
        actionable: list[dict] = []

        repos = self._get_repos(repo_name)

        for repo in repos:
            try:
                open_prs = repo.get_pulls(state="open", sort="updated", direction="desc")
                for pr in open_prs:
                    if len(actionable) >= max_prs:
                        break

                    reasons: list[str] = []

                    reviewer_logins = [r.login for r in pr.requested_reviewers]
                    if user_login in reviewer_logins:
                        reasons.append("you are a requested reviewer")

                    if pr.user.login == user_login and pr.review_comments > 0:
                        reasons.append(
                            f"your PR has {pr.review_comments} review comment(s)"
                        )

                    if pr.user.login == user_login and pr.mergeable_state == "clean":
                        reasons.append("ready to merge")

                    if reasons:
                        actionable.append(
                            {
                                "repo": repo.full_name,
                                "pr_number": pr.number,
                                "title": pr.title,
                                "author": pr.user.login,
                                "url": pr.html_url,
                                "draft": pr.draft,
                                "created_at": pr.created_at.isoformat(),
                                "updated_at": pr.updated_at.isoformat(),
                                "reasons": reasons,
                                "review_comments": pr.review_comments,
                                "mergeable_state": pr.mergeable_state,
                            }
                        )
            except GithubException as exc:
                logger.warning("Skipping repo %s: %s", repo.full_name, exc)
                continue

        return {
            "user": user_login,
            "actionable_pr_count": len(actionable),
            "prs": actionable,
        }

    # ---------------------------------------------------------------- tool 2

    def _get_ci_failures(
        self,
        repo_name: str | None = None,
        hours_back: int = 24,
        max_failures: int = 10,
    ) -> dict[str, Any]:
        """Failed workflow runs in the past N hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        failures: list[dict] = []

        repos = self._get_repos(repo_name)

        for repo in repos:
            if len(failures) >= max_failures:
                break
            try:
                runs = repo.get_workflow_runs(status="failure")
                for run in runs:
                    if len(failures) >= max_failures:
                        break
                    run_time = self._ensure_utc(run.created_at)
                    if run_time < cutoff:
                        break
                    failures.append(
                        {
                            "repo": repo.full_name,
                            "run_id": run.id,
                            "workflow_name": run.name,
                            "branch": run.head_branch,
                            "commit_sha": run.head_sha,
                            "commit_message": run.head_commit.message
                            if run.head_commit
                            else None,
                            "triggered_by": run.event,
                            "started_at": run_time.isoformat(),
                            "url": run.html_url,
                        }
                    )
            except GithubException as exc:
                logger.warning("Skipping repo %s: %s", repo.full_name, exc)
                continue

        return {
            "hours_back": hours_back,
            "failure_count": len(failures),
            "failures": failures,
        }

    # ---------------------------------------------------------------- tool 3

    def _correlate_failure_with_commits(
        self,
        repo_name: str,
        run_id: int,
        window_minutes: int = 120,
    ) -> dict[str, Any]:
        """Commits pushed to the branch in the window before a failed run."""
        repo = self._client.get_repo(repo_name)
        run = repo.get_workflow_run(run_id)

        run_start = self._ensure_utc(run.created_at)
        window_start = run_start - timedelta(minutes=window_minutes)
        branch = run.head_branch

        commits_in_window: list[dict] = []
        try:
            commits = repo.get_commits(
                sha=branch,
                since=window_start,
                until=run_start,
            )
            for commit in commits:
                author_login = commit.author.login if commit.author else "unknown"
                commits_in_window.append(
                    {
                        "sha": commit.sha,
                        "short_sha": commit.sha[:7],
                        "message": commit.commit.message.splitlines()[0],
                        "author": author_login,
                        "committed_at": self._ensure_utc(
                            commit.commit.author.date
                        ).isoformat(),
                        "url": commit.html_url,
                    }
                )
        except GithubException as exc:
            logger.warning("Could not fetch commits for branch %s: %s", branch, exc)

        return {
            "repo": repo_name,
            "run_id": run_id,
            "workflow_name": run.name,
            "branch": branch,
            "run_started_at": run_start.isoformat(),
            "window_start": window_start.isoformat(),
            "window_minutes": window_minutes,
            "likely_causative_commits": commits_in_window,
            "commit_count": len(commits_in_window),
            "note": (
                "These commits were pushed to the branch in the window before the "
                "failing run started. Review them to identify the root cause."
            ),
        }

    # ---------------------------------------------------------------- tool 4

    def _get_recent_activity(
        self,
        hours_back: int = 24,
        repo_name: str | None = None,
    ) -> dict[str, Any]:
        """User's recent pushes, PRs, and closed issues for standup generation."""
        user_login = self._authenticated_user.login
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        pushes: list[dict] = []
        prs_opened: list[dict] = []
        prs_merged: list[dict] = []
        issues_closed: list[dict] = []

        repos = self._get_repos(repo_name)

        for repo in repos:
            try:
                # commits
                try:
                    commits = repo.get_commits(author=user_login, since=cutoff)
                    for commit in commits:
                        pushes.append(
                            {
                                "repo": repo.full_name,
                                "sha": commit.sha[:7],
                                "message": commit.commit.message.splitlines()[0],
                                "url": commit.html_url,
                                "committed_at": self._ensure_utc(
                                    commit.commit.author.date
                                ).isoformat(),
                            }
                        )
                except GithubException:
                    pass

                # PRs
                pulls = repo.get_pulls(state="all", sort="updated", direction="desc")
                for pr in pulls:
                    updated = self._ensure_utc(pr.updated_at)
                    if updated < cutoff:
                        break
                    if pr.user.login != user_login:
                        continue

                    created = self._ensure_utc(pr.created_at)
                    if created >= cutoff:
                        prs_opened.append(
                            {
                                "repo": repo.full_name,
                                "pr_number": pr.number,
                                "title": pr.title,
                                "url": pr.html_url,
                                "created_at": created.isoformat(),
                            }
                        )

                    if pr.merged and pr.merged_at:
                        merged_at = self._ensure_utc(pr.merged_at)
                        if merged_at >= cutoff:
                            prs_merged.append(
                                {
                                    "repo": repo.full_name,
                                    "pr_number": pr.number,
                                    "title": pr.title,
                                    "url": pr.html_url,
                                    "merged_at": merged_at.isoformat(),
                                }
                            )

                # issues closed
                issues = repo.get_issues(
                    state="closed",
                    assignee=user_login,
                    sort="updated",
                    direction="desc",
                    since=cutoff,
                )
                for issue in issues:
                    if issue.pull_request:
                        continue
                    closed_at = self._ensure_utc(issue.closed_at) if issue.closed_at else None
                    if closed_at and closed_at >= cutoff:
                        issues_closed.append(
                            {
                                "repo": repo.full_name,
                                "issue_number": issue.number,
                                "title": issue.title,
                                "url": issue.html_url,
                                "closed_at": closed_at.isoformat(),
                            }
                        )

            except GithubException as exc:
                logger.warning("Skipping repo %s: %s", repo.full_name, exc)
                continue

        return {
            "user": user_login,
            "hours_back": hours_back,
            "summary": {
                "commits_pushed": len(pushes),
                "prs_opened": len(prs_opened),
                "prs_merged": len(prs_merged),
                "issues_closed": len(issues_closed),
            },
            "commits": pushes,
            "prs_opened": prs_opened,
            "prs_merged": prs_merged,
            "issues_closed": issues_closed,
        }

    # ================================================================ HELPERS

    def _get_repos(self, repo_name: str | None):
        if repo_name:
            return [self._client.get_repo(repo_name)]
        return list(self._authenticated_user.get_repos(sort="updated", direction="desc"))

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime:
        if dt is None:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)