"""
Shared Google OAuth helper.
Handles first-run browser login and token refresh automatically.
Used by both CalendarMCPServer and GmailMCPServer.
"""

import os
import json
import tempfile
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Both Calendar and Gmail scopes in one token
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_google_credentials() -> Credentials:
    """
    Returns valid Google credentials.
    - On Render: reads from GOOGLE_CREDENTIALS_JSON and GOOGLE_TOKEN_JSON env vars
    - Local: falls back to credentials.json and token.json files
    """
    creds: Credentials | None = None

    # ── TOKEN ──────────────────────────────────────────────
    token_json_env = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json_env:
        creds = Credentials.from_authorized_user_info(
            json.loads(token_json_env), SCOPES
        )
    else:
        # Local fallback
        from config.settings import settings
        token_path = Path(settings.GOOGLE_TOKEN_FILE)
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # ── REFRESH / RE-AUTH ───────────────────────────────────
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        return creds

    # ── FIRST RUN (local only) ──────────────────────────────
    creds_json_env = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json_env:
        # On Render — can't open browser, raise helpful error
        raise RuntimeError(
            "No valid Google token found. "
            "Re-authenticate locally, then update GOOGLE_TOKEN_JSON env var on Render."
        )

    # Local: use credentials.json file
    from config.settings import settings
    credentials_path = Path(settings.GOOGLE_CREDENTIALS_FILE)
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at '{credentials_path}'. "
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)

    # Save locally for next run
    token_path = Path(settings.GOOGLE_TOKEN_FILE)
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    return creds