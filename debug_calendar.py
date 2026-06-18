"""
Standalone calendar debug script — runs outside FastAPI to isolate the issue.
Usage: python debug_calendar.py
"""
import sys
sys.path.insert(0, ".")

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()

from oauth_helper import get_google_credentials
from googleapiclient.discovery import build

creds = get_google_credentials()
service = build("calendar", "v3", credentials=creds)

tz = ZoneInfo("Asia/Kolkata")
utc_now = datetime.now(timezone.utc)
local_now = datetime.now(tz)

print(f"UTC now   : {utc_now.isoformat()}")
print(f"IST now   : {local_now.isoformat()}")
print()

# Window 1: what the OLD code used (UTC midnight-to-midnight)
utc_start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
utc_end = utc_start + timedelta(days=1)
print(f"OLD query (UTC midnight): {utc_start.isoformat()} -> {utc_end.isoformat()}")
r1 = service.events().list(
    calendarId="primary",
    timeMin=utc_start.isoformat(),
    timeMax=utc_end.isoformat(),
    singleEvents=True,
    orderBy="startTime",
).execute()
old_items = r1.get("items", [])
print(f"  Events returned: {len(old_items)}")

print()

# Window 2: what the NEW code uses (IST midnight-to-midnight)
ist_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
ist_end = ist_start + timedelta(days=1)
print(f"NEW query (IST midnight): {ist_start.isoformat()} -> {ist_end.isoformat()}")
r2 = service.events().list(
    calendarId="primary",
    timeMin=ist_start.isoformat(),
    timeMax=ist_end.isoformat(),
    singleEvents=True,
    orderBy="startTime",
).execute()
new_items = r2.get("items", [])
print(f"  Events returned: {len(new_items)}")
for ev in new_items:
    start = ev.get("start", {})
    t = start.get("dateTime") or start.get("date")
    print(f"  - [{t}] {ev.get('summary', '(no title)')}")

print()

# Window 3: broad sanity check — next 7 days
print("BROAD check (next 7 days from UTC now):")
broad_end = utc_now + timedelta(days=7)
r3 = service.events().list(
    calendarId="primary",
    timeMin=utc_now.isoformat(),
    timeMax=broad_end.isoformat(),
    singleEvents=True,
    orderBy="startTime",
    maxResults=10,
).execute()
broad_items = r3.get("items", [])
print(f"  Events returned: {len(broad_items)}")
for ev in broad_items:
    start = ev.get("start", {})
    t = start.get("dateTime") or start.get("date")
    print(f"  - [{t}] {ev.get('summary', '(no title)')}")

# Also print which calendar IDs we have
print()
print("Available calendars:")
cal_list = service.calendarList().list().execute()
for cal in cal_list.get("items", []):
    print(f"  [{cal.get('id')}] {cal.get('summary')} (primary={cal.get('primary', False)})")
