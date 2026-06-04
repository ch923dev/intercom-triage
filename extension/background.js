// Background service worker — toolbar badge refresher.
// Reference: tasks.md T042 — US-006; backend-ingest pivot.
//
// The backend now polls Intercom directly (cross-package invariant #1 — the
// extension no longer has any Intercom access). This worker only mirrors the
// stored board's Urgent count onto the toolbar badge on the interval the
// operator picks in the popup footer. Polling is OFF by default.

import { fetchCategories, getStoredTickets } from './api.js';

const ALARM = 'triage-poll';
const BADGE_COLOR = '#ff4d2e';

/** One poll cycle: read the stored board + refresh the Urgent badge. */
async function poll() {
  try {
    const [catResp, tickets] = await Promise.all([fetchCategories(), getStoredTickets()]);
    const urgent = catResp.categories.find((c) => c.name.trim().toLowerCase() === 'urgent');
    const count = urgent ? tickets.filter((t) => t.category_id === urgent.id).length : 0;

    await chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR });
    await chrome.action.setBadgeText({ text: count > 0 ? String(count) : '' });
  } catch {
    // Backend down / transient — leave the last badge value alone; the popup
    // surfaces errors when it's opened. There is no Intercom session to re-auth.
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
