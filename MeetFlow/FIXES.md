# MeetFlow — Bug Fixes

## 🐛 Critical Bug Fixed: "Everyone alone in their own meeting"

### Root Cause

The previous version had **no real-time connection layer** between participants.

When person A and person B both clicked the same invite link (`/meeting/<id>/live`), each of them:
- Opened their own local camera ✅
- Saw their own video ✅  
- Had **zero awareness of anyone else in the room** ❌

The `live_meeting.html` page had camera/mic/chat code, but chat messages were only appended to the local DOM — never sent to anyone. There was no WebSocket, no WebRTC signaling, and no server-side room. Every participant was in a **completely isolated session**.

### Fix Applied

Added **Flask-SocketIO** (real-time WebSocket server) + **WebRTC** peer-to-peer connections so all participants share one live video/audio room.

#### Files changed

| File | Change |
|------|--------|
| `requirements.txt` | Added `flask-socketio`, `eventlet` |
| `app.py` | Added `SocketIO` init + signaling handlers (`join-room`, `webrtc-offer`, `webrtc-answer`, `webrtc-ice`, `chat-message`, `peer-left`) |
| `static/js/webrtc_room.js` | **NEW** — WebRTC room manager: peer connections, remote video tiles, chat relay |
| `templates/live_meeting.html` | Load `socket.io` + `webrtc_room.js`, call `initRoom()` after camera init, broadcast chat via `sendRoomChat()` |

#### How it works now

1. Host creates meeting → unique `meeting_id` stored in DB
2. All invitees receive the **same** URL: `/meeting/<meeting_id>/live`
3. Each person opens the page → `initMedia()` gets their local camera/mic
4. `initRoom(MEETING_ID, userName, stream)` connects to SocketIO server
5. Server places everyone in the same SocketIO room keyed by `meeting_id`
6. New joiners get the list of existing peer socket IDs → initiate WebRTC offers
7. Server relays `offer → answer → ICE candidates` between peers
8. Peer-to-peer audio/video streams flow directly between browsers
9. Chat messages broadcast to the room so everyone sees them in real time

### How to Run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python app.py          # must use python app.py, not flask run
```

For production:
```bash
gunicorn --worker-class eventlet -w 1 app:app
```
