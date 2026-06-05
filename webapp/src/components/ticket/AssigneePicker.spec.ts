import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AssigneePicker from './AssigneePicker.vue';

vi.mock('@/api/client', () => ({
  api: {
    listUsers: vi.fn().mockResolvedValue([
      { id: 1, name: 'Alice' },
      { id: 2, name: 'Bob' },
    ]),
    assignTicket: vi.fn(),
    listTickets: vi.fn().mockResolvedValue([]),
  },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

describe('AssigneePicker', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('lists users from the API', async () => {
    const wrapper = mount(AssigneePicker, { props: { ticketId: 't1', assignedTo: null } });
    await flushPromises();
    expect(wrapper.text()).toContain('Alice');
    expect(wrapper.text()).toContain('Bob');
  });
});
