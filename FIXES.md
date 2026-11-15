# MeetFlow — v5 Fixes (project would not work / could not log in)

## Critical
1. **Nobody could log in without Firebase keys.** The shipped `.env` has blank Firebase keys, and in that mode `login.html` showed only a "Continue with Google" button that redirected to `/auth/google` -> which required login -> back to `/login` (endless loop). The `/auth/demo` route existed but no form posted to it.
   **Fix:** `templates/login.html` now shows an email sign-in form (demo mode) that posts to `/auth/demo` and keeps `?next=`.
2. **Invite link sent invitees into a login loop.** `/meeting/<id>/live` redirected guests to `/login` and forgot the destination. **Fix:** guests now go to `/join/<id>` (join as guest or sign in) and the destination is remembered. Invite emails now link to `/join/<id>`.
3. **Login-alert email never sent** after Firebase login: the background thread read `request.headers` outside a request context. **Fix:** User-Agent is read before the thread starts.
4. **Missing route** `/api/translate/summary` (called by the live-meeting page) returned 404. **Fix:** route added.
5. **Crash on Python 3.9** (`str | None` type hints in `services/`). **Fix:** `from __future__ import annotations`.

## Security / robustness
6. `?next=` accepted any URL (open redirect). **Fix:** new `safe_next()` only allows same-site relative paths (server and client side).
7. `login_required` used the absolute `request.url`; now uses the relative path.
8. Non-numeric `duration_minutes` / `reminder_minutes` caused HTTP 500. **Fix:** safe parsing.
9. Removed a dead/confusing line in `auth_firebase`.

## Earlier fixes (v4) are kept — see below.

---

# MeetFlow — Bug Fixes (404 on Join via Email Link)

## Root Cause

When a user creates a meeting and sends an email invite, recipients click the link and get a **404 "Meeting not found"** error. There were **4 bugs** causing this:

---

## Bug 1 — `login_required` lost the destination URL

**File:** `app.py` — `login_required` decorator  
**Problem:** When a guest clicked a meeting link and wasn't logged in, they were redirected to `/login` with no memory of where they were going. After login, they always landed on `/dashboard`.  
**Fix:** The decorator now passes `?next=<original_url>` to the login page, and stores it in `session["login_next"]`.

---

## Bug 2 — Firebase auth always redirected to `/dashboard`

**File:** `app.py` — `auth_firebase` route  
**Problem:** After Firebase login, the server always returned `{"redirect": "/dashboard"}`, ignoring any `?next=` parameter.  
**Fix:** The route now reads `session["login_next"]` (set by the login page) and uses it as the redirect target.

---

## Bug 3 — Demo auth always redirected to `/dashboard`

**File:** `app.py` — `auth_demo` route  
**Problem:** Same as Bug 2 — demo/email login always sent users to `/dashboard`.  
**Fix:** Same fix — reads `session["login_next"]` first.

---

## Bug 4 — `APP_BASE_URL=http://localhost:5000` in email invites

**File:** `.env`  
**Problem:** Meeting invite emails contained links like `http://localhost:5000/meeting/<id>/live`. This URL only works on the host machine — recipients on other computers get a connection error, not a 404.  
**Fix:** Updated `.env` with clear instructions. **You must set `APP_BASE_URL` to your real server address** before sending invites:

```
# For a public server:
APP_BASE_URL=https://yourdomain.com

# For a local network:
APP_BASE_URL=http://192.168.1.100:5000
```

---

## Bug 5 — `/meeting/<mid>` redirect didn't preserve destination

**File:** `app.py` — `meeting_redirect` route  
**Problem:** Email links used `/meeting/<id>` which redirected everyone to the join page. Logged-in users had to click again to enter the room.  
**Fix:** Logged-in users are sent directly to `/meeting/<id>/live`. Not-logged-in users go to the join page, but `session["login_next"]` is pre-set to the live room so after login they land in the meeting.

---

## Bug 6 — Join page sign-in links pointed back to join page (not live room)

**File:** `templates/join_meeting.html`  
**Problem:** "Sign In & Join" buttons used `?next=/join/<mid>` — after login the user returned to the join preview page and had to click again.  
**Fix:** Links now use `?next=/meeting/<mid>/live` so users enter the room immediately after signing in.

---

## Summary of Changed Files

| File | Change |
|------|--------|
| `app.py` | `login_required` passes `?next=` to login |
| `app.py` | `login` route saves `next` in session |
| `app.py` | `auth_firebase` honours `login_next` session key |
| `app.py` | `auth_demo` honours `login_next` session key |
| `app.py` | `meeting_redirect` sends logged-in users directly to live room |
| `templates/login.html` | `sendToServer()` passes `?next=` to `/auth/firebase` |
| `templates/login.html` | `onAuthStateChanged` redirect honours `?next=` |
| `templates/join_meeting.html` | Sign-in links point to live room, not join page |
| `.env` | Added clear `APP_BASE_URL` instructions |

---
## v6 - Firebase login fixes
- SECURITY: `/auth/firebase` accepted ANY email even when the Firebase token was invalid (anyone could log in as anyone). Now the token is verified (google-auth, REST fallback) and the login is rejected with 401 if it can't be verified. Identity comes only from the verified token.
- Verification fallback now sends a Referer so API keys restricted by HTTP referrer still work.
- login.html: added messages for operation-not-allowed, configuration-not-found, invalid-api-key, app-not-authorized, user-disabled; real error codes logged to browser console; buttons reset after a server error.
- Opening http://127.0.0.1:5000 now redirects to http://localhost:5000 (Firebase authorises only localhost by default).
- Removed duplicate login-alert email (server already sends it).
- See FIREBASE_SETUP.md for the Firebase Console checklist.
