/* ============================================================
   MeetFlow — Main JavaScript Utilities
   Loaded on every page via base.html
   ============================================================ */

/* ── Toast Notification ───────────────────────────────────── */
(function () {
  /**
   * Show a toast notification
   * @param {string} message
   * @param {string} icon  - Material Symbols icon name
   * @param {number} duration - ms
   */
  window.showToast = function (message, icon = 'check_circle', duration = 3000) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    document.getElementById('toast-msg').textContent = message;
    document.getElementById('toast-icon').textContent = icon;
    toast.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.remove('show'), duration);
  };
})();

/* ── Modal helpers ────────────────────────────────────────── */
window.openModal = function (id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('hidden');
};
window.closeModal = function (id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
};

/* Close modal when clicking backdrop */
document.addEventListener('click', function (e) {
  if (e.target.classList.contains('modal-backdrop')) {
    e.target.classList.add('hidden');
  }
});

/* ── API helpers ──────────────────────────────────────────── */
window.api = {
  async get(url) {
    const r = await fetch(url);
    return r.json();
  },
  async post(url, data) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return r.json();
  },
  async put(url, data) {
    const r = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return r.json();
  },
  async del(url) {
    const r = await fetch(url, { method: 'DELETE' });
    return r.json();
  },
};

/* ── Flash auto-dismiss ───────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
  const flashContainer = document.getElementById('flash-container');
  if (flashContainer) {
    setTimeout(() => {
      flashContainer.style.transition = 'opacity .4s ease';
      flashContainer.style.opacity = '0';
      setTimeout(() => flashContainer.remove(), 400);
    }, 4000);
  }
});

/* ── Format helpers ───────────────────────────────────────── */
window.formatDate = function (isoString) {
  if (!isoString) return 'No date';
  const d = new Date(isoString.replace(' ', 'T'));
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

window.formatTime = function (isoString) {
  if (!isoString) return '';
  const d = new Date(isoString.replace(' ', 'T'));
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
};

window.formatDateTime = function (isoString) {
  if (!isoString) return 'No date';
  return `${window.formatDate(isoString)} at ${window.formatTime(isoString)}`;
};

/* ── Timer helper ─────────────────────────────────────────── */
window.createTimer = function (onTick) {
  let seconds = 0;
  let interval = null;
  function fmt(s) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = n => String(n).padStart(2, '0');
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
  }
  return {
    start() {
      interval = setInterval(() => { seconds++; onTick(fmt(seconds), seconds); }, 1000);
    },
    stop() { clearInterval(interval); },
    get seconds() { return seconds; },
    format: fmt,
  };
};

/* ── Keyboard shortcuts ───────────────────────────────────── */
document.addEventListener('keydown', function (e) {
  // ESC closes any open modal-backdrop
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-backdrop:not(.hidden)').forEach(m => m.classList.add('hidden'));
  }
});

/* ── Confirm delete helper ────────────────────────────────── */
window.confirmAction = function (message, callback) {
  if (window.confirm(message || 'Are you sure?')) callback();
};
