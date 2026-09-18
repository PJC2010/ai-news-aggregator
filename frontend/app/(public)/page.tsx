import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Layers3, Radio, Sparkles } from "lucide-react";
import { getPublicFeed } from "@/lib/public-api";
import { PublicEventCard } from "@/components/public-event-card";

export const metadata: Metadata = {
  title: "AI news, with the signal separated from the noise",
  description: "A public, source-led view of the AI events worth knowing.",
  alternates: { canonical: "/" },
  openGraph: { title: "Signal — AI news that matters", description: "A public, source-led view of important AI events.", url: "/", type: "website" },
};

export default async function LandingPage() {
  const feed = await getPublicFeed(1);
  return (
    <>
      <section className="public-hero">
        <div className="eyebrow"><Radio size={14} /> PUBLIC AI INTELLIGENCE</div>
        <h1>See what changed.<br />Understand why it matters.</h1>
        <p>Important AI events, concise summaries, and the source coverage behind them—open to every reader.</p>
        <div className="hero-actions">
          <Link className="button primary" href="/feed">Browse the public feed <ArrowRight size={16} /></Link>
          <Link className="button secondary" href="/login">Personalize your signal</Link>
        </div>
        <div className="public-principles">
          <span><Layers3 size={17} /> Multiple sources, one event</span>
          <span><Sparkles size={17} /> Clear significance, no hidden session</span>
        </div>
      </section>
      <section className="public-section">
        <div className="section-heading"><div><span className="eyebrow">LATEST EVENTS</span><h2>The public signal</h2></div><Link href="/feed" className="text-link">View all <ArrowRight size={15} /></Link></div>
        <div className="public-grid">{feed.items.slice(0, 3).map((event) => <PublicEventCard event={event} key={event.id} />)}</div>
      </section>
    </>
  );
}
