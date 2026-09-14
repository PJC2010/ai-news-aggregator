import { NextRequest, NextResponse } from "next/server";
import { authConfigured, createClient } from "@/lib/supabase/server";
import { isDemo } from "@/lib/api";

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  if (!isDemo() && authConfigured() && code) {
    const client = await createClient();
    const { error } = await client.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.redirect(
    new URL("/login?error=invalid_link", request.url),
  );
}
