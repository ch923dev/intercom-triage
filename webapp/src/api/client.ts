// Typed API client. Reference: tasks.md T030.
//
// Dev: requests hit `/api/*` and Vite proxies to `http://127.0.0.1:4000`.
// Prod: same-origin works because the operator opens the static build from
// the backend or behind a localhost reverse proxy.

import type {
  BulkResult,
  CategoriesResponse,
  Category,
  DraftReply,
  FilterSettings,
  Followup,
  MetricsResponse,
  NoteAttachment,
  NoteEntry,
  Playbook,
  ProposalsResponse,
  ResolvedSource,
  Snippet,
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
  resolveTicket: (
    ticketId: string,
  ): Promise<{ resolved_at: string; resolved_source: ResolvedSource }> =>
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

  /** Mark a ticket non-actionable. 409 if already resolved, 404 if unknown. */
  markNonActionable: (
    ticketId: string,
  ): Promise<{ resolved_at: string; resolved_source: ResolvedSource }> =>
    request(`/tickets/${ticketId}/non-actionable`, { method: 'POST', body: '{}' }),

  // ── notes (T047) ──────────────────────────────────────────────────────────
  listNotes: (): Promise<TicketNote[]> => request('/notes'),
  putNote: (ticketId: string, body: string) =>
    request<TicketNote | { ok: true; deleted: true }>(`/notes/${ticketId}`, {
      method: 'PUT',
      body: JSON.stringify({ body }),
    }),

  // ── note entries (time-tabled notes) ──────────────────────────────────────
  listNoteEntries: (): Promise<NoteEntry[]> => request('/notes/entries'),

  listNoteEntriesForTicket: (ticketId: string): Promise<NoteEntry[]> =>
    request(`/notes/entries/${ticketId}`),

  addNoteEntry: (body: {
    ticket_id: string;
    body: string;
    timer_min?: number | null;
    reason?: string | null;
  }): Promise<NoteEntry> =>
    request('/notes/entries', { method: 'POST', body: JSON.stringify(body) }),

  deleteNoteEntry: (entryId: number): Promise<{ ok: true; deleted: true; id: number }> =>
    request(`/notes/entries/${entryId}`, { method: 'DELETE' }),

  // ── attachments (note attachments) ────────────────────────────────────────
  listAttachments: (ticketId: string): Promise<NoteAttachment[]> =>
    request(`/attachments?ticket_id=${encodeURIComponent(ticketId)}`),

  uploadAttachment: (
    file: File,
    ownerKind: 'entry' | 'ticket',
    ownerId: string,
    ticketId: string,
  ): Promise<NoteAttachment> => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('owner_kind', ownerKind);
    fd.append('owner_id', ownerId);
    fd.append('ticket_id', ticketId);
    // Cannot use `request()` directly — multipart needs no `content-type` header
    // (browser sets the boundary). Replicate the error envelope manually.
    return fetch(`${BASE}/attachments`, { method: 'POST', body: fd }).then(async (resp) => {
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new ApiError(resp.status, body, `POST /attachments → ${resp.status}`);
      }
      return resp.json();
    });
  },

  deleteAttachment: (id: number): Promise<{ ok: true; deleted: true; id: number }> =>
    request(`/attachments/${id}`, { method: 'DELETE' }),

  // ── bulk actions (Phase 12 — plan §8d) ────────────────────────────────────
  /** Mark N tickets manually resolved. Per-id ok/failed in the response. */
  bulkResolve: (ticketIds: string[]): Promise<BulkResult> =>
    request('/tickets/bulk/resolve', {
      method: 'POST',
      body: JSON.stringify({ ticket_ids: ticketIds }),
    }),

  /** Reopen N resolved tickets. */
  bulkReopen: (ticketIds: string[]): Promise<BulkResult> =>
    request('/tickets/bulk/reopen', {
      method: 'POST',
      body: JSON.stringify({ ticket_ids: ticketIds }),
    }),

  /** Assign one category to N tickets via override rows. */
  bulkRecategorize: (ticketIds: string[], categoryId: number): Promise<BulkResult> =>
    request('/tickets/bulk/category', {
      method: 'PATCH',
      body: JSON.stringify({ ticket_ids: ticketIds, category_id: categoryId }),
    }),

  /** Suppress the resolution chip on N tickets. */
  bulkDismissChip: (ticketIds: string[]): Promise<BulkResult> =>
    request('/tickets/bulk/dismiss-chip', {
      method: 'POST',
      body: JSON.stringify({ ticket_ids: ticketIds }),
    }),

  /** Mark N tickets non-actionable. Per-id ok/failed in the response. */
  bulkMarkNonActionable: (ticketIds: string[]): Promise<BulkResult> =>
    request('/tickets/bulk/non-actionable', {
      method: 'POST',
      body: JSON.stringify({ ticket_ids: ticketIds }),
    }),

  /** Set the same follow-up `due_at` + reason on N tickets. */
  bulkSetFollowup: (
    ticketIds: string[],
    body: { due_at: string; reason?: string | null },
  ): Promise<BulkResult> =>
    request('/followups/bulk', {
      method: 'PUT',
      body: JSON.stringify({ ticket_ids: ticketIds, ...body }),
    }),

  /** Clear follow-ups on N tickets. Idempotent. */
  bulkClearFollowup: (ticketIds: string[]): Promise<BulkResult> =>
    request('/followups/bulk', {
      method: 'DELETE',
      body: JSON.stringify({ ticket_ids: ticketIds }),
    }),

  // ── playbooks ─────────────────────────────────────────────────────────────
  listPlaybooks: (
    opts: { ticketId?: string; categoryId?: number; includeArchived?: boolean } = {},
  ): Promise<Playbook[]> => {
    const qs = new URLSearchParams();
    if (opts.ticketId !== undefined) qs.set('ticket_id', opts.ticketId);
    if (opts.categoryId !== undefined) qs.set('category_id', String(opts.categoryId));
    if (opts.includeArchived) qs.set('include_archived', 'true');
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request(`/playbooks${suffix}`);
  },

  createPlaybook: (body: {
    category_id: number;
    label: string;
    body: string;
    source_ticket_id?: string | null;
  }): Promise<Playbook> => request('/playbooks', { method: 'POST', body: JSON.stringify(body) }),

  updatePlaybook: (id: number, body: { label?: string; body?: string }): Promise<Playbook> =>
    request(`/playbooks/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  archivePlaybook: (id: number): Promise<{ ok: true }> =>
    request(`/playbooks/${id}/archive`, { method: 'POST' }),

  restorePlaybook: (id: number): Promise<{ ok: true }> =>
    request(`/playbooks/${id}/restore`, { method: 'POST' }),

  draftPlaybook: (ticketId: string): Promise<{ body: string }> =>
    request('/playbooks/draft', { method: 'POST', body: JSON.stringify({ ticket_id: ticketId }) }),

  // RAG draft reply (roadmap 2.6): grounds an ephemeral customer reply in
  // similar resolved tickets + effective-category playbooks.
  draftReply: (ticketId: string): Promise<DraftReply> =>
    request('/playbooks/draft-reply', {
      method: 'POST',
      body: JSON.stringify({ ticket_id: ticketId }),
    }),

  // ── metrics (roadmap 1.4 — token / cost meter) ────────────────────────────
  /** Process-lifetime counters + per-day OpenRouter spend. */
  getMetrics: (): Promise<MetricsResponse> => request('/metrics'),

  // ── snippets (roadmap 1.5) ──────────────────────────────────────────────────
  listSnippets: (opts: { includeArchived?: boolean } = {}): Promise<Snippet[]> => {
    const qs = new URLSearchParams();
    if (opts.includeArchived) qs.set('include_archived', 'true');
    const suffix = qs.toString() ? `?${qs}` : '';
    return request(`/snippets${suffix}`);
  },

  createSnippet: (body: { title: string; body: string }): Promise<Snippet> =>
    request('/snippets', { method: 'POST', body: JSON.stringify(body) }),

  updateSnippet: (id: number, body: { title?: string; body?: string }): Promise<Snippet> =>
    request(`/snippets/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  archiveSnippet: (id: number): Promise<{ ok: true }> =>
    request(`/snippets/${id}/archive`, { method: 'POST' }),

  restoreSnippet: (id: number): Promise<{ ok: true }> =>
    request(`/snippets/${id}/restore`, { method: 'POST' }),
};
