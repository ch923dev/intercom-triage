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
// Detail carries `renderable_parts[]`; only the message types below hold
// conversation text — events (5/6/14/21/26/31/71) are skipped (see table below).

const INTERCOM_BASE = 'https://app.intercom.com';
const APP_ID_STORAGE_KEY = 'intercomAppId';

/** How far back the closure pass looks when paginating the closed list.
 *  Default: 7 days. The pass stops early once all candidate ids are found. */
const LOOKBACK_SECONDS = 7 * 24 * 60 * 60;

// Renderable types we know carry conversation text. Decoded via live
// inspection — assignment/attribute/translation events fall through and are
// filtered out implicitly because `blocksToPlainText` yields '' for them.
//   1  — Messenger inbound (customer)        → parts[], is_admin=false
//   12 — Email inbound (customer)            → parts[], is_admin=false
//   2  — Admin reply visible to the customer → parts[], is_admin=true
//   24 — Admin reply visible to the customer → parts[], is_admin=true
//   3  — Internal team note (admin-only)     → internal_notes[]
//   21 — Priority-change event               → skip
//   26 — Participant-added event             → skip
//   31 — Bot / workflow-rule event           → skip
//   5/6/14 — assignment/attribute events     → skip
//   71 — Bot / AI translation event          → skip
//
// Classification was verified against live conversations: type 2 and 24 are
// both ordinary customer-facing admin replies; type 3 is the genuine internal
// team note (terse, third-person teammate coordination, never sent to the
// customer). All three carry the teammate in `admin_summary` or `entity`.
const INBOUND_RENDERABLE_TYPES = new Set([1, 12]);
const ADMIN_REPLY_RENDERABLE_TYPES = new Set([2, 24]);
const INTERNAL_NOTE_RENDERABLE_TYPE = 3;
// Non-text events we *expect* to skip silently: assignment/attribute changes
// (5/6/14), priority change (21), participant added (26), bot/workflow-rule
// fired (31), and bot/AI translation (71). These are known-and-ignored, so
// they must NOT trigger the unknown-type warning below — only genuinely
// unrecognized codes should. Verified against a 2026-05-28 live capture
// (workspace j3dxf22l). Keep this list in sync with the table above.
const KNOWN_SKIPPED_RENDERABLE_TYPES = new Set([5, 6, 14, 21, 26, 31, 71]);

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
 * List one page of conversation summaries.
 *
 * @param {object} opts
 * @param {string} opts.appId   Workspace `app_id` (e.g. `j3dxf22l`).
 * @param {'open'|'snoozed'|'closed'} [opts.state='open']
 * @param {number} [opts.count=40]  Page size.
 * @param {string|null} [opts.startingAfter=null]  Pagination cursor.
 * @returns {Promise<{conversations: object[], nextCursor: string|null}>}
 */
export async function listConversations({ appId, state = 'open', count = 40, startingAfter = null }) {
  const params = {
    app_id: appId,
    inbox_type: 'all',
    sort_field: 'sorting_updated_at',
    sort_direction: 'desc',
    state,
    count,
    include_latest_conversation: 'false',
    'fields[]': 'attributes',
    search_text: '',
  };
  if (startingAfter) params.starting_after = startingAfter;
  const body = await requestJson('/ember/inbox/conversations/list', params);
  return {
    conversations: Array.isArray(body?.conversations) ? body.conversations : [],
    nextCursor: body?.pages?.next?.starting_after ?? null,
  };
}

/** Fetch one conversation with its renderable parts (the message text). */
export async function getConversation(appId, id) {
  return requestJson(`/ember/inbox/conversations/${encodeURIComponent(id)}`, { app_id: appId });
}

/** Epoch-ms of a list summary's last activity. Intercom uses a few different
 *  field names depending on the endpoint version; accept any of them. Returns
 *  `null` when none is present. */
function summaryUpdatedMs(summary) {
  const raw = summary?.last_updated ?? summary?.updated_at ?? summary?.sorting_updated_at;
  if (raw === null || raw === undefined || raw === '') return null;
  const iso = toIso(raw, null);
  return iso ? Date.parse(iso) : null;
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

// Fallback body for a part that has attachments but no text block (R.5).
// The per-upload field that holds the filename is reverse-engineered (the
// live capture confirmed uploads[] exists but not its object shape), so try
// the likely names and degrade to a generic marker — never crash, never
// re-drop. One line per upload; same 8000-char cap as blocksToPlainText.
function uploadsToPlainText(uploads) {
  if (!Array.isArray(uploads)) return '';
  return uploads
    .map((u) => {
      if (!u || typeof u !== 'object') return '[attachment]';
      const name = u.name ?? u.file_name ?? u.filename ?? null;
      return typeof name === 'string' && name.trim()
        ? `[attachment: ${name.trim()}]`
        : '[attachment]';
    })
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
  if (!summary) {
    return { id: null, name: null, email: null, type: 'user', location: null, timezone: null, phone: null, company: null };
  }
  // Intercom's `user_summary` carries two identifiers: `user_id` is the
  // user-facing "User id" shown in Intercom's contact panel; `id` is the
  // internal contact-record id. Prefer `user_id` so triage matches Intercom;
  // fall back to `id` for leads/contacts that have no external user_id.
  const userId = summary.user_id ?? summary.id;
  // Mirror Intercom's "User data" panel: compose location from geoip and pull
  // timezone / phone / company so the webapp can show the same identity block.
  const geo = (summary.geoip_data && typeof summary.geoip_data === 'object') ? summary.geoip_data : {};
  const locationParts = [geo.city_name, geo.region_code, geo.country_name].filter(Boolean);
  const company = summary.first_company?.name ?? summary.companies?.[0]?.name ?? null;
  return {
    id: userId != null ? String(userId) : null,
    name: summary.name ?? null,
    email: summary.email ?? null,
    type: summary.role ?? 'user',
    location: locationParts.length ? locationParts.join(', ') : null,
    timezone: summary.timezone ?? geo.timezone ?? null,
    phone: summary.phone ?? null,
    company,
  };
}

/** Admin replies carry the teammate in `entity` (type 24) or `admin_summary`
 *  (type 2). Either way it's an admin. */
function authorFromAdminBlob(blob) {
  if (!blob || typeof blob !== 'object') return { id: null, name: null, email: null, type: 'admin' };
  return {
    id: blob.id != null ? String(blob.id) : null,
    name: blob.name ?? null,
    email: blob.email ?? null,
    type: 'admin',
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
  const internalNotes = [];
  for (const node of detail.renderable_parts ?? []) {
    const renderableType = node?.renderable_type;
    const data = node.renderable_data ?? {};
    const createdAt = toIso(node.created_at, createdIso);

    if (INBOUND_RENDERABLE_TYPES.has(renderableType)) {
      const body = blocksToPlainText(data.blocks) || uploadsToPlainText(data.uploads);
      if (!body) continue;
      parts.push({
        // authorFromSummary always returns a (possibly all-null) object, so a
        // plain `|| author` fallback is dead code. Guard explicitly: a part
        // carrying its own user_summary uses it; an orphan inbound part (none)
        // attributes to the conversation-level customer author instead of a
        // fully-null author.
        author: data.user_summary ? authorFromSummary(data.user_summary) : author,
        body,
        created_at: createdAt,
        is_admin: false,
      });
    } else if (ADMIN_REPLY_RENDERABLE_TYPES.has(renderableType)) {
      const body = blocksToPlainText(data.blocks) || uploadsToPlainText(data.uploads);
      if (!body) continue;
      parts.push({
        author: authorFromAdminBlob(data.entity || data.admin_summary || data.author),
        body,
        created_at: createdAt,
        is_admin: true,
      });
    } else if (renderableType === INTERNAL_NOTE_RENDERABLE_TYPE) {
      const body = blocksToPlainText(data.blocks) || uploadsToPlainText(data.uploads);
      if (!body) continue;
      internalNotes.push({
        author: authorFromAdminBlob(data.admin_summary || data.entity || data.author),
        body,
        created_at: createdAt,
        is_admin: true,
      });
    } else if (!KNOWN_SKIPPED_RENDERABLE_TYPES.has(renderableType)) {
      // Unknown renderable_type: the mapping is reverse-engineered, so an
      // unrecognized code means Intercom may have introduced a new message
      // kind we'd otherwise drop on the floor. Surface it (code + conversation
      // id only — never the body, for privacy) so the operator can capture a
      // real payload and decide whether to map it. Skip behavior is unchanged.
      console.warn(
        `[intercom] unknown renderable_type ${String(renderableType)} on conversation ${id} — skipping (mapping is reverse-engineered; capture a real payload if this recurs)`,
      );
    }
    // Known events (assignment / attribute / translation / priority-change /
    // participant-added / bot-rule, types 5/6/14/21/26/31/71) are skipped
    // silently; genuinely unknown codes are warned above.
  }

  const updatedRaw =
    summary?.last_updated ?? detail.last_updated ?? detail.updated_at ?? detail.created_at;
  return {
    id,
    title: detail.title ?? null,
    state: detail.state ?? null,
    // Intercom returns a boolean here (`false` = not priority); the backend
    // schema expects `string | null`, so coerce.
    priority: typeof detail.priority === 'string' ? detail.priority : detail.priority ? 'priority' : null,
    created_at: createdIso,
    updated_at: toIso(updatedRaw, createdIso),
    author,
    url: `https://app.intercom.com/a/inbox/${appId}/inbox/conversation/${id}`,
    parts,
    internal_notes: internalNotes,
  };
}

/**
 * Fetch a page of conversations + their detail records, normalized for the
 * backend ingest endpoint. Concurrency-limited so we don't hammer Intercom.
 *
 * `knownState` is the backend's `{ticket_id: updated_at}` map (from
 * `GET /tickets/sync-state`). A conversation already stored with a `last_updated`
 * no newer than the stored value is skipped entirely — no detail fetch, no
 * re-categorization. New + changed conversations still go through.
 *
 * Paginates the list (cursor `pages.next.starting_after`) so a workspace with
 * more than one page of new/changed open conversations is fully synced rather
 * than truncated at the first page. Summaries are newest-first, so once a full
 * page yields nothing new or changed every older conversation below is also
 * unchanged — that's the stop signal. `maxPages` is a runaway guard; hitting it
 * is logged (never a silent truncation).
 *
 * Returns only the conversations that were fetched (the changed ones). The
 * skipped tickets keep their existing stored row untouched.
 */
export async function fetchHydratedBatch({
  appId,
  state = 'open',
  count = 40,
  concurrency = 4,
  knownState = {},
  maxPages = 20,
}) {
  const results = [];
  let startingAfter = null;
  let pages = 0;
  let truncated = false;

  while (true) {
    if (pages >= maxPages) {
      truncated = true;
      break;
    }
    pages += 1;
    const { conversations: summaries, nextCursor } = await listConversations({
      appId,
      state,
      count,
      startingAfter,
    });
    if (summaries.length === 0) break;

    const out = new Array(summaries.length).fill(null);
    let cursor = 0;
    let sawNewOrChanged = false;

    async function worker() {
      while (true) {
        const i = cursor++;
        if (i >= summaries.length) return;
        const summary = summaries[i];
        // Skip a conversation we already have stored unchanged. The list call is
        // cheap; this avoids the per-conversation detail fetch + an AI call.
        const knownIso = knownState[String(summary.id)];
        if (knownIso) {
          const updMs = summaryUpdatedMs(summary);
          const knownMs = Date.parse(knownIso);
          if (updMs !== null && Number.isFinite(knownMs) && updMs <= knownMs) {
            continue; // leaves out[i] === null
          }
        }
        // New (not in knownState) or changed — this page is worth a next page.
        sawNewOrChanged = true;
        try {
          const detail = await getConversation(appId, summary.id);
          out[i] = normalizeConversation(detail, appId, summary);
        } catch (err) {
          // Auth errors must bubble so the popup can surface the "log in" hint.
          if (err instanceof IntercomSessionError && (err.status === 401 || err.status === 403)) {
            throw err;
          }
          console.warn(`[intercom] skipped conversation ${summary.id}:`, err?.message ?? err);
          // out[i] stays null; the .filter() below drops it from the result.
        }
      }
    }

    await Promise.all(Array.from({ length: Math.min(concurrency, summaries.length) }, worker));
    for (const t of out) if (t !== null) results.push(t);

    // Newest-first: a whole page with nothing new/changed means everything
    // older is unchanged too. A brand-new conversation is never skip-known, so
    // it can't hide below an all-skipped page (new activity sorts to the top).
    if (!sawNewOrChanged || !nextCursor) break;
    startingAfter = nextCursor;
  }

  if (truncated) {
    console.warn(
      `[intercom] fetchHydratedBatch hit the ${maxPages}-page cap for state=${state} — ` +
        'some older new/changed conversations were not synced this pass.',
    );
  }

  return results;
}

/**
 * Fetch closed conversations until every id in `wanted` is found or we fall
 * past `oldestUnixSeconds` (the lookback floor). Returns the subset whose
 * ids are in `wanted`.
 *
 * Used by the sync flow to detect Intercom-closed transitions for tickets
 * we previously had as open.
 *
 * @param {object} opts
 * @param {string} opts.appId            Workspace `app_id`.
 * @param {string[]} opts.wanted         Conversation ids to search for.
 * @param {number} opts.oldestUnixSeconds Stop paginating once we reach this epoch.
 */
export async function listClosedConversations({ appId, wanted, oldestUnixSeconds }) {
  const found = [];
  let starting_after = null;
  const wantedSet = new Set(wanted);
  while (wantedSet.size > 0) {
    const params = {
      app_id: appId,
      inbox_type: 'all',
      sort_field: 'sorting_updated_at',
      sort_direction: 'desc',
      state: 'closed',
      count: 50,
      'fields[]': 'attributes',
    };
    if (starting_after) params.starting_after = starting_after;

    let body;
    try {
      body = await requestJson('/ember/inbox/conversations/list', params);
    } catch (err) {
      // Auth errors bubble; network errors end the pass early (best-effort).
      if (err instanceof IntercomSessionError && (err.status === 401 || err.status === 403)) {
        throw err;
      }
      break;
    }

    const convos = Array.isArray(body?.conversations) ? body.conversations : [];
    if (convos.length === 0) break;

    let oldestOnPage = Infinity;
    for (const c of convos) {
      // Intercom's list timestamps can be ISO strings or unix seconds.
      const raw = c.updated_at ?? c.sorting_updated_at ?? c.last_updated;
      let ts = Infinity;
      if (typeof raw === 'number' && Number.isFinite(raw)) {
        ts = raw;
      } else if (typeof raw === 'string' && raw) {
        const ms = Date.parse(raw);
        if (!Number.isNaN(ms)) ts = Math.floor(ms / 1000);
      }
      oldestOnPage = Math.min(oldestOnPage, ts);
      if (wantedSet.has(String(c.id))) {
        found.push(c);
        wantedSet.delete(String(c.id));
      }
    }

    if (oldestOnPage < oldestUnixSeconds) break;
    starting_after = body.pages?.next?.starting_after ?? null;
    if (!starting_after) break;
  }
  return found;
}

export { LOOKBACK_SECONDS };
export { IntercomSessionError };
