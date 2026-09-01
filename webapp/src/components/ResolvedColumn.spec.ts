// The terminal-lane marker is load-bearing, so it gets a test.
// Reference: tasks.md T199, invariant #10.
//
// `acceptsDropFromOpenLane` reads `data-lane` off the source list element. If a
// restyle or a vuedraggable upgrade drops that attribute (or wraps the list in
// another element), the predicate silently returns true and the
// Resolved <-> Non-actionable no-op comes back. This asserts the marker reaches
// the DOM on both terminal columns.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { mount } from '@vue/test-utils';
import ResolvedColumn from './ResolvedColumn.vue';
import NonActionableColumn from './NonActionableColumn.vue';
import { TERMINAL_LANE } from '@/utils/dragLanes';

vi.mock('@/api/client', () => ({
  api: {},
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

describe('terminal columns', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('ResolvedColumn marks its card list as a terminal lane', () => {
    const wrapper = mount(ResolvedColumn);
    expect(wrapper.find(`[data-lane="${TERMINAL_LANE}"]`).exists()).toBe(true);
    wrapper.unmount();
  });

  it('NonActionableColumn marks its card list as a terminal lane', () => {
    const wrapper = mount(NonActionableColumn);
    expect(wrapper.find(`[data-lane="${TERMINAL_LANE}"]`).exists()).toBe(true);
    wrapper.unmount();
  });
});
