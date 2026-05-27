// webapp/src/stores/tickets.parked.spec.ts
import { setActivePinia, createPinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTicketsStore } from '@/stores/tickets';
import { api } from '@/api/client';
import type { Ticket } from '@/types/api';

function ticket(id: string, over: Partial<Ticket> = {}): Ticket {
  return {
    id,
    title: id,
    state: 'open',
    priority: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    author: {
      name: 'C',
      email: null,
      id: null,
      type: 'user',
      location: null,
      timezone: null,
      phone: null,
      company: null,
    },
    url: null,
    parts: [],
    internal_notes: [],
    category_id: 1,
    proposal_id: null,
    summary: '',
    ai_confidence: 0.9,
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
    ai_priority: null,
    ai_sentiment: null,
    ai_labels: [],
    parked_at: null,
    parked_until: null,
    parked_reason: null,
    parked_note: null,
    ...over,
  } as Ticket;
}

describe('tickets store — parked', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('parked tickets drop out of category columns and into parkedTickets', () => {
    const store = useTicketsStore();
    const future = new Date(Date.now() + 3_600_000).toISOString();
    store.tickets.push(ticket('open-1'));
    store.tickets.push(
      ticket('parked-1', {
        parked_at: '2026-01-01T00:00:00Z',
        parked_until: future,
        parked_reason: 'other',
      }),
    );
    // byCategory excludes parked
    const col = store.byCategory.get(1) ?? [];
    expect(col.map((t) => t.id)).toEqual(['open-1']);
    expect(store.parkedTickets.map((t) => t.id)).toEqual(['parked-1']);
    expect(store.readyParkedCount).toBe(0);
  });

  it('readyParkedCount counts tickets whose parked_until has passed', () => {
    const store = useTicketsStore();
    const past = new Date(Date.now() - 1000).toISOString();
    store.tickets.push(
      ticket('ready-1', {
        parked_at: '2026-01-01T00:00:00Z',
        parked_until: past,
        parked_reason: 'other',
      }),
    );
    expect(store.readyParkedCount).toBe(1);
  });

  it('parkTicket sets the trio optimistically and calls the api', async () => {
    const store = useTicketsStore();
    store.tickets.push(ticket('p-1'));
    const spy = vi.spyOn(api, 'parkTicket').mockResolvedValue({
      parked_at: 'x',
      parked_until: 'y',
      parked_reason: 'other',
      parked_note: 'vendor delay',
    });
    const future = new Date(Date.now() + 3_600_000).toISOString();
    await store.parkTicket('p-1', future, 'other', 'vendor delay');
    expect(spy).toHaveBeenCalledWith('p-1', future, 'other', 'vendor delay');
    const parked = store.tickets.find((t) => t.id === 'p-1')!;
    expect(parked.parked_at).not.toBeNull();
    expect(parked.parked_note).toBe('vendor delay');
  });

  it('parkTicket rolls back the trio on api failure', async () => {
    const store = useTicketsStore();
    store.tickets.push(ticket('p-2'));
    vi.spyOn(api, 'parkTicket').mockRejectedValue(new Error('boom'));
    const future = new Date(Date.now() + 3_600_000).toISOString();
    await expect(store.parkTicket('p-2', future, 'other')).rejects.toThrow('boom');
    expect(store.tickets.find((t) => t.id === 'p-2')!.parked_at).toBeNull();
  });

  it('unparkTicket clears the trio optimistically', async () => {
    const store = useTicketsStore();
    const future = new Date(Date.now() + 3_600_000).toISOString();
    store.tickets.push(
      ticket('u-1', {
        parked_at: '2026-01-01T00:00:00Z',
        parked_until: future,
        parked_reason: 'other',
      }),
    );
    vi.spyOn(api, 'unparkTicket').mockResolvedValue(undefined);
    await store.unparkTicket('u-1');
    expect(store.tickets.find((t) => t.id === 'u-1')!.parked_at).toBeNull();
  });
});
