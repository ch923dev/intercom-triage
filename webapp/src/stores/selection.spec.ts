// Selection-store unit tests. Plan §8d / tasks.md T080.

import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useSelectionStore } from './selection';

describe('selectionStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  describe('toggle', () => {
    it('adds an id when absent', () => {
      const s = useSelectionStore();
      s.toggle('t1', 'colA');
      expect(s.has('t1')).toBe(true);
      expect(s.count).toBe(1);
    });

    it('removes an id when present', () => {
      const s = useSelectionStore();
      s.toggle('t1', 'colA');
      s.toggle('t1', 'colA');
      expect(s.has('t1')).toBe(false);
      expect(s.count).toBe(0);
    });

    it('updates lastAnchor to the toggled id', () => {
      const s = useSelectionStore();
      s.toggle('t1', 'colA');
      expect(s.lastAnchor).toEqual({ columnId: 'colA', id: 't1' });
      s.toggle('t2', 'colB');
      expect(s.lastAnchor).toEqual({ columnId: 'colB', id: 't2' });
    });
  });

  describe('addRange', () => {
    it('selects the contiguous slice between two anchors', () => {
      const s = useSelectionStore();
      const ordered = ['a', 'b', 'c', 'd', 'e'];
      s.addRange('col', 'b', 'd', ordered);
      expect(s.asArray().sort()).toEqual(['b', 'c', 'd']);
    });

    it('handles reverse range (anchor below click)', () => {
      const s = useSelectionStore();
      const ordered = ['a', 'b', 'c', 'd', 'e'];
      s.addRange('col', 'd', 'b', ordered);
      expect(s.asArray().sort()).toEqual(['b', 'c', 'd']);
    });

    it('is a no-op when ids are not in orderedIds', () => {
      const s = useSelectionStore();
      s.addRange('col', 'ghost', 'd', ['a', 'b', 'c']);
      expect(s.count).toBe(0);
    });

    it('moves the anchor to toId', () => {
      const s = useSelectionStore();
      s.addRange('col', 'a', 'c', ['a', 'b', 'c']);
      expect(s.lastAnchor).toEqual({ columnId: 'col', id: 'c' });
    });

    it('preserves prior selection on different rows', () => {
      const s = useSelectionStore();
      s.toggle('z', 'other');
      s.addRange('col', 'a', 'b', ['a', 'b', 'c']);
      expect(s.asArray().sort()).toEqual(['a', 'b', 'z']);
    });
  });

  describe('addAll', () => {
    it('adds every id in the array', () => {
      const s = useSelectionStore();
      s.addAll(['x', 'y', 'z'], 'colA');
      expect(s.count).toBe(3);
      expect(s.has('x')).toBe(true);
      expect(s.has('y')).toBe(true);
      expect(s.has('z')).toBe(true);
    });

    it('moves the anchor to the last id', () => {
      const s = useSelectionStore();
      s.addAll(['x', 'y', 'z'], 'colA');
      expect(s.lastAnchor).toEqual({ columnId: 'colA', id: 'z' });
    });

    it('is a no-op for empty input', () => {
      const s = useSelectionStore();
      s.addAll([], 'colA');
      expect(s.count).toBe(0);
      expect(s.lastAnchor).toBeNull();
    });
  });

  describe('remove', () => {
    it('removes an id without touching the anchor', () => {
      const s = useSelectionStore();
      s.toggle('a', 'col');
      s.toggle('b', 'col');
      s.remove('a');
      expect(s.has('a')).toBe(false);
      expect(s.has('b')).toBe(true);
      // Anchor was last set by toggle('b') — unchanged by remove.
      expect(s.lastAnchor).toEqual({ columnId: 'col', id: 'b' });
    });

    it('is a no-op on an absent id', () => {
      const s = useSelectionStore();
      s.toggle('a', 'col');
      s.remove('ghost');
      expect(s.count).toBe(1);
    });
  });

  describe('clear', () => {
    it('empties the set and resets the anchor', () => {
      const s = useSelectionStore();
      s.toggle('a', 'col');
      s.toggle('b', 'col');
      s.clear();
      expect(s.count).toBe(0);
      expect(s.lastAnchor).toBeNull();
      expect(s.isEmpty).toBe(true);
    });

    it('is a no-op when already empty', () => {
      const s = useSelectionStore();
      s.clear();
      expect(s.count).toBe(0);
      expect(s.lastAnchor).toBeNull();
    });
  });

  describe('isEmpty + asArray', () => {
    it('starts empty', () => {
      const s = useSelectionStore();
      expect(s.isEmpty).toBe(true);
      expect(s.asArray()).toEqual([]);
    });

    it('flips after adding', () => {
      const s = useSelectionStore();
      s.toggle('a', 'col');
      expect(s.isEmpty).toBe(false);
      expect(s.asArray()).toEqual(['a']);
    });
  });
});
