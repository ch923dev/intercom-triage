// Priority comparator unit tests (roadmap 1.2 — priority-sorted queue).

import { describe, expect, it } from 'vitest';
import { byPriorityDesc, priorityRank } from './priority';
import type { AIPriority } from '@/types/api';

/** Minimal row the comparator reads. */
function row(id: string, ai_priority: AIPriority | null) {
  return { id, ai_priority };
}

describe('priorityRank', () => {
  it('ranks urgent < high < normal < low (lower sorts first)', () => {
    expect(priorityRank('urgent')).toBeLessThan(priorityRank('high'));
    expect(priorityRank('high')).toBeLessThan(priorityRank('normal'));
    expect(priorityRank('normal')).toBeLessThan(priorityRank('low'));
  });

  it('ranks null and undefined the same as normal', () => {
    expect(priorityRank(null)).toBe(priorityRank('normal'));
    expect(priorityRank(undefined)).toBe(priorityRank('normal'));
  });
});

describe('byPriorityDesc', () => {
  it('orders a mixed column urgent → high → normal → low', () => {
    const list = [row('a', 'low'), row('b', 'urgent'), row('c', 'normal'), row('d', 'high')];
    const sorted = [...list].sort(byPriorityDesc);
    expect(sorted.map((t) => t.id)).toEqual(['b', 'd', 'c', 'a']);
  });

  it('sorts a null priority as normal (between high and low, not last)', () => {
    const list = [row('low', 'low'), row('nul', null), row('high', 'high')];
    const sorted = [...list].sort(byPriorityDesc);
    // null ranks as normal: after high, before low.
    expect(sorted.map((t) => t.id)).toEqual(['high', 'nul', 'low']);
  });

  it('is stable — preserves incoming order within a priority tier', () => {
    // Three urgents in a fixed incoming order (e.g. recency/follow-up).
    const list = [row('first', 'urgent'), row('second', 'urgent'), row('third', 'urgent')];
    const sorted = [...list].sort(byPriorityDesc);
    expect(sorted.map((t) => t.id)).toEqual(['first', 'second', 'third']);
  });

  it('keeps the tiebreak order across tiers (priority is the primary key)', () => {
    // Incoming order is a meaningful tiebreak (recency). A normal card that
    // arrived first must still fall below a later urgent card.
    const list = [
      row('normal-recent', 'normal'),
      row('urgent-older', 'urgent'),
      row('normal-older', 'normal'),
    ];
    const sorted = [...list].sort(byPriorityDesc);
    // urgent floats up; the two normals keep their incoming relative order.
    expect(sorted.map((t) => t.id)).toEqual(['urgent-older', 'normal-recent', 'normal-older']);
  });
});
