// Popup mini-board. Reference: tasks.md T041 (US-006), T053 (follow-up mirror).
//
// The full taxonomy (active categories + pending proposals) renders as column
// tabs; selecting a tab lists its tickets. Each card has a tap-to-move action
// — a button list of categories, sized for the popup — instead of the webapp's
// drag-and-drop. Overrides hit `PATCH /tickets/{id}/category`, which the
// backend persists, so a move survives the popup closing and reopening.
//
// T053 mirrors the webapp's alarm surface: `GET /followups` on open, the same
// once-per-second tick, a due banner at the top, a per-row countdown chip, and
// a 2 px accent left-bar on due rows.

import {
  fetchCategories,
  fetchFollowups,
  fetchSettings,
  getResolvedTickets,
  getStoredTickets,
  getSyncState,
  ingestTickets,
  markFollowupFired,
  markNonActionable,
  overrideCategory,
  parkTicket,
  reopenTicket,
  resolveTicket,
  unparkTicket,
  FULL_BOARD_URL,
} from './api.js';
import { fetchHydratedBatch, getAppId, IntercomSessionError, setAppId } from './intercom.js';

const RESOLVED_TAB_KEY = 'resolved';
const NON_ACTIONABLE_TAB_KEY = 'non-actionable';
const PARKED_TAB_KEY = 'parked';

const NON_ACTIONABLE_KIND_LABELS = {
  auto_reply: 'Auto-reply',
  thanks: 'Thanks',
  spam: 'Spam',
  out_of_office: 'Out of office',
  other: 'Other',
};

const state = {
  categories: [],
  proposals: [],
  tickets: [],
  resolvedTickets: [], // tickets with resolved_at set
  followups: {}, // ticket_id → follow-up record
  muteAlarms: false,
  now: Date.now(),
  dismissed: new Set(), // ticket ids whose due banner the user dismissed
  activeTab: null, // 'cat-<id>' | 'prop-<id>' | 'resolved'
  error: null,
  loading: true,
};

const el = {
  count: document.getElementById('count'),
  tabs: document.getElementById('tabs'),
  banner: document.getElementById('banner'),
  list: document.getElementById('list'),
  refresh: document.getElementById('refresh'),
  sync: document.getElementById('sync'),
  setup: document.getElementById('setup'),
  appIdInput: document.getElementById('appIdInput'),
  saveAppId: document.getElementById('saveAppId'),
  syncStatus: document.getElementById('syncStatus'),
  interval: document.getElementById('interval'),
  openBoard: document.getElementById('openBoard'),
};

let appId = '';

/** Per-render lookup of a ticket's countdown chip + card, so the tick loop can
 *  update them in place without a disruptive full re-render. */
let chipRefs = new Map();
let cardRefs = new Map();

// ── Helpers ──────────────────────────────────────────────────────────────────

function ago(iso) {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text != null) n.textContent = text;
  return n;
}

const sortedCategories = () =>
  [...state.categories].sort((a, b) => a.sort_order - b.sort_order);

/** Tickets belonging to the active tab (parked tickets are excluded from category columns). */
function ticketsForTab(key) {
  if (!key) return [];
  const [kind, rawId] = key.split('-');
  const id = Number(rawId);
  return kind === 'cat'
    ? state.tickets.filter((t) => t.category_id === id && t.parked_at === null)
    : state.tickets.filter((t) => t.proposal_id === id && t.parked_at === null);
}

function isDue(followup) {
  return Date.parse(followup.due_at) <= state.now;
}

/** Countdown chip label: `due now` once due, else `F/U 15m` / `F/U 2h`. */
function chipLabel(followup) {
  if (isDue(followup)) return 'due now';
  const mins = Math.round((Date.parse(followup.due_at) - state.now) / 60000);
  return mins < 60 ? `F/U ${mins}m` : `F/U ${Math.round(mins / 60)}h`;
}

// ── Rendering ────────────────────────────────────────────────────────────────

function renderTabs() {
  el.tabs.replaceChildren();
  const tabs = [
    ...sortedCategories().map((c) => ({
      key: `cat-${c.id}`,
      name: c.name,
      color: c.color,
      proposal: false,
      resolved: false,
      count: state.tickets.filter((t) => t.category_id === c.id && t.parked_at === null).length,
    })),
    ...state.proposals.map((p) => ({
      key: `prop-${p.id}`,
      name: p.name,
      color: null,
      proposal: true,
      resolved: false,
      count: state.tickets.filter((t) => t.proposal_id === p.id && t.parked_at === null).length,
    })),
    {
      key: RESOLVED_TAB_KEY,
      name: 'Resolved',
      color: null,
      proposal: false,
      resolved: true,
      nonActionable: false,
      count: state.resolvedTickets.filter((t) => t.resolved_source !== 'non_actionable').length,
    },
    {
      key: NON_ACTIONABLE_TAB_KEY,
      name: 'Non-actionable',
      color: null,
      proposal: false,
      resolved: false,
      nonActionable: true,
      count: state.resolvedTickets.filter((t) => t.resolved_source === 'non_actionable').length,
    },
    (() => {
      const parkedList = state.tickets.filter((t) => t.parked_at !== null && t.resolved_at === null);
      const readyCount = parkedList.filter((t) => t.parked_until && Date.parse(t.parked_until) <= state.now).length;
      return {
        key: PARKED_TAB_KEY,
        name: readyCount > 0 ? `Parked ★ ready` : 'Parked',
        color: null,
        proposal: false,
        resolved: false,
        nonActionable: false,
        parked: true,
        count: parkedList.length,
      };
    })(),
  ];

  for (const tab of tabs) {
    const btn = node('button', 'tab');
    if (tab.proposal) btn.classList.add('proposal');
    if (tab.resolved) btn.classList.add('resolved-tab');
    if (tab.nonActionable) btn.classList.add('non-actionable-tab');
    if (tab.parked) btn.classList.add('parked-tab');
    if (tab.key === state.activeTab) btn.classList.add('active');

    if (tab.color) {
      const dot = node('span', 'dot');
      dot.style.background = tab.color;
      btn.append(dot);
    }
    btn.append(node('span', null, tab.name));
    btn.append(node('span', 'tab-count', String(tab.count)));
    btn.addEventListener('click', () => {
      state.activeTab = tab.key;
      renderTabs();
      renderList();
    });
    el.tabs.append(btn);
  }
}

function renderCard(ticket, { isResolved = false } = {}) {
  const card = node('article', 'card');
  if (ticket.user_override) card.classList.add('overridden');
  if (isResolved) card.classList.add('resolved-card');

  const followup = state.followups[ticket.id];
  if (followup && isDue(followup)) card.classList.add('due');

  const head = node('div', 'card-head');
  head.append(node('span', 'mono muted', ticket.id));
  head.append(node('span', 'mono muted', ago(ticket.updated_at)));
  card.append(head);

  card.append(node('h3', 'card-title', ticket.title || '(no subject)'));
  if (ticket.summary) card.append(node('p', 'card-summary', ticket.summary));

  const meta = node('div', 'card-meta');
  meta.append(node('span', 'customer', ticket.author?.name || '—'));

  // Roadmap 0.2 — triage facets from the categorization call (display only).
  // Hide 'normal'/'neutral' baselines so a card only flags an actual signal.
  if (ticket.ai_priority && ticket.ai_priority !== 'normal') {
    const pri = node('span', `pri-chip pri-${ticket.ai_priority}`, ticket.ai_priority);
    pri.title = `AI priority: ${ticket.ai_priority}`;
    meta.append(pri);
  }
  if (ticket.ai_sentiment && ticket.ai_sentiment !== 'neutral') {
    const glyph = ticket.ai_sentiment === 'positive' ? '☺' : '☹';
    const sent = node('span', `sent-chip sent-${ticket.ai_sentiment}`, glyph);
    sent.title = `Customer sentiment: ${ticket.ai_sentiment}`;
    meta.append(sent);
  }

  if (followup && !isResolved) {
    const chip = node('span', 'fu-chip', chipLabel(followup));
    if (isDue(followup)) chip.classList.add('due');
    meta.append(chip);
    chipRefs.set(ticket.id, chip);
  }

  if (isResolved) {
    // Resolved + Non-actionable tabs both show ↺ Reopen. Non-actionable cards
    // also show the kind chip (e.g. "Non-actionable · Spam") when kind is set.
    const reopenBtn = node('button', 'action-btn reopen-btn', '↺ Reopen');
    reopenBtn.addEventListener('click', () => void doReopen(ticket));
    meta.append(reopenBtn);

    if (ticket.resolved_source === 'non_actionable') {
      const kindLabel = NON_ACTIONABLE_KIND_LABELS[ticket.non_actionable_kind];
      const chipText = kindLabel ? `Non-actionable · ${kindLabel}` : 'Non-actionable';
      meta.append(node('span', 'resolution-chip non-actionable', chipText));
    }
  } else {
    // Open/category tabs: show ✓ Resolve + ⊘ Non-actionable + Park/Unpark + Move buttons.
    const resolveBtn = node('button', 'action-btn resolve-btn', '✓ Resolve');
    resolveBtn.addEventListener('click', () => void doResolve(ticket));
    meta.append(resolveBtn);

    const naBtn = node('button', 'action-btn non-actionable-btn', '⊘ Non-actionable');
    naBtn.addEventListener('click', () => void doMarkNonActionable(ticket));
    meta.append(naBtn);

    if (ticket.parked_at !== null) {
      // Already parked — show Unpark button.
      const unparkBtn = node('button', 'action-btn unpark-btn', '▶ Unpark');
      unparkBtn.addEventListener('click', () => void doUnpark(ticket));
      meta.append(unparkBtn);
    } else {
      // Not parked — compact click-to-reveal Park menu (reason + duration).
      const parkWrap = node('div', 'park-wrap');
      const parkToggle = node('button', 'action-btn park-btn', '⏸ Park ▾');
      const menu = node('div', 'park-menu');
      parkToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.classList.toggle('open');
      });

      const reasonRow = node('div', 'park-row');
      const reasonSelect = node('select', 'park-reason');
      const reasons = [
        { value: 'waiting_on_customer', label: 'Customer' },
        { value: 'waiting_on_third_party', label: 'Third party' },
        { value: 'waiting_internal', label: 'Internal' },
        { value: 'other', label: 'Other' },
      ];
      for (const r of reasons) {
        const opt = document.createElement('option');
        opt.value = r.value;
        opt.textContent = r.label;
        reasonSelect.append(opt);
      }
      reasonRow.append(node('span', 'park-lbl', 'reason'), reasonSelect);

      // Free-text note, shown only when reason = 'other'.
      const noteInput = node('input', 'park-reason');
      noteInput.type = 'text';
      noteInput.maxLength = 200;
      noteInput.placeholder = 'Reason (optional)';
      const noteRow = node('div', 'park-row');
      noteRow.style.display = 'none';
      noteRow.append(noteInput);
      reasonSelect.addEventListener('change', () => {
        noteRow.style.display = reasonSelect.value === 'other' ? 'flex' : 'none';
      });

      const presetRow = node('div', 'park-row');
      const presets = [
        { label: '1h', minutes: 60 },
        { label: '4h', minutes: 240 },
        { label: '1d', minutes: 24 * 60 },
        { label: '3d', minutes: 3 * 24 * 60 },
      ];
      for (const p of presets) {
        const presetBtn = node('button', 'park-preset', `+${p.label}`);
        presetBtn.addEventListener('click', () => {
          const note = reasonSelect.value === 'other' ? noteInput.value.trim() || null : null;
          void doPark(
            ticket,
            new Date(Date.now() + p.minutes * 60 * 1000).toISOString(),
            reasonSelect.value,
            note,
          );
        });
        presetRow.append(presetBtn);
      }

      menu.append(node('span', 'park-menu-title', 'Park until'), reasonRow, noteRow, presetRow);
      parkWrap.append(parkToggle, menu);
      meta.append(parkWrap);
    }

    const moveBtn = node('button', 'move-btn', 'Move ▾');
    meta.append(moveBtn);

    // Tap-to-move: toggle a button list of categories.
    moveBtn.addEventListener('click', () => {
      const open = card.querySelector('.move-picker');
      if (open) {
        open.remove();
        return;
      }
      const picker = node('div', 'move-picker');
      for (const cat of sortedCategories()) {
        if (cat.id === ticket.category_id) continue;
        const target = node('button', 'move-target');
        const dot = node('span', 'dot');
        dot.style.background = cat.color || 'var(--ink-3)';
        target.append(dot, node('span', null, cat.name));
        target.addEventListener('click', () => void moveTicket(ticket, cat.id));
        picker.append(target);
      }
      card.append(picker);
    });
  }

  card.append(meta);

  // Roadmap 0.2 — secondary multi-label tags row.
  if (Array.isArray(ticket.ai_labels) && ticket.ai_labels.length) {
    const tags = node('div', 'card-labels');
    for (const label of ticket.ai_labels) tags.append(node('span', 'label-tag', label));
    card.append(tags);
  }

  cardRefs.set(ticket.id, card);
  return card;
}

function renderList() {
  el.list.replaceChildren();
  chipRefs = new Map();
  cardRefs = new Map();

  if (state.loading) {
    el.list.append(node('p', 'state mono', 'Loading…'));
    return;
  }
  if (state.error) {
    el.list.append(node('p', 'state error mono', state.error));
    return;
  }

  if (state.activeTab === PARKED_TAB_KEY) {
    const rows = state.tickets.filter((t) => t.parked_at !== null && t.resolved_at === null);
    if (rows.length === 0) {
      el.list.append(node('p', 'state mono', 'No parked tickets'));
      return;
    }
    // Ready (wake time passed) tickets first, then most-recently-parked.
    rows
      .slice()
      .sort((a, b) => {
        const readyA = Number(a.parked_until !== null && Date.parse(a.parked_until) <= state.now);
        const readyB = Number(b.parked_until !== null && Date.parse(b.parked_until) <= state.now);
        if (readyA !== readyB) return readyB - readyA;
        return new Date(b.parked_at ?? b.updated_at) - new Date(a.parked_at ?? a.updated_at);
      })
      .forEach((t) => el.list.append(renderCard(t)));
    return;
  }

  if (state.activeTab === RESOLVED_TAB_KEY || state.activeTab === NON_ACTIONABLE_TAB_KEY) {
    const wantNonActionable = state.activeTab === NON_ACTIONABLE_TAB_KEY;
    const rows = state.resolvedTickets.filter((t) =>
      wantNonActionable
        ? t.resolved_source === 'non_actionable'
        : t.resolved_source !== 'non_actionable',
    );
    if (rows.length === 0) {
      el.list.append(
        node('p', 'state mono', wantNonActionable ? 'No non-actionable tickets' : 'No resolved tickets'),
      );
      return;
    }
    // Most-recently-resolved first.
    rows
      .slice()
      .sort((a, b) => new Date(b.resolved_at ?? b.updated_at) - new Date(a.resolved_at ?? a.updated_at))
      .forEach((t) => el.list.append(renderCard(t, { isResolved: true })));
    return;
  }

  const rows = ticketsForTab(state.activeTab);
  if (rows.length === 0) {
    el.list.append(node('p', 'state mono', 'No tickets in this column'));
    return;
  }
  rows
    .slice()
    .sort((a, b) => {
      // Due follow-ups pinned to the top, then most-recently-updated.
      const dueA = Number(Boolean(state.followups[a.id] && isDue(state.followups[a.id])));
      const dueB = Number(Boolean(state.followups[b.id] && isDue(state.followups[b.id])));
      if (dueA !== dueB) return dueB - dueA;
      return new Date(b.updated_at) - new Date(a.updated_at);
    })
    .forEach((t) => el.list.append(renderCard(t)));
}

/** The due banner — shown while at least one non-dismissed follow-up is due. */
function renderBanner() {
  const due = Object.values(state.followups).filter(
    (f) => isDue(f) && !state.dismissed.has(f.ticket_id),
  );
  if (due.length === 0) {
    el.banner.hidden = true;
    el.banner.replaceChildren();
    return;
  }
  el.banner.hidden = false;
  el.banner.replaceChildren();
  const label =
    due.length === 1
      ? `Follow-up due — ${due[0].ticket_id}`
      : `${due.length} follow-ups due`;
  el.banner.append(node('span', 'banner-text mono', label));

  const open = node('button', 'banner-act', 'Open board');
  open.addEventListener('click', () => chrome.tabs.create({ url: FULL_BOARD_URL }));
  el.banner.append(open);

  const dismiss = node('button', 'banner-act', 'Dismiss');
  dismiss.addEventListener('click', () => {
    for (const f of due) state.dismissed.add(f.ticket_id);
    renderBanner();
  });
  el.banner.append(dismiss);
}

function renderCount() {
  el.count.textContent = state.loading ? '' : `${state.tickets.length} tickets`;
}

// ── Alarm loop (T053) ─────────────────────────────────────────────────────────

let audioCtx = null;

function ensureAudio() {
  if (audioCtx === null && typeof AudioContext !== 'undefined') {
    audioCtx = new AudioContext();
  }
}

/** A two-note WebAudio ping (880 → 1175 Hz) — matches the webapp cue. */
function playPing() {
  ensureAudio();
  if (audioCtx === null) return;
  if (audioCtx.state === 'suspended') void audioCtx.resume();
  const t0 = audioCtx.currentTime;
  [880, 1175].forEach((freq, i) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    const start = t0 + i * 0.34;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.22, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.3);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(start);
    osc.stop(start + 0.32);
  });
}

/** Once-per-second tick: advance `now`, refresh chips, ring newly-due alarms. */
function alarmTick() {
  state.now = Date.now();
  let newlyDue = false;
  for (const f of Object.values(state.followups)) {
    const due = isDue(f);
    const chip = chipRefs.get(f.ticket_id);
    if (chip) {
      chip.textContent = chipLabel(f);
      chip.classList.toggle('due', due);
    }
    const card = cardRefs.get(f.ticket_id);
    if (card) card.classList.toggle('due', due);
    if (due && !f.fired) {
      f.fired = true;
      newlyDue = true;
      void markFollowupFired(f.ticket_id);
    }
  }
  if (newlyDue && !state.muteAlarms) playPing();
  renderBanner();
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function moveTicket(ticket, categoryId) {
  try {
    await overrideCategory(ticket.id, categoryId);
    // Reflect the move locally so the card jumps columns without a full reload.
    ticket.category_id = categoryId;
    ticket.proposal_id = null;
    ticket.user_override = true;
    renderTabs();
    renderList();
  } catch (e) {
    state.error = e.message;
    renderList();
  }
}

/** Mark a ticket as resolved — removes it from the open board, adds to Resolved tab. */
async function doResolve(ticket) {
  try {
    const result = await resolveTicket(ticket.id);
    // Move locally from open tickets to resolved tickets.
    state.tickets = state.tickets.filter((t) => t.id !== ticket.id);
    ticket.resolved_at = result.resolved_at ?? new Date().toISOString();
    ticket.resolved_source = result.resolved_source ?? 'manual';
    state.resolvedTickets = [ticket, ...state.resolvedTickets];
    renderTabs();
    renderList();
  } catch (e) {
    state.error = e.message;
    renderList();
  }
}

/** Mark a ticket non-actionable — sub-state of resolved; moves to Resolved tab with a chip. */
async function doMarkNonActionable(ticket) {
  try {
    const result = await markNonActionable(ticket.id);
    // Move locally from open tickets to resolved tickets.
    state.tickets = state.tickets.filter((t) => t.id !== ticket.id);
    ticket.resolved_at = result.resolved_at ?? new Date().toISOString();
    ticket.resolved_source = result.resolved_source ?? 'non_actionable';
    state.resolvedTickets = [ticket, ...state.resolvedTickets];
    renderTabs();
    renderList();
  } catch (e) {
    state.error = e.message;
    renderList();
  }
}

/** Park an open ticket until `untilAt` ISO — moves it out of category columns, into Parked tab. */
async function doPark(ticket, untilAt, reason, note = null) {
  try {
    await parkTicket(ticket.id, untilAt, reason, note);
    // Reflect parked state locally so the card leaves its column and shows in Parked.
    ticket.parked_at = new Date().toISOString();
    ticket.parked_until = untilAt;
    ticket.parked_reason = reason;
    ticket.parked_note = note;
    renderTabs();
    renderList();
  } catch (e) {
    state.error = e.message;
    renderList();
  }
}

/** Unpark a parked ticket — clears parked state, returns it to its category column. */
async function doUnpark(ticket) {
  try {
    await unparkTicket(ticket.id);
    ticket.parked_at = null;
    ticket.parked_until = null;
    ticket.parked_reason = null;
    renderTabs();
    renderList();
  } catch (e) {
    state.error = e.message;
    renderList();
  }
}

/** Reopen a resolved ticket — moves it back into its category tab. */
async function doReopen(ticket) {
  try {
    await reopenTicket(ticket.id);
    state.resolvedTickets = state.resolvedTickets.filter((t) => t.id !== ticket.id);
    ticket.resolved_at = null;
    ticket.resolved_source = null;
    ticket.resolution_chip_state = null;
    state.tickets = [ticket, ...state.tickets];
    renderTabs();
    renderList();
  } catch (e) {
    state.error = e.message;
    renderList();
  }
}

async function load() {
  state.loading = true;
  state.error = null;
  renderCount();
  renderList();
  try {
    const [settings, catResp, followups, tickets, resolvedTickets] = await Promise.all([
      fetchSettings(),
      fetchCategories(),
      fetchFollowups(),
      getStoredTickets(),
      getResolvedTickets().catch(() => []), // best-effort; don't break open board
    ]);
    state.categories = catResp.categories;
    state.proposals = catResp.pending_proposals;
    state.muteAlarms = Boolean(settings.mute_alarms);
    state.followups = Object.fromEntries(followups.map((f) => [f.ticket_id, f]));
    state.tickets = tickets;
    state.resolvedTickets = resolvedTickets;

    // Keep the selected tab if it still exists, else default to the first.
    const keys = [
      ...state.categories.map((c) => `cat-${c.id}`),
      ...state.proposals.map((p) => `prop-${p.id}`),
      RESOLVED_TAB_KEY,
      NON_ACTIONABLE_TAB_KEY,
      PARKED_TAB_KEY,
    ];
    if (!keys.includes(state.activeTab)) state.activeTab = keys[0] ?? null;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
  state.now = Date.now();
  renderCount();
  renderTabs();
  renderList();
  renderBanner();
}

// ── Wiring ───────────────────────────────────────────────────────────────────

el.refresh.addEventListener('click', () => void load());

el.sync.addEventListener('click', () => void sync());

el.saveAppId.addEventListener('click', async () => {
  const value = el.appIdInput.value.trim();
  if (!value) return;
  await setAppId(value);
  appId = value;
  el.setup.hidden = true;
  await sync();
});

el.openBoard.addEventListener('click', () => {
  chrome.tabs.create({ url: FULL_BOARD_URL });
});

el.interval.addEventListener('change', async () => {
  const pollMinutes = Number(el.interval.value);
  await chrome.storage.local.set({ pollMinutes });
  chrome.runtime.sendMessage({ type: 'reschedule' });
});

// Unlock audio on the first interaction inside the popup (autoplay policy).
window.addEventListener('pointerdown', ensureAudio, { once: true });

function setSyncStatus(text, { error = false } = {}) {
  if (!text) {
    el.syncStatus.hidden = true;
    el.syncStatus.textContent = '';
    return;
  }
  el.syncStatus.hidden = false;
  el.syncStatus.textContent = text;
  el.syncStatus.classList.toggle('error', error);
}

/** Pull from Intercom, send to backend ingest, reload the stored board. */
async function sync() {
  if (!appId) {
    el.setup.hidden = false;
    el.appIdInput.focus();
    setSyncStatus('Set your Intercom workspace id to sync', { error: true });
    return;
  }
  el.sync.disabled = true;
  setSyncStatus('Pulling from Intercom…');
  try {
    const settings = await fetchSettings();
    const states = settings.states?.length ? settings.states : ['open'];
    // Already-stored tickets with an unchanged conversation are skipped — the
    // detail fetch + AI call only run for new / replied-to conversations.
    const knownState = await getSyncState().catch(() => ({}));
    const batches = await Promise.all(
      states.map((state) =>
        fetchHydratedBatch({ appId, state, count: 60, concurrency: 4, knownState }).catch((e) => {
          if (e instanceof IntercomSessionError) throw e;
          return [];
        }),
      ),
    );
    const hydrated = batches.flat();
    if (hydrated.length === 0) {
      setSyncStatus('Up to date — no new or changed conversations');
    } else {
      setSyncStatus(`Categorizing ${hydrated.length}…`);
      const result = await ingestTickets(hydrated);
      setSyncStatus(`Synced ${result.received} changed (AI: ${result.categorized})`);
    }
    await load();
  } catch (e) {
    setSyncStatus(e.message || 'Sync failed', { error: true });
  } finally {
    el.sync.disabled = false;
  }
}

(async function init() {
  const [{ pollMinutes = 0 }, savedAppId] = await Promise.all([
    chrome.storage.local.get('pollMinutes'),
    getAppId(),
  ]);
  el.interval.value = String(pollMinutes);
  appId = savedAppId;
  if (!appId) el.setup.hidden = false;
  else el.appIdInput.value = appId;
  await load();
  setInterval(alarmTick, 1000);
})();
