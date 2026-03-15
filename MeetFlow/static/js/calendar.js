/* ============================================================
   MeetFlow — Calendar JavaScript
   Full interactive calendar with meeting events
   ============================================================ */

const CalendarApp = (function () {
  const MONTHS = [
    'January','February','March','April','May','June',
    'July','August','September','October','November','December'
  ];
  const DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

  let currentDate = new Date();
  let meetingsData = [];

  /* ── Build meeting lookup map ── */
  function buildLookup(meetings) {
    const map = {};
    meetings.forEach(m => {
      if (!m.scheduled_at) return;
      const key = m.scheduled_at.slice(0, 10);
      if (!map[key]) map[key] = [];
      map[key].push(m);
    });
    return map;
  }

  /* ── Render calendar grid ── */
  function render(date) {
    const year  = date.getFullYear();
    const month = date.getMonth();
    const today = new Date();

    // Update header
    const titleEl = document.getElementById('calTitle');
    if (titleEl) titleEl.textContent = `${MONTHS[month]} ${year}`;

    const firstDay    = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const prevDays    = new Date(year, month, 0).getDate();
    const lookup      = buildLookup(meetingsData);
    const grid        = document.getElementById('calGrid');
    if (!grid) return;

    let html = '';

    // Previous month's tail days
    for (let i = firstDay - 1; i >= 0; i--) {
      html += `<div class="cal-cell other-month">
        <div class="cal-date" style="color:#cbd5e1">${prevDays - i}</div>
      </div>`;
    }

    // Current month days
    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr  = `${year}-${String(month + 1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
      const isToday  = today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;
      const dayMtgs  = lookup[dateStr] || [];
      const isWeekend = ((firstDay + day - 1) % 7 === 0 || (firstDay + day - 1) % 7 === 6);

      html += `<div class="cal-cell${isToday ? ' today' : ''}${isWeekend ? '' : ''}">
        <div class="cal-date">${day}</div>
        ${dayMtgs.slice(0, 3).map(m => `
          <a href="/meeting/${m.id}/live" class="cal-event ${m.status === 'completed' ? 'cal-event-done' : 'cal-event-primary'}" title="${escHtml(m.title)}">
            ${escHtml(m.title)}
          </a>`).join('')}
        ${dayMtgs.length > 3 ? `<div style="font-size:.625rem;color:#94a3b8;padding:.1rem .25rem">+${dayMtgs.length - 3} more</div>` : ''}
      </div>`;
    }

    // Next month's fill days
    const totalCells = firstDay + daysInMonth;
    const remaining  = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
    for (let i = 1; i <= remaining; i++) {
      html += `<div class="cal-cell other-month">
        <div class="cal-date" style="color:#cbd5e1">${i}</div>
      </div>`;
    }

    grid.innerHTML = html;
  }

  function escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── Public API ── */
  return {
    init(meetings) {
      meetingsData = meetings || [];
      render(currentDate);
    },
    prev() {
      currentDate = new Date(currentDate.getFullYear(), currentDate.getMonth() - 1, 1);
      render(currentDate);
    },
    next() {
      currentDate = new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 1);
      render(currentDate);
    },
    today() {
      currentDate = new Date();
      render(currentDate);
    },
  };
})();

window.CalendarApp = CalendarApp;
