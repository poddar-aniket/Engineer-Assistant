# orchestrator/api/main.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from orchestrator.core.gemini_client import GeminiClient
from orchestrator.core.mcp_registry import MCPRegistry
from orchestrator.api.router import router
from dotenv import load_dotenv
load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level singletons shared across requests via router.py
registry = MCPRegistry()
# gemini_client = GeminiClient(api_key=settings.GEMINI_API_KEY)
gemini_client = GeminiClient()
gemini_client.initialize()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — initializing MCP plugins...")
    await registry.initialize_all()
    logger.info("Plugins ready: %s", registry.list_names())
    yield
    logger.info("Shutting down — closing MCP plugins...")
    await registry.shutdown_all()


app = FastAPI(
    title="Engineer's Daily Co-pilot",
    version="0.4.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    checks = await registry.health_check()
    return {"status": "ok", "plugins": checks}