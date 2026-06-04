// Shared backend client for the popup and the background service worker.
// Reference: plan.md §2 — the extension calls the same localhost backend as
// the webapp. The backend binds 127.0.0.1:4000 and allows the
// chrome-extension:// origin via CORS.

export const API_BASE = 'http://127.0.0.1:4000';
export const FULL_BOARD_URL = 'http://localhost:5173/';

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, init = {}) {
  let resp;
  try {
    resp = await fetch(API_BASE + path, {
      headers: { 'content-type': 'application/json' },
      ...init,
    });
  } catch {
    throw new ApiError(0, 'Backend unreachable — is it running on :4000?');
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, `${init.method ?? 'GET'} ${path} → ${resp.status}`);
  }
  return resp.status === 204 ? undefined : resp.json();
}

/** Stored filter settings — drives the popup's lookback / state filters. */
export const fetchSettings = () => request('/settings');

/** Active categories + pending proposals. */
export const fetchCategories = () => request('/categories');

/** The stored board — fetched from Intercom + categorized by the backend. */
export const getStoredTickets = () => request('/tickets');

/** Override a ticket's category. The backend persists it as an Override row,
 *  so the change survives the popup closing and the next fetch. */
export const overrideCategory = (ticketId, categoryId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/category`, {
    method: 'PATCH',
    body: JSON.stringify({ category_id: categoryId }),
  });

/** Resolved tickets — `GET /tickets?resolved=true`. */
export const getResolvedTickets = () => request('/tickets?resolved=true');

/** Manually resolve a ticket. 409 if already resolved, 404 if unknown. */
export const resolveTicket = (ticketId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/resolve`, { method: 'POST' });

/** Reopen a previously-resolved ticket. 409 if already open, 404 if unknown. */
export const reopenTicket = (ticketId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/reopen`, { method: 'POST' });

/** Mark a ticket non-actionable. 409 if already resolved, 404 if unknown. */
export const markNonActionable = (ticketId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/non-actionable`, { method: 'POST' });

/** Park a ticket until `untilAt` (ISO with Z) with a structured reason.
 *  409 if resolved or already parked. */
export const parkTicket = (ticketId, untilAt, reason, note = null) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/park`, {
    method: 'POST',
    body: JSON.stringify({ until_at: untilAt, reason, note }),
  });

/** Unpark a ticket. 409 if not parked, 404 if unknown. */
export const unparkTicket = (ticketId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/unpark`, { method: 'POST' });

/** Active follow-up reminders — one row per ticket (T053). */
export const fetchFollowups = () => request('/followups');

/** Flag a follow-up's alarm as rung so reloads don't re-ring it. */
export const markFollowupFired = (ticketId) =>
  request(`/followups/${encodeURIComponent(ticketId)}/mark-fired`, { method: 'POST' });
