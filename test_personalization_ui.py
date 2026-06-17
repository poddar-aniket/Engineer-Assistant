# test_personalization_ui.py
"""
Day 5 smoke test — personalization loop + tier1_config.yaml + Streamlit wiring.
Run with: pytest test_personalization_ui.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from orchestrator.repository.models import Base
from orchestrator.repository.correction_repository import CorrectionRepository
from orchestrator.personalization.strategies import RecencyStrategy
from orchestrator.personalization.engine import PersonalizationEngine
from mcp_server.gmail_server.tier1_filter import (
    classify_email,
    filter_emails,
    WORK_DOMAINS,
    PERSONAL_DOMAINS,
    WORK_SUBJECT_KEYWORDS,
    NOISE_SUBJECT_KEYWORDS,
)


# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    from orchestrator.repository.correction_models import Correction  # noqa: F401
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Test 1: CorrectionRepository create and retrieve
# ---------------------------------------------------------------------------

def test_correction_repository_create_and_retrieve(db_session):
    repo = CorrectionRepository(db_session)
    correction = repo.create(
        action_type="send_email",
        original="Hi Priya, let me know if you are free",
        corrected="Hello Priya, please confirm your availability",
        user_note="Always use formal greetings",
    )
    assert correction.id is not None
    assert correction.action_type == "send_email"

    recent = repo.get_recent(limit=5)
    assert len(recent) == 1
    assert recent[0].corrected == "Hello Priya, please confirm your availability"


# ---------------------------------------------------------------------------
# Test 2: get_recent_mixed returns type-specific first then global
# ---------------------------------------------------------------------------

def test_correction_repository_mixed_retrieval(db_session):
    repo = CorrectionRepository(db_session)
    repo.create("send_email", "original A", "corrected A")
    repo.create("schedule_meeting", "original B", "corrected B")
    repo.create("send_email", "original C", "corrected C")

    mixed = repo.get_recent_mixed(action_type="send_email", limit=5)
    assert len(mixed) == 3
    types = [c.action_type for c in mixed]
    assert types[0] == "send_email"
    assert types[1] == "send_email"


# ---------------------------------------------------------------------------
# Test 3: RecencyStrategy returns empty string when no corrections
# ---------------------------------------------------------------------------

def test_recency_strategy_empty(db_session):
    repo = CorrectionRepository(db_session)
    strategy = RecencyStrategy(repo)
    context = strategy.get_context(action_type="send_email")
    assert context == ""


# ---------------------------------------------------------------------------
# Test 4: PersonalizationEngine builds personalized prompt
# ---------------------------------------------------------------------------

def test_personalization_engine_builds_prompt(db_session):
    repo = CorrectionRepository(db_session)
    repo.create(
        action_type="send_email",
        original="Hi there",
        corrected="Hello there",
        user_note="Use formal greetings",
    )
    engine = PersonalizationEngine(RecencyStrategy(repo))
    prompt = engine.build_personalized_prompt(
        base_prompt="Send an email to Priya",
        action_type="send_email",
    )
    assert "Past corrections to learn from" in prompt
    assert "Send an email to Priya" in prompt
    assert "formal greetings" in prompt


# ---------------------------------------------------------------------------
# Test 5: tier1_config.yaml loaded correctly
# ---------------------------------------------------------------------------

def test_tier1_config_loaded():
    assert len(WORK_DOMAINS) > 0
    assert "github.com" in WORK_DOMAINS
    assert "gmail.com" in PERSONAL_DOMAINS
    assert "meeting" in WORK_SUBJECT_KEYWORDS
    assert "unsubscribe" in NOISE_SUBJECT_KEYWORDS


# ---------------------------------------------------------------------------
# Test 6: tier1_filter classify_email uses loaded config
# ---------------------------------------------------------------------------

def test_tier1_filter_classify_email():
    assert classify_email("bot@github.com", "PR review requested") == "work"
    assert classify_email("friend@gmail.com", "Weekend plans") == "personal"
    assert classify_email("someone@gmail.com", "meeting agenda") == "ambiguous"
    assert classify_email("promo@shop.com", "Limited time offer") == "personal"