// Typed API client. Reference: tasks.md T030.
//
// Dev: requests hit `/api/*` and Vite proxies to `http://127.0.0.1:8000`.
// Prod: same-origin works because the operator opens the static build from
// the backend or behind a localhost reverse proxy.

import type {
  AppSettings,
  CategoriesResponse,
  Category,
  FilterSettings,
  Followup,
  HealthResponse,
  Ticket,
  TicketNote,
} from '@/types/api';

const BASE = '/api';

export class ApiError extends Error {
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
  // ── health ────────────────────────────────────────────────────────────────
  health: (): Promise<HealthResponse> => request('/health'),

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

  // ── tickets ───────────────────────────────────────────────────────────────
  fetchTickets: (filter: FilterSettings): Promise<Ticket[]> =>
    request('/tickets/fetch', { method: 'POST', body: JSON.stringify(filter) }),

  overrideCategory: (ticketId: string, categoryId: number) =>
    request<{ ok: true; category_id: number }>(`/tickets/${ticketId}/category`, {
      method: 'PATCH',
      body: JSON.stringify({ category_id: categoryId }),
    }),

  // ── settings ──────────────────────────────────────────────────────────────
  getSettings: (): Promise<AppSettings> => request('/settings'),
  putSettings: (s: AppSettings): Promise<AppSettings> =>
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

  // ── notes (T047) ──────────────────────────────────────────────────────────
  listNotes: (): Promise<TicketNote[]> => request('/notes'),
  putNote: (ticketId: string, body: string) =>
    request<TicketNote | { ok: true; deleted: true }>(`/notes/${ticketId}`, {
      method: 'PUT',
      body: JSON.stringify({ body }),
    }),
};
