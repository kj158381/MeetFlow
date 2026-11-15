"""
services/gmail_service.py
Read Gmail messages via Google OAuth access token.
"""
import logging, requests
logger = logging.getLogger(__name__)

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

def list_messages(access_token: str, max_results: int = 20, query: str = "") -> dict:
    params = {"maxResults": max_results}
    if query:
        params["q"] = query
    resp = requests.get(
        f"{GMAIL_BASE}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params, timeout=10
    )
    return resp.status_code, resp.json()


def get_message(access_token: str, message_id: str) -> dict:
    resp = requests.get(
        f"{GMAIL_BASE}/messages/{message_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "full"}, timeout=10
    )
    return resp.status_code, resp.json()


def parse_message_headers(payload: dict) -> dict:
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    return {
        "subject": headers.get("Subject", "(no subject)"),
        "from":    headers.get("From", ""),
        "to":      headers.get("To", ""),
        "date":    headers.get("Date", ""),
    }


def extract_body(part: dict, body: list):
    import base64
    if part.get("mimeType") in ("text/html", "text/plain") and part.get("body", {}).get("data"):
        decoded = base64.urlsafe_b64decode(part["body"]["data"] + "==").decode("utf-8", errors="replace")
        if part["mimeType"] == "text/html" or not body:
            body.clear()
            body.append(decoded)
    for sub in part.get("parts", []):
        extract_body(sub, body)
