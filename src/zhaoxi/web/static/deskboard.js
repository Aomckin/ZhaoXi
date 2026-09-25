// Presentation only. Acknowledgement reuses the existing delivery activation API.
const desk = document.querySelector('#desk');
const deskHandle = document.querySelector('#sideToggle');
const readRequests = new Set();
let deskReadTimer = null, deskReady = false;

function updateDeskUnread() {
  const unread = !!document.querySelector('#proactiveNotes .note-unread');
  document.querySelector('#deskUnread').hidden = !unread;
  const action = deskHandle.getAttribute('aria-expanded') === 'true' ? '收起' : '打开';
  deskHandle.setAttribute('aria-label', `${action}小桌边${unread ? '，有未读留言' : ''}`);
}

function toggleDesk(open) {
  clearTimeout(deskReadTimer);
  deskReady = false;
  deskHandle.setAttribute('aria-expanded', String(open));
  desk.setAttribute('aria-hidden', String(!open));
  desk.inert = !open;
  desk.classList.toggle('is-open', open);
  updateDeskUnread();
  if (open) {
    if (typeof window.refreshDeskContext === 'function') void window.refreshDeskContext();
    document.querySelector('#deskClose').focus({preventScroll: true});
    // Do not acknowledge a note while the board is still sliding into view.
    deskReadTimer = setTimeout(() => { deskReady = true; void markVisibleNotesRead(); }, 300);
  } else {
    deskHandle.focus({preventScroll: true});
  }
}

async function markVisibleNotesRead() {
  if (!deskReady || document.visibilityState !== 'visible' || deskHandle.getAttribute('aria-expanded') !== 'true') return;
  const scroller = desk.querySelector('.desk-content');
  const bounds = scroller.getBoundingClientRect();
  const pending = Array.from(document.querySelectorAll('#proactiveNotes [data-delivery]')).filter(note => {
    const rect = note.getBoundingClientRect();
    return note.querySelector('.note-unread') && !readRequests.has(note.dataset.delivery)
      && Math.min(rect.bottom, bounds.bottom, innerHeight) - Math.max(rect.top, bounds.top, 0) >= Math.min(60, rect.height);
  });
  for (const note of pending) {
    // Recheck after each awaited activation in case the user closes the board.
    if (!deskReady || document.visibilityState !== 'visible') break;
    const rect = note.getBoundingClientRect(), currentBounds = scroller.getBoundingClientRect();
    if (Math.min(rect.bottom, currentBounds.bottom, innerHeight) - Math.max(rect.top, currentBounds.top, 0) < Math.min(60, rect.height)) continue;
    const id = note.dataset.delivery;
    if (readRequests.has(id) || !note.querySelector('.note-unread')) continue;
    readRequests.add(id);
    try {
      const result = await request(`/api/proactive/${encodeURIComponent(id)}/activate`, {method: 'POST'});
      if (result.status !== 'acknowledged') throw new Error('not acknowledged');
      note.querySelector('.note-unread')?.remove();
      document.querySelector('#noteReadStatus').textContent = '';
      updateDeskUnread();
    } catch {
      // Keep the dot truthful. Retry only on another view/scroll, not a busy loop.
      document.querySelector('#noteReadStatus').textContent = '已读状态暂未保存，下次查看时重试。';
    } finally {
      readRequests.delete(id);
    }
  }
}

function showProactiveNote(d) {
  if (d.kind === 'system' || String(d.event_type || '').startsWith('system.') || !['delivered', 'acknowledged'].includes(d.status)) return;
  const box = document.querySelector('#proactiveNotes');
  const existing = document.getElementById('note-' + d.delivery_id);
  if (existing) {
    if (d.status === 'acknowledged') existing.querySelector('.note-unread')?.remove();
    updateDeskUnread();
    return;
  }
  if (!box.querySelector('[data-delivery]')) box.replaceChildren();
  const note = document.createElement('article');
  note.id = 'note-' + d.delivery_id;
  note.className = 'desk-note';
  note.dataset.delivery = d.delivery_id;
  note.innerHTML = `<span class="eyebrow">${d.status === 'delivered' ? '<span class="note-unread" role="img" aria-label="未读"></span>' : ''}朝汐的小纸条</span><p>${markdown(d.content)}</p><small>${escapeHtml(formatTime(d.delivered_at || d.available_at))}</small>`;
  box.prepend(note);
  while (box.children.length > 2) box.lastElementChild.remove();
  updateDeskUnread();
  // A new note never opens the board; an already visible note can be read.
  if (deskReady) void markVisibleNotesRead();
}

deskHandle.onclick = () => toggleDesk(deskHandle.getAttribute('aria-expanded') !== 'true');
document.querySelector('#deskClose').onclick = () => toggleDesk(false);
desk.querySelector('.desk-content').addEventListener('scroll', () => { void markVisibleNotesRead(); }, {passive: true});
document.addEventListener('visibilitychange', () => { void markVisibleNotesRead(); });
window.addEventListener('resize', () => { void markVisibleNotesRead(); });
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && deskHandle.getAttribute('aria-expanded') === 'true') toggleDesk(false);
});
document.querySelector('#endpoint').textContent = location.host;

// One character configuration, independent of theme and with a deterministic fallback.
const avatar = document.querySelector('#characterAvatar');
const avatarFallback = document.querySelector('#avatarFallback');
let defaultAvatar = '';
avatar.onload = () => { avatar.hidden = false; avatarFallback.hidden = true; };
avatar.onerror = () => {
  if (defaultAvatar && avatar.getAttribute('src') !== defaultAvatar) { avatar.src = defaultAvatar; return; }
  avatar.hidden = true; avatarFallback.hidden = false;
};
try {
  const config = JSON.parse(document.querySelector('#characterConfig').textContent);
  defaultAvatar = typeof config.avatar === 'string' ? config.avatar : '';
  const avatars = config.avatars || {};
  window.setCharacterAvatarState = state => {
    const source = typeof avatars[state] === 'string' ? avatars[state] : defaultAvatar;
    if (source && avatar.getAttribute('src') !== source) avatar.src = source;
  };
  window.setCharacterAvatarState();
} catch { /* Keep the 汐 fallback for absent or malformed character configuration. */ }
