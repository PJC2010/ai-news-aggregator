import "server-only";
import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { createClient, authConfigured } from "./supabase/server";
import { demoFeed, demoEvents, demoProfile } from "./demo";
import { isDemoMode } from "./runtime";
import type { Feed, Filters, NewsEvent, Profile } from "./types";

export const isDemo = isDemoMode;
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export const accessToken = cache(async (): Promise<string | null> => {
  if (isDemo()) return null;
  if (!authConfigured()) redirect("/login?setup=required");
  const client = await createClient();
  const {
    data: { user },
    error,
  } = await client.auth.getUser();
  if (error || !user) redirect("/login");
  const {
    data: { session },
  } = await client.auth.getSession();
  if (!session) redirect("/login");
  return session.access_token;
});
export async function backend<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  if (isDemo()) throw new Error("Demo mode cannot contact the live backend");
  const token = await accessToken();
  const base = new URL(process.env.BACKEND_URL || "http://127.0.0.1:8000");
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password
  )
    throw new Error("Invalid backend configuration");
  let response: Response;
  try {
    response = await fetch(new URL(path, base), {
      ...init,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(15_000),
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
  } catch {
    throw new ApiError(
      503,
      "The news service is temporarily unavailable. Please try again.",
    );
  }
  if (response.status === 401) redirect("/login?expired=true");
  if (!response.ok)
    throw new ApiError(
      response.status,
      response.status === 422
        ? "Check your topic selection and try again."
        : "The news service is temporarily unavailable. Please try again.",
    );
  return response.json() as Promise<T>;
}
export const getProfile = cache(async (): Promise<Profile> => {
  if (!isDemo()) return backend<Profile>("/me");
  const raw = (await cookies()).get("demo-topics")?.value;
  let topics = demoProfile.topics;
  try {
    const values: unknown = JSON.parse(raw || "null");
    if (
      Array.isArray(values) &&
      values.length <= 3 &&
      values.every(
        (value) =>
          typeof value === "string" &&
          demoProfile.available_topics.some((topic) => topic.id === value),
      )
    )
      topics = [...new Set(values)];
  } catch {
    /* Invalid sample preferences reset to defaults. */
  }
  return { ...demoProfile, topics };
});
export async function getFeed(filters: Filters): Promise<Feed> {
  if (isDemo()) return demoFeed(filters, (await getProfile()).topics);
  const params = new URLSearchParams({
    limit: "12",
    offset: String((filters.page - 1) * 12),
    sort: filters.sort,
    window: filters.window,
    following: String(filters.following),
  });
  for (const key of ["q", "topic", "event_type"] as const)
    if (filters[key]) params.set(key, filters[key]);
  return backend<Feed>(`/feed?${params}`);
}
export async function getEvent(id: string): Promise<NewsEvent | null> {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
  )
    return null;
  if (isDemo()) return demoEvents.find((item) => item.id === id) || null;
  try {
    return await backend<NewsEvent>(`/feed/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
