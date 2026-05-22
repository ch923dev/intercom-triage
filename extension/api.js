// Shared backend client for the popup and the background service worker.
// Reference: plan.md §2 — the extension calls the same localhost backend as
// the webapp. The backend binds 127.0.0.1:8000 and allows the
// chrome-extension:// origin via CORS.

export const API_BASE = 'http://127.0.0.1:8000';
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
    throw new ApiError(0, 'Backend unreachable — is it running on :8000?');
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, `${init.method ?? 'GET'} ${path} → ${resp.status}`);
  }
  return resp.status === 204 ? undefined : resp.json();
}

/** Stored filter settings — used verbatim as the `/tickets/fetch` body. */
export const fetchSettings = () => request('/settings');

/** Active categories + pending proposals. */
export const fetchCategories = () => request('/categories');

/** Hydrated + categorized tickets for the given filter. */
export const fetchTickets = (filter) =>
  request('/tickets/fetch', { method: 'POST', body: JSON.stringify(filter) });

/** Override a ticket's category. The backend persists it as an Override row,
 *  so the change survives the popup closing and the next fetch. */
export const overrideCategory = (ticketId, categoryId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/category`, {
    method: 'PATCH',
    body: JSON.stringify({ category_id: categoryId }),
  });
