// Time formatting helpers ported from the design's data.js.

export function formatAgo(ms: number): string {
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

export function formatAgoFromDate(d: string | Date): string {
  const t = typeof d === 'string' ? new Date(d) : d;
  return formatAgo(Date.now() - t.getTime());
}

export function formatCountdown(msUntil: number): string {
  if (msUntil <= 0) {
    const over = Math.floor(-msUntil / 1000);
    if (over < 60) return 'due now';
    if (over < 3600) return `${Math.floor(over / 60)}m overdue`;
    return `${Math.floor(over / 3600)}h overdue`;
  }
  const sec = Math.floor(msUntil / 1000);
  if (sec < 60) return `in ${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `in ${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `in ${hr}h`;
  return `in ${Math.floor(hr / 24)}d`;
}
