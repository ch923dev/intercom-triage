// Typed API client. Reference: tasks.md T030.
//
// Dev: requests hit `/api/*` and Vite proxies to `http://127.0.0.1:8000`.
// Prod: same-origin works because the operator opens the static build from
// the backend or behind a localhost reverse proxy.

import type {
  CategoriesResponse,
  Category,
  FilterSettings,
  Followup,
  ProposalsResponse,
  ResolvedSource,
  Ticket,
  TicketNote,
} from '@/types/api';

const BASE = '/api';

class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(BASE + path, {
    headers: { 'content-type': 'application/json', ...(init.headers ?? {}) },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body, `${init.method ?? 'GET'} ${path} → ${resp.status}`);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  // ── categories ────────────────────────────────────────────────────────────
  listCategories: (): Promise<CategoriesResponse> => request('/categories'),

  createCategory: (body: Pick<Category, 'name' | 'description'> & Partial<Category>) =>
    request<Category>('/categories', { method: 'POST', body: JSON.stringify(body) }),

  patchCategory: (id: number, body: Partial<Category>) =>
    request<Category>(`/categories/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  archiveCategory: (id: number) =>
    request<{ ok: true }>(`/categories/${id}/archive`, { method: 'POST' }),

  mergeCategory: (src: number, dst: number) =>
    request<{ ok: true; moved_count: number }>(`/categories/${src}/merge-into/${dst}`, {
      method: 'POST',
    }),

  // ── proposals ─────────────────────────────────────────────────────────────
  listProposals: (): Promise<ProposalsResponse> => request('/proposals'),

  approveProposal: (id: number, body: { color?: string | null; sort_order?: number | null } = {}) =>
    request<Category>(`/proposals/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  mergeProposal: (id: number, categoryId: number) =>
    request<{ ok: true; moved_count: number }>(`/proposals/${id}/merge-into/${categoryId}`, {
      method: 'POST',
    }),

  rejectProposal: (id: number) =>
    request<{ ok: true }>(`/proposals/${id}/reject`, { method: 'POST' }),

  // ── tickets ───────────────────────────────────────────────────────────────
  /** The stored board — extension-ingested + categorized tickets.
   *  Pass `resolved: true` to fetch the resolved column; `false` for open only
   *  (default: open only, matching server default). */
  listTickets: (opts: { resolved?: boolean } = {}): Promise<Ticket[]> => {
    const qs = opts.resolved === undefined ? '' : `?resolved=${opts.resolved}`;
    return request(`/tickets${qs}`);
  },

  overrideCategory: (ticketId: string, categoryId: number) =>
    request<{ ok: true; category_id: number }>(`/tickets/${ticketId}/category`, {
      method: 'PATCH',
      body: JSON.stringify({ category_id: categoryId }),
    }),

  /** Operator-editable title + summary. Omit a field to leave it unchanged;
   *  pass `""` (empty string) to clear the override and let the next sync
   *  restore the AI/Intercom-derived value. */
  editTicket: (ticketId: string, body: { title?: string; summary?: string }) =>
    request<{ ok: true }>(`/tickets/${ticketId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  // ── settings ──────────────────────────────────────────────────────────────
  // The backend `/settings` row carries only the filter shape (plan §4); UI
  // tweaks (dark mode, accent, density) stay client-side until T049.
  getSettings: (): Promise<FilterSettings> => request('/settings'),
  putSettings: (s: FilterSettings): Promise<FilterSettings> =>
    request('/settings', { method: 'PUT', body: JSON.stringify(s) }),

  // ── followups (Phase 10 — T046) ───────────────────────────────────────────
  listFollowups: (): Promise<Followup[]> => request('/followups'),
  setFollowup: (ticketId: string, body: { due_at: string; reason?: string | null }) =>
    request<Followup>(`/followups/${ticketId}`, { method: 'PUT', body: JSON.stringify(body) }),
  snoozeFollowup: (ticketId: string, minutes: number) =>
    request<Followup>(`/followups/${ticketId}/snooze`, {
      method: 'POST',
      body: JSON.stringify({ minutes }),
    }),
  markFollowupFired: (ticketId: string) =>
    request<{ ok: true }>(`/followups/${ticketId}/mark-fired`, { method: 'POST' }),
  clearFollowup: (ticketId: string) =>
    request<{ ok: true }>(`/followups/${ticketId}`, { method: 'DELETE' }),

  // ── resolution (T011/T012) ────────────────────────────────────────────────
  /** Manually resolve a ticket. Returns the stamped resolved_at + source. */
  resolveTicket: (ticketId: string): Promise<{ resolved_at: string; resolved_source: ResolvedSource }> =>
    request(`/tickets/${ticketId}/resolve`, { method: 'POST', body: '{}' }),

  /** Reopen a resolved ticket. */
  reopenTicket: (ticketId: string): Promise<void> =>
    request(`/tickets/${ticketId}/reopen`, { method: 'POST' }),

  /** Set (or clear) the per-ticket AI-resolve override.
   *  Pass `null` to inherit `settings.ai_resolve_default`. */
  setAiResolve: (ticketId: string, enabled: boolean | null): Promise<void> =>
    request(`/tickets/${ticketId}/ai-resolve`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),

  /** Suppress the resolution chip until the ticket is updated again. */
  dismissChip: (ticketId: string): Promise<void> =>
    request(`/tickets/${ticketId}/dismiss-chip`, { method: 'POST' }),

  // ── notes (T047) ──────────────────────────────────────────────────────────
  listNotes: (): Promise<TicketNote[]> => request('/notes'),
  putNote: (ticketId: string, body: string) =>
    request<TicketNote | { ok: true; deleted: true }>(`/notes/${ticketId}`, {
      method: 'PUT',
      body: JSON.stringify({ body }),
    }),
};
