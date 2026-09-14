"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, backend, getProfile, isDemo } from "@/lib/api";
import { authConfigured, createClient } from "@/lib/supabase/server";

export type FormState = { error?: string; success?: string };
export async function updateTopics(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const profile = await getProfile();
  const topics = form.getAll("topics");
  if (
    topics.length > profile.topic_limit ||
    new Set(topics).size !== topics.length ||
    topics.some(
      (value) =>
        typeof value !== "string" ||
        !profile.available_topics.some((topic) => topic.id === value),
    )
  )
    return {
      error: `Choose up to ${profile.topic_limit} topics from the list.`,
    };
  if (isDemo()) {
    (await cookies()).set("demo-topics", JSON.stringify(topics), {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    });
  } else {
    try {
      await backend("/me/topics", {
        method: "PUT",
        body: JSON.stringify({ topics }),
      });
    } catch (error) {
      if (error instanceof ApiError) return { error: error.message };
      throw error;
    }
  }
  revalidatePath("/", "layout");
  return {
    success: isDemo()
      ? "Sample preferences saved in this browser."
      : "Your topics have been saved.",
  };
}
export async function sendSignInLink(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  if (isDemo())
    return { error: "Sign-in is disabled in the sample workspace." };
  if (!authConfigured())
    return { error: "Sign-in has not been configured for this workspace yet." };
  const email = form.get("email");
  if (
    typeof email !== "string" ||
    email.length > 320 ||
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
  )
    return { error: "Enter a valid email address." };
  let appUrl: URL;
  try {
    appUrl = new URL(process.env.APP_URL || "http://localhost:3000");
    if (
      appUrl.username ||
      appUrl.password ||
      (appUrl.protocol !== "https:" &&
        !(
          appUrl.protocol === "http:" &&
          ["localhost", "127.0.0.1"].includes(appUrl.hostname)
        ))
    )
      throw new Error();
  } catch {
    return { error: "The sign-in redirect is not configured correctly." };
  }
  const client = await createClient();
  const { error } = await client.auth.signInWithOtp({
    email: email.trim(),
    options: { emailRedirectTo: `${appUrl.origin}/auth/callback` },
  });
  if (error)
    return {
      error: "We could not send the link. Please wait a moment and try again.",
    };
  return {
    success:
      "Check your email for a sign-in link. Open it in this browser to continue.",
  };
}
export async function signOut() {
  if (!isDemo() && authConfigured()) {
    const client = await createClient();
    await client.auth.signOut();
  }
  redirect("/login");
}
