// Desktop notification helper — a thin wrapper over the browser Notification
// API. The alarm loop uses it to surface a follow-up firing while the browser
// tab is not focused. The enable/disable preference lives in the tweaks store;
// this module deals only with the browser-level permission + construction.

/** True when the browser exposes the Notification API. */
export function supported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window;
}

/** Current permission state — 'denied' when notifications are unsupported. */
export function permission(): NotificationPermission {
  return supported() ? Notification.permission : 'denied';
}

/** Prompt for permission. Resolves to 'denied' when unsupported or on error. */
export async function requestPermission(): Promise<NotificationPermission> {
  if (!supported()) return 'denied';
  try {
    return await Notification.requestPermission();
  } catch {
    return 'denied';
  }
}

/**
 * Show a desktop notification. No-op unless permission is granted. `tag`
 * dedupes — a later notification with the same tag replaces the earlier one
 * rather than stacking, so a re-fired follow-up does not pile up. Wrapped in
 * try/catch: some browsers throw from the constructor, and that must never
 * break the once-per-second alarm tick.
 */
export function notify(
  title: string,
  body: string,
  tag: string,
  onClick: () => void,
): void {
  if (permission() !== 'granted') return;
  try {
    const n = new Notification(title, { body, tag });
    n.onclick = () => {
      window.focus();
      onClick();
      n.close();
    };
  } catch {
    // Swallowed — the in-app alarm banner still shows.
  }
}
