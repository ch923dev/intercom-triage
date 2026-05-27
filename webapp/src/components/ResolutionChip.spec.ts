// ResolutionChip spec — renders correct variant per resolved_source +
// resolution_chip_state. Reference: spec §10.2.

import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ResolutionChip from './ResolutionChip.vue';
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
    ai_priority: null,
    ai_sentiment: null,
    ai_labels: [],
    parked_at: null,
    parked_until: null,
    parked_reason: null,
    ...overrides,
  };
}

describe('ResolutionChip', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('renders nothing for an open ticket with no chip state', () => {
    const w = mount(ResolutionChip, { props: { ticket: base() } });
    expect(w.find('.resolution-chip').exists()).toBe(false);
  });

  it('renders nothing for a resolved non-actionable ticket (column conveys source)', () => {
    const w = mount(ResolutionChip, {
      props: {
        ticket: base({ resolved_at: NOW, resolved_source: 'non_actionable' }),
      },
    });
    expect(w.find('.resolution-chip').exists()).toBe(false);
  });

  it('renders the advisory chip when resolution_chip_state is set', () => {
    const w = mount(ResolutionChip, {
      props: {
        ticket: base({
          resolution_chip_state: 'ai_resolved',
          ai_resolution_confidence: 0.81,
        }),
      },
    });
    expect(w.text()).toContain('AI: resolved?');
    expect(w.text()).toContain('0.81');
  });
});
