// ResolutionChip spec — renders correct variant per resolved_source +
// resolution_chip_state. Reference: spec §10.2, T107.

import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ResolutionChip from './ResolutionChip.vue';
import type { NonActionableKind, Ticket } from '@/types/api';

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
    non_actionable_kind: null,
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
    resolved_by: null,
    acted_by: null,
    assigned_to: null,
    assigned_at: null,
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

describe('ResolutionChip — non-actionable kind label (T107)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('shows kind label when non_actionable_kind is set', () => {
    const w = mount(ResolutionChip, {
      props: {
        ticket: base({
          resolved_at: NOW,
          resolved_source: 'non_actionable',
          non_actionable_kind: 'spam',
        }),
      },
    });
    expect(w.text()).toContain('Non-actionable · Spam');
  });

  it('shows plain Non-actionable when non_actionable_kind is null', () => {
    const w = mount(ResolutionChip, {
      props: {
        ticket: base({
          resolved_at: NOW,
          resolved_source: 'non_actionable',
          non_actionable_kind: null,
        }),
      },
    });
    const text = w.text();
    expect(text).toContain('Non-actionable');
    expect(text).not.toContain('·');
  });

  it('renders correct labels for all five kinds', () => {
    const cases: Array<[NonActionableKind, string]> = [
      ['auto_reply', 'Auto-reply'],
      ['thanks', 'Thanks'],
      ['spam', 'Spam'],
      ['out_of_office', 'Out of office'],
      ['other', 'Other'],
    ];
    for (const [kind, label] of cases) {
      const w = mount(ResolutionChip, {
        props: {
          ticket: base({
            resolved_at: NOW,
            resolved_source: 'non_actionable',
            non_actionable_kind: kind,
          }),
        },
      });
      expect(w.text()).toContain(`Non-actionable · ${label}`);
    }
  });

  it('does not render the kind chip for non-non_actionable resolved tickets', () => {
    const w = mount(ResolutionChip, {
      props: {
        ticket: base({
          resolved_at: NOW,
          resolved_source: 'manual',
          non_actionable_kind: null,
        }),
      },
    });
    expect(w.find('.resolution-chip').exists()).toBe(false);
  });
});
