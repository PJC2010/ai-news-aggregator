import type { MetadataRoute } from "next";
import { getPublicFeed } from "@/lib/public-api";

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
  const feed = await getPublicFeed(1);
  return [
    { url: new URL("/", base).toString(), changeFrequency: "daily", priority: 1 },
    { url: new URL("/feed", base).toString(), changeFrequency: "hourly", priority: 0.9 },
    ...feed.items.map((event) => ({ url: new URL(`/events/${event.id}`, base).toString(), lastModified: new Date(event.published_at), changeFrequency: "weekly" as const, priority: 0.7 })),
  ];
}
