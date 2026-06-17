# orchestrator/api/main.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from orchestrator.scheduler import build_scheduler
from config.settings import settings
from orchestrator.core.gemini_client import GeminiClient
from orchestrator.core.mcp_registry import MCPRegistry
from orchestrator.api.router import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

registry = MCPRegistry()
gemini_client = GeminiClient()
gemini_client.initialize()

_scheduler = None  # module-level handle, set during lifespan startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler

    logger.info("Starting up — initializing MCP plugins...")
    await registry.initialize_all()
    logger.info("Plugins ready: %s", registry.list_names())

    # Scheduler jobs build their own short-lived orchestrator + DB session
    # per run via build_orchestrator_with_session — nothing is held open
    # across the lifetime of the process.
    from orchestrator.api.router import build_orchestrator_with_session
    _scheduler = build_scheduler(build_orchestrator_with_session)
    _scheduler.start()
    logger.info(
        "Scheduler started — briefing at %02d:%02d %s",
        settings.BRIEFING_HOUR,
        settings.BRIEFING_MINUTE,
        settings.LOCAL_TIMEZONE,
    )

    yield

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    logger.info("Shutting down — closing MCP plugins...")
    await registry.shutdown_all()


app = FastAPI(
    title="Engineer's Daily Co-pilot",
    version="0.5.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    checks = await registry.health_check()
    return {
        "status": "ok",
        "plugins": checks,
        "scheduler_running": _scheduler.running if _scheduler else False,
    }