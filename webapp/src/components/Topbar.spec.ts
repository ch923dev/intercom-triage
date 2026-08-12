// Topbar sync-button lookback conversion (review finding #7).
// `lookbackHours` is the SOLE place translating the operator's board lookback
// (days/value) into the hours bound the backend consumes — a regression that
// drops the ×24 would silently narrow a 7-day fetch to 7 hours, undetected.

import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Topbar from './Topbar.vue';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import type { FilterSettings } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: { getSettings: vi.fn() },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

const BASE_SETTINGS: FilterSettings = {
  lookback_unit: 'hours',
  lookback_value: 24,
  states: ['open'],
  include_category_ids: null,
  mute_alarms: false,
  use_ai: true,
  ai_resolve_default: false,
  ai_resolve_confidence_threshold: 0.7,
  hide_empty_categories: true,
};

const SYNC_BTN = 'button[title="Pull latest conversations from Intercom"]';

describe('Topbar sync lookback conversion', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  async function mountWith(unit: 'hours' | 'days', value: number) {
    const { api } = await import('@/api/client');
    (api.getSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_SETTINGS,
      lookback_unit: unit,
      lookback_value: value,
    });
    const settings = useSettingsStore();
    await settings.load();
    const tickets = useTicketsStore();
    const spy = vi.spyOn(tickets, 'syncNow').mockResolvedValue(undefined);
    const wrapper = mount(Topbar);
    return { wrapper, spy };
  }

  it('converts the board lookback days → hours (×24) for the backend bound', async () => {
    const { wrapper, spy } = await mountWith('days', 7);
    await wrapper.get(SYNC_BTN).trigger('click');
    expect(spy).toHaveBeenCalledWith(168);
  });

  it('passes the raw value straight through when the unit is hours', async () => {
    const { wrapper, spy } = await mountWith('hours', 6);
    await wrapper.get(SYNC_BTN).trigger('click');
    expect(spy).toHaveBeenCalledWith(6);
  });
});
