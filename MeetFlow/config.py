"""
Meeting Automation — config.py
Centralised configuration: reads .env and exposes all settings.
"""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Config:
    # ── Flask core ────────────────────────────────────────────────
    SECRET_KEY                = os.environ.get("SECRET_KEY", "meetingauto-secret-2025-xK9mP3qR")
    APP_BASE_URL              = os.environ.get("APP_BASE_URL", "http://localhost:5000").rstrip("/")
    SESSION_COOKIE_HTTPONLY   = True
    SESSION_COOKIE_SAMESITE   = "Lax"
    PERMANENT_SESSION_LIFETIME= 86400 * 7  # 7 days

    # ── Database ──────────────────────────────────────────────────
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "instance", "meetingauto.db"))
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(BASE_DIR, "static", "uploads"))
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

    # ── Firebase Auth ─────────────────────────────────────────────
    FIREBASE_API_KEY      = os.environ.get("FIREBASE_API_KEY", "").strip()
    FIREBASE_AUTH_DOMAIN  = os.environ.get("FIREBASE_AUTH_DOMAIN", "").strip()
    FIREBASE_PROJECT_ID   = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
    FIREBASE_APP_ID       = os.environ.get("FIREBASE_APP_ID", "").strip()
    FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET", "").strip()
    FIREBASE_ENABLED      = bool(FIREBASE_API_KEY)

    # ── Google OAuth (Contacts / Calendar / Gmail) ─────────────────
    GOOGLE_OAUTH_CLIENT_ID     = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    GOOGLE_OAUTH_ENABLED       = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)

    # ── Gemini AI ─────────────────────────────────────────────────
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
    AI_ENABLED     = bool(GEMINI_API_KEY)

    # ── Google Translate (optional) ───────────────────────────────
    GOOGLE_TRANSLATE_API_KEY = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "").strip()
    TRANSLATE_API_ENABLED    = bool(GOOGLE_TRANSLATE_API_KEY)

    # ── Default SMTP (fallback from .env) ─────────────────────────
    DEFAULT_SMTP_ADDRESS  = os.environ.get("SMTP_GMAIL_ADDRESS", "").strip()
    DEFAULT_SMTP_PASSWORD = os.environ.get("SMTP_GMAIL_APP_PASSWORD", "").strip()

    # ── Supported translation languages ───────────────────────────
    LANG_NAMES = {
        "es": "Spanish", "fr": "French", "de": "German", "hi": "Hindi",
        "zh": "Chinese", "ja": "Japanese", "ar": "Arabic", "pt": "Portuguese",
        "ru": "Russian", "ko": "Korean", "ta": "Tamil", "it": "Italian",
        "nl": "Dutch", "pl": "Polish", "tr": "Turkish",
    }
