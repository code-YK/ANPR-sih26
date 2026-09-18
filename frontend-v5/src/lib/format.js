const clock = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const dateTime = new Intl.DateTimeFormat(undefined, {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const dateOnly = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", year: "numeric" });

function toDate(value) {
  if (value == null) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtClock(value) {
  const d = toDate(value);
  return d ? clock.format(d) : "—";
}

export function fmtDateTime(value) {
  const d = toDate(value);
  return d ? dateTime.format(d) : "—";
}

export function fmtDate(value) {
  const d = toDate(value);
  return d ? dateOnly.format(d) : "—";
}

/** "4s", "3m 12s", "2h 05m" */
export function fmtDuration(totalSeconds) {
  if (totalSeconds == null || !Number.isFinite(totalSeconds)) return "—";
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

export function fmtAgo(value, now = Date.now()) {
  const d = toDate(value);
  if (!d) return "—";
  const seconds = Math.round((now - d.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return fmtDate(d);
}

export function fmtConfidence(value) {
  return value == null ? "—" : value.toFixed(2);
}

export function fmtPercent(value, digits = 0) {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

/**
 * Groups an Indian registration mark for display the way it is stamped:
 * state · district · series · number (GJ 01 AB 1234). Anything that doesn't
 * fit the shape is shown exactly as read -- the plate text itself is never
 * altered, only spaced.
 */
export function plateGroups(plate) {
  if (!plate) return [];
  const raw = String(plate).toUpperCase().replace(/[^A-Z0-9?]/g, "");
  const match = raw.match(/^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})(\??)$/);
  if (!match) return [raw];
  return [match[1], match[2], match[3], match[4] + match[5]].filter(Boolean);
}

export function titleCase(value) {
  if (!value) return "";
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function humanize(value) {
  return value ? String(value).replaceAll("_", " ") : "";
}
