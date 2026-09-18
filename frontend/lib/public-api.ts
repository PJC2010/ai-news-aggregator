import "server-only";
import { cache } from "react";
import { demoEvents } from "./demo";
import type { PublicEvent, PublicFeed } from "./types";

const validId = (id: string) =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);

function fromDemo(event: (typeof demoEvents)[number]): PublicEvent {
  return {
    id: event.id,
    title: event.primary_article.title,
    summary: event.summary,
    significance_score: event.significance_score,
    event_type: event.event_type,
    published_at: event.latest_published_at,
    primary_link: event.primary_article.url,
    source_count: event.cluster_size,
    coverage: event.coverage?.slice(0, 10).map((source) => ({
      title: source.title,
      source: source.source,
      url: source.url,
    })),
    coverage_limit: 10,
  };
}

async function publicBackend<T>(path: string): Promise<T> {
  const base = new URL(process.env.BACKEND_URL || "http://127.0.0.1:8000");
  if (!["http:", "https:"].includes(base.protocol) || base.username || base.password)
    throw new Error("Invalid backend configuration");
  const response = await fetch(new URL(path, base), {
    next: { revalidate: 300 },
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`Public news request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export const getPublicFeed = cache(async (page = 1): Promise<PublicFeed> => {
  const safePage = Number.isSafeInteger(page) && page > 0 ? Math.min(page, 834) : 1;
  const limit = 12;
  if (process.env.DASHBOARD_DEMO_MODE === "true") {
    const offset = (safePage - 1) * limit;
    return {
      total: demoEvents.length,
      limit,
      offset,
      as_of: new Date().toISOString(),
      items: demoEvents.slice(offset, offset + limit).map(fromDemo),
    };
  }
  return publicBackend(`/public/feed?limit=${limit}&offset=${(safePage - 1) * limit}`);
});

export const getPublicEvent = cache(async (id: string): Promise<PublicEvent | null> => {
  if (!validId(id)) return null;
  if (process.env.DASHBOARD_DEMO_MODE === "true") {
    const event = demoEvents.find((item) => item.id === id);
    return event ? fromDemo(event) : null;
  }
  try {
    return await publicBackend(`/public/events/${id}`);
  } catch {
    return null;
  }
});
