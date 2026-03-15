"""
services/google_auth_service.py
Firebase token verification and Google OAuth helpers.
"""
import logging, requests
logger = logging.getLogger(__name__)

def verify_firebase_token(id_token: str, api_key: str) -> dict | None:
    """Verify Firebase ID token via Firebase REST API. Returns user dict or None."""
    if not api_key or not id_token:
        return None
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}"
        resp = requests.post(url, json={"idToken": id_token}, timeout=10)
        data = resp.json()
        if "error" in data:
            logger.warning(f"Firebase token error: {data['error']}")
            return None
        users = data.get("users", [])
        return users[0] if users else None
    except Exception as e:
        logger.warning(f"Firebase verify failed: {e}")
        return None


def exchange_google_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """Exchange OAuth code for access + refresh tokens."""
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=10)
    return resp.json()
