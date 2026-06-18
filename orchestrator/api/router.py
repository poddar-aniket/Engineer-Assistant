# orchestrator/api/router.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator.core.agent_orchestrator import AgentOrchestrator
from orchestrator.repository.action_repository import ActionRepository
from orchestrator.repository.correction_repository import CorrectionRepository
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

class CorrectionRequest(BaseModel):
    action_type: str
    original: str
    corrected: str
    user_note: str = ""


# ------------------------------------------------------------------
# Shared orchestrator construction — single source of truth so the
# per-request dependency and the scheduler never drift out of sync.
# ------------------------------------------------------------------

def _build_orchestrator(db: Session) -> AgentOrchestrator:
    from orchestrator.api.main import registry, gemini_client
    return AgentOrchestrator(
        github=registry.get("github"),
        calendar=registry.get("calendar"),
        gmail=registry.get("gmail"),
        gemini_client=gemini_client,
        action_repository=ActionRepository(db),
        correction_repository=CorrectionRepository(db),
    )


def get_orchestrator(db: Session = Depends(get_db)) -> AgentOrchestrator:
    """Per-request dependency — uses FastAPI's get_db() so the session
    is opened and closed within the request lifecycle."""
    return _build_orchestrator(db)


def build_orchestrator_with_session() -> tuple[AgentOrchestrator, Session]:
    """Used by the scheduler. Opens a fresh session per job run instead
    of holding one open for the lifetime of the process — caller is
    responsible for closing the returned session when the job finishes."""
    from orchestrator.repository.database import SessionLocal
    db = SessionLocal()
    orch = _build_orchestrator(db)
    return orch, db


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
    logger.info("Command result: %s", result)
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


@router.post("/corrections")
def store_correction(
    body: CorrectionRequest,
    orch: AgentOrchestrator = Depends(get_orchestrator),
):
    result = orch.store_correction(
        action_type=body.action_type,
        original=body.original,
        corrected=body.corrected,
        user_note=body.user_note or None,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("/corrections")
def get_corrections(orch: AgentOrchestrator = Depends(get_orchestrator)):
    return orch.get_corrections()