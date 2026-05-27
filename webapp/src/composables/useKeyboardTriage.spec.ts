// useKeyboardTriage spec — the pure key→action dispatcher (NFR-007).
// Covers navigation (j/k clamping + first-press), resolve, digit→category
// mapping, and the no-op guards (empty board, unfocused, out-of-range digit,
// unknown keys). The form-control / modal guards live in App.vue's keydown
// handler (they gate *whether* dispatch runs), so they're verified by the
// caller's own logic, not here — this file pins the mapping table.

import { describe, expect, it } from 'vitest';
import { dispatchTriageKey, type TriageContext } from './useKeyboardTriage';

function ctx(overrides: Partial<TriageContext> = {}): TriageContext {
  return {
    orderedIds: ['a', 'b', 'c'],
    focusedId: 'b',
    categoryIds: [10, 20, 30],
    ...overrides,
  };
}

describe('dispatchTriageKey — navigation (j/k)', () => {
  it('j moves to the next ticket', () => {
    expect(dispatchTriageKey('j', ctx({ focusedId: 'a' }))).toEqual({ type: 'navigate', id: 'b' });
  });

  it('k moves to the previous ticket', () => {
    expect(dispatchTriageKey('k', ctx({ focusedId: 'b' }))).toEqual({ type: 'navigate', id: 'a' });
  });

  it('j clamps at the last ticket', () => {
    expect(dispatchTriageKey('j', ctx({ focusedId: 'c' }))).toEqual({ type: 'navigate', id: 'c' });
  });

  it('k clamps at the first ticket', () => {
    expect(dispatchTriageKey('k', ctx({ focusedId: 'a' }))).toEqual({ type: 'navigate', id: 'a' });
  });

  it('first press (no focus) lands on the first ticket', () => {
    expect(dispatchTriageKey('j', ctx({ focusedId: null }))).toEqual({ type: 'navigate', id: 'a' });
    expect(dispatchTriageKey('k', ctx({ focusedId: null }))).toEqual({ type: 'navigate', id: 'a' });
  });

  it('lands on the first ticket when the focus fell off the board', () => {
    expect(dispatchTriageKey('j', ctx({ focusedId: 'gone' }))).toEqual({
      type: 'navigate',
      id: 'a',
    });
  });

  it('is a no-op on an empty board', () => {
    expect(dispatchTriageKey('j', ctx({ orderedIds: [], focusedId: null }))).toEqual({
      type: 'none',
    });
  });
});

describe('dispatchTriageKey — resolve (e)', () => {
  it('resolves the focused ticket', () => {
    expect(dispatchTriageKey('e', ctx({ focusedId: 'b' }))).toEqual({ type: 'resolve', id: 'b' });
  });

  it('is a no-op when nothing is focused', () => {
    expect(dispatchTriageKey('e', ctx({ focusedId: null }))).toEqual({ type: 'none' });
  });

  it('is a no-op when the focused id is not on the board', () => {
    expect(dispatchTriageKey('e', ctx({ focusedId: 'gone' }))).toEqual({ type: 'none' });
  });
});

describe('dispatchTriageKey — recategorize (1..9)', () => {
  it('maps digit N to the Nth active category', () => {
    expect(dispatchTriageKey('1', ctx())).toEqual({
      type: 'recategorize',
      id: 'b',
      categoryId: 10,
    });
    expect(dispatchTriageKey('3', ctx())).toEqual({
      type: 'recategorize',
      id: 'b',
      categoryId: 30,
    });
  });

  it('is a no-op for an out-of-range digit', () => {
    expect(dispatchTriageKey('4', ctx())).toEqual({ type: 'none' });
    expect(dispatchTriageKey('9', ctx())).toEqual({ type: 'none' });
  });

  it('is a no-op when nothing is focused', () => {
    expect(dispatchTriageKey('1', ctx({ focusedId: null }))).toEqual({ type: 'none' });
  });

  it('does not treat 0 as a category key', () => {
    expect(dispatchTriageKey('0', ctx())).toEqual({ type: 'none' });
  });
});

describe('dispatchTriageKey — unhandled keys', () => {
  it.each(['a', 'r', '/', 'Escape', 'ArrowRight', 'E', 'J'])('%s is a no-op', (key) => {
    expect(dispatchTriageKey(key, ctx())).toEqual({ type: 'none' });
  });
});
