// Background service worker — optional polling + toolbar badge.
// Reference: tasks.md T042 — US-006.
//
// Polling is OFF by default. When the operator picks an interval in the popup,
// `pollMinutes` is written to chrome.storage.local and we register a
// chrome.alarms alarm. Each tick fetches the board and writes the Urgent count
// onto the action badge. Interval "Off" clears the alarm and the badge — no
// background calls happen.

import { fetchCategories, fetchSettings, fetchTickets } from './api.js';

const ALARM = 'triage-poll';
const BADGE_COLOR = '#ff4d2e';

/** Fetch the board once and reflect the Urgent count on the badge. */
async function poll() {
  try {
    const [settings, catResp] = await Promise.all([fetchSettings(), fetchCategories()]);
    const tickets = await fetchTickets(settings);

    const urgent = catResp.categories.find((c) => c.name.trim().toLowerCase() === 'urgent');
    const count = urgent ? tickets.filter((t) => t.category_id === urgent.id).length : 0;

    await chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR });
    await chrome.action.setBadgeText({ text: count > 0 ? String(count) : '' });
  } catch {
    // Backend down or degraded — leave the last badge value untouched.
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

// The popup sends this after the operator changes the interval.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'reschedule') {
    reschedule().then(() => sendResponse({ ok: true }));
    return true; // keep the channel open for the async response
  }
  return false;
});
