// Sample tickets ported from the design's `data.js` so the scaffold UI works
// before backend `/tickets/fetch` (T025) is wired up. Delete this module once
// the live route is in.

import type { Ticket } from '@/types/api';

// Categories: 1=Urgent, 2=Bug, 3=Feature Request, 4=Question, 5=Billing, 6=Complaint, 7=Other.
const CAT = {
  urgent: 1,
  bug: 2,
  feature: 3,
  question: 4,
  billing: 5,
  complaint: 6,
  other: 7,
} as const;

const NOW = Date.now();
const mins = (m: number) => new Date(NOW - m * 60_000).toISOString();

interface Seed {
  id: string;
  cat: number;
  conf: number;
  state: 'open' | 'snoozed' | 'closed';
  customer: string;
  company: string;
  plan: string;
  title: string;
  summary: string;
  msgs: number;
  ago: number;
}

const SEEDS: Seed[] = [
  {
    id: 'INT-48211',
    cat: CAT.urgent,
    conf: 0.97,
    state: 'open',
    customer: 'Priya Shankar',
    company: 'Northwind Labs',
    plan: 'Enterprise',
    title: 'Production webhook deliveries dropped at 14:02 UTC',
    summary:
      'Webhook endpoint receiving zero events since 14:02 UTC across all workspaces. Status page still green.',
    msgs: 8,
    ago: 4,
  },
  {
    id: 'INT-48207',
    cat: CAT.urgent,
    conf: 0.91,
    state: 'open',
    customer: 'Marco Wei',
    company: 'Halcyon Health',
    plan: 'Enterprise',
    title: 'SSO login loop after SAML metadata refresh',
    summary:
      'Whole org cannot authenticate through Okta SAML since last metadata sync. Users hit a redirect loop.',
    msgs: 5,
    ago: 11,
  },
  {
    id: 'INT-48198',
    cat: CAT.bug,
    conf: 0.88,
    state: 'open',
    customer: 'Sofia Reyes',
    company: 'Pebble Studio',
    plan: 'Pro',
    title: 'Export CSV includes hidden rows in filtered view',
    summary: '"Export visible" exports the full dataset instead of the filtered subset.',
    msgs: 3,
    ago: 38,
  },
  {
    id: 'INT-48191',
    cat: CAT.bug,
    conf: 0.84,
    state: 'open',
    customer: 'Daniel Bauer',
    company: 'Schauer & Söhne',
    plan: 'Pro',
    title: 'Time zone offset wrong in scheduled-send digest',
    summary:
      'Digest emails set for 09:00 local time arrive at 02:00 in CET. Started after last week’s release.',
    msgs: 4,
    ago: 72,
  },
  {
    id: 'INT-48180',
    cat: CAT.bug,
    conf: 0.79,
    state: 'open',
    customer: 'Aiko Tanaka',
    company: 'Mejiro AI',
    plan: 'Pro',
    title: 'Drag-and-drop reorder snaps back on Safari 17',
    summary: 'Reordering by drag works visually but releases revert. Safari 17.4 macOS only.',
    msgs: 6,
    ago: 95,
  },
  {
    id: 'INT-48176',
    cat: CAT.feature,
    conf: 0.93,
    state: 'open',
    customer: 'Lena Hofmann',
    company: 'Atlas Cargo',
    plan: 'Enterprise',
    title: 'Bulk-edit tags across multiple records',
    summary:
      'Multi-select on records with a tag editor that applies/removes in one action. Willing to pay.',
    msgs: 2,
    ago: 140,
  },
  {
    id: 'INT-48172',
    cat: CAT.feature,
    conf: 0.86,
    state: 'open',
    customer: 'James Okafor',
    company: 'Verdant Realty',
    plan: 'Pro',
    title: 'Slack notification routing per workspace',
    summary:
      'Per-workspace Slack channel mapping; currently all notifications fan out to one global channel.',
    msgs: 3,
    ago: 210,
  },
  {
    id: 'INT-48165',
    cat: CAT.feature,
    conf: 0.74,
    state: 'open',
    customer: 'Helena Voss',
    company: 'Brightline Capital',
    plan: 'Enterprise',
    title: 'Audit log export to S3 bucket',
    summary: 'Scheduled export of the audit log to a customer-owned S3 bucket, weekly cadence.',
    msgs: 4,
    ago: 265,
  },
  {
    id: 'INT-48160',
    cat: CAT.question,
    conf: 0.89,
    state: 'open',
    customer: 'Renee Ortiz',
    company: 'Cloudleaf',
    plan: 'Pro',
    title: 'How does the API rate-limit interact with bursts?',
    summary:
      'Asks whether the documented 600 req/min limit is a hard cap or token-bucket. Plans a backfill of ~2M records.',
    msgs: 1,
    ago: 58,
  },
  {
    id: 'INT-48157',
    cat: CAT.question,
    conf: 0.82,
    state: 'open',
    customer: 'Tom Greaves',
    company: 'Riverbend',
    plan: 'Starter',
    title: 'Can a workspace have more than one owner?',
    summary: 'Wants to add a co-owner before parental leave. Asks about permission scope.',
    msgs: 2,
    ago: 305,
  },
  {
    id: 'INT-48154',
    cat: CAT.question,
    conf: 0.71,
    state: 'open',
    customer: 'Inés Carrasco',
    company: 'Mariposa Co.',
    plan: 'Pro',
    title: 'Migrating from the legacy v1 API',
    summary: 'Asks for a migration guide from /v1/records to the v2 cursor-paginated endpoints.',
    msgs: 1,
    ago: 420,
  },
  {
    id: 'INT-48150',
    cat: CAT.billing,
    conf: 0.95,
    state: 'open',
    customer: 'Yuki Sato',
    company: 'Tessellate',
    plan: 'Pro',
    title: 'Charged twice for May invoice',
    summary: 'Two identical $480 charges for the May invoice. Asks for one to be refunded.',
    msgs: 2,
    ago: 85,
  },
  {
    id: 'INT-48144',
    cat: CAT.billing,
    conf: 0.88,
    state: 'open',
    customer: 'Marcus Lindqvist',
    company: 'Norra AB',
    plan: 'Enterprise',
    title: 'Add VAT number to invoice line',
    summary: 'Swedish VAT number on invoices retroactively for Q1 for tax filing.',
    msgs: 3,
    ago: 180,
  },
  {
    id: 'INT-48139',
    cat: CAT.complaint,
    conf: 0.81,
    state: 'open',
    customer: 'Naomi Patel',
    company: 'Lumen Press',
    plan: 'Pro',
    title: 'Onboarding flow is "deliberately confusing"',
    summary:
      'Long-form feedback about the multi-step setup. Calls out the workspace invite step as misleading.',
    msgs: 5,
    ago: 155,
  },
  {
    id: 'INT-48128',
    cat: CAT.other,
    conf: 0.42,
    state: 'open',
    customer: 'Anya Volkov',
    company: 'Selkie Studio',
    plan: 'Pro',
    title: 'Forwarded internal thread — context unclear',
    summary:
      'Forwarded a long internal email chain without a question. Mentions an integration but no specific ask.',
    msgs: 1,
    ago: 330,
  },
  {
    id: 'INT-48119',
    cat: CAT.other,
    conf: 0.35,
    state: 'open',
    customer: 'unknown',
    company: '—',
    plan: 'Free',
    title: '(no subject)',
    summary: 'Single-word message "hello?" from a trial account.',
    msgs: 1,
    ago: 510,
  },
];

export const SAMPLE_TICKETS: Ticket[] = SEEDS.map((s) => ({
  id: s.id,
  title: s.title,
  state: s.state,
  priority: null,
  created_at: mins(s.ago + 60),
  updated_at: mins(s.ago),
  author: { id: null, name: s.customer, email: null, type: 'user' },
  url: `https://app.intercom.com/a/apps/demo/conversations/${s.id}`,
  parts: [],
  category_id: s.cat,
  proposal_id: null,
  summary: s.summary,
  ai_confidence: s.conf,
  user_override: false,
  followup: null,
  note: null,
}));
