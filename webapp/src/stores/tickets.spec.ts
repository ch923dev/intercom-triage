// Tickets-store spec — covers markNonActionable + bulkMarkNonActionable
// optimistic + rollback. Reference:
// docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md §10.2.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useTicketsStore } from './tickets';
import type { Ticket } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    markNonActionable: vi.fn(),
    bulkMarkNonActionable: vi.fn(),
    resolveTicket: vi.fn(),
    reopenTicket: vi.fn(),
    bulkResolve: vi.fn(),
    bulkReopen: vi.fn(),
    bulkRecategorize: vi.fn(),
    bulkDismissChip: vi.fn(),
    setAiResolve: vi.fn(),
    dismissChip: vi.fn(),
    overrideCategory: vi.fn(),
    editTicket: vi.fn(),
    listTickets: vi.fn(),
  },
}));

const NOW = '2026-05-25T00:00:00.000Z';

function fakeTicket(id: string, overrides: Partial<Ticket> = {}): Ticket {
  return {
    id,
    title: `t-${id}`,
    state: 'open',
    priority: null,
    created_at: NOW,
    updated_at: NOW,
    author: { id: null, name: null, email: null, type: 'user' },
    url: null,
    parts: [],
    internal_notes: [],
    category_id: 1,
    proposal_id: null,
    summary: '',
    ai_confidence: 0,
    user_override: false,
    title_user_edited: false,
    summary_user_edited: false,
    followup: null,
    note: null,
    resolved_at: null,
    resolved_source: null,
    ai_resolve_enabled: false,
    ai_resolve_override: null,
    ai_resolution_verdict: null,
    ai_resolution_confidence: null,
    ai_resolution_reason: null,
    resolution_chip_state: null,
    ...overrides,
  };
}

describe('ticketsStore.markNonActionable', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('moves the ticket to resolvedTickets with non_actionable source', async () => {
    const { api } = await import('@/api/client');
    (api.markNonActionable as ReturnType<typeof vi.fn>).mockResolvedValue({
      resolved_at: NOW,
      resolved_source: 'non_actionable',
    });
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    await s.markNonActionable('a');

    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    const moved = s.resolvedTickets.find((t) => t.id === 'a');
    expect(moved).toBeDefined();
    expect(moved!.resolved_source).toBe('non_actionable');
  });

  it('rolls back on API failure', async () => {
    const { api } = await import('@/api/client');
    (api.markNonActionable as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('b'));

    await expect(s.markNonActionable('b')).rejects.toThrow('boom');
    expect(s.tickets.find((t) => t.id === 'b')).toBeDefined();
    expect(s.resolvedTickets.find((t) => t.id === 'b')).toBeUndefined();
  });
});

describe('ticketsStore.resolved getters', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('splits resolvedTickets by source into pureResolvedTickets + nonActionableTickets', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('m', { resolved_at: NOW, resolved_source: 'manual' }),
      fakeTicket('n', { resolved_at: NOW, resolved_source: 'non_actionable' }),
      fakeTicket('i', { resolved_at: NOW, resolved_source: 'intercom_closed' }),
    );

    expect(s.pureResolvedTickets.map((t) => t.id).sort()).toEqual(['i', 'm']);
    expect(s.nonActionableTickets.map((t) => t.id)).toEqual(['n']);
  });
});

describe('ticketsStore.bulkMarkNonActionable', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('moves every ok id and rolls back failed ids', async () => {
    const { api } = await import('@/api/client');
    (api.bulkMarkNonActionable as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok_ids: ['x', 'z'],
      failed: [{ id: 'y', reason: 'already resolved' }],
    });
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('x'), fakeTicket('y'), fakeTicket('z'));

    const result = await s.bulkMarkNonActionable(['x', 'y', 'z']);

    expect(result.ok_ids).toEqual(['x', 'z']);
    expect(s.resolvedTickets.map((t) => t.id).sort()).toEqual(['x', 'z']);
    expect(s.tickets.find((t) => t.id === 'y')).toBeDefined();
  });
});
