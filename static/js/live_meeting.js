/* ============================================================
   MeetFlow — Live Meeting JavaScript
   Handles: Camera, Mic, Screen Share, AI Key Points,
            Meeting Notes Save, Gmail Invite, Chat, Timer
   ============================================================ */

/* ── State ────────────────────────────────────────────────── */
const MeetingState = {
  isMicMuted: false,
  isCamOff: false,
  isScreenSharing: false,
  localStream: null,
  screenStream: null,
  keyPoints: [],
  timerSeconds: 0,
  timerInterval: null,
  chatMessages: [],
};

/* ── DOM refs ─────────────────────────────────────────────── */
const $video        = () => document.getElementById('localVideo');
const $videoOff     = () => document.getElementById('videoOffPlaceholder');
const $micBtn       = () => document.getElementById('micBtn');
const $camBtn       = () => document.getElementById('camBtn');
const $shareBtn     = () => document.getElementById('shareBtn');
const $micIcon      = () => document.getElementById('micIcon');
const $camIcon      = () => document.getElementById('camIcon');
const $shareIcon    = () => document.getElementById('shareIcon');
const $micStatus    = () => document.getElementById('micStatusIcon');
const $timerEl      = () => document.getElementById('recordingTimer');
const $keyPointList = () => document.getElementById('keyPointsList');
const $summaryEl    = () => document.getElementById('summaryText');
const $summaryBox   = () => document.getElementById('summarySection');
const $transcript   = () => document.getElementById('transcriptInput');
const $chatMessages = () => document.getElementById('chatMessages');

/* ── Camera / Mic Init ────────────────────────────────────── */
async function initMedia() {
  try {
    MeetingState.localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    $video().srcObject = MeetingState.localStream;
    $video().play().catch(() => {});
    setNotification('Camera & mic connected', 'videocam');
  } catch (err) {
    console.warn('Media access denied:', err.message);
    $videoOff().classList.remove('hidden');
    $video().classList.add('hidden');
    setNotification('No camera/mic access', 'videocam_off');
  }
}

/* ── Toggle Mic ───────────────────────────────────────────── */
function toggleMic() {
  MeetingState.isMicMuted = !MeetingState.isMicMuted;
  if (MeetingState.localStream) {
    MeetingState.localStream.getAudioTracks().forEach(t => {
      t.enabled = !MeetingState.isMicMuted;
    });
  }
  const muted = MeetingState.isMicMuted;
  $micBtn().classList.toggle('active-danger', muted);
  $micIcon().textContent  = muted ? 'mic_off' : 'mic';
  $micStatus() && ($micStatus().textContent = muted ? 'mic_off' : 'mic');
  setNotification(muted ? 'Microphone muted' : 'Microphone on', muted ? 'mic_off' : 'mic');
}

/* ── Toggle Camera ────────────────────────────────────────── */
function toggleCamera() {
  MeetingState.isCamOff = !MeetingState.isCamOff;
  if (MeetingState.localStream) {
    MeetingState.localStream.getVideoTracks().forEach(t => {
      t.enabled = !MeetingState.isCamOff;
    });
  }
  const off = MeetingState.isCamOff;
  $camBtn().classList.toggle('active-danger', off);
  $camIcon().textContent = off ? 'videocam_off' : 'videocam';
  $videoOff() && $videoOff().classList.toggle('hidden', !off);
  $video() && $video().classList.toggle('opacity-0', off);
  setNotification(off ? 'Camera off' : 'Camera on', off ? 'videocam_off' : 'videocam');
}

/* ── Screen Share ─────────────────────────────────────────── */
async function toggleScreenShare() {
  if (!MeetingState.isScreenSharing) {
    try {
      MeetingState.screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      $video().srcObject = MeetingState.screenStream;
      MeetingState.isScreenSharing = true;
      $shareBtn().classList.add('active-primary');
      $shareIcon().textContent = 'stop_screen_share';
      setNotification('Screen sharing started', 'present_to_all');
      MeetingState.screenStream.getVideoTracks()[0].addEventListener('ended', stopScreenShare);
    } catch (e) {
      setNotification('Screen share cancelled', 'cancel');
    }
  } else {
    stopScreenShare();
  }
}

function stopScreenShare() {
  if (MeetingState.screenStream) {
    MeetingState.screenStream.getTracks().forEach(t => t.stop());
    MeetingState.screenStream = null;
  }
  if (MeetingState.localStream) {
    $video().srcObject = MeetingState.localStream;
  }
  MeetingState.isScreenSharing = false;
  $shareBtn().classList.remove('active-primary');
  $shareIcon().textContent = 'present_to_all';
  setNotification('Screen sharing stopped', 'stop_screen_share');
}

/* ── Timer ────────────────────────────────────────────────── */
function startTimer() {
  MeetingState.timerInterval = setInterval(() => {
    MeetingState.timerSeconds++;
    const s = MeetingState.timerSeconds;
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = n => String(n).padStart(2, '0');
    const fmt = h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
    if ($timerEl()) $timerEl().textContent = `Live • ${fmt}`;
  }, 1000);
}

/* ── AI Key Point Extraction ──────────────────────────────── */
async function extractKeyPoints() {
  const text = $transcript().value.trim();
  if (!text) { setNotification('Enter transcript text first', 'warning'); return; }

  const btn = document.querySelector('[data-action="extract-kp"]');
  if (btn) { btn.disabled = true; btn.dataset.originalText = btn.innerHTML; btn.innerHTML = '<span class="msymbol ai-pulse">hourglass_empty</span> Extracting…'; }

  try {
    const data = await api.post('/api/ai/extract-key-points', { transcript: text });
    MeetingState.keyPoints = [...MeetingState.keyPoints, ...data.key_points];
    renderKeyPoints();
    if (data.summary) {
      $summaryEl().textContent = data.summary;
      $summaryBox() && $summaryBox().classList.remove('hidden');
    }
    setNotification(`${data.key_points.length} key points captured!`, 'auto_awesome');
  } catch (e) {
    setNotification('AI extraction failed', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = btn.dataset.originalText || 'Extract Key Points'; }
  }
}

/* ── Add Manual Key Point ─────────────────────────────────── */
function addManualKeyPoint() {
  const text = prompt('Enter a key point:');
  if (text && text.trim()) {
    MeetingState.keyPoints.push({
      type: 'manual',
      text: text.trim(),
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    });
    renderKeyPoints();
    setNotification('Key point added', 'add_task');
  }
}

function removeKeyPoint(idx) {
  MeetingState.keyPoints.splice(idx, 1);
  renderKeyPoints();
}

/* ── Render Key Points ────────────────────────────────────── */
const KP_CONFIG = {
  decision:  { icon: 'gavel',      colorText: '#60a5fa', colorClass: 'kp-decision' },
  action:    { icon: 'task_alt',   colorText: '#4ade80', colorClass: 'kp-action'   },
  deadline:  { icon: 'schedule',   colorText: '#fbbf24', colorClass: 'kp-deadline' },
  follow_up: { icon: 'replay',     colorText: '#c084fc', colorClass: 'kp-follow_up'},
  manual:    { icon: 'edit_note',  colorText: '#94a3b8', colorClass: 'kp-manual'   },
};

function renderKeyPoints() {
  const container = $keyPointList();
  if (!container) return;
  if (MeetingState.keyPoints.length === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:2rem 0">
        <span class="msymbol" style="font-size:2.5rem;color:#374151">auto_awesome</span>
        <p style="color:#6b7280;font-size:.8125rem;margin-top:.5rem">AI will capture key points as the meeting progresses</p>
      </div>`;
    return;
  }
  container.innerHTML = MeetingState.keyPoints.map((kp, i) => {
    const cfg = KP_CONFIG[kp.type] || KP_CONFIG.manual;
    return `
      <div class="key-point-card ${cfg.colorClass}">
        <span class="msymbol" style="color:${cfg.colorText};font-size:1.125rem;margin-top:.125rem">${cfg.icon}</span>
        <div style="flex:1;min-width:0">
          <p style="font-size:.6875rem;font-weight:700;color:${cfg.colorText};text-transform:uppercase;letter-spacing:.05em;margin-bottom:.25rem">${kp.type.replace('_', ' ')}</p>
          <p style="font-size:.8125rem;color:#e2e8f0;line-height:1.4">${escapeHtml(kp.text)}</p>
          ${kp.timestamp ? `<p style="font-size:.6875rem;color:#6b7280;margin-top:.25rem">${kp.timestamp}</p>` : ''}
        </div>
        <button onclick="removeKeyPoint(${i})" style="background:none;border:none;cursor:pointer;color:#4b5563;padding:.25rem" title="Remove">
          <span class="msymbol" style="font-size:1rem">close</span>
        </button>
      </div>`;
  }).join('');
}

/* ── Save AI Notes to DB ──────────────────────────────────── */
async function saveAINotes() {
  if (MeetingState.keyPoints.length === 0) {
    setNotification('No key points to save yet', 'info');
    return false;
  }
  const summary = $summaryEl() ? $summaryEl().textContent : '';
  try {
    const data = await api.post('/api/notes/save-from-meeting', {
      meeting_id: window.MEETING_ID,
      key_points: MeetingState.keyPoints,
      ai_summary: summary,
    });
    if (data.success) {
      setNotification('Notes saved to Meeting Notes!', 'check_circle');
      return true;
    }
  } catch (e) {
    setNotification('Failed to save notes', 'error');
  }
  return false;
}

/* ── End Meeting ──────────────────────────────────────────── */
async function endMeeting() {
  if (!confirm('End the meeting? AI notes will be saved automatically.')) return;
  await saveAINotes();
  try { await api.post(`/api/meetings/${window.MEETING_ID}/end`, {}); } catch (e) {}
  if (MeetingState.localStream) MeetingState.localStream.getTracks().forEach(t => t.stop());
  if (MeetingState.screenStream) MeetingState.screenStream.getTracks().forEach(t => t.stop());
  clearInterval(MeetingState.timerInterval);
  window.location.href = '/meeting-notes';
}

/* ── Chat ─────────────────────────────────────────────────── */
function sendChatMessage() {
  const input = document.getElementById('chatInput');
  if (!input) return;
  const msg = input.value.trim();
  if (!msg) return;
  const container = $chatMessages();
  if (container) {
    container.insertAdjacentHTML('beforeend', `
      <div style="display:flex;justify-content:flex-end;margin-bottom:.5rem">
        <div style="max-width:80%;background:var(--primary);color:#fff;padding:.625rem 1rem;border-radius:1rem 1rem 0 1rem;font-size:.8125rem;line-height:1.4">
          ${escapeHtml(msg)}
        </div>
      </div>`);
    container.scrollTop = container.scrollHeight;
  }
  input.value = '';
}

/* ── AI Sidebar Tabs ──────────────────────────────────────── */
function switchAiTab(btn, panelName) {
  document.querySelectorAll('.ai-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  ['ai', 'transcript', 'chat'].forEach(name => {
    const panel = document.getElementById(`panel-${name}`);
    if (panel) panel.classList.toggle('hidden', name !== panelName);
  });
}

/* ── Gmail Invite ─────────────────────────────────────────── */
function openInviteModal() {
  const modal = document.getElementById('inviteModal');
  if (modal) modal.classList.remove('hidden');
}
function closeInviteModal() {
  const modal = document.getElementById('inviteModal');
  if (modal) modal.classList.add('hidden');
}

async function sendGmailInvites() {
  const textarea = document.getElementById('inviteEmails');
  if (!textarea) return;
  const emails = textarea.value.trim().split('\n').map(e => e.trim()).filter(e => e.includes('@'));
  if (!emails.length) { setNotification('Enter at least one valid email', 'warning'); return; }

  try {
    const data = await api.post('/api/notify/meeting-invite', {
      recipients: emails,
      meeting_title: window.MEETING_TITLE || 'Meeting',
      meeting_time: window.MEETING_TIME || new Date().toISOString(),
      meeting_link: window.location.href,
    });
    if (data.success) {
      setNotification(`Invites sent to ${emails.length} participant(s)!`, 'mail');
      closeInviteModal();
      textarea.value = '';
    }
  } catch (e) {
    setNotification('Failed to send invites', 'error');
  }
}

/* ── Inline notification (dark bar) ──────────────────────── */
function setNotification(msg, icon = 'info') {
  // Remove existing
  document.querySelectorAll('.meeting-notification').forEach(n => n.remove());
  const el = document.createElement('div');
  el.className = 'meeting-notification';
  el.style.cssText = `
    position:fixed; bottom:6rem; left:50%; transform:translateX(-50%);
    display:flex; align-items:center; gap:.625rem;
    padding:.625rem 1.25rem;
    background:rgba(15,23,42,.9); backdrop-filter:blur(8px);
    color:#fff; border-radius:.875rem;
    font-size:.8125rem; font-weight:500;
    box-shadow:0 8px 24px rgba(0,0,0,.35);
    z-index:999; animation:kp-in .25s ease;
    border:1px solid rgba(255,255,255,.1);
  `;
  el.innerHTML = `<span class="msymbol" style="color:var(--primary);font-size:1.125rem">${icon}</span>${escapeHtml(msg)}`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2500);
}

/* ── Utils ────────────────────────────────────────────────── */
function escapeHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Init ─────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
  initMedia();
  startTimer();

  // Wire up Enter key in chat
  const chatInput = document.getElementById('chatInput');
  if (chatInput) {
    chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMessage(); });
  }

  // Wire up invite button
  const inviteBtn = document.getElementById('inviteBtn');
  if (inviteBtn) inviteBtn.addEventListener('click', openInviteModal);

  // Warn before leaving if key points present
  window.addEventListener('beforeunload', function (e) {
    if (MeetingState.keyPoints.length > 0) {
      e.preventDefault();
      e.returnValue = 'You have unsaved AI key points. Leave anyway?';
    }
  });
});
