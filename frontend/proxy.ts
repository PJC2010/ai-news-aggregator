import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const publicHits = new Map<string, { count: number; reset: number }>();
const PUBLIC_PATH = /^(?:\/$|\/feed\/?$|\/events\/[^/]+\/?$|\/sitemap\.xml$)/;

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  if (PUBLIC_PATH.test(request.nextUrl.pathname)) {
    const now = Date.now();
    const key = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
    const hit = publicHits.get(key);
    const bucket = !hit || hit.reset <= now ? { count: 1, reset: now + 60_000 } : { ...hit, count: hit.count + 1 };
    publicHits.set(key, bucket);
    if (publicHits.size > 10_000) {
      for (const [address, value] of publicHits) if (value.reset <= now) publicHits.delete(address);
      if (publicHits.size > 10_000) publicHits.delete(publicHits.keys().next().value!);
    }
    if (bucket.count > 60)
      return new NextResponse("Too many requests", { status: 429, headers: { "Retry-After": String(Math.ceil((bucket.reset - now) / 1000)), "Cache-Control": "no-store" } });
    response.headers.set("Cache-Control", "public, s-maxage=300, stale-while-revalidate=600");
    response.headers.set("X-RateLimit-Limit", "60");
    response.headers.set("X-RateLimit-Remaining", String(Math.max(0, 60 - bucket.count)));
    return response;
  }
  response.headers.set("Cache-Control", "private, no-store");
  if (
    process.env.DASHBOARD_DEMO_MODE === "true" ||
    !process.env.SUPABASE_URL ||
    !process.env.SUPABASE_PUBLISHABLE_KEY
  )
    return response;
  const supabase = createServerClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_PUBLISHABLE_KEY,
    {
      cookieOptions: {
        httpOnly: true,
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
      },
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (values) => {
          values.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          response.headers.set("Cache-Control", "private, no-store");
          values.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );
  // This refreshes verified sessions. Pages/actions independently verify identity.
  await supabase.auth.getClaims();
  return response;
}
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
