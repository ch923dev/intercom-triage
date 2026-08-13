import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BugAlertsPage from './BugAlertsPage.vue';
import { useBugAlertsStore } from '@/stores/bugAlerts';
import { api } from '@/api/client';
import type { BugAlert } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listBugAlerts: vi.fn(),
    dismissBugAlert: vi.fn(),
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
    title: 'Export broken',
    url: 'https://example.com/conv/T1',
    ...over,
  };
}

/** Mount with the store pre-seeded, bypassing onMounted's load. */
async function mountWith(alerts: BugAlert[]) {
  mocked.listBugAlerts.mockResolvedValue(alerts);
  const wrapper = mount(BugAlertsPage);
  await useBugAlertsStore().load();
  await wrapper.vm.$nextTick();
  return wrapper;
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

  it('explains an empty list without implying a failure', async () => {
    const wrapper = await mountWith([]);
    expect(wrapper.text()).toContain('No bug alerts recorded');
  });
});
