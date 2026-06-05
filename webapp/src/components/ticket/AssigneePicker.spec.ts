import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AssigneePicker from './AssigneePicker.vue';
import { api } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: {
    listUsers: vi.fn().mockResolvedValue([
      { id: 1, name: 'Alice' },
      { id: 2, name: 'Bob' },
    ]),
    assignTicket: vi
      .fn()
      .mockResolvedValue({ assigned_to: { id: 1, name: 'Alice' }, assigned_at: null }),
    listTickets: vi.fn().mockResolvedValue([]),
  },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

describe('AssigneePicker', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(api.assignTicket).mockResolvedValue({
      assigned_to: { id: 1, name: 'Alice' },
      assigned_at: null,
    });
    vi.mocked(api.listUsers).mockResolvedValue([
      { id: 1, name: 'Alice' },
      { id: 2, name: 'Bob' },
    ]);
  });

  it('lists users from the API', async () => {
    const wrapper = mount(AssigneePicker, { props: { ticketId: 't1', assignedTo: null } });
    await flushPromises();
    expect(wrapper.text()).toContain('Alice');
    expect(wrapper.text()).toContain('Bob');
  });

  it('calls assignTicket with the selected user id on change', async () => {
    const wrapper = mount(AssigneePicker, { props: { ticketId: 't1', assignedTo: null } });
    await flushPromises();
    await wrapper.find('select').setValue('1');
    await flushPromises();
    expect(api.assignTicket).toHaveBeenCalledWith('t1', 1);
  });

  it('shows an error hint when listUsers rejects', async () => {
    vi.mocked(api.listUsers).mockRejectedValueOnce(new Error('network error'));
    const wrapper = mount(AssigneePicker, { props: { ticketId: 't1', assignedTo: null } });
    await flushPromises();
    expect(wrapper.find('.err').exists()).toBe(true);
  });
});
