// BulkActionBar spec — Non-actionable button disabled when any selected ticket
// is already resolved. Reference: spec §10.2.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import BulkActionBar from './BulkActionBar.vue';
import { useSelectionStore } from '@/stores/selection';
import { useTicketsStore } from '@/stores/tickets';
import type { Ticket } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listTickets: vi.fn().mockResolvedValue([]),
    listCategories: vi.fn().mockResolvedValue({ categories: [], pending_proposals: [] }),
    listFollowups: vi.fn().mockResolvedValue([]),
  },
}));

const NOW = '2026-05-25T00:00:00.000Z';

function fake(id: string, overrides: Partial<Ticket> = {}): Ticket {
  return {
    id,
    title: id,
    state: 'open',
    priority: null,
    created_at: NOW,
    updated_at: NOW,
    author: {
      id: null,
      name: null,
      email: null,
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
    ai_priority: null,
    ai_sentiment: null,
    ai_labels: [],
    parked_at: null,
    parked_until: null,
    parked_reason: null,
    parked_note: null,
    non_actionable_kind: null,
    ...overrides,
  };
}

describe('BulkActionBar — Non-actionable button', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('is enabled when every selected ticket is open', () => {
    const selection = useSelectionStore();
    const tickets = useTicketsStore();
    tickets.tickets.push(fake('a'), fake('b'));
    selection.toggle('a', 'col1');
    selection.toggle('b', 'col1');

    const w = mount(BulkActionBar);
    const btn = w.findAll('button').find((b) => b.text() === 'Non-actionable');
    expect(btn).toBeDefined();
    expect(btn!.attributes('disabled')).toBeUndefined();
  });

  it('is disabled when any selected ticket is already resolved', () => {
    const selection = useSelectionStore();
    const tickets = useTicketsStore();
    tickets.tickets.push(fake('a'));
    tickets.resolvedTickets.push(fake('r', { resolved_at: NOW, resolved_source: 'manual' }));
    selection.toggle('a', 'col1');
    selection.toggle('r', 'resolved');

    const w = mount(BulkActionBar);
    const btn = w.findAll('button').find((b) => b.text() === 'Non-actionable');
    expect(btn).toBeDefined();
    expect(btn!.attributes('disabled')).toBeDefined();
  });
});
