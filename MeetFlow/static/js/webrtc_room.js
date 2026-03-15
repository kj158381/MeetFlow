/**
 * webrtc_room.js — MeetFlow Real-Time Multi-User Room
 *
 * THE FIX: Previously every user who opened /meeting/<id>/live was
 * completely isolated — local camera only, no connection to anyone else.
 *
 * This module:
 *  1. Connects every user to the same SocketIO room keyed by MEETING_ID
 *  2. Uses WebRTC (RTCPeerConnection) to establish peer-to-peer audio/video
 *  3. Relays offers, answers, and ICE candidates through Flask-SocketIO
 *  4. Adds/removes participant video tiles dynamically
 *  5. Relays chat messages so everyone sees them in real time
 */

const ICE_SERVERS = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
  ],
};

// socket and peer state
let _socket = null;
let _localStream = null;
let _peers = {};         // { sid: RTCPeerConnection }
window._peers = _peers;  // expose for UI updates
let _peerNames = {};     // { sid: displayName }
let _myRoom = null;
let _myName = "Guest";

/* ── Bootstrap ────────────────────────────────────────────── */
function initRoom(meetingId, userName, localStream) {
  _myRoom = meetingId;
  _myName = userName || "Guest";
  _localStream = localStream;

  // Load Socket.IO client from CDN if not already present
  if (typeof io === "undefined") {
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.4/socket.io.min.js";
    s.onload = () => _connect();
    document.head.appendChild(s);
  } else {
    _connect();
  }
}

function _connect() {
  _socket = io({ transports: ["websocket", "polling"] });

  _socket.on("connect", () => {
    console.log("[MeetFlow] Socket connected:", _socket.id);
    _socket.emit("join-room", { room: _myRoom, name: _myName });
    updateParticipantCount();
  });

  // Server sends us the list of peers already in the room
  _socket.on("room-peers", ({ peers }) => {
    console.log("[MeetFlow] Existing peers:", peers);
    peers.forEach(sid => _createOffer(sid));
  });

  // A new peer joined — they will send us an offer
  _socket.on("peer-joined", ({ sid, name }) => {
    console.log("[MeetFlow] Peer joined:", sid, name);
    _peerNames[sid] = name;
    // Don't create offer here — wait for their offer (they initiate as newcomer)
    updateParticipantCount();
  });

  // WebRTC signaling
  _socket.on("webrtc-offer", async ({ sdp, from }) => {
    console.log("[MeetFlow] Got offer from", from);
    const pc = _getOrCreatePC(from);
    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    _socket.emit("webrtc-answer", { target: from, sdp: pc.localDescription });
  });

  _socket.on("webrtc-answer", async ({ sdp, from }) => {
    console.log("[MeetFlow] Got answer from", from);
    const pc = _peers[from];
    if (pc) await pc.setRemoteDescription(new RTCSessionDescription(sdp));
  });

  _socket.on("webrtc-ice", async ({ candidate, from }) => {
    const pc = _peers[from];
    if (pc && candidate) {
      try { await pc.addIceCandidate(new RTCIceCandidate(candidate)); } catch (e) {}
    }
  });

  // Peer disconnected
  _socket.on("peer-left", ({ sid }) => {
    console.log("[MeetFlow] Peer left:", sid);
    _removePeer(sid);
    updateParticipantCount();
  });

  // Real-time chat from others
  _socket.on("chat-message", ({ name, text, time }) => {
    _appendRemoteChat(name, text, time);
  });

  _socket.on("disconnect", () => {
    console.log("[MeetFlow] Socket disconnected");
  });
}

/* ── WebRTC helpers ───────────────────────────────────────── */
async function _createOffer(targetSid) {
  const pc = _getOrCreatePC(targetSid);
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  _socket.emit("webrtc-offer", { target: targetSid, sdp: pc.localDescription });
}

function _getOrCreatePC(sid) {
  if (_peers[sid]) return _peers[sid];

  const pc = new RTCPeerConnection(ICE_SERVERS);
  _peers[sid] = pc;

  // Add local tracks to this connection
  if (_localStream) {
    _localStream.getTracks().forEach(track => pc.addTrack(track, _localStream));
  }

  // Send ICE candidates to the peer via signaling server
  pc.onicecandidate = ({ candidate }) => {
    if (candidate && _socket) {
      _socket.emit("webrtc-ice", { target: sid, candidate });
    }
  };

  // When we receive remote audio/video, display it
  pc.ontrack = ({ streams }) => {
    if (streams && streams[0]) {
      _addRemoteVideo(sid, streams[0]);
    }
  };

  pc.onconnectionstatechange = () => {
    console.log(`[MeetFlow] PC ${sid} state:`, pc.connectionState);
    if (["disconnected", "failed", "closed"].includes(pc.connectionState)) {
      _removePeer(sid);
    }
  };

  return pc;
}

function _removePeer(sid) {
  if (_peers[sid]) {
    _peers[sid].close();
    delete _peers[sid];
  }
  delete _peerNames[sid];
  const tile = document.getElementById("remote-" + sid);
  if (tile) tile.remove();
  updateParticipantCount();
}

/* ── Video tile management ────────────────────────────────── */
function _addRemoteVideo(sid, stream) {
  // Don't add duplicates
  if (document.getElementById("remote-" + sid)) {
    document.getElementById("remote-" + sid).querySelector("video").srcObject = stream;
    return;
  }

  const name = _peerNames[sid] || "Participant";
  const initials = name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
  const colors = ["#4F46E5", "#7C3AED", "#0891B2", "#059669", "#D97706"];
  const color = colors[Math.abs(_hashStr(sid)) % colors.length];

  const tile = document.createElement("div");
  tile.id = "remote-" + sid;
  tile.className = "remote-peer-tile";
  tile.style.cssText = `
    position:relative; background:#0d1424; border-radius:12px;
    overflow:hidden; aspect-ratio:16/9; min-height:120px;
    border:1px solid rgba(255,255,255,0.08); flex:1 1 280px; max-width:420px;
  `;
  tile.innerHTML = `
    <video autoplay playsinline style="width:100%;height:100%;object-fit:cover;"></video>
    <div class="peer-avatar-bg" style="
      position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
      background:linear-gradient(135deg,${color}33,#0d1424);
    ">
      <div style="
        width:56px;height:56px;border-radius:50%;background:${color};
        display:flex;align-items:center;justify-content:center;
        color:white;font-size:20px;font-weight:700;
      ">${initials}</div>
    </div>
    <div style="
      position:absolute;bottom:8px;left:10px;
      background:rgba(0,0,0,0.6);color:white;
      font-size:11px;padding:3px 8px;border-radius:20px;
    ">${name}</div>
  `;

  const video = tile.querySelector("video");
  video.srcObject = stream;
  video.onloadedmetadata = () => {
    // Hide avatar once video is playing
    tile.querySelector(".peer-avatar-bg").style.display = "none";
  };

  // Find or create remote peers container
  let container = document.getElementById("remotePeersContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "remotePeersContainer";
    container.style.cssText = `
      display:flex;flex-wrap:wrap;gap:8px;padding:8px;
      width:100%;justify-content:center;
    `;
    // Insert before the local video area or after it
    const localArea = document.getElementById("localVideoArea") ||
                      document.getElementById("localVideo")?.parentElement?.parentElement;
    if (localArea && localArea.parentElement) {
      localArea.parentElement.insertBefore(container, localArea.nextSibling);
    } else {
      document.body.appendChild(container);
    }
  }
  container.appendChild(tile);
}

function _hashStr(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  return h;
}

/* ── Participant count ────────────────────────────────────── */
function updateParticipantCount() {
  const count = Object.keys(_peers).length + 1; // +1 for self
  const el = document.getElementById("participantCount");
  if (el) el.textContent = count;
  const el2 = document.getElementById("liveParticipantBadge");
  if (el2) el2.textContent = count + " in call";
}

/* ── Chat relay ───────────────────────────────────────────── */
function sendRoomChat(text) {
  if (!_socket || !_myRoom || !text.trim()) return;
  const time = new Date().toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit" });
  _socket.emit("chat-message", { room: _myRoom, name: _myName, text, time });
}

function _appendRemoteChat(name, text, time) {
  const feed = document.getElementById("chatFeed");
  if (!feed) return;
  const ph = feed.querySelector(".text-center");
  if (ph) ph.remove();
  const el = document.createElement("div");
  el.className = "fade-up flex justify-start";
  el.innerHTML = `
    <div class="max-w-xs rounded-2xl rounded-tl-sm px-3 py-2" style="background:#1e3a5f">
      <p class="text-xs font-semibold" style="color:#93c5fd">${name}</p>
      <p class="text-xs text-white mt-0.5">${text}</p>
      <p class="text-xs mt-0.5" style="color:rgba(255,255,255,.5)">${time}</p>
    </div>`;
  feed.appendChild(el);
  feed.scrollTop = feed.scrollHeight;
}

/* ── Cleanup on page leave ────────────────────────────────── */
window.addEventListener("beforeunload", () => {
  if (_socket && _myRoom) {
    _socket.emit("leave-room", { room: _myRoom });
    _socket.disconnect();
  }
  Object.values(_peers).forEach(pc => pc.close());
});

/* ── Update local stream in all peer connections ──────────── */
function updateLocalStream(newStream) {
  _localStream = newStream;
  Object.values(_peers).forEach(pc => {
    const senders = pc.getSenders();
    newStream.getTracks().forEach(track => {
      const sender = senders.find(s => s.track && s.track.kind === track.kind);
      if (sender) sender.replaceTrack(track);
    });
  });
}
