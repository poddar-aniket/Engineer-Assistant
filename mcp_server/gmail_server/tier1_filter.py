"""
Tier-1 email heuristic filter.
Fast rule-based classification — no LLM call needed.
Returns: 'work', 'personal', or 'ambiguous' (ambiguous goes to Gemini Tier-2)
"""
from __future__ import annotations

import os
import yaml

from config.settings import settings

# ---------------------------------------------------------------------------
# Load config from tier1_config.yaml
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "tier1_config.yaml"
))

def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

_config = _load_config()

WORK_DOMAINS: set[str] = set(_config.get("work_domains", []))
PERSONAL_DOMAINS: set[str] = set(_config.get("personal_domains", []))
WORK_SUBJECT_KEYWORDS: set[str] = set(_config.get("work_subject_keywords", []))
NOISE_SUBJECT_KEYWORDS: set[str] = set(_config.get("noise_subject_keywords", []))

ALL_WORK_DOMAINS = WORK_DOMAINS | set(settings.WORK_EMAIL_DOMAINS)


# ---------------------------------------------------------------------------
# Classification logic (unchanged)
# ---------------------------------------------------------------------------

def classify_email(sender: str, subject: str) -> str:
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    domain = _extract_domain(sender_lower)

    if any(kw in subject_lower for kw in NOISE_SUBJECT_KEYWORDS):
        return "personal"

    if domain in ALL_WORK_DOMAINS:
        return "work"

    if domain in PERSONAL_DOMAINS:
        if any(kw in subject_lower for kw in WORK_SUBJECT_KEYWORDS):
            return "ambiguous"
        return "personal"

    if any(kw in subject_lower for kw in WORK_SUBJECT_KEYWORDS):
        return "work"

    return "ambiguous"


def filter_emails(emails: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {"work": [], "personal": [], "ambiguous": []}
    for email in emails:
        label = classify_email(
            sender=email.get("sender", ""),
            subject=email.get("subject", ""),
        )
        email["tier1_label"] = label
        buckets[label].append(email)
    return buckets


def _extract_domain(sender: str) -> str:
    if "<" in sender:
        sender = sender.split("<")[-1].strip(">").strip()
    if "@" in sender:
        return sender.split("@")[-1].strip()
    return sender