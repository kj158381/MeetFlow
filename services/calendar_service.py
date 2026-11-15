"""
services/calendar_service.py
Google Calendar API — fetch upcoming events.
"""
import logging, requests
from datetime import datetime
logger = logging.getLogger(__name__)

CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"

def fetch_google_calendar_events(access_token: str, max_results: int = 50) -> tuple[int, list]:
    """Returns (status_code, list_of_event_dicts)."""
    now = datetime.utcnow().isoformat() + "Z"
    resp = requests.get(
        f"{CALENDAR_BASE}/calendars/primary/events",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "timeMin": now, "maxResults": max_results,
            "singleEvents": True, "orderBy": "startTime"
        },
        timeout=10
    )
    if resp.status_code != 200:
        return resp.status_code, []

    events = []
    for event in resp.json().get("items", []):
        events.append({
            "id":    event.get("id", ""),
            "title": event.get("summary", "Untitled Event"),
            "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", ""),
            "end":   event.get("end",   {}).get("dateTime") or event.get("end",   {}).get("date", ""),
        })
    return 200, events
