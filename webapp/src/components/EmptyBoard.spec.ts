import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';
import EmptyBoard from './EmptyBoard.vue';
import { useTicketsStore } from '@/stores/tickets';

describe('EmptyBoard', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('shows the no-tickets heading, a sync button, and the poller hint', () => {
    const wrapper = mount(EmptyBoard);
    const text = wrapper.text();
    expect(text).toContain('No tickets yet');
    expect(text).toContain('Sync from Intercom');
    expect(text).toContain('INTERCOM_POLL_INTERVAL_SECONDS');
  });

  it('disables the button and swaps the label while a sync is in flight', () => {
    const tickets = useTicketsStore();
    tickets.syncing = true;
    const wrapper = mount(EmptyBoard);
    const btn = wrapper.get('button');
    expect(btn.attributes('disabled')).toBeDefined();
    expect(btn.text()).toContain('Syncing…');
  });

  it('does not mention the Chrome extension', () => {
    expect(mount(EmptyBoard).text().toLowerCase()).not.toContain('extension');
  });
});
