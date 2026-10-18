import type { Show } from './shows';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
export const WEEKDAY_OPTIONS = WEEKDAYS.map((label, value) => ({ value, label }));

export function formatDateTime(iso: string | null, timeZone?: string): string {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone,
    }).format(new Date(iso));
  } catch {
    // An unknown time zone name must not break the page.
    return new Date(iso).toLocaleString();
  }
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(iso));
}

function ordinal(n: number): string {
  const rest = n % 100;
  if (rest >= 11 && rest <= 13) return `${n}th`;
  return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`;
}

/** "Manual", "Daily 08:00", "Weekly Mon 08:00", "Monthly on the 5th 08:00". */
export function describeSchedule(
  show: Pick<Show, 'schedule_kind' | 'schedule_time' | 'schedule_weekday' | 'schedule_monthday'>,
): string {
  const time = show.schedule_time?.slice(0, 5) ?? '';
  switch (show.schedule_kind) {
    case 'manual':
      return 'Manual';
    case 'daily':
      return `Daily ${time}`.trim();
    case 'weekly': {
      const day = WEEKDAYS[show.schedule_weekday ?? 0]?.slice(0, 3) ?? '';
      return `Weekly ${day} ${time}`.trim();
    }
    case 'monthly':
      return `Monthly on the ${ordinal(show.schedule_monthday ?? 1)} ${time}`.trim();
  }
}
