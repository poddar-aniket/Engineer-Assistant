# orchestrator/scheduler.py
from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings

logger = logging.getLogger(__name__)

_last_seen_failure_ids: set[str] = set()


async def run_morning_briefing(build_orchestrator_with_session: Callable) -> None:
    logger.info("Scheduler: running morning briefing")
    orchestrator, db = build_orchestrator_with_session()
    try:
        await orchestrator.get_briefing()
        logger.info("Scheduler: briefing complete")
    except Exception as exc:
        logger.error("Scheduler: briefing failed — %s", exc)
    finally:
        db.close()


async def run_ci_failure_poll(build_orchestrator_with_session: Callable) -> None:
    global _last_seen_failure_ids

    if not settings.ENABLE_PUSH_NOTIFICATIONS:
        return

    logger.info("Scheduler: polling CI failures")
    orchestrator, db = build_orchestrator_with_session()
    try:
        result = await orchestrator.check_ci_failures()
        if result.success and result.data:
            # adjust the key below to match whatever get_ci_failures actually returns
            current_ids = {str(f.get("id", f)) for f in result.data}
            new_ids = current_ids - _last_seen_failure_ids
            if new_ids:
                logger.warning("Scheduler: %d new CI failure(s) detected", len(new_ids))
            _last_seen_failure_ids = current_ids
        elif not result.success:
            logger.error("Scheduler: get_ci_failures failed — %s", result.error)
    except Exception as exc:
        logger.error("Scheduler: CI poll failed — %s", exc)
    finally:
        db.close()


def build_scheduler(build_orchestrator_with_session: Callable) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.LOCAL_TIMEZONE)

    scheduler.add_job(
        run_morning_briefing,
        trigger=CronTrigger(
            hour=settings.BRIEFING_HOUR,
            minute=settings.BRIEFING_MINUTE,
            timezone=settings.LOCAL_TIMEZONE,
        ),
        args=[build_orchestrator_with_session],
        id="morning_briefing",
        name="Morning Briefing",
        replace_existing=True,
    )

    if settings.ENABLE_PUSH_NOTIFICATIONS:
        scheduler.add_job(
            run_ci_failure_poll,
            trigger="interval",
            minutes=settings.CI_POLL_INTERVAL_MINUTES,
            args=[build_orchestrator_with_session],
            id="ci_failure_poll",
            name="CI Failure Poll",
            replace_existing=True,
        )

    return scheduler