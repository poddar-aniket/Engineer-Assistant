"""
Shared Google OAuth helper.
Handles first-run browser login and token refresh automatically.
Used by both CalendarMCPServer and GmailMCPServer.
"""

import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from config.settings import settings

# Both Calendar and Gmail scopes in one token
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_google_credentials() -> Credentials:
    """
    Returns valid Google credentials.
    - First run: opens browser for login, saves token.json
    - Subsequent runs: loads token.json, refreshes if expired
    """
    creds: Credentials | None = None
    token_path = Path(settings.GOOGLE_TOKEN_FILE)
    credentials_path = Path(settings.GOOGLE_CREDENTIALS_FILE)

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at '{credentials_path}'. "
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    # Load existing token if present
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # If no valid creds, do the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Silent refresh
            creds.refresh(Request())
        else:
            # First run — opens browser
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save for next run
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds