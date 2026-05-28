import type { NonActionableKind } from '@/types/api';

export const NON_ACTIONABLE_KIND_LABELS: Record<NonActionableKind, string> = {
  auto_reply: 'Auto-reply',
  thanks: 'Thanks',
  spam: 'Spam',
  out_of_office: 'Out of office',
  other: 'Other',
};
