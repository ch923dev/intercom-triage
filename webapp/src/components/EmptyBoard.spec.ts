import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import EmptyBoard from './EmptyBoard.vue';

describe('EmptyBoard', () => {
  it('shows the no-tickets heading and points at the backend sync path', () => {
    const wrapper = mount(EmptyBoard);
    const text = wrapper.text();
    expect(text).toContain('No tickets yet');
    expect(text).toContain('POST /tickets/sync');
    expect(text).toContain('INTERCOM_POLL_INTERVAL_SECONDS');
  });

  it('does not mention the Chrome extension', () => {
    expect(mount(EmptyBoard).text().toLowerCase()).not.toContain('extension');
  });
});
