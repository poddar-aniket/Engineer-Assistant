# orchestrator/api/router.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator.core.agent_orchestrator import AgentOrchestrator
from orchestrator.repository.action_repository import ActionRepository
from orchestrator.repository.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------
# Request schemas
# ------------------------------------------------------------------

class CommandRequest(BaseModel):
    user_input: str

class RejectRequest(BaseModel):
    reason: str = ""


# ------------------------------------------------------------------
# Dependency: builds AgentOrchestrator per-request using the
# shared MCPRegistry + per-request DB session
# ------------------------------------------------------------------

def get_orchestrator(db: Session = Depends(get_db)) -> AgentOrchestrator:
    from orchestrator.api.main import registry, gemini_client
    action_repo = ActionRepository(db)
    return AgentOrchestrator(
        github=registry.get("github"),
        calendar=registry.get("calendar"),
        gmail=registry.get("gmail"),
        gemini_client=gemini_client,
        action_repository=action_repo,
    )


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.get("/briefing")
async def get_briefing(orch: AgentOrchestrator = Depends(get_orchestrator)):
    result = await orch.get_briefing()
    return result


@router.post("/command")
async def handle_command(
    body: CommandRequest,
    orch: AgentOrchestrator = Depends(get_orchestrator),
):
    result = await orch.handle_command(body.user_input)
    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/actions/pending")
def get_pending_actions(orch: AgentOrchestrator = Depends(get_orchestrator)):
    return orch.get_pending_actions()


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: int,
    orch: AgentOrchestrator = Depends(get_orchestrator),
):
    result = await orch.approve_action(action_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/actions/{action_id}/reject")
def reject_action(
    action_id: int,
    body: RejectRequest,
    orch: AgentOrchestrator = Depends(get_orchestrator),
):
    result = orch.reject_action(action_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result