import type { BusinessConfig, DayHours } from "./types.js";

const DAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;
type DayKey = (typeof DAY_KEYS)[number];

/** Local weekday key and minutes-since-midnight for `date` in `timezone`. */
function localParts(date: Date, timezone: string): { day: DayKey; minutes: number } {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = formatter.formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";

  const weekday = get("weekday").toLowerCase().slice(0, 3) as DayKey;
  // Intl can render midnight as "24" in hour12:false; normalise it to 0.
  const hour = Number(get("hour")) % 24;
  const minute = Number(get("minute"));
  return { day: weekday, minutes: hour * 60 + minute };
}

function parseRange(range: DayHours): { open: number; close: number } | null {
  if (!range) return null;
  const match = /^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$/.exec(range.trim());
  if (!match) return null;
  const [, openHour, openMinute, closeHour, closeMinute] = match as unknown as string[];
  return {
    open: Number(openHour) * 60 + Number(openMinute),
    close: Number(closeHour) * 60 + Number(closeMinute),
  };
}

/** True when `date` falls inside the configured opening hours. */
export function isWithinBusinessHours(config: BusinessConfig, date = new Date()): boolean {
  const { day, minutes } = localParts(date, config.timezone);
  const range = parseRange(config.businessHours[day]);
  if (!range) return false;
  // Overnight ranges such as "18:00-02:00" wrap past midnight.
  if (range.close <= range.open) {
    return minutes >= range.open || minutes < range.close;
  }
  return minutes >= range.open && minutes < range.close;
}

/**
 * Human-readable opening hours with consecutive identical days grouped, so a
 * customer sees "Mon-Fri 9am-7pm" rather than seven separate entries.
 */
export function describeBusinessHours(config: BusinessConfig): string {
  const labels: Record<DayKey, string> = {
    mon: "Mon",
    tue: "Tue",
    wed: "Wed",
    thu: "Thu",
    fri: "Fri",
    sat: "Sat",
    sun: "Sun",
  };
  const ordered: DayKey[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

  const groups: { start: DayKey; end: DayKey; hours: DayHours }[] = [];
  for (const day of ordered) {
    const hours = config.businessHours[day] ?? null;
    const last = groups.at(-1);
    if (last && last.hours === hours) {
      last.end = day;
    } else {
      groups.push({ start: day, end: day, hours });
    }
  }

  return groups
    .map(({ start, end, hours }) => {
      const days = start === end ? labels[start] : `${labels[start]}-${labels[end]}`;
      return `${days} ${hours ?? "closed"}`;
    })
    .join(", ");
}
