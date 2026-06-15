"""
Tier-1 email heuristic filter.
Fast rule-based classification — no LLM call needed.
Returns: 'work', 'personal', or 'ambiguous' (ambiguous goes to Gemini Tier-2 in Day 3)
"""
from __future__ import annotations

from config.settings import settings



WORK_DOMAINS = {
    "github.com", "gitlab.com", "jira.atlassian.com", "atlassian.com",
    "slack.com", "notion.so", "linear.app", "figma.com", "vercel.com",
    "aws.amazon.com", "google.com", "microsoft.com", "zoom.us",
    "loom.com", "confluence.atlassian.com", "circleci.com", "datadog.com",
}

PERSONAL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "protonmail.com", "me.com",
}

WORK_SUBJECT_KEYWORDS = {
    "pr", "pull request", "review", "ci", "build failed", "deployment",
    "incident", "alert", "pipeline", "sprint", "standup", "release",
    "jira", "ticket", "issue", "merge", "commit", "production", "staging",
    "invoice", "contract", "proposal", "meeting", "agenda", "onboarding",
}

NOISE_SUBJECT_KEYWORDS = {
    "unsubscribe", "newsletter", "offer", "deal", "sale", "discount",
    "promo", "coupon", "% off", "limited time", "click here", "verify your email",
    "confirm your", "no-reply", "noreply", "donotreply",
}

ALL_WORK_DOMAINS = WORK_DOMAINS | set(settings.WORK_EMAIL_DOMAINS)
def classify_email(sender: str, subject: str) -> str:
    """
    Classify a single email.

    Returns:
        'work'      — high confidence work email
        'personal'  — high confidence personal/noise
        'ambiguous' — needs Tier-2 Gemini classification
    """
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    # Extract domain from sender
    domain = _extract_domain(sender_lower)

    # Noise/spam → personal
    if any(kw in subject_lower for kw in NOISE_SUBJECT_KEYWORDS):
        return "personal"

    # Known work domain → work
    if domain in ALL_WORK_DOMAINS:
        return "work"

    # Known personal domain + no work keywords → personal
    if domain in PERSONAL_DOMAINS:
        if any(kw in subject_lower for kw in WORK_SUBJECT_KEYWORDS):
            return "ambiguous"  # personal domain but work-looking subject
        return "personal"

    # Work subject keywords → work
    if any(kw in subject_lower for kw in WORK_SUBJECT_KEYWORDS):
        return "work"

    # Can't decide → let Gemini handle it
    return "ambiguous"


def filter_emails(
    emails: list[dict],
) -> dict[str, list[dict]]:
    """
    Classify a list of emails into buckets.

    Each email dict must have at least:
        - 'sender': str
        - 'subject': str

    Returns:
        {
            'work': [...],
            'personal': [...],
            'ambiguous': [...]   ← passed to Tier-2 in Day 3
        }
    """
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
    """Extract domain from email address like 'John <john@company.com>' or 'john@company.com'."""
    if "<" in sender:
        sender = sender.split("<")[-1].strip(">").strip()
    if "@" in sender:
        return sender.split("@")[-1].strip()
    return sender