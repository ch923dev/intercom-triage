// Background service worker — optional Intercom poll + toolbar badge.
// Reference: tasks.md T042 — US-006; ingest pivot (Slice B).
//
// Polling is OFF by default. When the operator picks an interval in the popup,
// `pollMinutes` is written to chrome.storage.local and we register a
// chrome.alarms alarm. Each tick:
//   1. Pulls a batch from the operator's Intercom session (if a workspace id
//      is configured) and POSTs it to `/tickets/ingest`.
//   2. Reads the stored board from `/tickets` and writes the Urgent count
//      onto the action badge.
// Interval "Off" clears the alarm and the badge — no background calls.

import {
  fetchCategories,
  fetchSettings,
  getStoredTickets,
  getSyncState,
  ingestTickets,
} from './api.js';
import {
  fetchHydratedBatch,
  getAppId,
  getConversation,
  IntercomSessionError,
  listClosedConversations,
  LOOKBACK_SECONDS,
  normalizeConversation,
} from './intercom.js';

const ALARM = 'triage-poll';
const BADGE_COLOR = '#ff4d2e';

/** Pull from Intercom + ingest (best-effort — a stale badge is better than no badge). */
async function ingestFromIntercom(settings) {
  const appId = await getAppId();
  if (!appId) return; // operator hasn't set the workspace yet
  const states = settings.states?.length ? settings.states : ['open'];
  // Skip Intercom detail fetches for conversations already stored unchanged.
  const knownState = await getSyncState().catch(() => ({}));
  const batches = await Promise.all(
    states.map((state) =>
      fetchHydratedBatch({ appId, state, count: 60, concurrency: 4, knownState }).catch((e) => {
        // Session expired / not signed in is the only failure worth surfacing;
        // any other error just leaves the stored board unchanged for this tick.
        if (e instanceof IntercomSessionError && (e.status === 401 || e.status === 403)) {
          throw e;
        }
        return [];
      }),
    ),
  );
  const openConvos = batches.flat();

  // ── Closure pass ────────────────────────────────────────────────────────────
  // Any ticket tracked in the backend but absent from the open list may have
  // flipped to closed. We search the Intercom closed list for those ids; any
  // found are hydrated and included in the ingest so _upsert_ticket can stamp
  // the open→closed transition (resolved_at / resolved_source='intercom_closed').
  const openIds = new Set(openConvos.map((c) => c.id));
  const trackedIds = Object.keys(knownState);
  const candidateClosedIds = trackedIds.filter((id) => !openIds.has(id));

  let closedHydrated = [];
  if (candidateClosedIds.length > 0) {
    const oldestUnixSeconds = Math.floor(Date.now() / 1000) - LOOKBACK_SECONDS;
    const closedSummaries = await listClosedConversations({
      appId,
      wanted: candidateClosedIds,
      oldestUnixSeconds,
    }).catch((e) => {
      if (e instanceof IntercomSessionError && (e.status === 401 || e.status === 403)) throw e;
      return [];
    });

    // Hydrate each found closed conversation the same way as open ones.
    const concurrency = 4;
    const out = new Array(closedSummaries.length).fill(null);
    let cursor = 0;
    async function hydrateWorker() {
      while (true) {
        const i = cursor++;
        if (i >= closedSummaries.length) return;
        const summary = closedSummaries[i];
        try {
          const detail = await getConversation(appId, summary.id);
          out[i] = normalizeConversation(detail, appId, summary);
        } catch (err) {
          if (err instanceof IntercomSessionError && (err.status === 401 || err.status === 403)) {
            throw err;
          }
          console.warn(`[intercom] closure pass skipped ${summary.id}:`, err?.message ?? err);
        }
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(concurrency, closedSummaries.length) }, hydrateWorker),
    );
    closedHydrated = out.filter((t) => t !== null);
  }

  const hydrated = [...openConvos, ...closedHydrated];
  if (hydrated.length > 0) await ingestTickets(hydrated);
}

/** One poll cycle: ingest (if configured) + refresh the badge. */
async function poll() {
  try {
    const settings = await fetchSettings();
    await ingestFromIntercom(settings);

    const [catResp, tickets] = await Promise.all([fetchCategories(), getStoredTickets()]);
    const urgent = catResp.categories.find((c) => c.name.trim().toLowerCase() === 'urgent');
    const count = urgent ? tickets.filter((t) => t.category_id === urgent.id).length : 0;

    await chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR });
    await chrome.action.setBadgeText({ text: count > 0 ? String(count) : '' });
  } catch (e) {
    // An expired Intercom session is the one background failure worth a signal:
    // the operator gets no other feedback until they open the popup. Surface it
    // on the badge so re-auth is visible; a later successful tick overwrites '!'
    // with the Urgent count. Every other error (backend down, transient) leaves
    // the last badge value alone — the popup surfaces those when it's opened.
    if (e instanceof IntercomSessionError && (e.status === 401 || e.status === 403)) {
      await chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR });
      await chrome.action.setBadgeText({ text: '!' });
    }
  }
}

/** Re-read the configured interval and (re)arm or disarm the alarm. */
async function reschedule() {
  const { pollMinutes = 0 } = await chrome.storage.local.get('pollMinutes');
  await chrome.alarms.clear(ALARM);

  if (pollMinutes > 0) {
    chrome.alarms.create(ALARM, { periodInMinutes: pollMinutes });
    await poll(); // refresh immediately so the badge isn't stale until the first tick
  } else {
    await chrome.action.setBadgeText({ text: '' });
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) void poll();
});

chrome.runtime.onInstalled.addListener(() => void reschedule());
chrome.runtime.onStartup.addListener(() => void reschedule());

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'reschedule') {
    reschedule().then(() => sendResponse({ ok: true }));
    return true; // keep the channel open for the async response
  }
  return false;
});
