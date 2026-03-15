import eventlet
eventlet.monkey_patch()

"""
app.py — Meeting Automation
Main Flask application factory + all route registrations.
"""
import os, json, uuid, logging, requests, threading
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, flash, make_response)
from flask_socketio import SocketIO, join_room, leave_room, emit as sio_emit

from config import Config
from database.models import (db, User, Meeting, MeetingNote, Task,
                              Contact, CalendarEvent, EmailNotification, UserSettings)
from utils.helpers import (send_gmail_smtp, email_html_template, pick_avatar_color)
from services.gemini_service import extract_key_points, gemini_translate
from services.google_auth_service import verify_firebase_token, exchange_google_code
from services.gmail_service import list_messages, get_message, parse_message_headers, extract_body
from services.contacts_service import fetch_google_contacts
from services.calendar_service import fetch_google_calendar_events

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=Config.PERMANENT_SESSION_LIFETIME,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{Config.DATABASE}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    os.makedirs(os.path.dirname(Config.DATABASE), exist_ok=True)
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()
    _register_routes(app)
    return app


# ─── SocketIO setup (real-time WebRTC signaling) ──────────────────────────────
# This is the core fix: all users in the same meeting room connect here
# and relay WebRTC offer/answer/ICE candidates to each other, so they
# end up in one shared video call instead of isolated solo sessions.

socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*", logger=False, engineio_logger=False)

# Tracks { room_id -> set(socket_id) }
_room_members = {}

def _init_socketio(app):
    socketio.init_app(app)

    @socketio.on("join-room")
    def on_join(data):
        room = data.get("room")
        user_name = data.get("name", "Guest")
        if not room:
            return
        join_room(room)
        _room_members.setdefault(room, set()).add(request.sid)
        # Tell everyone else in the room that a new peer arrived
        sio_emit("peer-joined", {"sid": request.sid, "name": user_name}, room=room, skip_sid=request.sid)
        # Send the new peer the list of existing members so it can initiate connections
        existing = list(_room_members[room] - {request.sid})
        sio_emit("room-peers", {"peers": existing}, to=request.sid)

    @socketio.on("leave-room")
    def on_leave(data):
        room = data.get("room")
        if room:
            leave_room(room)
            _room_members.get(room, set()).discard(request.sid)
            sio_emit("peer-left", {"sid": request.sid}, room=room)

    @socketio.on("disconnect")
    def on_disconnect():
        # Remove from all rooms on disconnect
        for room, members in list(_room_members.items()):
            if request.sid in members:
                members.discard(request.sid)
                sio_emit("peer-left", {"sid": request.sid}, room=room)

    # WebRTC signaling relay events — just forward between peers
    @socketio.on("webrtc-offer")
    def on_offer(data):
        target = data.get("target")
        if target:
            sio_emit("webrtc-offer", {"sdp": data["sdp"], "from": request.sid}, to=target)

    @socketio.on("webrtc-answer")
    def on_answer(data):
        target = data.get("target")
        if target:
            sio_emit("webrtc-answer", {"sdp": data["sdp"], "from": request.sid}, to=target)

    @socketio.on("webrtc-ice")
    def on_ice(data):
        target = data.get("target")
        if target:
            sio_emit("webrtc-ice", {"candidate": data["candidate"], "from": request.sid}, to=target)

    # Real-time chat relay
    @socketio.on("chat-message")
    def on_chat(data):
        room = data.get("room")
        if room:
            sio_emit("chat-message", {"name": data.get("name","Guest"), "text": data.get("text",""), "time": data.get("time","")}, room=room, skip_sid=request.sid)


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if "user" not in session:
            # Preserve the full requested path so we can redirect back after login
            next_url = request.url
            resp = make_response(redirect(url_for("login", next=next_url)))
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        return f(*a, **kw)
    return d

def api_login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if "user" not in session:
            return jsonify({"success": False, "error": "Not authenticated", "authenticated": False}), 401
        return f(*a, **kw)
    return d

def current_user():
    return session.get("user")

def get_google_access_token():
    """Return Google access token from session, falling back to DB if missing."""
    tok = session.get("google_access_token")
    if tok:
        return tok
    user = current_user()
    if user:
        try:
            s = UserSettings.query.filter_by(user_id=user["id"]).first()
            if s and s.google_access_token:
                # Restore into session for subsequent requests
                session["google_access_token"]  = s.google_access_token
                session["google_refresh_token"] = s.google_refresh_token or ""
                return s.google_access_token
        except Exception:
            pass
    return None


# ─── DB helpers ───────────────────────────────────────────────────────────────

def upsert_user(uid, email, name, picture="", auth_type="firebase", firebase_uid="", email_verified=0):
    now  = datetime.utcnow()
    user = User.query.get(uid)
    if user:
        user.name = name; user.picture = picture; user.auth_type = auth_type
        user.firebase_uid = firebase_uid; user.email_verified = email_verified; user.last_login = now
    else:
        user = User.query.filter_by(email=email).first()
        if user:
            uid = user.id
            user.name = name; user.picture = picture; user.firebase_uid = firebase_uid
            user.email_verified = email_verified; user.last_login = now
        else:
            user = User(id=uid, email=email, name=name, picture=picture,
                        auth_type=auth_type, firebase_uid=firebase_uid,
                        email_verified=email_verified, last_login=now)
            db.session.add(user)
    db.session.commit()
    _ensure_settings(uid)
    return uid

def _ensure_settings(user_id):
    if not UserSettings.query.filter_by(user_id=user_id).first():
        db.session.add(UserSettings(id=str(uuid.uuid4()), user_id=user_id))
        db.session.commit()

def get_settings(user_id):
    _ensure_settings(user_id)
    s = UserSettings.query.filter_by(user_id=user_id).first()
    result = s.to_dict() if s else {}
    if not result.get("gmail_address") and Config.DEFAULT_SMTP_ADDRESS:
        result["gmail_address"]      = Config.DEFAULT_SMTP_ADDRESS
        result["gmail_app_password"] = Config.DEFAULT_SMTP_PASSWORD
        result["smtp_enabled"]       = 1 if (Config.DEFAULT_SMTP_ADDRESS and Config.DEFAULT_SMTP_PASSWORD) else 0
    return result

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


# ─── Translation helpers ──────────────────────────────────────────────────────

def google_translate_api(text, target_lang, source_lang="en"):
    if not Config.TRANSLATE_API_ENABLED or not text: return None
    try:
        r = requests.post(
            f"https://translation.googleapis.com/language/translate/v2?key={Config.GOOGLE_TRANSLATE_API_KEY}",
            json={"q": text, "target": target_lang, "source": source_lang, "format": "text"}, timeout=10)
        d = r.json()
        if "error" in d: return None
        t = d.get("data", {}).get("translations", [])
        return t[0].get("translatedText") if t else None
    except Exception: return None

def mymemory_translate(text, target_lang, source_lang="en"):
    try:
        r = requests.get("https://api.mymemory.translated.net/get",
                         params={"q": text[:500], "langpair": f"{source_lang}|{target_lang}", "of": "json"}, timeout=10)
        d = r.json()
        t = d.get("responseData", {}).get("translatedText", "")
        if d.get("responseStatus") == 200 and t and t.upper() != text.upper(): return t
    except Exception: pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  ROUTE REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

def _register_routes(app):

    # ─── AUTH ─────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return redirect(url_for("dashboard") if "user" in session else url_for("login"))

    @app.route("/login")
    def login():
        if "user" in session:
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        # Save ?next= so auth handlers can redirect there after login
        next_url = request.args.get("next", "")
        if next_url:
            session["login_next"] = next_url
        resp = make_response(render_template("login.html",
            firebase_enabled=Config.FIREBASE_ENABLED,
            firebase_config={
                "apiKey": Config.FIREBASE_API_KEY, "authDomain": Config.FIREBASE_AUTH_DOMAIN,
                "projectId": Config.FIREBASE_PROJECT_ID, "storageBucket": Config.FIREBASE_STORAGE_BUCKET,
                "appId": Config.FIREBASE_APP_ID,
            }))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    @app.route("/auth/firebase", methods=["POST"])
    def auth_firebase():
        data = request.get_json() or {}
        id_token = data.get("idToken", ""); email = data.get("email", "").strip().lower()
        name = data.get("name", "").strip(); picture = data.get("picture", "")
        firebase_uid = data.get("uid", ""); email_verified = 1 if data.get("emailVerified") else 0

        if not email or "@" not in email:
            return jsonify({"success": False, "error": "Invalid email."}), 400

        if Config.FIREBASE_ENABLED and id_token:
            fb_user = verify_firebase_token(id_token, Config.FIREBASE_API_KEY)
            if fb_user:
                firebase_uid  = fb_user.get("localId", firebase_uid)
                email         = fb_user.get("email", email).lower()
                name          = fb_user.get("displayName", name) or email.split("@")[0].replace(".", " ").title()
                picture       = fb_user.get("photoUrl", picture)
                email_verified= 1 if fb_user.get("emailVerified") else 0

        if not name: name = email.split("@")[0].replace(".", " ").replace("_", " ").title()
        uid       = firebase_uid or str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
        final_uid = upsert_user(uid, email, name, picture, "firebase", firebase_uid, email_verified)
        session.permanent = True
        session["user"] = {"id": final_uid or uid, "email": email, "name": name,
                           "picture": picture, "auth_type": "firebase", "email_verified": bool(email_verified)}
        # ── Restore persisted Google tokens into session ──
        try:
            _uid = final_uid or uid
            s = UserSettings.query.filter_by(user_id=_uid).first()
            if s and s.google_access_token:
                session["google_access_token"]  = s.google_access_token
                session["google_refresh_token"] = s.google_refresh_token or ""
        except Exception:
            pass

        def _alert():
            with app.app_context():
                try:
                    s = get_settings(final_uid or uid)
                    gu = s.get("gmail_address") or Config.DEFAULT_SMTP_ADDRESS
                    gp = s.get("gmail_app_password") or Config.DEFAULT_SMTP_PASSWORD
                    if not gu or not gp: return
                    ltime  = datetime.now().strftime("%B %d, %Y at %I:%M %p UTC")
                    device = request.headers.get("User-Agent", "Unknown")[:120]
                    html   = email_html_template("🔐 New Login Detected", f"Hi {name},",
                        f"<p>New sign-in on your Meeting Automation account.</p>"
                        f"<table style='width:100%;border-collapse:collapse;margin:12px 0'>"
                        f"<tr><td style='padding:8px;color:#6b7280;font-size:13px'>⏰ Time</td><td style='padding:8px;font-weight:600'>{ltime}</td></tr>"
                        f"<tr style='background:#f8faff'><td style='padding:8px;color:#6b7280;font-size:13px'>📧 Account</td><td style='padding:8px;font-weight:600'>{email}</td></tr>"
                        f"<tr><td style='padding:8px;color:#6b7280;font-size:13px'>💻 Device</td><td style='padding:8px'>{device[:80]}</td></tr>"
                        f"</table><p style='color:#6b7280;font-size:13px'>If this wasn't you, secure your account immediately.</p>")
                    send_gmail_smtp(gu, gp, email, "🔐 New Login — Meeting Automation", html)
                except Exception as e:
                    logger.warning(f"Login alert failed: {e}")
        threading.Thread(target=_alert, daemon=True).start()
        # Honour ?next= param so invite links work after login
        next_url = request.args.get("next") or request.get_json(silent=True, force=True) and None
        # next may come as a query param on the POST or stored in session
        next_url = request.args.get("next") or session.pop("login_next", None) or url_for("dashboard")
        return jsonify({"success": True, "redirect": next_url})

    @app.route("/auth/demo", methods=["POST"])
    def auth_demo():
        """Email/password login when Firebase is not configured."""
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        if not email or "@" not in email:
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("login"))
        name     = email.split("@")[0].replace(".", " ").replace("_", " ").title()
        uid      = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
        final_uid = upsert_user(uid, email, name, "", "demo", "", 0)
        session.permanent = True
        session["user"] = {"id": final_uid or uid, "email": email, "name": name,
                           "picture": "", "auth_type": "demo", "email_verified": False}
        # ── Restore persisted Google tokens into session ──
        try:
            s = UserSettings.query.filter_by(user_id=final_uid or uid).first()
            if s and s.google_access_token:
                session["google_access_token"]  = s.google_access_token
                session["google_refresh_token"] = s.google_refresh_token or ""
        except Exception:
            pass
        next_url = session.pop("login_next", None) or url_for("dashboard")
        return redirect(next_url)

    @app.route("/auth/google")
    def auth_google_redirect():
        """Redirect /auth/google → /auth/google/connect for backward-compat."""
        return redirect(url_for("google_connect"))

    @app.route("/api/notify/login-alert", methods=["POST"])
    @api_login_required
    def api_login_alert():
        """Send a login-alert email (called from the login page JS)."""
        user = current_user()
        data = request.get_json(silent=True) or {}
        def _alert():
            with app.app_context():
                try:
                    s      = get_settings(user["id"])
                    gu     = s.get("gmail_address") or Config.DEFAULT_SMTP_ADDRESS
                    gp     = s.get("gmail_app_password") or Config.DEFAULT_SMTP_PASSWORD
                    if not gu or not gp: return
                    ltime  = data.get("login_time", datetime.now().strftime("%B %d, %Y at %I:%M %p UTC"))
                    device = data.get("device", "Unknown")[:120]
                    html   = email_html_template("🔐 New Login Detected", f"Hi {user['name']},",
                        f"<p>New sign-in on your Meeting Automation account.</p>"
                        f"<table style='width:100%;border-collapse:collapse;margin:12px 0'>"
                        f"<tr><td style='padding:8px;color:#6b7280;font-size:13px'>⏰ Time</td><td style='padding:8px;font-weight:600'>{ltime}</td></tr>"
                        f"<tr style='background:#f8faff'><td style='padding:8px;color:#6b7280;font-size:13px'>📧 Account</td><td style='padding:8px;font-weight:600'>{user['email']}</td></tr>"
                        f"<tr><td style='padding:8px;color:#6b7280;font-size:13px'>💻 Device</td><td style='padding:8px'>{device[:80]}</td></tr>"
                        f"</table><p style='color:#6b7280;font-size:13px'>If this wasn't you, secure your account immediately.</p>")
                    send_gmail_smtp(gu, gp, user["email"], "🔐 New Login — Meeting Automation", html)
                except Exception as e:
                    logger.warning(f"Login alert failed: {e}")
        threading.Thread(target=_alert, daemon=True).start()
        return jsonify({"success": True})

    @app.route("/logout")
    def logout():
        session.clear()
        resp = make_response(redirect(url_for("login")))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    @app.route("/api/auth/check")
    def api_auth_check():
        if "user" in session:
            u = session["user"]
            return jsonify({"authenticated": True, "email": u.get("email"), "name": u.get("name")})
        return jsonify({"authenticated": False}), 401

    # ─── PAGE ROUTES ───────────────────────────────────────────────────────────

    @app.route("/dashboard")
    @login_required
    def dashboard():
        user = current_user()
        meetings     = Meeting.query.filter_by(user_id=user["id"]).order_by(Meeting.scheduled_at.desc()).limit(8).all()
        open_tasks   = Task.query.filter_by(user_id=user["id"]).filter(Task.status != "done").order_by(Task.created_at.desc()).limit(8).all()
        done_tasks   = Task.query.filter_by(user_id=user["id"], status="done").order_by(Task.created_at.desc()).limit(5).all()
        upcoming     = Meeting.query.filter_by(user_id=user["id"], status="scheduled").order_by(Meeting.scheduled_at).limit(5).all()
        total        = Meeting.query.filter_by(user_id=user["id"]).count()
        completed    = Meeting.query.filter_by(user_id=user["id"], status="completed").count()
        emails_sent  = EmailNotification.query.filter_by(user_id=user["id"], status="sent").count()
        return render_template("dashboard.html",
            user=user, meetings=meetings, tasks=open_tasks, completed_tasks=done_tasks,
            upcoming=upcoming, settings=get_settings(user["id"]),
            total_meetings=total, completed=completed, emails_sent=emails_sent)

    @app.route("/calendar")
    @login_required
    def calendar():
        user = current_user()
        meetings = [m.to_dict() for m in Meeting.query.filter_by(user_id=user["id"]).order_by(Meeting.scheduled_at).all()]
        return render_template("calendar.html", user=user, meetings=meetings, settings=get_settings(user["id"]))

    @app.route("/meeting/new", methods=["GET", "POST"])
    @login_required
    def new_meeting():
        user = current_user()
        if request.method == "POST":
            mid   = str(uuid.uuid4())
            title = request.form.get("title", "Untitled Meeting").strip()
            sat   = request.form.get("scheduled_at", datetime.now().isoformat())
            dur   = int(request.form.get("duration_minutes", 60))
            parts = request.form.getlist("participants")
            desc  = request.form.get("description", "").strip()
            loc   = request.form.get("location", "").strip()
            link  = request.form.get("meeting_link", "").strip()
            m = Meeting(id=mid, user_id=user["id"], title=title, scheduled_at=sat,
                        duration_minutes=dur, participants=json.dumps(parts),
                        description=desc, location=loc,
                        meeting_link=link or url_for("live_meeting", mid=mid, _external=True))
            n = MeetingNote(id=str(uuid.uuid4()), meeting_id=mid, user_id=user["id"],
                            title=f"Notes: {title}", content="", key_points="[]")
            db.session.add(m); db.session.add(n)
            try:
                end = datetime.fromisoformat(sat) + timedelta(minutes=dur)
                db.session.add(CalendarEvent(id=str(uuid.uuid4()), user_id=user["id"],
                    meeting_id=mid, title=title, start_time=sat, end_time=end.isoformat()))
            except Exception: pass
            db.session.commit()
            if parts: _send_invites_bg(app, user, mid, title, sat, parts)
            flash(f"Meeting '{title}' created successfully!", "success")
            return redirect(url_for("live_meeting", mid=mid))
        contacts = Contact.query.filter_by(user_id=user["id"]).order_by(Contact.name).all()
        return render_template("new_meeting.html", user=user, contacts=contacts)

    @app.route("/meeting/<mid>")
    def meeting_redirect(mid):
        """Bare /meeting/<id> links (from emails).
        Logged-in users go straight to the live room.
        Guests are shown the join preview page to sign in first.
        """
        if "user" in session:
            return redirect(url_for("live_meeting", mid=mid))
        # Not logged in – save destination so after login they land in the room
        session["login_next"] = url_for("live_meeting", mid=mid)
        return redirect(url_for("join_meeting", mid=mid))

    @app.route("/meeting/<mid>/live")
    def live_meeting(mid):
        is_guest   = request.args.get("guest") == "1"
        guest_name = request.args.get("name", "Guest")
        meeting    = Meeting.query.get(mid)

        # ── If meeting not in local DB (shared link / email invite from
        #    another user or instance) build a lightweight stub so the
        #    room still loads instead of returning 404.
        if not meeting:
            meeting = Meeting.query.filter(Meeting.id.like(mid[:8] + "%")).first()
        if not meeting:
            import datetime as _dt
            _stub_dict = {
                "id": mid, "title": "MeetFlow Meeting", "status": "live",
                "scheduled_at": _dt.datetime.utcnow().isoformat(),
                "duration_minutes": 60, "participants": [], "meeting_link": "",
                "user_id": "", "description": ""
            }
            import types
            stub = types.SimpleNamespace(**_stub_dict)
            stub.to_dict = lambda: _stub_dict
            meeting = stub

        if is_guest:
            guest_user = {"id": "guest", "name": guest_name, "email": "", "picture": "", "auth_type": "guest"}
            notes = MeetingNote.query.filter_by(meeting_id=mid).first()
            return render_template("live_meeting.html", user=guest_user, meeting=meeting.to_dict(),
                notes=notes, settings={}, translate_api_enabled=Config.TRANSLATE_API_ENABLED,
                ai_enabled=Config.AI_ENABLED, is_guest=True)
        if "user" not in session: return redirect(url_for("login"))
        user  = current_user()
        notes = MeetingNote.query.filter_by(meeting_id=mid).first()
        return render_template("live_meeting.html", user=user, meeting=meeting.to_dict(),
            notes=notes, settings=get_settings(user["id"]),
            translate_api_enabled=Config.TRANSLATE_API_ENABLED,
            ai_enabled=Config.AI_ENABLED, is_guest=False)

    @app.route("/meeting-notes")
    @login_required
    def meeting_notes():
        user = current_user()
        rows = (db.session.query(MeetingNote, Meeting.title, Meeting.scheduled_at)
                .outerjoin(Meeting, MeetingNote.meeting_id == Meeting.id)
                .filter(MeetingNote.user_id == user["id"])
                .order_by(MeetingNote.updated_at.desc()).all())
        note_list = []
        for n, mt, ms in rows:
            d = n.to_dict(); d["meeting_title"] = mt; d["meeting_scheduled"] = ms
            note_list.append(d)
        return render_template("meeting_notes.html", user=user, notes=note_list)

    @app.route("/tasks")
    @login_required
    def tasks():
        user = current_user()
        return render_template("tasks.html", user=user,
            tasks=Task.query.filter_by(user_id=user["id"]).order_by(Task.created_at.desc()).all())

    @app.route("/contacts")
    @login_required
    def contacts():
        user = current_user()
        return render_template("contacts.html", user=user,
            contacts=Contact.query.filter_by(user_id=user["id"]).order_by(Contact.name).all(),
            google_connected=bool(get_google_access_token()),
            google_oauth_enabled=Config.GOOGLE_OAUTH_ENABLED)

    @app.route("/join")
    @login_required
    def join_page():
        user = current_user()
        recent = Meeting.query.filter_by(user_id=user["id"]).order_by(Meeting.scheduled_at.desc()).limit(5).all()
        return render_template("join_page.html", user=user, recent_meetings=recent)

    @app.route("/join/<mid>")
    def join_meeting(mid):
        # Strip any accidental trailing path components
        mid = mid.strip("/").split("/")[0]
        meeting = Meeting.query.get(mid)

        # Try prefix match for short IDs
        if not meeting and len(mid) >= 8:
            meeting = Meeting.query.filter(Meeting.id.like(mid[:8] + "%")).first()

        user = session.get("user")

        # If still not found, render stub join page instead of 404.
        # This handles links shared via email where the recipient's DB
        # doesn't have that meeting record yet.
        if not meeting:
            stub_meeting = {
                "id": mid, "title": "MeetFlow Meeting", "status": "live",
                "scheduled_at": None, "duration_minutes": 60,
                "participants": [], "meeting_link": "", "description": ""
            }
            return render_template("join_meeting.html",
                meeting=stub_meeting, user=user,
                live_url="/meeting/" + mid + "/live" if user else None,
                mid=mid)

        return render_template("join_meeting.html", meeting=meeting.to_dict(), user=user,
            live_url=url_for("live_meeting", mid=mid) if user else None, mid=mid)

    @app.route("/settings")
    @login_required
    def settings():
        user = current_user()
        email_count = EmailNotification.query.filter_by(user_id=user["id"], status="sent").count()
        return render_template("settings.html", user=user, settings=get_settings(user["id"]),
            email_count=email_count, firebase_enabled=Config.FIREBASE_ENABLED,
            translate_api_enabled=Config.TRANSLATE_API_ENABLED, ai_enabled=Config.AI_ENABLED,
            google_oauth_enabled=Config.GOOGLE_OAUTH_ENABLED,
            google_connected=bool(get_google_access_token()))

    @app.route("/settings/save", methods=["POST"])
    @login_required
    def settings_save():
        user = current_user(); data = request.form; chk = lambda f: 1 if data.get(f) == "on" else 0
        s = UserSettings.query.filter_by(user_id=user["id"]).first()
        if not s:
            s = UserSettings(id=str(uuid.uuid4()), user_id=user["id"]); db.session.add(s)
        s.display_name = data.get("display_name",""); s.timezone = data.get("timezone","UTC")
        s.language = data.get("language","en"); s.gmail_address = data.get("gmail_address","")
        s.gmail_app_password = data.get("gmail_app_password",""); s.smtp_enabled = chk("smtp_enabled")
        s.notif_browser = chk("notif_browser"); s.notif_email = chk("notif_email")
        s.notif_meeting_start = chk("notif_meeting_start"); s.notif_meeting_reminder = chk("notif_meeting_reminder")
        s.notif_task_due = chk("notif_task_due"); s.notif_meeting_invite = chk("notif_meeting_invite")
        s.notif_summary_ready = chk("notif_summary_ready"); s.reminder_minutes = int(data.get("reminder_minutes",15))
        s.feat_ai_summary = chk("feat_ai_summary"); s.feat_auto_transcript = chk("feat_auto_transcript")
        s.feat_smart_tasks = chk("feat_smart_tasks"); s.feat_calendar_sync = chk("feat_calendar_sync")
        s.feat_live_translation = chk("feat_live_translation"); s.translation_language = data.get("translation_language","es")
        s.theme = data.get("theme","light"); s.sidebar_compact = chk("sidebar_compact"); s.calendar_view = data.get("calendar_view","month")
        nn = data.get("display_name","").strip()
        if nn:
            u = User.query.get(user["id"])
            if u: u.name = nn
            session["user"] = {**session["user"], "name": nn}
        db.session.commit()
        flash("Settings saved successfully!", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/upload-avatar", methods=["POST"])
    @login_required
    def upload_avatar():
        user = current_user()
        if "avatar" not in request.files: return jsonify({"success": False, "message": "No file uploaded"})
        f = request.files["avatar"]
        if not f or f.filename == "" or not allowed_file(f.filename):
            return jsonify({"success": False, "message": "Invalid file."})
        ext = f.filename.rsplit(".", 1)[1].lower()
        filename = f"avatar_{user['id']}.{ext}"
        f.save(os.path.join(Config.UPLOAD_FOLDER, filename))
        pic_url = f"/static/uploads/{filename}"
        u = User.query.get(user["id"])
        if u: u.picture = pic_url
        db.session.commit(); session["user"] = {**session["user"], "picture": pic_url}
        return jsonify({"success": True, "url": pic_url})

    @app.route("/settings/test-email", methods=["POST"])
    @login_required
    def test_email():
        import smtplib
        user = current_user(); s = get_settings(user["id"]); bd = request.get_json(silent=True) or {}
        gu = bd.get("gmail_address","").strip() or s.get("gmail_address","")
        gp = bd.get("gmail_app_password","").strip() or s.get("gmail_app_password","")
        if not gu or not gp: return jsonify({"success": False, "message": "Add Gmail address and App Password first."})
        if len(gp.replace(" ","")) < 16: return jsonify({"success": False, "message": "App Password must be 16 chars."})
        try:
            html = email_html_template("✅ Gmail Connected!", f"Hi {user['name']},",
                "<p>Your Gmail SMTP is working with Meeting Automation! 🎉</p>")
            send_gmail_smtp(gu, gp, gu, "✅ Meeting Automation — Gmail Connected!", html)
            db.session.add(EmailNotification(id=str(uuid.uuid4()), user_id=user["id"], recipient_email=gu,
                subject="Test email", body="Test sent", html_body=html, status="sent"))
            db.session.commit()
            return jsonify({"success": True, "message": f"✅ Test email sent to {gu}!"})
        except smtplib.SMTPAuthenticationError:
            return jsonify({"success": False, "message": "❌ Auth failed. Use a 16-char Gmail App Password from myaccount.google.com → Security → App passwords."})
        except Exception as e:
            return jsonify({"success": False, "message": f"❌ Error: {str(e)[:300]}"})

    @app.route("/settings/save-gmail", methods=["POST"])
    @login_required
    def save_gmail():
        user = current_user(); data = request.get_json() or {}
        s = UserSettings.query.filter_by(user_id=user["id"]).first()
        if s:
            s.gmail_address = data.get("gmail_address",""); s.gmail_app_password = data.get("gmail_app_password","")
            s.smtp_enabled = 1 if data.get("smtp_enabled") else 0; db.session.commit()
        return jsonify({"success": True})

    # ─── CALENDAR API ──────────────────────────────────────────────────────────

    @app.route("/api/calendar/events")
    @api_login_required
    def api_calendar_events():
        user = current_user()
        return jsonify([e.to_dict() for e in CalendarEvent.query.filter_by(user_id=user["id"]).order_by(CalendarEvent.start_time).all()])

    @app.route("/api/calendar/events", methods=["POST"])
    @api_login_required
    def api_create_event():
        user = current_user(); data = request.get_json() or {}
        ev = CalendarEvent(id=str(uuid.uuid4()), user_id=user["id"],
            meeting_id=data.get("meeting_id"), title=data.get("title","Event"),
            start_time=data.get("start_time"), end_time=data.get("end_time"),
            all_day=data.get("all_day",0), color=data.get("color","#5b6af0"))
        db.session.add(ev); db.session.commit()
        return jsonify({"success": True, "event_id": ev.id})

    @app.route("/api/calendar/events/<eid>", methods=["PUT"])
    @api_login_required
    def api_update_event(eid):
        user = current_user(); data = request.get_json() or {}
        ev = CalendarEvent.query.filter_by(id=eid, user_id=user["id"]).first()
        if ev:
            ev.title = data.get("title", ev.title); ev.start_time = data.get("start_time", ev.start_time)
            ev.end_time = data.get("end_time", ev.end_time); ev.color = data.get("color", ev.color)
            db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/calendar/events/<eid>", methods=["DELETE"])
    @api_login_required
    def api_delete_event(eid):
        user = current_user()
        ev = CalendarEvent.query.filter_by(id=eid, user_id=user["id"]).first()
        if ev: db.session.delete(ev); db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/calendar/sync", methods=["POST"])
    @api_login_required
    def api_calendar_sync():
        user = current_user(); synced = 0
        for m in Meeting.query.filter_by(user_id=user["id"]).all():
            if CalendarEvent.query.filter_by(meeting_id=m.id).first(): continue
            try:
                end = datetime.fromisoformat(m.scheduled_at) + timedelta(minutes=m.duration_minutes)
                db.session.add(CalendarEvent(id=str(uuid.uuid4()), user_id=user["id"],
                    meeting_id=m.id, title=m.title, start_time=m.scheduled_at, end_time=end.isoformat()))
                synced += 1
            except Exception: pass
        db.session.commit()
        return jsonify({"success": True, "synced": synced, "message": f"{synced} event(s) synced."})

    # ─── MEETINGS API ──────────────────────────────────────────────────────────

    @app.route("/api/meetings")
    @api_login_required
    def api_meetings():
        user = current_user()
        return jsonify([m.to_dict() for m in Meeting.query.filter_by(user_id=user["id"]).order_by(Meeting.scheduled_at).all()])

    @app.route("/api/meetings", methods=["POST"])
    @api_login_required
    def api_create_meeting():
        user = current_user(); data = request.get_json() or {}; mid = str(uuid.uuid4())
        db.session.add(Meeting(id=mid, user_id=user["id"], title=data.get("title","Untitled"),
            scheduled_at=data.get("scheduled_at", datetime.now().isoformat()),
            duration_minutes=data.get("duration_minutes",60), participants=json.dumps(data.get("participants",[]))))
        db.session.add(MeetingNote(id=str(uuid.uuid4()), meeting_id=mid, user_id=user["id"],
            title=f"Notes: {data.get('title','')}", content="", key_points="[]"))
        db.session.commit()
        return jsonify({"success": True, "meeting_id": mid})

    @app.route("/api/meetings/<mid>/end", methods=["POST"])
    @api_login_required
    def api_end_meeting(mid):
        user = current_user(); m = Meeting.query.filter_by(id=mid, user_id=user["id"]).first()
        if m: m.status = "completed"; db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/meetings/<mid>/info")
    def api_meeting_info(mid):
        m = Meeting.query.get(mid)
        if not m: return jsonify({"error": "Not found"}), 404
        return jsonify({"id": m.id, "title": m.title, "scheduled_at": m.scheduled_at,
                        "duration_minutes": m.duration_minutes, "status": m.status})

    # ─── NOTES API ────────────────────────────────────────────────────────────

    @app.route("/api/notes/<nid>", methods=["GET"])
    @api_login_required
    def api_get_note(nid):
        user = current_user(); n = MeetingNote.query.filter_by(id=nid, user_id=user["id"]).first()
        return jsonify(n.to_dict()) if n else (jsonify({"error": "Not found"}), 404)

    @app.route("/api/notes/<nid>", methods=["PUT"])
    @api_login_required
    def api_update_note(nid):
        user = current_user(); data = request.get_json() or {}
        n = MeetingNote.query.filter_by(id=nid, user_id=user["id"]).first()
        if n:
            n.content = data.get("content",""); n.key_points = json.dumps(data.get("key_points",[]))
            n.ai_summary = data.get("ai_summary",""); n.updated_at = datetime.utcnow()
            db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/notes/save-from-meeting", methods=["POST"])
    @api_login_required
    def api_save_from_meeting():
        user = current_user(); data = request.get_json() or {}; mid = data.get("meeting_id")
        n = MeetingNote.query.filter_by(meeting_id=mid, user_id=user["id"]).first()
        kp = json.dumps(data.get("key_points",[])); summ = data.get("ai_summary","")
        if n:
            n.key_points = kp; n.ai_summary = summ; n.updated_at = datetime.utcnow()
        else:
            db.session.add(MeetingNote(id=str(uuid.uuid4()), meeting_id=mid, user_id=user["id"],
                title="AI Meeting Notes", content="", key_points=kp, ai_summary=summ))
        db.session.commit()
        return jsonify({"success": True, "message": "Notes saved!"})

    # ─── TASKS API ────────────────────────────────────────────────────────────

    @app.route("/api/tasks", methods=["GET"])
    @api_login_required
    def api_tasks():
        user = current_user()
        return jsonify([t.to_dict() for t in Task.query.filter_by(user_id=user["id"]).order_by(Task.created_at.desc()).all()])

    @app.route("/api/tasks", methods=["POST"])
    @api_login_required
    def api_create_task():
        user = current_user(); data = request.get_json() or {}
        t = Task(id=str(uuid.uuid4()), user_id=user["id"], meeting_id=data.get("meeting_id"),
            title=data.get("title","New Task"), description=data.get("description",""),
            priority=data.get("priority","medium"), due_date=data.get("due_date"))
        db.session.add(t); db.session.commit()
        return jsonify({"success": True, "task_id": t.id, "task": t.to_dict()})

    @app.route("/api/tasks/<tid>", methods=["PUT"])
    @api_login_required
    def api_update_task(tid):
        user = current_user(); data = request.get_json() or {}
        t = Task.query.filter_by(id=tid, user_id=user["id"]).first()
        if t:
            t.status = data.get("status", t.status); t.title = data.get("title", t.title)
            t.description = data.get("description", t.description); t.priority = data.get("priority", t.priority)
            t.due_date = data.get("due_date", t.due_date); db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/tasks/<tid>", methods=["DELETE"])
    @api_login_required
    def api_delete_task(tid):
        user = current_user(); t = Task.query.filter_by(id=tid, user_id=user["id"]).first()
        if t: db.session.delete(t); db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/tasks/<tid>/send-reminder", methods=["POST"])
    @api_login_required
    def api_task_send_reminder(tid):
        import smtplib
        user = current_user(); s = get_settings(user["id"])
        t = Task.query.filter_by(id=tid, user_id=user["id"]).first()
        if not t: return jsonify({"success": False, "message": "Task not found."})
        gu = s.get("gmail_address",""); gp = s.get("gmail_app_password","")
        if not s.get("smtp_enabled") or not gu or not gp:
            return jsonify({"success": False, "message": "Configure Gmail SMTP in Settings first."})
        try:
            html = email_html_template(f"📋 Task Reminder: {t.title}", f"Hi {user['name']},",
                f"<p>Reminder for your task:</p>"
                f"<table style='width:100%;border-collapse:collapse;margin:12px 0'>"
                f"<tr><td style='padding:8px;color:#6b7280;font-size:13px'>Task</td><td style='padding:8px;font-weight:600'>{t.title}</td></tr>"
                f"<tr style='background:#f8faff'><td style='padding:8px;color:#6b7280;font-size:13px'>Priority</td><td style='padding:8px'>{t.priority.title()}</td></tr>"
                f"<tr><td style='padding:8px;color:#6b7280;font-size:13px'>Due Date</td><td style='padding:8px'>{t.due_date or 'Not set'}</td></tr>"
                f"</table>")
            send_gmail_smtp(gu, gp, user["email"], f"📋 Task Reminder: {t.title}", html)
            return jsonify({"success": True, "message": f"Reminder sent to {user['email']}!"})
        except smtplib.SMTPAuthenticationError:
            return jsonify({"success": False, "message": "Gmail auth failed. Check your App Password."})
        except Exception as e:
            return jsonify({"success": False, "message": f"Error: {str(e)[:200]}"})

    # ─── CONTACTS API ──────────────────────────────────────────────────────────

    @app.route("/api/contacts", methods=["POST"])
    @api_login_required
    def api_create_contact():
        user = current_user(); data = request.get_json() or {}
        c = Contact(id=str(uuid.uuid4()), user_id=user["id"], name=data.get("name",""),
            email=data.get("email",""), role=data.get("role",""), company=data.get("company",""),
            phone=data.get("phone",""), source="manual", avatar_color=pick_avatar_color(data.get("name","")))
        db.session.add(c); db.session.commit()
        return jsonify({"success": True, "contact_id": c.id, "contact": c.to_dict()})

    @app.route("/api/contacts/<cid>", methods=["DELETE"])
    @api_login_required
    def api_delete_contact(cid):
        user = current_user(); c = Contact.query.filter_by(id=cid, user_id=user["id"]).first()
        if c: db.session.delete(c); db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/contacts/google-sync")
    @api_login_required
    def api_google_contacts_sync():
        user = current_user(); access_token = get_google_access_token()
        if not access_token:
            return jsonify({"success": False, "error": "Not connected to Google", "needs_auth": True,
                            "auth_url": url_for("google_connect")}), 401
        status, google_contacts = fetch_google_contacts(access_token)
        if status == 401:
            session.pop("google_access_token", None)
            return jsonify({"success": False, "error": "Token expired", "needs_auth": True,
                            "auth_url": url_for("google_connect")}), 401
        imported = 0
        for gc in google_contacts:
            email = gc.get("email",""); name = gc.get("name","")
            if email and Contact.query.filter_by(user_id=user["id"], email=email).first(): continue
            if not email and name and Contact.query.filter_by(user_id=user["id"], name=name).first(): continue
            db.session.add(Contact(id=str(uuid.uuid4()), user_id=user["id"], name=name or "(No name)",
                email=email, role="Google Contact", company=gc.get("company",""),
                phone=gc.get("phone",""), source="google", avatar_color=pick_avatar_color(name)))
            imported += 1
        db.session.commit()
        return jsonify({"success": True, "imported": imported, "message": f"Imported {imported} new contacts from Google."})

    # ─── EMAIL API ─────────────────────────────────────────────────────────────

    @app.route("/api/notify/meeting-invite", methods=["POST"])
    @api_login_required
    def api_notify_meeting_invite():
        import smtplib
        user = current_user(); data = request.get_json() or {}
        recipients = [e.strip() for e in data.get("recipients",[]) if e and "@" in str(e)]
        title = data.get("meeting_title","Meeting"); mtime = data.get("meeting_time",""); link = data.get("meeting_link","")
        s = get_settings(user["id"]); gu = s.get("gmail_address",""); gp = s.get("gmail_app_password","")
        smtp_ok = bool(s.get("smtp_enabled") and gu and gp)
        if not recipients: return jsonify({"success": False, "message": "No valid email addresses."})
        subject = f"📅 You're invited to: {title}"; sent = 0; failed = 0; results = {}
        for email in recipients:
            html = email_html_template(f"📅 {title}", "Hi there,",
                f"<p><strong>{user['name']}</strong> has invited you to a meeting.</p>"
                f"<table style='width:100%;border-collapse:collapse;margin:16px 0;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden'>"
                f"<tr style='background:#f8faff'><td style='padding:12px 16px;color:#6b7280;font-size:13px'>📅 When</td>"
                f"<td style='padding:12px 16px;font-size:14px;font-weight:600'>{mtime}</td></tr>"
                f"<tr><td style='padding:12px 16px;color:#6b7280;font-size:13px'>👤 Host</td>"
                f"<td style='padding:12px 16px;font-size:14px'>{user['name']} ({user['email']})</td></tr>"
                f"</table>", link, "Join Meeting Now")
            text = f"Hi,\n\n{user['name']} invited you.\nMeeting: {title}\nWhen: {mtime}\nJoin: {link}"
            status = "queued"
            if smtp_ok:
                try:
                    send_gmail_smtp(gu, gp, email, subject, html, text, reply_to=gu)
                    status = "sent"; sent += 1; results[email] = "✅ sent"
                except Exception as e:
                    status = "failed"; failed += 1; results[email] = f"❌ {str(e)[:80]}"
            db.session.add(EmailNotification(id=str(uuid.uuid4()), user_id=user["id"], recipient_email=email,
                subject=subject, body=text, html_body=html, status=status))
        db.session.commit()
        if not smtp_ok:
            return jsonify({"success": True, "smtp_needed": True,
                "message": f"⚠️ {len(recipients)} invite(s) queued. Set up Gmail SMTP in Settings to send real emails."})
        msg = f"✅ {sent} invite(s) sent!" if sent == len(recipients) else f"✅ {sent} sent, ❌ {failed} failed."
        return jsonify({"success": sent > 0, "message": msg, "sent": sent, "failed": failed, "results": results})

    @app.route("/api/send-email", methods=["POST"])
    @api_login_required
    def api_send_email():
        user = current_user(); data = request.get_json() or {}; s = get_settings(user["id"])
        to_emails = data.get("to",[]); subject = data.get("subject","").strip(); body_text = data.get("body","").strip()
        if isinstance(to_emails, str):
            to_emails = [e.strip() for e in to_emails.replace(",","\n").splitlines() if e.strip()]
        to_emails = [e.strip() for e in to_emails if e and "@" in str(e)]
        if not to_emails: return jsonify({"success": False, "message": "No valid recipient."})
        if not subject: return jsonify({"success": False, "message": "Subject required."})
        gu = s.get("gmail_address",""); gp = s.get("gmail_app_password","")
        if not s.get("smtp_enabled") or not gu or not gp:
            return jsonify({"success": False, "smtp_needed": True, "message": "Configure Gmail SMTP in Settings first."})
        html_content = "".join(
            f"<p style='margin:0 0 12px 0;color:#374151;font-size:15px;line-height:1.7'>{line}</p>" if line.strip() else "<br/>"
            for line in body_text.splitlines())
        html = email_html_template(subject, "Hi,", html_content)
        sent = 0; failed = 0; results = {}
        for email in to_emails:
            status = "queued"
            try:
                send_gmail_smtp(gu, gp, email, subject, html, body_text, reply_to=gu)
                status = "sent"; sent += 1; results[email] = "✅ sent"
            except Exception as e:
                status = "failed"; failed += 1; results[email] = f"❌ {str(e)[:80]}"
            db.session.add(EmailNotification(id=str(uuid.uuid4()), user_id=user["id"], recipient_email=email,
                subject=subject, body=body_text, html_body=html, status=status))
        db.session.commit()
        return jsonify({"success": sent > 0, "message": f"✅ {sent} email(s) sent." if sent == len(to_emails)
            else f"⚠️ {sent} sent, {failed} failed.", "sent": sent, "results": results})

    # ─── AI (GEMINI) API ──────────────────────────────────────────────────────

    @app.route("/api/ai/extract-key-points", methods=["POST"])
    @api_login_required
    def api_ai_key_points():
        data = request.get_json() or {}
        return jsonify(extract_key_points(data.get("transcript","").strip(), Config.GEMINI_API_KEY))

    @app.route("/api/translate", methods=["POST"])
    @api_login_required
    def api_translate():
        data = request.get_json() or {}; text = data.get("text","").strip()
        lang = data.get("target_lang","es"); source_lang = data.get("source_lang","en")
        lang_name = Config.LANG_NAMES.get(lang, lang.upper())
        if not text: return jsonify({"translated":"","lang":lang,"method":"none"})
        if Config.AI_ENABLED:
            t = gemini_translate(text, lang, source_lang, lang_name, Config.GEMINI_API_KEY)
            if t: return jsonify({"translated":t,"lang":lang,"lang_name":lang_name,"method":"gemini"})
        t = google_translate_api(text, lang, source_lang)
        if t: return jsonify({"translated":t,"lang":lang,"lang_name":lang_name,"method":"google"})
        t = mymemory_translate(text, lang, source_lang)
        if t: return jsonify({"translated":t,"lang":lang,"lang_name":lang_name,"method":"mymemory"})
        return jsonify({"translated":f"[{lang_name}] {text}","lang":lang,"lang_name":lang_name,"method":"unavailable"})

    @app.route("/api/settings")
    @api_login_required
    def api_get_settings():
        user = current_user(); s = get_settings(user["id"]); s.pop("gmail_app_password", None)
        return jsonify(s)

    # ─── GOOGLE OAUTH ─────────────────────────────────────────────────────────

    @app.route("/auth/google/setup")
    @login_required
    def google_setup():
        """Alias — used by setup-error links in templates."""
        from flask import redirect, url_for as _uf
        return redirect(_uf("google_connect"))

    @app.route("/auth/google/connect")
    @login_required
    def google_connect():
        import urllib.parse
        if not Config.GOOGLE_OAUTH_ENABLED:
            flash("Configure Google OAuth credentials in Settings first.", "info")
            return redirect(url_for("settings"))
        redirect_uri = url_for("google_callback", _external=True)
        params = {"client_id": Config.GOOGLE_OAUTH_CLIENT_ID, "redirect_uri": redirect_uri,
                  "response_type": "code",
                  "scope": "https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/gmail.readonly openid email profile",
                  "access_type": "offline", "prompt": "consent"}
        return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params))

    @app.route("/auth/google/callback")
    def google_callback():
        code = request.args.get("code"); error = request.args.get("error")
        if error or not code:
            flash(f"Google sign-in cancelled: {error or 'no code'}", "error")
            return redirect(url_for("contacts"))
        if "user" not in session:
            flash("Session expired.", "error"); return redirect(url_for("login"))
        try:
            redirect_uri = url_for("google_callback", _external=True)
            token_resp = exchange_google_code(code, Config.GOOGLE_OAUTH_CLIENT_ID,
                                              Config.GOOGLE_OAUTH_CLIENT_SECRET, redirect_uri)
            if token_resp.get("access_token"):
                access_tok  = token_resp["access_token"]
                refresh_tok = token_resp.get("refresh_token", "")
                session["google_access_token"]  = access_tok
                session["google_refresh_token"] = refresh_tok
                # ── Persist tokens to DB so they survive session expiry ──
                user = current_user()
                if user:
                    s = UserSettings.query.filter_by(user_id=user["id"]).first()
                    if s:
                        s.google_access_token  = access_tok
                        if refresh_tok:
                            s.google_refresh_token = refresh_tok
                        db.session.commit()
                flash("✅ Google account connected! Contacts & Calendar access enabled.", "success")
                return redirect(url_for("contacts") + "?synced=1")
            flash(f"❌ Google auth failed: {token_resp.get('error','unknown')}", "error")
        except Exception as e:
            flash(f"❌ Google auth error: {e}", "error")
        return redirect(url_for("contacts"))

    @app.route("/api/contacts/google-calendar")
    @api_login_required
    def api_google_calendar_sync():
        user = current_user(); access_token = get_google_access_token()
        if not access_token: return jsonify({"success": False, "error": "Not connected", "needs_auth": True}), 401
        status, events = fetch_google_calendar_events(access_token)
        if status == 401:
            session.pop("google_access_token", None)
            return jsonify({"success": False, "error": "Token expired", "needs_auth": True}), 401
        synced = 0
        for event in events:
            if CalendarEvent.query.filter_by(id=event["id"], user_id=user["id"]).first(): continue
            db.session.add(CalendarEvent(id=event["id"], user_id=user["id"], title=event["title"],
                start_time=event["start"], end_time=event["end"])); synced += 1
        db.session.commit()
        return jsonify({"success": True, "synced": synced, "message": f"Synced {synced} calendar events."})

    @app.route("/api/gmail/messages")
    @api_login_required
    def api_gmail_messages():
        access_token = get_google_access_token()
        if not access_token:
            return jsonify({"success": False, "error": "Not connected", "needs_auth": True,
                            "auth_url": url_for("google_connect")}), 401
        max_results = int(request.args.get("maxResults", 20)); query = request.args.get("q","")
        status, data = list_messages(access_token, max_results, query)
        if status == 401:
            session.pop("google_access_token", None)
            return jsonify({"success": False, "error": "Token expired", "needs_auth": True,
                            "auth_url": url_for("google_connect")}), 401
        messages = []
        for m in data.get("messages", [])[:max_results]:
            msg_status, detail = get_message(access_token, m["id"])
            if msg_status != 200: continue
            payload = detail.get("payload",{}); headers = parse_message_headers(payload)
            messages.append({"id": m["id"], **headers, "snippet": detail.get("snippet",""),
                              "labelIds": detail.get("labelIds",[])})
        return jsonify({"success": True, "messages": messages})

    @app.route("/api/gmail/message/<message_id>")
    @api_login_required
    def api_gmail_message_detail(message_id):
        access_token = get_google_access_token()
        if not access_token: return jsonify({"success": False, "error": "Not connected"}), 401
        msg_status, data = get_message(access_token, message_id)
        if msg_status == 401:
            session.pop("google_access_token", None)
            return jsonify({"success": False, "error": "Token expired", "needs_auth": True}), 401
        payload = data.get("payload",{}); body = []
        extract_body(payload, body); headers = parse_message_headers(payload)
        return jsonify({"success": True, "id": message_id, **headers,
                        "body": body[0] if body else "", "snippet": data.get("snippet","")})

    @app.route("/api/integrations/status")
    @api_login_required
    def api_integrations_status():
        s = get_settings(current_user()["id"])
        return jsonify({"google_contacts": bool(get_google_access_token()),
                        "google_calendar": bool(get_google_access_token()),
                        "gmail_read": bool(get_google_access_token()),
                        "gmail_smtp": bool(s.get("smtp_enabled")),
                        "gemini_ai": Config.AI_ENABLED, "google_translate": Config.TRANSLATE_API_ENABLED})

    @app.route("/api/debug/config")
    @api_login_required
    def api_debug_config():
        s = get_settings(current_user()["id"])
        return jsonify({"firebase_auth": {"configured": Config.FIREBASE_ENABLED},
                        "google_oauth": {"configured": Config.GOOGLE_OAUTH_ENABLED},
                        "gemini_ai": {"configured": Config.AI_ENABLED},
                        "google_translate": {"configured": Config.TRANSLATE_API_ENABLED},
                        "gmail_smtp_env": {"configured": bool(Config.DEFAULT_SMTP_ADDRESS)},
                        "gmail_smtp_user": {"configured": bool(s.get("smtp_enabled") and s.get("gmail_address"))},
                        "google_connected": {"configured": bool(get_google_access_token())}})

    # ─── CONTEXT + ERROR HANDLERS ─────────────────────────────────────────────

    @app.context_processor
    def inject_globals():
        user = session.get("user"); sett = {}
        if user:
            try:
                s = UserSettings.query.filter_by(user_id=user["id"]).first()
                if s: sett = s.to_dict()
            except Exception: pass
        return {"now": datetime.now().hour, "firebase_enabled": Config.FIREBASE_ENABLED,
                "firebase_config": {"apiKey": Config.FIREBASE_API_KEY, "authDomain": Config.FIREBASE_AUTH_DOMAIN,
                                    "projectId": Config.FIREBASE_PROJECT_ID, "storageBucket": Config.FIREBASE_STORAGE_BUCKET,
                                    "appId": Config.FIREBASE_APP_ID} if Config.FIREBASE_ENABLED else {},
                "ai_enabled": Config.AI_ENABLED, "translate_api_enabled": Config.TRANSLATE_API_ENABLED,
                "google_oauth_enabled": Config.GOOGLE_OAUTH_ENABLED,
                "google_connected": bool(get_google_access_token()), "settings": sett}

    @app.errorhandler(404)
    def not_found(e): return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(500)
    def server_error(e): return render_template("error.html", code=500, message="Internal server error."), 500


def _send_invites_bg(app, user, mid, title, sat, recipients):
    def _do():
        with app.app_context():
            s = get_settings(user["id"]); gu = s.get("gmail_address",""); gp = s.get("gmail_app_password","")
            smtp_ok = bool(s.get("smtp_enabled") and gu and gp)
            join_url = f"{Config.APP_BASE_URL}/meeting/{mid}/live"
            for email in recipients:
                if not email or "@" not in email: continue
                html = email_html_template(f"📅 {title}", "Hi there,",
                    f"<p><strong>{user['name']}</strong> scheduled a meeting and invited you.</p>"
                    f"<p>When: <strong>{sat}</strong></p>", join_url, "Join Meeting")
                text = f"Hi,\n\n{user['name']} scheduled '{title}'.\nWhen: {sat}\nJoin: {join_url}"
                status = "queued"
                if smtp_ok:
                    try: send_gmail_smtp(gu, gp, email, f"📅 Invite: {title}", html, text, reply_to=gu); status = "sent"
                    except Exception as e: logger.warning(f"Invite to {email} failed: {e}")
                db.session.add(EmailNotification(id=str(uuid.uuid4()), user_id=user["id"], meeting_id=mid,
                    recipient_email=email, subject=f"📅 Invite: {title}", body=text, html_body=html, status=status))
            db.session.commit()
    threading.Thread(target=_do, daemon=True).start()


app = create_app()
_init_socketio(app)

if __name__ == "__main__":
    print(f"\n{'═'*62}")
    print(f"  🚀  Meeting Automation — Production Edition")
    print(f"  📍  URL:           http://localhost:5000")
    print(f"  🔥  Firebase:      {'✅ ENABLED' if Config.FIREBASE_ENABLED  else '⚠️  Add FIREBASE_API_KEY to .env'}")
    print(f"  🤖  Gemini AI:     {'✅ ENABLED' if Config.AI_ENABLED        else '⚠️  Add GEMINI_API_KEY to .env'}")
    print(f"  🌐  Translate:     {'✅ ENABLED' if Config.TRANSLATE_API_ENABLED else '⚠️  Using free MyMemory fallback'}")
    print(f"  🔗  Google OAuth:  {'✅ ENABLED' if Config.GOOGLE_OAUTH_ENABLED else '⚠️  Add GOOGLE_OAUTH_CLIENT_ID'}")
    print(f"{'═'*62}\n")
    socketio.run(app, debug=True, port=5000, host="0.0.0.0")
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "MeetFlow Running!"
