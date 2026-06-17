# test_scheduler.py
"""
Smoke tests for orchestrator/scheduler.py.

Verifies job registration, feature-flag gating, session lifecycle
(close-on-success and close-on-failure), and the CI-failure dedupe logic.
Uses fake orchestrator/session factories so no real GitHub/Calendar/Gmail/
Gemini credentials are required.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from orchestrator import scheduler as scheduler_module
from orchestrator.scheduler import (
    build_scheduler,
    run_ci_failure_poll,
    run_morning_briefing,
)


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def make_fake_factory(orchestrator):
    """Returns a callable shaped like build_orchestrator_with_session."""
    session = FakeSession()

    def factory():
        return orchestrator, session

    factory.session = session  # convenience handle for assertions
    return factory


@pytest.fixture(autouse=True)
def reset_failure_cache():
    scheduler_module._last_seen_failure_ids = set()
    yield
    scheduler_module._last_seen_failure_ids = set()


def test_build_scheduler_registers_morning_briefing_job(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_PUSH_NOTIFICATIONS", False)
    fake_factory = make_fake_factory(MagicMock())

    sched = build_scheduler(fake_factory)
    job_ids = {job.id for job in sched.get_jobs()}

    assert "morning_briefing" in job_ids
    assert "ci_failure_poll" not in job_ids


def test_build_scheduler_registers_ci_poll_job_when_flag_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_PUSH_NOTIFICATIONS", True)
    monkeypatch.setattr(settings, "CI_POLL_INTERVAL_MINUTES", 15)
    fake_factory = make_fake_factory(MagicMock())

    sched = build_scheduler(fake_factory)
    job_ids = {job.id for job in sched.get_jobs()}

    assert "morning_briefing" in job_ids
    assert "ci_failure_poll" in job_ids


async def test_run_morning_briefing_closes_session_on_success():
    orch = MagicMock()
    orch.get_briefing = AsyncMock(return_value={"github": [], "calendar": [], "email": []})
    fake_factory = make_fake_factory(orch)

    await run_morning_briefing(fake_factory)

    orch.get_briefing.assert_awaited_once()
    assert fake_factory.session.closed is True


async def test_run_morning_briefing_closes_session_on_failure():
    orch = MagicMock()
    orch.get_briefing = AsyncMock(side_effect=RuntimeError("boom"))
    fake_factory = make_fake_factory(orch)

    # must not raise -- scheduler jobs should never propagate exceptions
    await run_morning_briefing(fake_factory)

    assert fake_factory.session.closed is True


async def test_run_ci_failure_poll_skips_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_PUSH_NOTIFICATIONS", False)
    orch = MagicMock()
    orch.check_ci_failures = AsyncMock()
    fake_factory = make_fake_factory(orch)

    await run_ci_failure_poll(fake_factory)

    orch.check_ci_failures.assert_not_awaited()


async def test_run_ci_failure_poll_calls_check_ci_failures_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_PUSH_NOTIFICATIONS", True)

    fake_result = SimpleNamespace(success=True, data=[{"id": "build-1"}], error=None)
    orch = MagicMock()
    orch.check_ci_failures = AsyncMock(return_value=fake_result)
    fake_factory = make_fake_factory(orch)

    await run_ci_failure_poll(fake_factory)

    orch.check_ci_failures.assert_awaited_once()
    assert fake_factory.session.closed is True
    assert scheduler_module._last_seen_failure_ids == {"build-1"}


async def test_run_ci_failure_poll_dedupes_repeated_failures(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENABLE_PUSH_NOTIFICATIONS", True)
    scheduler_module._last_seen_failure_ids = {"build-1"}

    fake_result = SimpleNamespace(success=True, data=[{"id": "build-1"}], error=None)
    orch = MagicMock()
    orch.check_ci_failures = AsyncMock(return_value=fake_result)
    fake_factory = make_fake_factory(orch)

    with caplog.at_level("WARNING"):
        await run_ci_failure_poll(fake_factory)

    assert "new CI failure" not in caplog.text


async def test_run_ci_failure_poll_logs_only_new_failures(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENABLE_PUSH_NOTIFICATIONS", True)
    scheduler_module._last_seen_failure_ids = {"build-1"}

    fake_result = SimpleNamespace(
        success=True, data=[{"id": "build-1"}, {"id": "build-2"}], error=None
    )
    orch = MagicMock()
    orch.check_ci_failures = AsyncMock(return_value=fake_result)
    fake_factory = make_fake_factory(orch)

    with caplog.at_level("WARNING"):
        await run_ci_failure_poll(fake_factory)

    assert "1 new CI failure" in caplog.text
    assert scheduler_module._last_seen_failure_ids == {"build-1", "build-2"}


def test_build_orchestrator_with_session_uses_fresh_session_each_call(monkeypatch):
    """Regression test for the critical fix: the scheduler must never reuse
    a single cached DB session/orchestrator across job runs."""
    import orchestrator.api.main as main_module
    from orchestrator.api.router import build_orchestrator_with_session

    monkeypatch.setattr(main_module, "registry", SimpleNamespace(get=lambda name: MagicMock()))
    monkeypatch.setattr(main_module, "gemini_client", MagicMock())

    orch1, db1 = build_orchestrator_with_session()
    orch2, db2 = build_orchestrator_with_session()

    assert db1 is not db2

    db1.close()
    db2.close()