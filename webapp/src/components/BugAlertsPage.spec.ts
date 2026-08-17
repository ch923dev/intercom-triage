import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BugAlertsPage from './BugAlertsPage.vue';
import { useBugAlertsStore } from '@/stores/bugAlerts';
import { api } from '@/api/client';
import type { BugAlert, SimilarBug } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listBugAlerts: vi.fn(),
    dismissBugAlert: vi.fn(),
    ackBugAlert: vi.fn(),
    setBugNote: vi.fn(),
    getSimilarBugs: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function make(over: Partial<BugAlert> = {}): BugAlert {
  return {
    ticket_id: 'T1',
    severity: 'medium',
    confidence: 0.82,
    evidence: 'the export button does nothing',
    occurrences: 2,
    first_detected_at: new Date().toISOString(),
    last_detected_at: new Date().toISOString(),
    posted_at: null,
    posted_severity: null,
    slack_channel: null,
    slack_ts: null,
    dismissed_at: null,
    acked_at: null,
    acked_by: null,
    note: null,
    note_by: null,
    note_at: null,
    title: 'Export broken',
    url: 'https://example.com/conv/T1',
    ...over,
  };
}

/** Mount with the store pre-seeded, bypassing onMounted's load.
 *
 * `getSimilarBugs` defaults to no precedent: the page fetches it for every
 * visible row, so without a default every test would trip over an unmocked call.
 */
async function mountWith(alerts: BugAlert[], priors: SimilarBug[] = []) {
  mocked.listBugAlerts.mockResolvedValue(alerts);
  mocked.getSimilarBugs.mockResolvedValue(priors);
  const wrapper = mount(BugAlertsPage);
  await useBugAlertsStore().load();
  await flush();
  await wrapper.vm.$nextTick();
  return wrapper;
}

/** Let queued microtasks settle — several actions are fire-and-forget. */
function flush() {
  return new Promise((r) => setTimeout(r, 0));
}

function makePrior(over: Partial<SimilarBug> = {}): SimilarBug {
  return {
    ticket_id: 'T-old',
    severity: 'high',
    score: 0.82,
    note: 'stale cache key — clear session, re-export',
    note_by: { id: 1, name: 'Christian' },
    note_at: '2026-08-14T09:00:00Z',
    title: 'Export button broken',
    url: 'https://example.com/conv/T-old',
    ...over,
  };
}

describe('BugAlertsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('renders severity, the evidence quote, confidence and occurrences', async () => {
    const wrapper = await mountWith([make({ severity: 'high' })]);
    const text = wrapper.text();
    expect(text).toContain('high');
    expect(text).toContain('the export button does nothing');
    expect(text).toContain('82% confident');
    expect(text).toContain('seen 2×');
  });

  it('links the title to the conversation', async () => {
    const wrapper = await mountWith([make()]);
    const link = wrapper.get('a.name');
    expect(link.attributes('href')).toBe('https://example.com/conv/T1');
    expect(link.text()).toBe('Export broken');
  });

  it('falls back to the ticket id when the ticket has aged out', async () => {
    const wrapper = await mountWith([make({ title: null, url: null })]);
    expect(wrapper.find('a.name').exists()).toBe(false);
    expect(wrapper.text()).toContain('T1');
  });

  it('builds a Slack permalink only when channel and ts are both present', async () => {
    const withTs = await mountWith([
      make({ posted_at: '2026-08-13T09:00:00Z', slack_channel: 'C123', slack_ts: '1786610549.68' }),
    ]);
    expect(withTs.get('a.slack').attributes('href')).toBe(
      'https://slack.com/archives/C123/p178661054968',
    );

    setActivePinia(createPinia());
    const halfBuilt = await mountWith([
      make({ posted_at: '2026-08-13T09:00:00Z', slack_channel: 'C123', slack_ts: null }),
    ]);
    expect(halfBuilt.find('a.slack').exists()).toBe(false);
  });

  it('distinguishes awaiting, announced and escalating states', async () => {
    const waiting = await mountWith([make()]);
    expect(waiting.text()).toContain('awaiting announcement');

    setActivePinia(createPinia());
    const announced = await mountWith([
      make({ posted_at: '2026-08-13T09:00:00Z', posted_severity: 'medium' }),
    ]);
    expect(announced.text()).toContain('announced');
    expect(announced.text()).not.toContain('escalation pending');

    setActivePinia(createPinia());
    const escalating = await mountWith([
      make({ severity: 'high', posted_at: '2026-08-13T09:00:00Z', posted_severity: 'medium' }),
    ]);
    expect(escalating.text()).toContain('escalation pending');
  });

  it('dismisses a row and swaps the button for a done marker', async () => {
    const wrapper = await mountWith([make()]);
    mocked.dismissBugAlert.mockResolvedValue(make({ dismissed_at: '2026-08-13T10:00:00Z' }));

    await wrapper.get('button.dismiss').trigger('click');
    await new Promise((r) => setTimeout(r, 0));
    await wrapper.vm.$nextTick();

    expect(mocked.dismissBugAlert).toHaveBeenCalledWith('T1');
    expect(wrapper.find('button.dismiss').exists()).toBe(false);
    expect(wrapper.text()).toContain('dismissed');
  });

  it('lists dismissed and low-severity alerts rather than hiding them', async () => {
    const wrapper = await mountWith([
      make({ ticket_id: 'low', severity: 'low' }),
      make({ ticket_id: 'gone', dismissed_at: '2026-08-13T10:00:00Z' }),
    ]);
    expect(wrapper.findAll('li.card')).toHaveLength(2);
  });

  it('filters by severity', async () => {
    const wrapper = await mountWith([
      make({ ticket_id: 'h', severity: 'high' }),
      make({ ticket_id: 'l', severity: 'low' }),
    ]);
    await wrapper.findAll('select')[0].setValue('high');
    const rows = wrapper.findAll('li.card');
    expect(rows).toHaveLength(1);
    expect(rows[0].text()).toContain('h');
  });

  it('filters by state', async () => {
    const wrapper = await mountWith([
      make({ ticket_id: 'waiting' }),
      make({ ticket_id: 'sent', posted_at: '2026-08-13T09:00:00Z', posted_severity: 'medium' }),
    ]);
    await wrapper.findAll('select')[1].setValue('announced');
    const rows = wrapper.findAll('li.card');
    expect(rows).toHaveLength(1);
    expect(rows[0].text()).toContain('sent');
  });

  it('acknowledges a row and swaps the button for a done marker', async () => {
    const wrapper = await mountWith([make({ posted_at: '2026-08-14T09:00:00Z' })]);
    mocked.ackBugAlert.mockResolvedValue({
      alert: make({
        posted_at: '2026-08-14T09:00:00Z',
        acked_at: '2026-08-15T10:00:00Z',
        acked_by: { id: 1, name: 'Christian' },
      }),
      slack_updated: true,
    });

    await wrapper.get('button.ack').trigger('click');
    await new Promise((r) => setTimeout(r, 0));
    await wrapper.vm.$nextTick();

    expect(mocked.ackBugAlert).toHaveBeenCalledWith('T1');
    expect(wrapper.find('button.ack').exists()).toBe(false);
    expect(wrapper.text()).toContain('acknowledged');
    // The state line names the owner rather than just saying "announced".
    expect(wrapper.text()).toContain('owned by Christian');
  });

  it('reports a failed Slack mirror without implying the ack was lost', async () => {
    const wrapper = await mountWith([
      make({ posted_at: '2026-08-14T09:00:00Z', slack_channel: 'C1', slack_ts: '1.2' }),
    ]);
    mocked.ackBugAlert.mockResolvedValue({
      alert: make({
        posted_at: '2026-08-14T09:00:00Z',
        slack_channel: 'C1',
        slack_ts: '1.2',
        acked_at: '2026-08-15T10:00:00Z',
        acked_by: { id: 1, name: 'Christian' },
      }),
      slack_updated: false,
    });

    await wrapper.get('button.ack').trigger('click');
    await new Promise((r) => setTimeout(r, 0));
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('Slack message not updated');
    expect(wrapper.text()).toContain('owned by Christian'); // the ack still stands
  });

  it('offers no Acknowledge button on an already-acknowledged row', async () => {
    const wrapper = await mountWith([
      make({ acked_at: '2026-08-15T10:00:00Z', acked_by: { id: 1, name: 'Christian' } }),
    ]);
    expect(wrapper.find('button.ack').exists()).toBe(false);
    // Dismiss is still available — owning something is not finishing it.
    expect(wrapper.find('button.dismiss').exists()).toBe(true);
  });

  it('keeps the owner visible on a row that was acknowledged and then dismissed', async () => {
    const wrapper = await mountWith([
      make({
        acked_at: '2026-08-15T10:00:00Z',
        acked_by: { id: 1, name: 'Christian' },
        dismissed_at: '2026-08-15T11:00:00Z',
      }),
    ]);
    const text = wrapper.text();
    expect(text).toContain('dismissed');
    expect(text).toContain('acked by Christian');
  });

  it('filters by the acknowledged state', async () => {
    const wrapper = await mountWith([
      make({
        ticket_id: 'owned',
        acked_at: '2026-08-15T10:00:00Z',
        acked_by: { id: 1, name: 'C' },
      }),
      make({ ticket_id: 'fresh', posted_at: '2026-08-14T09:00:00Z', posted_severity: 'medium' }),
    ]);
    await wrapper.findAll('select')[1].setValue('acknowledged');
    const rows = wrapper.findAll('li.card');
    expect(rows).toHaveLength(1);
    expect(rows[0].text()).toContain('owned');
  });

  it('shows a prior fix when one is offered', async () => {
    const wrapper = await mountWith([make()], [makePrior()]);
    const text = wrapper.text();
    expect(text).toContain('seen before');
    expect(text).toContain('Export button broken');
    expect(text).toContain('82% similar');
    expect(text).toContain('stale cache key');
    expect(text).toContain('Christian');
    expect(wrapper.get('.prior a').attributes('href')).toBe('https://example.com/conv/T-old');
  });

  it('shows no prior-fix panel when there is no precedent', async () => {
    const wrapper = await mountWith([make()]);
    // Absent, not empty — a "no similar bugs" line on every alert is noise.
    expect(wrapper.find('.prior').exists()).toBe(false);
  });

  it('writes a note and shows its author', async () => {
    const wrapper = await mountWith([make()]);
    mocked.setBugNote.mockResolvedValue(
      make({
        note: 'stale cache key',
        note_by: { id: 1, name: 'Christian' },
        note_at: '2026-08-15T10:00:00Z',
      }),
    );

    await wrapper.get('button.note-edit').trigger('click');
    await wrapper.get('textarea.note-input').setValue('stale cache key');
    await wrapper.get('button.note-save').trigger('click');
    await flush();
    await wrapper.vm.$nextTick();

    expect(mocked.setBugNote).toHaveBeenCalledWith('T1', 'stale cache key');
    expect(wrapper.text()).toContain('stale cache key');
    expect(wrapper.text()).toContain('noted by Christian');
    expect(wrapper.find('textarea.note-input').exists()).toBe(false); // editor closed
  });

  it('seeds the editor with the existing note so an edit is not a retype', async () => {
    const wrapper = await mountWith([
      make({ note: 'first take', note_by: { id: 1, name: 'C' }, note_at: '2026-08-15T09:00:00Z' }),
    ]);
    await wrapper.get('button.note-edit').trigger('click');
    expect(wrapper.get<HTMLTextAreaElement>('textarea.note-input').element.value).toBe(
      'first take',
    );
  });

  it('keeps the editor open when saving fails, so the text is not lost', async () => {
    const wrapper = await mountWith([make()]);
    mocked.setBugNote.mockRejectedValue(new Error('offline'));

    await wrapper.get('button.note-edit').trigger('click');
    await wrapper.get('textarea.note-input').setValue('half-written thought');
    await wrapper.get('button.note-save').trigger('click');
    await flush();
    await wrapper.vm.$nextTick();

    const editor = wrapper.find<HTMLTextAreaElement>('textarea.note-input');
    expect(editor.exists()).toBe(true);
    expect(editor.element.value).toBe('half-written thought');
  });

  it('explains an empty list without implying a failure', async () => {
    const wrapper = await mountWith([]);
    expect(wrapper.text()).toContain('No bug alerts recorded');
  });
});
