/** Robust time parsing + relative timestamps. */

const MS_THRESHOLD = 1e12;

/**
 * Coerce a backend timestamp into epoch milliseconds.
 *
 * Backend rows arrive in mixed shapes: ISO-8601 strings, UNIX epoch
 * *seconds* floats (e.g. conversation created_at = time.time()), or ms
 * numbers. Feeding seconds into `new Date()` silently renders as 1970 —
 * the classic "1/21/1970" placeholder bug — so auto-detect and convert.
 */
export function toEpochMs(input: string | number | Date | null | undefined): number | null {
  if (input == null || input === '') return null;
  if (input instanceof Date) return isNaN(input.getTime()) ? null : input.getTime();
  if (typeof input === 'number') {
    if (!isFinite(input) || input <= 0) return null;
    const ms = Math.abs(input) < MS_THRESHOLD ? input * 1000 : input;
    return isNaN(ms) ? null : ms;
  }
  const num = Number(input);
  if (typeof input === 'string' && /^-?\d+(\.\d+)?$/.test(input.trim())) {
    return toEpochMs(num);
  }
  const d = new Date(input);
  return isNaN(d.getTime()) ? null : d.getTime();
}

/** Parse any backend timestamp into a Date, or null when unparseable. */
export function toDate(input: string | number | Date | null | undefined): Date | null {
  const ms = toEpochMs(input);
  return ms == null ? null : new Date(ms);
}

/**
 * Human-friendly relative label ("Just now", "5 min ago", "Yesterday",
 * "Aug 3") for live telemetry and history surfaces.
 */
export function formatRelativeTime(input: string | number | Date | null | undefined): string {
  const ms = toEpochMs(input);
  if (ms == null) return '';
  const diff = Date.now() - ms;
  const abs = Math.abs(diff);
  if (abs < 30_000) return 'Just now';
  const minutes = Math.floor(abs / 60_000);
  if (minutes < 60) return minutes === 1 ? '1 min ago' : `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  const d = new Date(ms);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/** Compact wall-clock label for chart axes / timestamps (HH:MM:SS). */
export function formatClock(input: string | number | Date | null | undefined): string {
  const ms = toEpochMs(input);
  if (ms == null) return '';
  return new Date(ms).toLocaleTimeString(undefined, { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
