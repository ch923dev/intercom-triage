// Popup mini-board. Reference: tasks.md T041 — US-006.
//
// The full taxonomy (active categories + pending proposals) renders as column
// tabs; selecting a tab lists its tickets. Each card has a tap-to-move action
// — a button list of categories, sized for the popup — instead of the webapp's
// drag-and-drop. Overrides hit `PATCH /tickets/{id}/category`, which the
// backend persists, so a move survives the popup closing and reopening.

import { fetchCategories, fetchSettings, fetchTickets, overrideCategory, FULL_BOARD_URL } from './api.js';

const state = {
  categories: [],
  proposals: [],
  tickets: [],
  activeTab: null, // 'cat-<id>' | 'prop-<id>'
  error: null,
  loading: true,
};

const el = {
  count: document.getElementById('count'),
  tabs: document.getElementById('tabs'),
  list: document.getElementById('list'),
  refresh: document.getElementById('refresh'),
  interval: document.getElementById('interval'),
  openBoard: document.getElementById('openBoard'),
};

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

/** Tickets belonging to the active tab. */
function ticketsForTab(key) {
  if (!key) return [];
  const [kind, rawId] = key.split('-');
  const id = Number(rawId);
  return kind === 'cat'
    ? state.tickets.filter((t) => t.category_id === id)
    : state.tickets.filter((t) => t.proposal_id === id);
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
      count: state.tickets.filter((t) => t.category_id === c.id).length,
    })),
    ...state.proposals.map((p) => ({
      key: `prop-${p.id}`,
      name: p.name,
      color: null,
      proposal: true,
      count: state.tickets.filter((t) => t.proposal_id === p.id).length,
    })),
  ];

  for (const tab of tabs) {
    const btn = node('button', 'tab');
    if (tab.proposal) btn.classList.add('proposal');
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

function renderCard(ticket) {
  const card = node('article', 'card');
  if (ticket.user_override) card.classList.add('overridden');

  const head = node('div', 'card-head');
  head.append(node('span', 'mono muted', ticket.id));
  head.append(node('span', 'mono muted', ago(ticket.updated_at)));
  card.append(head);

  card.append(node('h3', 'card-title', ticket.title || '(no subject)'));
  if (ticket.summary) card.append(node('p', 'card-summary', ticket.summary));

  const meta = node('div', 'card-meta');
  meta.append(node('span', 'customer', ticket.author?.name || '—'));
  const moveBtn = node('button', 'move-btn', 'Move ▾');
  meta.append(moveBtn);
  card.append(meta);

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

  return card;
}

function renderList() {
  el.list.replaceChildren();

  if (state.loading) {
    el.list.append(node('p', 'state mono', 'Loading…'));
    return;
  }
  if (state.error) {
    el.list.append(node('p', 'state error mono', state.error));
    return;
  }
  const rows = ticketsForTab(state.activeTab);
  if (rows.length === 0) {
    el.list.append(node('p', 'state mono', 'No tickets in this column'));
    return;
  }
  rows
    .slice()
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
    .forEach((t) => el.list.append(renderCard(t)));
}

function renderCount() {
  el.count.textContent = state.loading ? '' : `${state.tickets.length} tickets`;
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

async function load() {
  state.loading = true;
  state.error = null;
  renderCount();
  renderList();
  try {
    const [settings, catResp] = await Promise.all([fetchSettings(), fetchCategories()]);
    state.categories = catResp.categories;
    state.proposals = catResp.pending_proposals;
    state.tickets = await fetchTickets(settings);

    // Keep the selected tab if it still exists, else default to the first.
    const keys = [
      ...state.categories.map((c) => `cat-${c.id}`),
      ...state.proposals.map((p) => `prop-${p.id}`),
    ];
    if (!keys.includes(state.activeTab)) state.activeTab = keys[0] ?? null;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
  renderCount();
  renderTabs();
  renderList();
}

// ── Wiring ───────────────────────────────────────────────────────────────────

el.refresh.addEventListener('click', () => void load());

el.openBoard.addEventListener('click', () => {
  chrome.tabs.create({ url: FULL_BOARD_URL });
});

el.interval.addEventListener('change', async () => {
  const pollMinutes = Number(el.interval.value);
  await chrome.storage.local.set({ pollMinutes });
  chrome.runtime.sendMessage({ type: 'reschedule' });
});

(async function init() {
  const { pollMinutes = 0 } = await chrome.storage.local.get('pollMinutes');
  el.interval.value = String(pollMinutes);
  await load();
})();
