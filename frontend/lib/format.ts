import type { Filters } from "./types.ts";

export const EVENT_TYPES = [
  "model_release",
  "paper",
  "funding",
  "regulation",
  "research_breakthrough",
  "tool_release",
  "other",
];
export function label(value: string | null): string {
  if (!value) return "Awaiting analysis";
  return value
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}
export function safeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
export function publisher(value: string): string {
  const safe = safeUrl(value);
  return safe ? new URL(safe).hostname.replace(/^www\./, "") : "Source";
}
export function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      }).format(date);
}
export function relativeTime(value: string, now: string): string {
  const hours = Math.max(
    0,
    Math.floor((Date.parse(now) - Date.parse(value)) / 3_600_000),
  );
  if (!Number.isFinite(hours)) return "Date unavailable";
  return hours < 1
    ? "Just now"
    : hours < 24
      ? `${hours}h ago`
      : `${Math.floor(hours / 24)}d ago`;
}
export function parseFilters(
  input: Record<string, string | string[] | undefined>,
): Filters {
  const one = (key: string) =>
    typeof input[key] === "string" ? (input[key] as string) : "";
  const page = Number(one("page"));
  return {
    q: one("q").trim().slice(0, 200),
    topic: one("topic").slice(0, 60),
    following: one("following") === "true",
    window:
      one("window") === "today"
        ? "today"
        : one("window") === "all"
          ? "all"
          : "week",
    sort: one("sort") === "latest" ? "latest" : "ranked",
    event_type: EVENT_TYPES.includes(one("event_type"))
      ? one("event_type")
      : "",
    page: Number.isInteger(page) && page >= 1 && page <= 8334 ? page : 1,
  };
}
export function feedHref(
  filters: Filters,
  changes: Partial<Filters> = {},
): string {
  const merged = { ...filters, ...changes };
  const params = new URLSearchParams();
  Object.entries(merged).forEach(([key, value]) => {
    if (value !== "" && value !== false && !(key === "page" && value === 1))
      params.set(key, String(value));
  });
  return `/dashboard?${params.toString()}`;
}
