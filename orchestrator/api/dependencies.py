# orchestrator/api/dependencies.py
from __future__ import annotations

import logging
from functools import lru_cache

from orchestrator.core import gemini_client
from orchestrator.core.mcp_registry import MCPRegistry
from orchestrator.core.gemini_client import GeminiClient
from orchestrator.core.agent_orchestrator import AgentOrchestrator
from orchestrator.repository.database import get_db
from orchestrator.repository.action_repository import ActionRepository
from config.settings import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_orchestrator() -> AgentOrchestrator:
    registry = MCPRegistry()
    github = registry.get("github")
    calendar = registry.get("calendar")
    gmail = registry.get("gmail")
    # gemini_client = GeminiClient(api_key=settings.GEMINI_API_KEY)
    gemini_client = GeminiClient()
    gemini_client.initialize()
    session = next(get_db())
    action_repo = ActionRepository(session)
    return AgentOrchestrator(
        github=github,
        calendar=calendar,
        gmail=gmail,
        gemini_client=gemini_client,
        action_repository=action_repo,
    )