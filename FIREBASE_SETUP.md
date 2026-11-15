# Firebase checklist for MeetFlow (do these in https://console.firebase.google.com)

Project: meeting-automation-0202

1. Build > Authentication > **Get started** (error: auth/configuration-not-found)
2. Authentication > Sign-in method > enable **Google** and **Email/Password** (error: auth/operation-not-allowed)
3. Authentication > Settings > **Authorized domains** must contain `localhost`
   (error: auth/unauthorized-domain). Open the app at http://localhost:5000 - NOT 127.0.0.1.
4. Project settings > Your apps > Web app: copy apiKey, authDomain, projectId, appId into `.env`
   (error: auth/invalid-api-key). Restart `python app.py` after every .env change.
5. Google Cloud Console > APIs & Services > Credentials > the browser key: if restricted, allow
   "Identity Toolkit API" and "Token Service API", and referrers `localhost:5000/*` and
   `meeting-automation-0202.firebaseapp.com/*` (error: auth/app-not-authorized).
6. Email/Password sign-in needs the user to exist: Authentication > Users > Add user.
7. Debug: press F12 > Console on /login; the exact Firebase error code is printed there.
