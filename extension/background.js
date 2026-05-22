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
import { fetchHydratedBatch, getAppId, IntercomSessionError } from './intercom.js';

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
  const hydrated = batches.flat();
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
  } catch {
    // Backend down or Intercom session expired — leave the last badge value
    // alone. The popup surfaces actionable errors when the operator opens it.
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
