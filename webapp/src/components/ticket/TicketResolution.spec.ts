// TicketResolution flyout spec — Mark-non-actionable button visibility
// per ticket state. Reference: spec §10.2.

import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import TicketResolution from './TicketResolution.vue';
import type { Ticket } from '@/types/api';

const NOW = '2026-05-25T00:00:00.000Z';

function base(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 't1',
    title: 'x',
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
    ...overrides,
  };
}

describe('TicketResolution', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('shows Mark non-actionable + Mark resolved on an open ticket', () => {
    const w = mount(TicketResolution, { props: { ticket: base() } });
    expect(w.text()).toContain('Mark non-actionable');
    expect(w.text()).toContain('Mark resolved');
    expect(w.text()).not.toContain('Reopen');
  });

  it('shows only Reopen on a resolved ticket', () => {
    const w = mount(TicketResolution, {
      props: {
        ticket: base({ resolved_at: NOW, resolved_source: 'non_actionable' }),
      },
    });
    expect(w.text()).toContain('Reopen');
    expect(w.text()).not.toContain('Mark non-actionable');
    expect(w.text()).not.toContain('Mark resolved');
  });

  it('renders non-actionable status pill copy', () => {
    const w = mount(TicketResolution, {
      props: {
        ticket: base({ resolved_at: NOW, resolved_source: 'non_actionable' }),
      },
    });
    expect(w.text()).toContain('Non-actionable');
  });
});
