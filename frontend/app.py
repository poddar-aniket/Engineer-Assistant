from __future__ import annotations

import streamlit as st
import requests
from datetime import datetime as _dt

API_BASE = "http://localhost:8000/api/v1"

# The briefing endpoint fans out to GitHub, Calendar, and Gmail before it
# ever reaches Gemini, so it legitimately needs more headroom than a single
# action approval or correction submit. Giving it its own timeout stops the
# client from giving up on a request the server is still happily finishing.
DEFAULT_TIMEOUT = 30
BRIEFING_TIMEOUT = 180

st.set_page_config(
    page_title="DevMitra",
    page_icon=None,
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
    .status-pill {
        display: inline-block;
        padding: 2px 12px;
        border-radius: 12px;
        font-size: 0.82em;
        font-weight: 600;
        color: #fafafa;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

STATUS_COLORS = {
    "PENDING": "#946f1f",
    "APPROVED": "#1f5c94",
    "EXECUTED": "#1f7a4c",
    "REJECTED": "#8a2a2a",
    "FAILED": "#6e1f1f",
}


def status_badge(status: str) -> str:
    color = STATUS_COLORS.get((status or "").upper(), "#444444")
    return f'<span class="status-pill" style="background-color:{color};">{status}</span>'

def _fmt_time(ts: str) -> str:
    try:
        parsed = _dt.fromisoformat(ts)
        return parsed.strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return ts or ""
def _extract_iso(value) -> str:
    if isinstance(value, dict):
        return value.get("dateTime") or value.get("date") or ""
    return value or ""


def render_action_result(action_type: str, result_data) -> None:
    if not isinstance(result_data, dict):
        st.text(str(result_data))
        return

    if action_type in ("schedule_meeting", "add_calendar_event"):
        title = result_data.get("title", "Event")
        start = _fmt_time(_extract_iso(result_data.get("start")))
        end = _fmt_time(_extract_iso(result_data.get("end")))
        st.success(f"'{title}' scheduled for {start} - {end}.")
        link = result_data.get("link")
        if link:
            st.markdown(f"[View in Google Calendar]({link})")
        return

    if action_type in ("send_email", "create_email_draft"):
        to = result_data.get("to") or result_data.get("recipient", "")
        subject = result_data.get("subject", "")
        verb = "sent to" if action_type == "send_email" else "drafted for"
        st.success(f"Email {verb} {to}: \"{subject}\"")
        return

    # Fallback for any other action type — generic friendly listing
    for k, v in result_data.items():
        if k.endswith("_id"):
            continue
        if isinstance(v, dict):
            v = _extract_iso(v) or v
        st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")


def render_today_schedule(events: list[dict]) -> None:
    if not events:
        st.info("No events scheduled today.")
        return
    for ev in sorted(events, key=lambda e: e.get("start", "")):
        start = _fmt_time(ev.get("start", ""))
        end = _fmt_time(ev.get("end", ""))
        title = ev.get("title") or "(untitled event)"
        st.markdown(f"**{start} - {end}**   {title}")
        extras = []
        if ev.get("location"):
            extras.append(f"Location: {ev['location']}")
        if ev.get("attendees"):
            extras.append(f"With: {', '.join(ev['attendees'])}")
        if extras:
            st.caption("  |  ".join(extras))


def render_check_availability(result: dict) -> None:
    is_free = result.get("is_free")
    checked_from = _fmt_time(result.get("checked_from", ""))
    checked_to = _fmt_time(result.get("checked_to", ""))
    if is_free:
        st.success(f"You're free from {checked_from} to {checked_to}.")
        return
    st.warning(f"You're busy during part or all of {checked_from} to {checked_to}.")
    slots = result.get("busy_slots", [])
    if slots:
        st.markdown("**Conflicting events:**")
        for slot in slots:
            s = _fmt_time(slot.get("start", ""))
            e = _fmt_time(slot.get("end", ""))
            st.markdown(f"- {s} - {e}")


def render_generic_list(items: list) -> None:
    for item in items:
        if isinstance(item, dict):
            with st.container(border=True):
                for k, v in item.items():
                    if v in (None, "", [], {}):
                        continue
                    st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")
        else:
            st.markdown(f"- {item}")
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_error_detail(r: requests.Response) -> str:
    try:
        body = r.json()
        return body.get("detail") or body.get("error") or r.text
    except ValueError:
        return r.text or f"HTTP {r.status_code}"


def api_get(path: str, timeout: int = DEFAULT_TIMEOUT) -> dict | list | None:
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=timeout)
        if r.status_code >= 400:
            return {"success": False, "error": _parse_error_detail(r)}
        return r.json()
    except requests.exceptions.Timeout:
        st.error(
            f"No response within {timeout}s. The backend may still be "
            "working on this -- check the API server's terminal. If it "
            "logs a 200 OK a little after this point, the request just "
            "needs more time than this page currently allows for."
        )
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_post(path: str, payload: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}{path}", json=payload or {}, timeout=timeout)
        if r.status_code >= 400:
            return {"success": False, "error": _parse_error_detail(r)}
        return r.json()
    except requests.exceptions.Timeout:
        st.error(
            f"No response within {timeout}s. The backend may still be "
            "working on this -- check the API server's terminal before "
            "retrying."
        )
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None


# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

if "briefing" not in st.session_state:
    st.session_state.briefing = None
if "last_draft" not in st.session_state:
    st.session_state.last_draft = None
if "correction_submitted" not in st.session_state:
    st.session_state.correction_submitted = False


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("DevMitra")
page = st.sidebar.radio(
    "Navigate",
    ["Briefing", "Command", "Pending Actions", "Corrections"],
)


# ---------------------------------------------------------------------------
# Page: Briefing
# ---------------------------------------------------------------------------

if page == "Briefing":
    st.title("Morning Briefing")

    if st.button("Generate Briefing"):
        with st.spinner(f"Fetching briefing (up to {BRIEFING_TIMEOUT}s)..."):
            data = api_get("/briefing", timeout=BRIEFING_TIMEOUT)
            if data:
                st.session_state.briefing = data

    briefing = st.session_state.briefing
    if briefing:
        st.subheader("Summary")
        st.write(briefing.get("summary", "No summary available."))

        for section in briefing.get("sections", []):
            title = section.get("title", "Section")
            content = section.get("content", "")
            with st.container(border=True):
                with st.expander(title, expanded=True):
                    st.text(content)

        st.subheader("Standup Draft")
        st.text_area(
            "Copy and use in your standup",
            value=briefing.get("standup_draft", ""),
            height=150,
        )

        if briefing.get("errors"):
            with st.expander("Errors during briefing generation"):
                for err in briefing["errors"]:
                    st.warning(err)


# ---------------------------------------------------------------------------
# Page: Command
# ---------------------------------------------------------------------------

elif page == "Command":
    st.title("Issue a Command")

    with st.expander("Supported commands", expanded=False):
        st.markdown("""
- **Schedule a meeting** — "Schedule a team sync tomorrow at 2pm to 3pm with priya@example.com"
- **Send an email** — "Send an email to priya@example.com about the release update"
- **Create email draft** — "Draft an email to manager@example.com about taking Friday off"
- **Check availability** — "Am I free tomorrow from 3pm to 4pm?"
- **Add calendar event** — "Add a reminder on Friday at 9am called Submit report"
- **Summarise emails** — "Summarise my recent emails about the PR review"
- **Today's schedule** — "What's on my calendar today?"
        """)

    user_input = st.text_input(
        "What do you want to do?",
        placeholder="e.g. Schedule a meeting with Priya tomorrow at 3pm",
    )

    if st.button("Submit Command") and user_input.strip():
        with st.spinner("Parsing command..."):
            result = api_post("/command", {"user_input": user_input})
            if result:
                st.session_state.last_draft = result
                st.session_state.correction_submitted = False

    draft = st.session_state.last_draft
    if draft and draft.get("success"):

        if draft.get("read_only_type"):
            with st.container(border=True):
                result_data = draft.get("read_only_result")
                if result_data:
                    st.text(str(result_data))
                elif draft.get("error"):
                    st.error(draft.get("error"))
                else:
                    st.info("No results returned.")

        elif draft.get("action"):
            action = draft.get("action", {})
            status = action.get("status", "")

            with st.container(border=True):
                st.markdown("**Details:**")
                st.text(action.get("display", ""))

                if status.upper() == "PENDING":

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Approve"):
                            with st.spinner("Executing..."):
                                res = api_post(f"/actions/{action['id']}/approve")
                                if res and res.get("success"):
                                    result_data = res.get("action", {}).get("result")
                                    st.session_state.last_draft["action"]["status"] = "EXECUTED"
                                    st.session_state.last_draft["action"]["result"] = result_data
                                    st.rerun()
                                else:
                                    st.error((res or {}).get("error") or "Could not execute this action.")
                    with col2:
                        if st.button("Reject"):
                            res = api_post(
                                f"/actions/{action['id']}/reject",
                                {"reason": "Rejected from UI"},
                            )
                            if res and res.get("success"):
                                st.warning("Action rejected.")
                                st.session_state.last_draft = None
                                st.rerun()
                elif status.upper() == "EXECUTED":
                    st.success("Done — action completed successfully.")
                elif status.upper()  == "REJECTED":
                    st.warning("This action was rejected.")

            if status.upper() == "EXECUTED" and action.get("result"):
                st.divider()
                render_action_result(action.get("action_type", ""), action.get("result"))

            st.divider()
            st.markdown("**Submit a correction to improve future drafts:**")
            corrected = st.text_area(
                "What should it have done instead?",
                placeholder="e.g. Use 'Hello' instead of 'Hi' in email greetings",
            )
            user_note = st.text_input(
                "Optional note explaining the correction",
                placeholder="e.g. Always use formal greetings",
            )
            if st.button("Submit Correction") and corrected.strip():
                payload = {
                    "action_type": action.get("action_type", "general"),
                    "original": action.get("display", ""),
                    "corrected": corrected,
                    "user_note": user_note or "",
                }
                res = api_post("/corrections", payload)
                if res and res.get("success"):
                    st.success("Correction saved. Future drafts will learn from this.")
                    st.session_state.correction_submitted = True
# ---------------------------------------------------------------------------
# Page: Pending Actions
# ---------------------------------------------------------------------------

elif page == "Pending Actions":
    st.title("Pending Actions")

    if st.button("Refresh"):
        st.rerun()

    actions = api_get("/actions/pending")
    if not actions:
        st.info("No pending actions.")
    else:
        for action in actions:
            display_text = action.get("display", "")
            preview = (
                display_text
                if len(display_text) <= 60
                else display_text[:60] + "..."
            )
            with st.container(border=True):
                with st.expander(
                    f"[{action['action_type']}] {preview}",
                    expanded=True,
                ):
                    st.markdown(f"**ID:** {action['id']}")
                    st.markdown(f"**Type:** `{action['action_type']}`")
                    st.text(display_text)
                    st.markdown(f"**Created:** {action.get('created_at', '')}")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Approve", key=f"approve_{action['id']}"):
                            res = api_post(f"/actions/{action['id']}/approve")
                            if res and res.get("success"):
                                st.success("Executed.")
                                st.rerun()
                            else:
                                st.error("Failed.")
                    with col2:
                        if st.button("Reject", key=f"reject_{action['id']}"):
                            res = api_post(
                                f"/actions/{action['id']}/reject",
                                {"reason": "Rejected from pending actions view"},
                            )
                            if res and res.get("success"):
                                st.warning("Rejected.")
                                st.rerun()
            


# ---------------------------------------------------------------------------
# Page: Corrections
# ---------------------------------------------------------------------------

elif page == "Corrections":
    st.title("Correction History")
    st.info(
        "Corrections you submit are automatically injected into future "
        "Gemini prompts to personalise responses over time."
    )

    with st.container(border=True):
        st.markdown("**Submit a correction:**")
        action_type = st.selectbox(
            "Action type this correction applies to",
            ["general", "schedule_meeting", "send_email", "create_email_draft",
             "check_availability", "add_calendar_event", "summarise_emails", "get_todays_schedule"],
        )
        original = st.text_area(
            "What did the assistant do?",
            placeholder="e.g. It scheduled the meeting for 1 hour",
        )
        corrected = st.text_area(
            "What should it have done instead?",
            placeholder="e.g. Default meeting duration should be 30 minutes",
        )
        user_note = st.text_input(
            "Optional note",
            placeholder="e.g. I prefer shorter meetings by default",
        )
        if st.button("Submit Correction") and corrected.strip():
            payload = {
                "action_type": action_type,
                "original": original,
                "corrected": corrected,
                "user_note": user_note or "",
            }
            res = api_post("/corrections", payload)
            if res and res.get("success"):
                st.success("Correction saved.")

    st.divider()
    st.markdown("**Past corrections:**")
    corrections = api_get("/corrections")
    if corrections is None or len(corrections) == 0:
        st.info("No corrections submitted yet.")
    else:
        for c in corrections:
            with st.container(border=True):
                st.markdown(f"**Type:** `{c.get('action_type', '')}`")
                st.markdown(f"**Original:** {c.get('original', '')}")
                st.markdown(f"**Corrected:** {c.get('corrected', '')}")
                if c.get("user_note"):
                    st.markdown(f"**Note:** {c.get('user_note')}")
                st.caption(c.get("created_at", ""))