# Engineer's Daily Co-pilot

A personal agentic assistant for software engineers. It connects to
GitHub, Google Calendar, and Gmail through custom MCP plugins, generates
a daily briefing, accepts free-text commands, drafts every action for
your approval before anything is sent or scheduled, and learns from your
corrections over time.

See [`docs/architecture.md`](docs/architecture.md) for the system design,
component diagram, and key architectural decisions.

## Features

- Morning briefing: actionable GitHub PRs, CI failures with root-cause
  correlation, today's calendar events, and important emails
- PR/CI triage — separates PRs needing attention from ones that can wait
- CI failure root-cause correlation — links a failed build to the likely
  commit
- Standup draft generation from your actual GitHub activity
- Email triage with work/personal classification (free heuristic filter
  first, Gemini only for ambiguous cases)
- Free-text command interface — "schedule a meeting with Sam Thursday at
  3" becomes a draft action
- Email-to-calendar extraction — pulls meeting details out of an email
  and proposes a calendar event
- Approve-before-send action layer — nothing is sent, created, or
  scheduled without your explicit sign-off
- Personalization loop — every correction you make is stored and used to
  influence future drafts
- Action/decision history log
- Scheduled morning briefing and optional CI-failure polling
- Plugin architecture — every integration is a self-contained folder; no
  orchestrator code changes needed to add a new one

## Prerequisites

- Python 3.10 or higher
- A GitHub Personal Access Token with repo read access
- A Google Cloud project with the Calendar API and Gmail API enabled,
  and an OAuth 2.0 Desktop app client (`credentials.json`)
- A free-tier Gemini API key

## Setup

1. Clone the repository and check out `main`.

2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate        # venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your values (see the table
   below for what each variable means).

4. Place your Google OAuth `credentials.json` in the project root, then
   run the one-time OAuth flow to generate `token.json`:
   ```
   python oauth_helper.py
   ```

5. Apply database migrations:
   ```
   alembic upgrade head
   ```

6. (Recommended) Run the test suite to confirm everything is wired
   correctly:
   ```
   pytest
   ```

## Running the app

Two processes run side by side. Start the backend first:
```
uvicorn orchestrator.api.main:app --reload --host 0.0.0.0 --port 8000
```

Then, in a separate terminal, start the frontend:
```
streamlit run frontend/app.py
```

Streamlit will open in your browser (default `http://localhost:8501`)
and talk to the API at `http://localhost:8000/api/v1`.

You can check backend and plugin health directly at
`http://localhost:8000/health`.

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `GITHUB_TOKEN` | GitHub Personal Access Token | `ghp_...` |
| `GITHUB_USERNAME` | Your GitHub username | `jdoe` |
| `GOOGLE_CREDENTIALS_FILE` | Path to OAuth client credentials | `credentials.json` |
| `GOOGLE_TOKEN_FILE` | Path to generated OAuth token | `token.json` |
| `WORK_EMAIL_DOMAINS` | Comma-separated domains treated as work email, merged with `config/tier1_config.yaml` | `mycompany.com,contractor.io` |
| `GEMINI_API_KEY` | Gemini API key (free tier) | `AIza...` |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.1-flash-lite` |
| `GEMINI_RPM_LIMIT` | Requests-per-minute cap (stay under the free-tier limit of 15) | `12` |
| `SLACK_BOT_TOKEN` | Slack bot token (only used if `ENABLE_SLACK_PLUGIN=true`) | `xoxb-...` |
| `SLACK_CHANNEL_ID` | Slack channel for alerts | `C0123456` |
| `APP_HOST` | Backend host | `localhost` |
| `APP_PORT` | Backend port | `8000` |
| `BRIEFING_HOUR` | Hour the daily briefing job runs (24h, local time) | `8` |
| `BRIEFING_MINUTE` | Minute the daily briefing job runs | `0` |
| `CI_POLL_INTERVAL_MINUTES` | How often the CI-failure poll job runs (only if `ENABLE_PUSH_NOTIFICATIONS=true`) | `15` |
| `DATABASE_URL` | SQLAlchemy database URL | `sqlite:///./engineer_copilot.db` |
| `LOCAL_TIMEZONE` | Your local timezone, used for scheduling and UTC conversion | `Asia/Kolkata` |
| `ENABLE_SLACK_PLUGIN` | Enable the Slack plugin (stretch) | `false` |
| `ENABLE_EMBEDDING_PERSONALIZATION` | Use embedding-based retrieval instead of recency-based | `false` |
| `ENABLE_PUSH_NOTIFICATIONS` | Enable the CI-failure polling job | `false` |
| `ENABLE_WEEKLY_RETROSPECTIVE` | Enable the weekly retrospective summary (stretch) | `false` |

`.env` is never committed — see `.gitignore`. Use `.env.example` as the
template.

## Project Structure

```
mcp_server/        custom MCP plugins (GitHub, Calendar, Gmail) implementing BaseMCPServer
orchestrator/       core logic — briefing, drafting, approval, personalization, API, scheduler
frontend/            Streamlit UI
config/              settings, MCP server registry config, tier-1 email filter config
migrations/          Alembic migrations
docs/                architecture documentation
```

## Adding a new integration

Create a folder under `mcp_server/` with a `manifest.yaml` and a
`server.py` implementing `BaseMCPServer`, then enable it in
`config/mcp_servers.yaml`. No changes to orchestrator code are required.

## Testing

```
pytest
```

`pytest.ini` sets `asyncio_mode = auto`, so async tests don't need a
`@pytest.mark.asyncio` decorator.