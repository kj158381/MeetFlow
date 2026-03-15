# 🚀 Meeting Automation — Production-Ready Web App

A full-featured meeting management platform built with **Flask**, **SQLAlchemy**, **Firebase Auth**, **Google APIs**, and **Gemini AI**.

---

## 📁 Project Structure

```
meeting_automation/
├── app.py                  # Main Flask app + all routes
├── config.py               # Centralised configuration
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variables template
├── .env                    # Your local config (gitignored)
│
├── database/
│   ├── __init__.py
│   └── models.py           # SQLAlchemy ORM models
│
├── routes/                 # (optional: split routes here as app grows)
│   └── __init__.py
│
├── services/
│   ├── __init__.py
│   ├── gemini_service.py   # Gemini AI (key points + translation)
│   ├── google_auth_service.py  # Firebase token verification
│   ├── gmail_service.py    # Gmail read via Google OAuth
│   ├── contacts_service.py # Google People API
│   └── calendar_service.py # Google Calendar API
│
├── utils/
│   ├── __init__.py
│   └── helpers.py          # Email building + SMTP sending
│
├── static/
│   ├── css/main.css        # Custom CSS
│   ├── js/
│   │   ├── main.js         # Shared JS
│   │   ├── calendar.js     # Calendar page logic
│   │   └── live_meeting.js # Live meeting + AI logic
│   ├── uploads/            # User avatar uploads
│   └── favicon.svg
│
├── templates/
│   ├── base.html           # Layout with sidebar
│   ├── login.html          # Login page (Firebase + email)
│   ├── dashboard.html      # Analytics + overview
│   ├── calendar.html       # Meeting calendar
│   ├── new_meeting.html    # Create meeting form
│   ├── live_meeting.html   # Live meeting + AI notes
│   ├── meeting_notes.html  # Meeting notes archive
│   ├── tasks.html          # Task management
│   ├── contacts.html       # Contacts (Google sync)
│   ├── join_page.html      # Join meeting by ID/URL
│   ├── join_meeting.html   # Public join link
│   ├── settings.html       # Full settings page
│   └── error.html          # Error pages
│
└── instance/
    └── meetingauto.db      # SQLite database (auto-created)
```

---

## ⚡ Quick Start

### 1. Clone and set up environment

```bash
git clone <repo>
cd meeting_automation
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run the app

```bash
python app.py
```

Open **http://localhost:5000**

---

## 🔑 API Keys Setup

### Firebase Auth (Google Sign-In)
1. Go to [Firebase Console](https://console.firebase.google.com)
2. Create project → Project Settings → Your apps → Add Web app
3. Copy `apiKey`, `authDomain`, `projectId`, `appId` to `.env`
4. Enable **Google** sign-in: Authentication → Sign-in method

### Gmail SMTP (Sending Emails)
> ⚠️ Use an **App Password**, NOT your regular Gmail password.
1. [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable 2-Step Verification
3. Search "App passwords" → Select Mail → Generate 16-char code
4. Add to `.env` as `SMTP_GMAIL_APP_PASSWORD`

### Google OAuth (Contacts, Calendar, Gmail Access)
> ⚠️ This is **different** from Firebase Auth!
1. [console.cloud.google.com](https://console.cloud.google.com)
2. APIs & Services → Credentials → Create → OAuth 2.0 Client
3. Set **Authorized Redirect URI**: `http://localhost:5000/auth/google/callback`
4. Enable APIs: **People API**, **Calendar API**, **Gmail API**
5. Copy Client ID and Secret to `.env`

### Gemini AI (Free)
1. [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Create API key → add to `.env` as `GEMINI_API_KEY`

---

## 🗄️ Database Models

| Model | Fields |
|-------|--------|
| `User` | id, email, name, picture, auth_type, firebase_uid |
| `Meeting` | id, user_id, title, scheduled_at, duration, status, participants |
| `MeetingNote` | id, meeting_id, content, key_points, ai_summary, translations |
| `Task` | id, user_id, meeting_id, title, status, priority, due_date |
| `Contact` | id, user_id, name, email, role, company, phone, source |
| `CalendarEvent` | id, user_id, meeting_id, title, start_time, end_time |
| `EmailNotification` | id, user_id, recipient_email, subject, status |
| `UserSettings` | id, user_id, gmail config, notifications, AI features, theme |

---

## 🌟 Features

| Feature | Status |
|---------|--------|
| Google OAuth Login (Firebase) | ✅ |
| Email/Password Login | ✅ |
| Dashboard Analytics | ✅ |
| Google Calendar Sync | ✅ |
| Create/Edit/Delete Meetings | ✅ |
| AI Meeting Notes (Gemini) | ✅ |
| AI Key Point Extraction | ✅ |
| Live Translation (12 languages) | ✅ |
| Task Management + Gmail Reminders | ✅ |
| Google Contacts Sync | ✅ |
| Gmail Read Access | ✅ |
| Email Meeting Invites | ✅ |
| Join Meeting (Meet/Zoom/Teams) | ✅ |
| Dark/Light Mode | ✅ |
| Full Settings Page | ✅ |

---

## 🚀 Production Deployment

```bash
gunicorn -w 4 -b 0.0.0.0:5000 "app:app"
```

Set in `.env`:
- `SECRET_KEY` = strong random string
- `APP_BASE_URL` = your domain (e.g. `https://yourdomain.com`)
- Update Google OAuth redirect URI to your domain
