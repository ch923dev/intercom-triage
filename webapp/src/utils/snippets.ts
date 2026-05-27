// Snippet variable substitution (roadmap 1.5).
//
// Substitution is done CLIENT-SIDE from the ticket the operator is viewing —
// the simplest design for a local single-operator tool, and it keeps the
// backend a thin verbatim CRUD store (snippet bodies are persisted with
// `{{variable}}` placeholders intact). The operator opens a ticket flyout,
// picks a snippet, and `renderSnippet` fills the placeholders.
//
// Supported variables (all sourced from data the open ticket already carries):
//   {{customer_name}}    — ticket.author.name
//   {{customer_email}}   — ticket.author.email
//   {{customer_company}} — ticket.author.company
//   {{ticket_id}}        — ticket.id
//
// Unknown / unsupported variables are LEFT AS-IS (the literal `{{whatever}}`
// stays in the output) so the operator can see at a glance that a placeholder
// went unfilled rather than silently losing text. A *known* variable whose
// value is missing/empty on this ticket renders as the empty string.

import type { Ticket } from '@/types/api';

const PLACEHOLDER = /\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}/gi;

/** The variable names `renderSnippet` knows how to fill, in display order. */
export const SUPPORTED_VARIABLES = [
  'customer_name',
  'customer_email',
  'customer_company',
  'ticket_id',
] as const;

export type SnippetVariable = (typeof SUPPORTED_VARIABLES)[number];

/** Build the variable → value map for a ticket. A known variable with no data
 *  on this ticket maps to the empty string. */
export function variablesForTicket(ticket: Ticket): Record<SnippetVariable, string> {
  return {
    customer_name: ticket.author.name ?? '',
    customer_email: ticket.author.email ?? '',
    customer_company: ticket.author.company ?? '',
    ticket_id: ticket.id,
  };
}

/** Replace `{{variable}}` placeholders in `body` using `vars`. Names not in
 *  `vars` are left untouched (the literal placeholder is preserved). Matching
 *  is case-insensitive and tolerates inner whitespace (`{{ customer_name }}`). */
export function substitute(body: string, vars: Record<string, string>): string {
  return body.replace(PLACEHOLDER, (match, rawName: string) => {
    const name = rawName.toLowerCase();
    return Object.prototype.hasOwnProperty.call(vars, name) ? vars[name] : match;
  });
}

/** Render a snippet body against the ticket the operator is viewing. Pass
 *  `null` to preview the raw body (no ticket context) — placeholders stay. */
export function renderSnippet(body: string, ticket: Ticket | null): string {
  if (ticket === null) return body;
  return substitute(body, variablesForTicket(ticket));
}
