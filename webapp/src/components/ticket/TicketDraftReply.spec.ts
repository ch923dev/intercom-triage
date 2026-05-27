// TicketDraftReply flyout spec — RAG draft reply (roadmap 2.6). Verifies the
// component calls the draft-reply API, renders the returned draft + grounding
// ids, and surfaces an error on failure.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import type { VueWrapper } from '@vue/test-utils';
import TicketDraftReply from './TicketDraftReply.vue';
import { api } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: {
    draftReply: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

// The first <button> is the CollapsibleSection header toggle; the generate
// action is the button whose label is one of these. Click it specifically so
// the test exercises drafting rather than collapsing the section.
async function clickGenerate(w: VueWrapper): Promise<void> {
  const btn = w
    .findAll('button')
    .find((b) => ['Draft reply', 'Re-draft', 'Drafting…'].includes(b.text()));
  if (!btn) throw new Error('generate button not found');
  await btn.trigger('click');
}

describe('TicketDraftReply', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('drafts a reply and renders the body + grounding ids', async () => {
    mocked.draftReply.mockResolvedValue({
      body: 'Sorry about that — see TPAST.',
      grounding_ticket_ids: ['TPAST', 'TOLD'],
      playbook_ids: [3],
    });
    const w = mount(TicketDraftReply, { props: { ticketId: 'TCUR' } });

    await clickGenerate(w);
    await flushPromises();

    expect(mocked.draftReply).toHaveBeenCalledWith('TCUR');
    const textarea = w.find('textarea');
    expect(textarea.exists()).toBe(true);
    expect((textarea.element as HTMLTextAreaElement).value).toBe('Sorry about that — see TPAST.');
    expect(w.text()).toContain('TPAST');
    expect(w.text()).toContain('TOLD');
  });

  it('shows the empty-grounding note when no precedents were found', async () => {
    mocked.draftReply.mockResolvedValue({
      body: 'Generic reply.',
      grounding_ticket_ids: [],
      playbook_ids: [],
    });
    const w = mount(TicketDraftReply, { props: { ticketId: 'TCUR' } });

    await clickGenerate(w);
    await flushPromises();

    expect(w.text()).toContain('No similar resolved tickets found.');
  });

  it('surfaces an error when the draft call fails', async () => {
    mocked.draftReply.mockRejectedValue(new Error('503'));
    const w = mount(TicketDraftReply, { props: { ticketId: 'TCUR' } });

    await clickGenerate(w);
    await flushPromises();

    expect(w.text()).toContain('AI draft failed');
    expect(w.find('textarea').exists()).toBe(false);
  });
});
