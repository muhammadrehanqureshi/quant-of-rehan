/**
 * Formatting, in the one timezone this project uses (SO-8).
 *
 * The wire already carries the Karachi offset, but every label is still
 * formatted explicitly in `Asia/Karachi`: a viewer whose laptop is set to
 * another zone must see the exchange's clock, never their own. Prices are
 * formatted with a grouped thousands separator and a trimmed decimal tail,
 * and volumes are compacted so a busy tape does not widen the axis.
 */

const KARACHI = "Asia/Karachi";

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: KARACHI,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: KARACHI,
  day: "2-digit",
  month: "short",
});

const stampFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: KARACHI,
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatClock(iso: string): string {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) {
    return iso;
  }
  return timeFormat.format(moment);
}

export function formatDay(iso: string): string {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) {
    return iso;
  }
  return dayFormat.format(moment);
}

export function formatStamp(iso: string): string {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) {
    return iso;
  }
  return stampFormat.format(moment);
}

export function formatPrice(value: number, decimals = 2): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return value.toLocaleString("en-GB", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatVolume(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(2)}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  return String(Math.round(value));
}

/** A short, plain sentence about a duration in minutes. */
export function formatMinutes(minutes: number): string {
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}
