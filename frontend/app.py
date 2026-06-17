from __future__ import annotations

import streamlit as st
import requests

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="Engineer's Daily Co-pilot",
    page_icon=None,
    layout="wide",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api_get(path: str) -> dict | list | None:
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_post(path: str, payload: dict = {}) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}{path}", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
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

st.sidebar.title("Engineer's Daily Co-pilot")
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
        with st.spinner("Fetching briefing..."):
            data = api_get("/briefing")
            if data:
                st.session_state.briefing = data

    briefing = st.session_state.briefing
    if briefing:
        st.subheader("Summary")
        st.write(briefing.get("summary", "No summary available."))

        sections = briefing.get("sections", {})

        with st.expander("GitHub", expanded=True):
            github = sections.get("github", {})
            prs = github.get("actionable_prs", [])
            failures = github.get("ci_failures", [])
            activity = github.get("recent_activity", [])

            if prs:
                st.markdown("**Actionable PRs**")
                for pr in prs:
                    st.markdown(
                        f"- [{pr.get('title')}]({pr.get('url')}) "
                        f"— {pr.get('repo')} — {pr.get('reason')}"
                    )
            else:
                st.write("No actionable PRs.")

            if failures:
                st.markdown("**CI Failures**")
                for f in failures:
                    st.markdown(
                        f"- {f.get('repo')} — `{f.get('branch')}` — {f.get('conclusion')}"
                    )
            else:
                st.write("No CI failures.")

            if activity:
                st.markdown("**Recent Activity**")
                for a in activity:
                    st.markdown(f"- {a.get('type')} on {a.get('repo')}")

        with st.expander("Calendar", expanded=True):
            calendar = sections.get("calendar", {})
            events = calendar.get("today_events", [])
            if events:
                for e in events:
                    st.markdown(
                        f"- **{e.get('title')}** — {e.get('start')} to {e.get('end')}"
                    )
            else:
                st.write("No events today.")

        with st.expander("Email", expanded=True):
            email_section = sections.get("email", {})
            work_emails = email_section.get("work", [])
            ambiguous_emails = email_section.get("ambiguous", [])

            if work_emails:
                st.markdown("**Work Emails**")
                for e in work_emails:
                    st.markdown(
                        f"- **{e.get('subject')}** from {e.get('sender')}"
                    )
            if ambiguous_emails:
                st.markdown("**Needs Attention**")
                for e in ambiguous_emails:
                    st.markdown(
                        f"- **{e.get('subject')}** from {e.get('sender')}"
                    )
            if not work_emails and not ambiguous_emails:
                st.write("No important emails.")

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
        action = draft.get("action", {})
        st.success("Draft action created")
        st.markdown(f"**Type:** `{action.get('action_type')}`")
        st.markdown(f"**Status:** `{action.get('status')}`")
        st.markdown("**Details:**")
        st.text(action.get("display", ""))

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Approve"):
                with st.spinner("Executing..."):
                    res = api_post(f"/actions/{action['id']}/approve")
                    if res and res.get("success"):
                        st.success("Action executed successfully.")
                        st.session_state.last_draft = None
                    else:
                        st.error("Execution failed.")

        with col2:
            if st.button("Reject"):
                res = api_post(
                    f"/actions/{action['id']}/reject",
                    {"reason": "Rejected from UI"},
                )
                if res and res.get("success"):
                    st.warning("Action rejected.")
                    st.session_state.last_draft = None

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
            with st.expander(
                f"[{action['action_type']}] {action['display'][:60]}...",
                expanded=True,
            ):
                st.markdown(f"**ID:** {action['id']}")
                st.markdown(f"**Type:** `{action['action_type']}`")
                st.text(action.get("display", ""))
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
    st.markdown(
        "To add a correction, go to the **Command** page, submit a command, "
        "and use the correction form below the draft card."
    )