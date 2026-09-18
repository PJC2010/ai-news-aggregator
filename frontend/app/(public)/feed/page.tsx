import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { PublicEventCard } from "@/components/public-event-card";
import { getPublicFeed } from "@/lib/public-api";

export const metadata: Metadata = { title: "Public AI event feed", description: "Browse the latest public AI events and their source coverage.", alternates: { canonical: "/feed" }, openGraph: { title: "Public AI event feed · Signal", description: "The latest important AI events, summarized and sourced.", url: "/feed", type: "website" } };

export default async function PublicFeedPage({ searchParams }: { searchParams: Promise<{ page?: string }> }) {
  const raw = (await searchParams).page;
  const page = raw && /^\d+$/.test(raw) ? Math.max(1, Math.min(834, Number(raw))) : 1;
  const feed = await getPublicFeed(page);
  const pages = Math.max(1, Math.ceil(feed.total / feed.limit));
  return (
    <section className="public-section public-feed">
      <div className="public-title"><span className="eyebrow">PUBLIC FEED</span><h1>AI events worth your attention.</h1><p>Read the brief, inspect the coverage, and follow the primary source.</p></div>
      <div className="public-grid">{feed.items.map((event) => <PublicEventCard event={event} key={event.id} />)}</div>
      <nav className="pagination" aria-label="Feed pagination">
        {page > 1 ? <Link className="button secondary" href={`/feed?page=${page - 1}`}><ArrowLeft size={15} /> Previous</Link> : <span />}
        <span>Page {page} of {pages}</span>
        {page < pages ? <Link className="button secondary" href={`/feed?page=${page + 1}`}>Next <ArrowRight size={15} /></Link> : <span />}
      </nav>
    </section>
  );
}
