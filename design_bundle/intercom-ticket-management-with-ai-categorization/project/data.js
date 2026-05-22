// Sample triage data + category taxonomy.
// Loaded as a normal script (no JSX), stashed on window.

window.TRIAGE_CATEGORIES = [
  { id: 'urgent',   label: 'Urgent',           swatch: 'oklch(0.62 0.20 25)' },
  { id: 'bug',      label: 'Bug',              swatch: 'oklch(0.56 0.18 285)' },
  { id: 'feature',  label: 'Feature Request',  swatch: 'oklch(0.66 0.13 205)' },
  { id: 'question', label: 'Question',         swatch: 'oklch(0.72 0.13 92)' },
  { id: 'billing',  label: 'Billing',          swatch: 'oklch(0.62 0.13 148)' },
  { id: 'complaint',label: 'Complaint',        swatch: 'oklch(0.66 0.16 50)' },
  { id: 'other',    label: 'Other',            swatch: 'oklch(0.65 0.00 0)' },
];

window.TRIAGE_STATES = ['open', 'snoozed', 'closed'];

// updated relative to "now" — minutes ago
const t = (m) => ({ updatedAgoMin: m });

window.TRIAGE_TICKETS = [
  { id: 'INT-48211', cat: 'urgent', conf: 0.97, state: 'open',
    customer: 'Priya Shankar', company: 'Northwind Labs', plan: 'Enterprise',
    title: 'Production webhook deliveries dropped at 14:02 UTC',
    summary: 'Customer reports webhook endpoint receiving zero events since 14:02 UTC across all workspaces. Status page still shows green.',
    lastMsg: 'We just lost all webhooks at 14:02. Nothing in the dashboard, nothing in the logs.',
    msgs: 8, ...t(4) },

  { id: 'INT-48207', cat: 'urgent', conf: 0.91, state: 'open',
    customer: 'Marco Wei', company: 'Halcyon Health', plan: 'Enterprise',
    title: 'SSO login loop after SAML metadata refresh',
    summary: 'Entire org cannot authenticate through Okta SAML since last metadata sync. Users hit a redirect loop and are locked out.',
    lastMsg: 'Whole team is locked out. We have a customer demo in 30 minutes.',
    msgs: 5, ...t(11) },

  { id: 'INT-48198', cat: 'bug', conf: 0.88, state: 'open',
    customer: 'Sofia Reyes', company: 'Pebble Studio', plan: 'Pro',
    title: 'Export CSV includes hidden rows in filtered view',
    summary: 'When the table has an active filter, the "Export visible" action exports the full dataset instead of the filtered subset.',
    lastMsg: 'I filtered to October but the CSV has all 12 months.',
    msgs: 3, ...t(38) },

  { id: 'INT-48191', cat: 'bug', conf: 0.84, state: 'open',
    customer: 'Daniel Bauer', company: 'Schauer & Söhne', plan: 'Pro',
    title: 'Time zone offset wrong in scheduled-send digest',
    summary: 'Digest emails set to deliver at 09:00 local time arrive at 02:00 for users in CET. Started after last week\u2019s release.',
    lastMsg: 'The 9am digest keeps showing up at 2am. Same for two other admins here.',
    msgs: 4, ...t(72) },

  { id: 'INT-48180', cat: 'bug', conf: 0.79, state: 'open',
    customer: 'Aiko Tanaka', company: 'Mejiro AI', plan: 'Pro',
    title: 'Drag-and-drop reorder snaps back on Safari 17',
    summary: 'Reordering cards by drag works visually but releases revert position. Reproduced on Safari 17.4 macOS, not Chrome.',
    lastMsg: 'Tried clearing cache. Same behavior on two machines.',
    msgs: 6, ...t(95) },

  { id: 'INT-48176', cat: 'feature', conf: 0.93, state: 'open',
    customer: 'Lena Hofmann', company: 'Atlas Cargo', plan: 'Enterprise',
    title: 'Bulk-edit tags across multiple records',
    summary: 'Requests a multi-select on the records list with a tag editor that applies/removes tags in one action. Will pay for it.',
    lastMsg: 'Doing this 600 rows at a time. Would buy a higher tier for it.',
    msgs: 2, ...t(140) },

  { id: 'INT-48172', cat: 'feature', conf: 0.86, state: 'open',
    customer: 'James Okafor', company: 'Verdant Realty', plan: 'Pro',
    title: 'Slack notification routing per workspace',
    summary: 'Wants per-workspace Slack channel mapping; currently all notifications fan out to one global channel.',
    lastMsg: 'Our ops team can\u2019t tell which workspace fired the alert.',
    msgs: 3, ...t(210) },

  { id: 'INT-48165', cat: 'feature', conf: 0.74, state: 'open',
    customer: 'Helena Voss', company: 'Brightline Capital', plan: 'Enterprise',
    title: 'Audit log export to S3 bucket',
    summary: 'Compliance team needs a scheduled export of the audit log to a customer-owned S3 bucket, weekly cadence.',
    lastMsg: 'SOC 2 auditor is asking. We need this by end of quarter.',
    msgs: 4, ...t(265) },

  { id: 'INT-48160', cat: 'question', conf: 0.89, state: 'open',
    customer: 'Renee Ortiz', company: 'Cloudleaf', plan: 'Pro',
    title: 'How does the API rate-limit interact with bursts?',
    summary: 'Asks whether the documented 600 req/min limit is a hard cap or token-bucket. Plans a backfill of ~2M records.',
    lastMsg: 'If we burst 4k requests in 5s, do we get rejected or queued?',
    msgs: 1, ...t(58) },

  { id: 'INT-48157', cat: 'question', conf: 0.82, state: 'open',
    customer: 'Tom Greaves', company: 'Riverbend', plan: 'Starter',
    title: 'Can a workspace have more than one owner?',
    summary: 'Wants to add a co-owner to their workspace before going on parental leave. Asks about permission scope.',
    lastMsg: 'I\u2019m out for 4 months. Can my co-founder have the same access?',
    msgs: 2, ...t(305) },

  { id: 'INT-48154', cat: 'question', conf: 0.71, state: 'open',
    customer: 'Inés Carrasco', company: 'Mariposa Co.', plan: 'Pro',
    title: 'Migrating from the legacy v1 API',
    summary: 'New engineer onboarding; asks for a migration guide from /v1/records to the v2 cursor-paginated endpoints.',
    lastMsg: 'Is there a side-by-side cheat sheet? Our integration is 3 years old.',
    msgs: 1, ...t(420) },

  { id: 'INT-48150', cat: 'billing', conf: 0.95, state: 'open',
    customer: 'Yuki Sato', company: 'Tessellate', plan: 'Pro',
    title: 'Charged twice for May invoice',
    summary: 'Customer sees two identical $480 charges on their card statement for the May invoice. Asks for one to be refunded.',
    lastMsg: 'Statement shows two charges, same amount, same day.',
    msgs: 2, ...t(85) },

  { id: 'INT-48144', cat: 'billing', conf: 0.88, state: 'open',
    customer: 'Marcus Lindqvist', company: 'Norra AB', plan: 'Enterprise',
    title: 'Add VAT number to invoice line',
    summary: 'Finance team needs the Swedish VAT number printed on invoices retroactively for Q1 for tax filing.',
    lastMsg: 'Need this before Friday. Can you reissue Q1?',
    msgs: 3, ...t(180) },

  { id: 'INT-48139', cat: 'complaint', conf: 0.81, state: 'open',
    customer: 'Naomi Patel', company: 'Lumen Press', plan: 'Pro',
    title: 'Onboarding flow is "deliberately confusing"',
    summary: 'Long-form negative feedback about the multi-step setup. Specifically calls out the workspace invite step as misleading.',
    lastMsg: 'I lost half my evening to step 3. Why is this the default?',
    msgs: 5, ...t(155) },

  { id: 'INT-48133', cat: 'complaint', conf: 0.69, state: 'open',
    customer: 'Greg Holloway', company: '—', plan: 'Free',
    title: 'Support response times "unacceptable"',
    summary: 'Complaint about waiting 36 hours for a reply on a Pro-trial question. Threatens to evaluate competitor product.',
    lastMsg: 'I\u2019ll just switch to the other one if no one\u2019s home here.',
    msgs: 1, ...t(240) },

  { id: 'INT-48128', cat: 'other', conf: 0.42, state: 'open',
    customer: 'Anya Volkov', company: 'Selkie Studio', plan: 'Pro',
    title: 'Forwarded internal thread — context unclear',
    summary: 'Customer forwarded a long internal email chain without a question. Mentions an integration with their own product but no specific ask.',
    lastMsg: '(forwarded message — see thread)',
    msgs: 1, ...t(330) },

  { id: 'INT-48119', cat: 'other', conf: 0.35, state: 'open',
    customer: 'unknown', company: '—', plan: 'Free',
    title: '(no subject)',
    summary: 'Single-word message "hello?" sent from a trial account. No further context provided.',
    lastMsg: 'hello?',
    msgs: 1, ...t(510) },

  // snoozed
  { id: 'INT-48105', cat: 'feature', conf: 0.78, state: 'snoozed',
    customer: 'Bo Hansen', company: 'Fjord Logistics', plan: 'Pro',
    title: 'Webhook retries with exponential backoff',
    summary: 'Snoozed pending eng spec. Customer wants retry policy configurable per endpoint.',
    lastMsg: 'Any update on the retry policy thing?',
    msgs: 7, ...t(640) },

  { id: 'INT-48091', cat: 'billing', conf: 0.84, state: 'snoozed',
    customer: 'Camille Doré', company: 'Atelier 9', plan: 'Pro',
    title: 'Annual renewal quote',
    summary: 'Waiting on AE to send a renewal quote with the discount applied.',
    lastMsg: 'Just bumping this — any update on the quote?',
    msgs: 4, ...t(700) },

  // closed
  { id: 'INT-48070', cat: 'bug', conf: 0.91, state: 'closed',
    customer: 'Iris Chen', company: 'Pampas', plan: 'Pro',
    title: 'Avatar upload silently fails on >5MB',
    summary: 'Fixed in 2026.5.2; closed by operator.',
    lastMsg: 'Confirmed working now, thanks.',
    msgs: 6, ...t(420) },
];

// Compute updated_at as a real Date for slider math.
const NOW = Date.now();
window.TRIAGE_TICKETS.forEach(tk => {
  tk.updatedAt = new Date(NOW - tk.updatedAgoMin * 60 * 1000);
});
window.TRIAGE_NOW = NOW;

// Quick lookup
window.TRIAGE_CAT_BY_ID = Object.fromEntries(window.TRIAGE_CATEGORIES.map(c => [c.id, c]));

// ─── Follow-up seeds + notes ───────────────────────────────────────────────
// One alarm fires 12s after load so the user immediately sees the system work.
window.__triageFollowups = window.__triageFollowups || {
  'INT-48211': { dueAt: NOW + 12 * 1000,        fired: false, reason: 'Eng on-call ETA' },
  'INT-48207': { dueAt: NOW + 8 * 60 * 1000,    fired: false, reason: 'SSO bridge retest' },
  'INT-48150': { dueAt: NOW + 45 * 60 * 1000,   fired: false, reason: 'Refund confirmation' },
};

// Sample next-step notes so the feature reads as populated, not empty.
window.__triageNotes = window.__triageNotes || {
  'INT-48211': '1. Page @on-call infra\n2. Check webhook queue depth in Grafana\n3. Reply with workaround (manual replay endpoint)',
  'INT-48207': 'Asked customer to share IdP metadata diff. Waiting on attachment before we re-import.',
  'INT-48191': 'Probable regression in 2026.5.1 — flagged for QA, no customer action yet.',
};

// Quick action presets shown in the flyout's Notes section.
window.TRIAGE_NEXT_STEPS = [
  'Page @on-call',
  'Reply with workaround',
  'Escalate to AE',
  'Ask for repro / logs',
  'Wait for customer',
  'Route to Eng triage',
  'Refund / credit',
];

// Follow-up preset durations (minutes).
window.TRIAGE_FOLLOWUP_PRESETS = [
  { label: '15m',  min: 15 },
  { label: '1h',   min: 60 },
  { label: '4h',   min: 240 },
  { label: 'EOD',  min: 480 },
  { label: '24h',  min: 1440 },
];

// Format helpers
window.formatAgo = (mins) => {
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  const h = Math.floor(mins / 60);
  if (h < 24) return h + 'h ago';
  const d = Math.floor(h / 24);
  if (d < 30) return d + 'd ago';
  return Math.floor(d / 30) + 'mo ago';
};

// Countdown to a future timestamp (ms). Returns 'due' / 'overdue' for past.
window.formatCountdown = (msUntil) => {
  if (msUntil <= 0) {
    const over = Math.floor(-msUntil / 1000);
    if (over < 60) return 'due now';
    if (over < 3600) return Math.floor(over / 60) + 'm overdue';
    return Math.floor(over / 3600) + 'h overdue';
  }
  const sec = Math.floor(msUntil / 1000);
  if (sec < 60) return 'in ' + sec + 's';
  const min = Math.floor(sec / 60);
  if (min < 60) return 'in ' + min + 'm';
  const hr = Math.floor(min / 60);
  if (hr < 24) return 'in ' + hr + 'h';
  return 'in ' + Math.floor(hr / 24) + 'd';
};

// Soft alarm tone via WebAudio — two-note ping, ~700ms.
window.playTriageAlarm = () => {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    window.__triageAudio = window.__triageAudio || new Ctx();
    const ctx = window.__triageAudio;
    if (ctx.state === 'suspended') ctx.resume();
    const now = ctx.currentTime;
    [[880, 0], [1175, 0.18]].forEach(([freq, t0]) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = freq;
      g.gain.setValueAtTime(0, now + t0);
      g.gain.linearRampToValueAtTime(0.18, now + t0 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, now + t0 + 0.5);
      o.connect(g).connect(ctx.destination);
      o.start(now + t0);
      o.stop(now + t0 + 0.55);
    });
  } catch (e) { /* no audio, no problem */ }
};
