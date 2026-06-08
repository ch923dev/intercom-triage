// Bulk pre-flight diff unit tests (roadmap 1.6).
//
// The preview is computed client-side from already-loaded ticket states; the
// affect/skip rules must match the backend 409/no-op semantics in
// backend/app/services/bulk.py. These cases pin each rule incl. its skip case.

import { describe, expect, it } from 'vitest';
import { type BulkAction, bulkPreview, bulkPreviewLabel, MAX_BULK_IDS } from './bulkPreview';
import type { Ticket } from '@/types/api';

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
    resolved_by: null,
    acted_by: null,
    assigned_to: null,
    assigned_at: null,
    ...overrides,
  };
}

const resolved = (id: string) => fake(id, { resolved_at: NOW, resolved_source: 'manual' });

describe('bulkPreview — resolve / non_actionable', () => {
  it('affects open tickets, skips already-resolved ones', () => {
    const selected = [fake('a'), fake('b'), resolved('c')];
    for (const action of ['resolve', 'non_actionable'] as BulkAction[]) {
      const p = bulkPreview(action, selected);
      expect(p.willAffect).toBe(2);
      expect(p.willSkip).toBe(1);
    }
  });

  it('affects all when none are resolved', () => {
    const p = bulkPreview('resolve', [fake('a'), fake('b')]);
    expect(p.willAffect).toBe(2);
    expect(p.willSkip).toBe(0);
  });
});

describe('bulkPreview — reopen', () => {
  it('affects resolved tickets, skips open ones', () => {
    const selected = [resolved('a'), resolved('b'), fake('c')];
    const p = bulkPreview('reopen', selected);
    expect(p.willAffect).toBe(2);
    expect(p.willSkip).toBe(1);
  });
});

describe('bulkPreview — recategorize', () => {
  it('affects tickets not in the target, skips ones already there', () => {
    const selected = [
      fake('a', { category_id: 1 }),
      fake('b', { category_id: 2 }),
      fake('c', { category_id: 2 }),
    ];
    // Move to category 2: a changes, b & c already there.
    const p = bulkPreview('recategorize', selected, 2);
    expect(p.willAffect).toBe(1);
    expect(p.willSkip).toBe(2);
  });

  it('counts a null-category ticket as a change when target is set', () => {
    const selected = [fake('a', { category_id: null }), fake('b', { category_id: 5 })];
    const p = bulkPreview('recategorize', selected, 5);
    expect(p.willAffect).toBe(1); // only the null-category one changes
    expect(p.willSkip).toBe(1);
  });

  it('affects nothing when no target category is provided', () => {
    const p = bulkPreview('recategorize', [fake('a'), fake('b')], null);
    expect(p.willAffect).toBe(0);
    expect(p.willSkip).toBe(2);
  });
});

describe('bulkPreview — dismiss_chip / clear_followup', () => {
  it('dismiss_chip affects only tickets with a chip', () => {
    const selected = [fake('a', { resolution_chip_state: 'ai_resolved' }), fake('b')];
    const p = bulkPreview('dismiss_chip', selected);
    expect(p.willAffect).toBe(1);
    expect(p.willSkip).toBe(1);
  });

  it('clear_followup affects only tickets with a follow-up', () => {
    const followup = {
      ticket_id: 'a',
      due_at: NOW,
      reason: null,
      fired: false,
      created_at: NOW,
      updated_at: NOW,
    };
    const selected = [fake('a', { followup }), fake('b'), fake('c')];
    const p = bulkPreview('clear_followup', selected);
    expect(p.willAffect).toBe(1);
    expect(p.willSkip).toBe(2);
  });
});

describe('bulkPreview — cap (invariant #9)', () => {
  it('flags overCap when selection exceeds MAX_BULK_IDS, not at the cap', () => {
    const atCap = Array.from({ length: MAX_BULK_IDS }, (_, i) => fake(`t${i}`));
    expect(bulkPreview('resolve', atCap).overCap).toBe(false);

    const overCap = [...atCap, fake('extra')];
    expect(bulkPreview('resolve', overCap).overCap).toBe(true);
  });
});

describe('bulkPreviewLabel', () => {
  it('renders "N will <verb>" with no skip clause when nothing is skipped', () => {
    const p = bulkPreview('resolve', [fake('a'), fake('b')]);
    expect(bulkPreviewLabel('resolve', p)).toBe('2 will resolve');
  });

  it('appends the skip count + reason', () => {
    const p = bulkPreview('resolve', [fake('a'), resolved('b'), resolved('c')]);
    expect(bulkPreviewLabel('resolve', p)).toBe('1 will resolve, 2 skipped (already resolved)');
  });

  it('uses the per-action verb and skip reason', () => {
    const p = bulkPreview('recategorize', [fake('a', { category_id: 1 })], 1);
    expect(bulkPreviewLabel('recategorize', p)).toBe(
      '0 will change category, 1 skipped (already in target)',
    );
  });

  it('appends the over-cap note when the selection exceeds the cap', () => {
    const overCap = Array.from({ length: MAX_BULK_IDS + 1 }, (_, i) => fake(`t${i}`));
    const p = bulkPreview('resolve', overCap);
    expect(bulkPreviewLabel('resolve', p)).toContain(`over ${MAX_BULK_IDS} cap`);
  });
});
