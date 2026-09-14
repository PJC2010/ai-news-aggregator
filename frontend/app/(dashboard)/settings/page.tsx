import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, UserRound } from "lucide-react";
import { getProfile, isDemo } from "@/lib/api";
import { TopicForm } from "@/components/forms";

export const metadata: Metadata = { title: "My topics" };
export default async function Settings() {
  const profile = await getProfile();
  return (
    <div className="settings-page">
      <Link href="/" className="back-link">
        <ArrowLeft size={16} />
        Back to overview
      </Link>
      <div className="page-intro">
        <div>
          <div className="eyebrow">
            <span className="tiny-rule" />
            MAKE IT YOURS
          </div>
          <h1>Follow your curiosity.</h1>
          <p>A focused feed starts with the things you care about.</p>
        </div>
      </div>
      <div className="settings-panel">
        <TopicForm profile={profile} demo={isDemo()} />
      </div>
      <div className="account-panel">
        <UserRound size={22} />
        <div>
          <strong>{isDemo() ? "Sample reader" : profile.email}</strong>
          <p>
            {profile.subscription_tier === "free"
              ? "Free account · Up to 3 topics"
              : "Pro account · All available topics"}
          </p>
        </div>
        <span className="count-pill">
          {profile.subscription_tier.toUpperCase()}
        </span>
      </div>
      <p className="settings-note">
        Your Following feed matches topic keywords in event titles and
        summaries. These are broad filters; they may miss relevant stories.
        Reading preferences do not generate additional AI analysis.
      </p>
    </div>
  );
}
