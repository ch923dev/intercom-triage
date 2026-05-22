// Intercom session-cookie client.
//
// The operator has no Intercom Access Token, so the extension fetches
// conversations from Intercom's internal `ember/` API using the operator's
// logged-in browser session. The manifest's `host_permissions` for
// `https://app.intercom.com/*` exempts the calls from CORS and lets `fetch`
// attach the session cookies via `credentials: 'include'`.
//
// **Stability caveat:** these endpoints are undocumented + can change without
// notice. A 401/403 means the operator isn't logged in; the popup surfaces a
// "Log in to Intercom" hint when that happens.
//
// Endpoints (workspace = `app_id`):
//   - list  : GET /ember/inbox/conversations/list
//   - detail: GET /ember/inbox/conversations/{id}
// Detail carries `renderable_parts[]`; only `renderable_type` 1 (inbound) and
// 24 (admin reply) hold conversation text — events (5/14/etc.) are skipped.

const INTERCOM_BASE = 'https://app.intercom.com';
const APP_ID_STORAGE_KEY = 'intercomAppId';

// Renderable types we know carry conversation text. Inclusive list — anything
// else (assignment, attribute change, internal note metadata) is filtered out
// implicitly because `blocksToPlainText` yields an empty string for it.
//   1  — Messenger inbound (user)
//   12 — Email inbound (user)
//   24 — Admin reply (Messenger or email)
//   25 — Admin internal note (skipped — type 17 in some workspaces)
const MESSAGE_RENDERABLE_TYPES = new Set([1, 12, 24]);
const INBOUND_RENDERABLE_TYPES = new Set([1, 12]);

class IntercomSessionError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'IntercomSessionError';
    this.status = status;
  }
}

/** Read the saved workspace id (`app_id`) from `chrome.storage.local`. */
export async function getAppId() {
  const { [APP_ID_STORAGE_KEY]: appId = '' } = await chrome.storage.local.get(APP_ID_STORAGE_KEY);
  return appId;
}

export async function setAppId(appId) {
  await chrome.storage.local.set({ [APP_ID_STORAGE_KEY]: appId });
}

async function requestJson(path, params = {}) {
  const url = new URL(INTERCOM_BASE + path);
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((item) => url.searchParams.append(k, item));
    else if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }
  let resp;
  try {
    resp = await fetch(url.toString(), { credentials: 'include' });
  } catch {
    throw new IntercomSessionError(0, 'Intercom unreachable from this browser');
  }
  if (resp.status === 401 || resp.status === 403) {
    throw new IntercomSessionError(
      resp.status,
      'Not signed in to Intercom — open https://app.intercom.com and log in',
    );
  }
  if (!resp.ok) {
    throw new IntercomSessionError(resp.status, `Intercom ${path} → ${resp.status}`);
  }
  return resp.json();
}

/**
 * List conversation summaries.
 *
 * @param {object} opts
 * @param {string} opts.appId   Workspace `app_id` (e.g. `j3dxf22l`).
 * @param {'open'|'snoozed'|'closed'} [opts.state='open']
 * @param {number} [opts.count=40]  Page size.
 */
export async function listConversations({ appId, state = 'open', count = 40 }) {
  const body = await requestJson('/ember/inbox/conversations/list', {
    app_id: appId,
    inbox_type: 'all',
    sort_field: 'sorting_updated_at',
    sort_direction: 'desc',
    state,
    count,
    include_latest_conversation: 'false',
    'fields[]': 'attributes',
    search_text: '',
  });
  return Array.isArray(body?.conversations) ? body.conversations : [];
}

/** Fetch one conversation with its renderable parts (the message text). */
export async function getConversation(appId, id) {
  return requestJson(`/ember/inbox/conversations/${encodeURIComponent(id)}`, { app_id: appId });
}

// ── Normalizer ──────────────────────────────────────────────────────────────
//
// Intercom's `renderable_data.blocks` is an array of typed nodes: paragraphs,
// lists, code blocks, images, etc. We need plain text for the AI prompt. Strip
// HTML in `text` fields and flatten list items.

function blocksToPlainText(blocks) {
  if (!Array.isArray(blocks)) return '';
  const lines = [];
  for (const block of blocks) {
    if (!block || typeof block !== 'object') continue;
    // Messenger paragraphs / headings: `{ type, text }`
    if (typeof block.text === 'string') lines.push(stripHtml(block.text));
    // Email blocks: `{ type: 'html', content: '<p>…</p>' }`
    if (typeof block.content === 'string') lines.push(stripHtml(block.content));
    // Lists: `{ items: [string | { text }] }`
    if (Array.isArray(block.items)) {
      for (const item of block.items) {
        if (typeof item === 'string') lines.push(`• ${stripHtml(item)}`);
        else if (item && typeof item.text === 'string') lines.push(`• ${stripHtml(item.text)}`);
      }
    }
  }
  return lines
    .map((line) => line.trim())
    .filter(Boolean)
    .join('\n')
    .slice(0, 8000);
}

function stripHtml(s) {
  return String(s)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function toIso(value, fallback) {
  // Intercom's internal API gives ISO strings here, but accept unix seconds
  // too — older Intercom endpoints + a few attribute fields use them.
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'number' && Number.isFinite(value)) {
    return new Date(value * 1000).toISOString();
  }
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return fallback;
  return d.toISOString();
}

function normalizeAuthor(raw) {
  if (!raw || typeof raw !== 'object') return { id: null, name: null, email: null, type: null };
  return {
    id: raw.id != null ? String(raw.id) : null,
    name: raw.name ?? null,
    email: raw.email ?? null,
    type: raw.type ?? raw.role ?? null,
  };
}

function authorFromSummary(summary) {
  if (!summary) return { id: null, name: null, email: null, type: 'user' };
  return {
    id: summary.id != null ? String(summary.id) : null,
    name: summary.name ?? null,
    email: summary.email ?? null,
    type: summary.role ?? 'user',
  };
}

/**
 * Convert an Intercom detail payload into the backend's `HydratedTicket` shape:
 *   { id, title, state, priority, created_at, updated_at, author, url, parts[] }
 *
 * @param {object} detail   Response from `getConversation`.
 * @param {string} appId    Workspace id, used to build the deep link.
 * @param {object} [summary] Optional list-level summary; its `last_updated`
 *                           is more reliable than anything on the detail.
 */
export function normalizeConversation(detail, appId, summary) {
  const id = String(detail.id);
  const author = authorFromSummary(detail.user_summary);
  const nowIso = new Date().toISOString();
  const createdIso = toIso(detail.created_at, nowIso);

  const parts = [];
  for (const node of detail.renderable_parts ?? []) {
    const renderableType = node?.renderable_type;
    if (!MESSAGE_RENDERABLE_TYPES.has(renderableType)) continue;
    const data = node.renderable_data ?? {};
    const body = blocksToPlainText(data.blocks);
    if (!body) continue;
    parts.push({
      author: INBOUND_RENDERABLE_TYPES.has(renderableType)
        ? authorFromSummary(data.user_summary) || author
        : normalizeAuthor(data.author),
      body,
      created_at: toIso(node.created_at, createdIso),
    });
  }

  const updatedRaw =
    summary?.last_updated ?? detail.last_updated ?? detail.updated_at ?? detail.created_at;
  return {
    id,
    title: detail.title ?? null,
    state: detail.state ?? null,
    priority: detail.priority ?? null,
    created_at: createdIso,
    updated_at: toIso(updatedRaw, createdIso),
    author,
    url: `https://app.intercom.com/a/inbox/${appId}/inbox/conversation/${id}`,
    parts,
  };
}

/**
 * Fetch a page of conversations + their detail records, normalized for the
 * backend ingest endpoint. Concurrency-limited so we don't hammer Intercom.
 */
export async function fetchHydratedBatch({ appId, state = 'open', count = 40, concurrency = 4 }) {
  const summaries = await listConversations({ appId, state, count });

  const out = new Array(summaries.length);
  let cursor = 0;

  async function worker() {
    while (true) {
      const i = cursor++;
      if (i >= summaries.length) return;
      const summary = summaries[i];
      const detail = await getConversation(appId, summary.id);
      out[i] = normalizeConversation(detail, appId, summary);
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, summaries.length) }, worker));
  return out;
}

export { IntercomSessionError };
