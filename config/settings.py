"""
Central settings — all env vars and feature flags live here.
Pydantic BaseSettings reads from .env automatically.
"""

from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # GitHub
    GITHUB_TOKEN: str = ""
    GITHUB_USERNAME: str = ""

    # Google OAuth
    GOOGLE_CREDENTIALS_FILE: str = "credentials.json"
    GOOGLE_TOKEN_FILE: str = "token.json"
    WORK_EMAIL_DOMAINS: list[str] = []

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_RPM_LIMIT: int = 12

    # Slack
    SLACK_BOT_TOKEN: str = ""
    SLACK_CHANNEL_ID: str = ""

    # App
    APP_HOST: str = "localhost"
    APP_PORT: int = 8000
    BRIEFING_HOUR: int = 8
    BRIEFING_MINUTE: int = 0

    # Database
    DATABASE_URL: str = "sqlite:///./engineer_copilot.db"

    # Feature flags
    ENABLE_SLACK_PLUGIN: bool = False
    ENABLE_EMBEDDING_PERSONALIZATION: bool = False
    ENABLE_PUSH_NOTIFICATIONS: bool = False
    ENABLE_WEEKLY_RETROSPECTIVE: bool = False
    LOCAL_TIMEZONE: str = "Asia/Kolkata"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Parses "mycompany.com,contractor.io" → ["mycompany.com", "contractor.io"]
        env_list_separator = ","
        extra="ignore"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Singleton — import this everywhere
settings = get_settings()