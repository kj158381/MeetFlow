"""
database/models.py
SQLAlchemy ORM models for Meeting Automation.
"""
from datetime import datetime
import uuid
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def gen_uuid():
    return str(uuid.uuid4())

# ─── Users ──────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"
    id             = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    email          = db.Column(db.String(255), unique=True, nullable=False)
    name           = db.Column(db.String(255))
    picture        = db.Column(db.String(512), default="")
    auth_type      = db.Column(db.String(32), default="firebase")
    firebase_uid   = db.Column(db.String(128), default="")
    email_verified = db.Column(db.Integer, default=0)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    last_login     = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    meetings       = db.relationship("Meeting", back_populates="user", lazy="dynamic")
    tasks          = db.relationship("Task",    back_populates="user", lazy="dynamic")
    contacts       = db.relationship("Contact", back_populates="user", lazy="dynamic")
    settings       = db.relationship("UserSettings", back_populates="user", uselist=False)

    def to_dict(self):
        return {
            "id": self.id, "email": self.email, "name": self.name,
            "picture": self.picture, "auth_type": self.auth_type,
            "email_verified": bool(self.email_verified),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# ─── Meetings ────────────────────────────────────────────────────────────────

class Meeting(db.Model):
    __tablename__ = "meetings"
    id               = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id          = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    title            = db.Column(db.String(255), nullable=False)
    scheduled_at     = db.Column(db.String(32))
    duration_minutes = db.Column(db.Integer, default=60)
    status           = db.Column(db.String(32), default="scheduled")  # scheduled|live|completed|cancelled
    participants     = db.Column(db.Text, default="[]")
    description      = db.Column(db.Text, default="")
    location         = db.Column(db.String(255), default="")
    meeting_link     = db.Column(db.String(512), default="")
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    user       = db.relationship("User",  back_populates="meetings")
    notes      = db.relationship("MeetingNote", back_populates="meeting", lazy="dynamic")
    tasks      = db.relationship("Task",        back_populates="meeting", lazy="dynamic")
    cal_events = db.relationship("CalendarEvent", back_populates="meeting", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "title": self.title,
            "scheduled_at": self.scheduled_at, "duration_minutes": self.duration_minutes,
            "status": self.status, "participants": self.participants,
            "description": self.description, "location": self.location,
            "meeting_link": self.meeting_link,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# ─── Meeting Notes ───────────────────────────────────────────────────────────

class MeetingNote(db.Model):
    __tablename__ = "meeting_notes"
    id          = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    meeting_id  = db.Column(db.String(36), db.ForeignKey("meetings.id"), nullable=False)
    user_id     = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    title       = db.Column(db.String(255))
    content     = db.Column(db.Text, default="")
    key_points  = db.Column(db.Text, default="[]")
    ai_summary  = db.Column(db.Text, default="")
    translations= db.Column(db.Text, default="{}")
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    meeting = db.relationship("Meeting", back_populates="notes")

    def to_dict(self):
        return {
            "id": self.id, "meeting_id": self.meeting_id, "user_id": self.user_id,
            "title": self.title, "content": self.content, "key_points": self.key_points,
            "ai_summary": self.ai_summary, "translations": self.translations,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

# ─── Tasks ───────────────────────────────────────────────────────────────────

class Task(db.Model):
    __tablename__ = "tasks"
    id          = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id     = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    meeting_id  = db.Column(db.String(36), db.ForeignKey("meetings.id"), nullable=True)
    title       = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    status      = db.Column(db.String(32), default="todo")   # todo|in_progress|done
    priority    = db.Column(db.String(16), default="medium") # low|medium|high
    due_date    = db.Column(db.String(32))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    user    = db.relationship("User",    back_populates="tasks")
    meeting = db.relationship("Meeting", back_populates="tasks")

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "meeting_id": self.meeting_id,
            "title": self.title, "description": self.description, "status": self.status,
            "priority": self.priority, "due_date": self.due_date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# ─── Contacts ────────────────────────────────────────────────────────────────

class Contact(db.Model):
    __tablename__ = "contacts"
    id           = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id      = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    name         = db.Column(db.String(255), nullable=False)
    email        = db.Column(db.String(255))
    role         = db.Column(db.String(128))
    company      = db.Column(db.String(128))
    phone        = db.Column(db.String(32), default="")
    avatar_color = db.Column(db.String(16), default="#5b6af0")
    source       = db.Column(db.String(32), default="manual")  # manual|google|gmail
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="contacts")

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "name": self.name,
            "email": self.email, "role": self.role, "company": self.company,
            "phone": self.phone, "avatar_color": self.avatar_color,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# ─── Calendar Events ─────────────────────────────────────────────────────────

class CalendarEvent(db.Model):
    __tablename__ = "calendar_events"
    id         = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id    = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    meeting_id = db.Column(db.String(36), db.ForeignKey("meetings.id"), nullable=True)
    title      = db.Column(db.String(255), nullable=False)
    start_time = db.Column(db.String(32))
    end_time   = db.Column(db.String(32))
    all_day    = db.Column(db.Integer, default=0)
    color      = db.Column(db.String(16), default="#5b6af0")
    synced_at  = db.Column(db.DateTime, default=datetime.utcnow)

    meeting = db.relationship("Meeting", back_populates="cal_events")

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "meeting_id": self.meeting_id,
            "title": self.title, "start_time": self.start_time, "end_time": self.end_time,
            "all_day": bool(self.all_day), "color": self.color,
        }

# ─── Email Notifications ──────────────────────────────────────────────────────

class EmailNotification(db.Model):
    __tablename__ = "email_notifications"
    id              = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id         = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    meeting_id      = db.Column(db.String(36), nullable=True)
    recipient_email = db.Column(db.String(255), nullable=False)
    subject         = db.Column(db.String(512))
    body            = db.Column(db.Text)
    html_body       = db.Column(db.Text, default="")
    sent_at         = db.Column(db.DateTime, default=datetime.utcnow)
    status          = db.Column(db.String(16), default="queued")  # queued|sent|failed

# ─── User Settings ────────────────────────────────────────────────────────────

class UserSettings(db.Model):
    __tablename__ = "user_settings"
    id                     = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id                = db.Column(db.String(36), db.ForeignKey("users.id"), unique=True, nullable=False)
    display_name           = db.Column(db.String(255))
    timezone               = db.Column(db.String(64), default="UTC")
    language               = db.Column(db.String(8),  default="en")
    # Gmail SMTP
    gmail_address          = db.Column(db.String(255), default="")
    gmail_app_password     = db.Column(db.String(64),  default="")
    smtp_enabled           = db.Column(db.Integer, default=0)
    # Google OAuth tokens (persisted so reconnect not needed every login)
    google_access_token    = db.Column(db.Text, default="")
    google_refresh_token   = db.Column(db.Text, default="")
    # Notifications
    notif_browser          = db.Column(db.Integer, default=1)
    notif_email            = db.Column(db.Integer, default=1)
    notif_meeting_start    = db.Column(db.Integer, default=1)
    notif_meeting_reminder = db.Column(db.Integer, default=1)
    notif_task_due         = db.Column(db.Integer, default=1)
    notif_meeting_invite   = db.Column(db.Integer, default=1)
    notif_summary_ready    = db.Column(db.Integer, default=1)
    reminder_minutes       = db.Column(db.Integer, default=15)
    # AI Features
    feat_ai_summary        = db.Column(db.Integer, default=1)
    feat_auto_transcript   = db.Column(db.Integer, default=1)
    feat_smart_tasks       = db.Column(db.Integer, default=1)
    feat_calendar_sync     = db.Column(db.Integer, default=1)
    feat_live_translation  = db.Column(db.Integer, default=1)
    translation_language   = db.Column(db.String(8), default="es")
    # Appearance
    theme                  = db.Column(db.String(16), default="light")
    sidebar_compact        = db.Column(db.Integer, default=0)
    calendar_view          = db.Column(db.String(16), default="month")
    updated_at             = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="settings")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
