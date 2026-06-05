import { describe, expect, it } from 'vitest';
import { renderSnippet, substitute, variablesForTicket } from './snippets';
import type { Ticket } from '@/types/api';

function fakeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 'TCK-1',
    title: 't',
    state: 'open',
    priority: null,
    created_at: '2026-05-27T00:00:00Z',
    updated_at: '2026-05-27T00:00:00Z',
    author: {
      id: null,
      name: 'Ada Lovelace',
      email: 'ada@example.com',
      type: 'user',
      location: null,
      timezone: null,
      phone: null,
      company: 'Analytical Engines Ltd',
    },
    url: null,
    parts: [],
    internal_notes: [],
    category_id: 1,
    proposal_id: null,
    summary: '',
    ai_confidence: 0,
    user_override: false,
    title_user_edited: false,
    summary_user_edited: false,
    followup: null,
    note: null,
    resolved_at: null,
    resolved_source: null,
    ai_resolve_enabled: false,
    ai_resolve_override: null,
    ai_resolution_verdict: null,
    ai_resolution_confidence: null,
    ai_resolution_reason: null,
    resolution_chip_state: null,
    ai_priority: null,
    ai_sentiment: null,
    ai_labels: [],
    parked_at: null,
    parked_until: null,
    parked_reason: null,
    parked_note: null,
    non_actionable_kind: null,
    resolved_by: null,
    acted_by: null,
    assigned_to: null,
    assigned_at: null,
    ...overrides,
  };
}

describe('snippet substitution', () => {
  it('fills {{customer_name}} from the ticket author', () => {
    const out = renderSnippet('Hi {{customer_name}}, thanks!', fakeTicket());
    expect(out).toBe('Hi Ada Lovelace, thanks!');
  });

  it('fills all supported variables', () => {
    const body = '{{customer_name}} <{{customer_email}}> at {{customer_company}} re {{ticket_id}}';
    expect(renderSnippet(body, fakeTicket())).toBe(
      'Ada Lovelace <ada@example.com> at Analytical Engines Ltd re TCK-1',
    );
  });

  it('is case-insensitive and tolerates inner whitespace', () => {
    expect(renderSnippet('Hi {{ Customer_Name }}!', fakeTicket())).toBe('Hi Ada Lovelace!');
  });

  it('leaves unknown variables as literal placeholders', () => {
    const out = renderSnippet('Hi {{customer_name}} {{order_number}}', fakeTicket());
    expect(out).toBe('Hi Ada Lovelace {{order_number}}');
  });

  it('renders a known-but-missing variable as the empty string', () => {
    const t = fakeTicket({
      author: { ...fakeTicket().author, name: null, company: null },
    });
    expect(renderSnippet('Hi {{customer_name}} ({{customer_company}})', t)).toBe('Hi  ()');
  });

  it('returns the raw body (placeholders intact) with no ticket context', () => {
    expect(renderSnippet('Hi {{customer_name}}', null)).toBe('Hi {{customer_name}}');
  });

  it('substitute leaves placeholders for names not in the var map', () => {
    expect(substitute('{{a}} {{b}}', { a: 'X' })).toBe('X {{b}}');
  });

  it('variablesForTicket maps empties for missing author fields', () => {
    const vars = variablesForTicket(
      fakeTicket({ author: { ...fakeTicket().author, name: null, email: null } }),
    );
    expect(vars.customer_name).toBe('');
    expect(vars.customer_email).toBe('');
    expect(vars.ticket_id).toBe('TCK-1');
  });
});
