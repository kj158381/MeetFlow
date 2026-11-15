"""
services/google_auth_service.py
Firebase token verification and Google OAuth helpers.
"""
from __future__ import annotations
import logging, requests
logger = logging.getLogger(__name__)

def _verify_locally(id_token: str, project_id: str) -> dict | None:
    """Verify the ID token's signature/expiry/audience against Google's public
    certs (the officially recommended way). Returns a REST-shaped user dict."""
    from google.oauth2 import id_token as g_id_token
    from google.auth.transport import requests as g_requests
    claims = g_id_token.verify_firebase_token(id_token, g_requests.Request(), audience=project_id)
    if not claims:
        return None
    return {
        "localId":       claims.get("user_id") or claims.get("sub", ""),
        "email":         claims.get("email", ""),
        "displayName":   claims.get("name", ""),
        "photoUrl":      claims.get("picture", ""),
        "emailVerified": bool(claims.get("email_verified")),
    }


def _verify_via_rest(id_token: str, api_key: str, auth_domain: str = "") -> dict | None:
    """Fallback: ask Firebase's REST API. Sends a Referer so keys restricted to
    'HTTP referrers' in Google Cloud still work from the server."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}"
    headers = {"Referer": f"https://{auth_domain}/"} if auth_domain else {}
    resp = requests.post(url, json={"idToken": id_token}, headers=headers, timeout=10)
    data = resp.json()
    if "error" in data:
        logger.warning(f"Firebase REST token error: {data['error'].get('message', data['error'])}")
        return None
    users = data.get("users", [])
    return users[0] if users else None


def verify_firebase_token(id_token: str, api_key: str, project_id: str = "", auth_domain: str = "") -> dict | None:
    """Verify a Firebase ID token. Returns a user dict, or None if it is NOT valid.
    Never returns a user for an unverifiable token."""
    if not id_token:
        return None
    if project_id:
        try:
            user = _verify_locally(id_token, project_id)
            if user:
                return user
        except ValueError as e:                      # bad signature / expired / wrong project
            logger.warning(f"Firebase token rejected: {e}")
            return None
        except Exception as e:                       # e.g. could not download Google certs
            logger.warning(f"Local Firebase verify unavailable ({e}); trying REST")
    if not api_key:
        return None
    try:
        return _verify_via_rest(id_token, api_key, auth_domain)
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
