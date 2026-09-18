import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight, Layers3 } from "lucide-react";
import { notFound } from "next/navigation";
import { getPublicEvent } from "@/lib/public-api";
import { dateLabel, label, publisher, safeUrl } from "@/lib/format";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const event = await getPublicEvent(id);
  if (!event) return { title: "Event not found", robots: { index: false } };
  const description = event.summary || `Source coverage for ${event.title}.`;
  return {
    title: event.title,
    description,
    alternates: { canonical: `/events/${id}` },
    openGraph: { title: event.title, description, url: `/events/${id}`, type: "article", publishedTime: event.published_at },
  };
}

export default async function PublicEventPage({ params }: Props) {
  const { id } = await params;
  const event = await getPublicEvent(id);
  if (!event) notFound();
  const canonical = new URL(`/events/${id}`, process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").toString();
  const structuredData = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    headline: event.title,
    datePublished: event.published_at,
    description: event.summary,
    mainEntityOfPage: canonical,
    isBasedOn: safeUrl(event.primary_link) || undefined,
    publisher: { "@type": "Organization", name: "Signal" },
  };
  return (
    <article className="public-detail">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData).replace(/</g, "\\u003c") }} />
      <Link href="/feed" className="back-link"><ArrowLeft size={16} /> Back to public feed</Link>
      <header>
        <div className="card-meta"><span className={`tag tag-${event.event_type || "pending"}`}>{label(event.event_type)}</span><span>{dateLabel(event.published_at)} · UTC</span><span><Layers3 size={14} /> {event.source_count} sources</span></div>
        <h1>{event.title}</h1>
        {safeUrl(event.primary_link) && <a className="text-link" href={event.primary_link} target="_blank" rel="noopener noreferrer">Read the primary source at {publisher(event.primary_link)} <ArrowUpRight size={14} /></a>}
      </header>
      <div className="public-detail-grid">
        <div>
          <section className="summary-panel"><span className="eyebrow">THE PUBLIC BRIEF</span><p>{event.summary || "A public summary is not available yet. The primary source remains available above."}</p></section>
          <section className="coverage"><div className="section-heading"><h2>Source coverage</h2><span className="count-pill">Up to {event.coverage_limit || 10} records</span></div>
            {(event.coverage || []).map((source, index) => <div className="coverage-row" key={`${source.url}-${index}`}><span className="source-number">{String(index + 1).padStart(2, "0")}</span><div><span className="source-name">{source.source}</span><a href={safeUrl(source.url) || undefined} target="_blank" rel="noopener noreferrer">{source.title}</a></div><ArrowUpRight size={18} /></div>)}
          </section>
        </div>
        <aside className="public-score"><span className="eyebrow">SIGNIFICANCE</span><strong>{event.significance_score ?? "—"}<small>/ 10</small></strong><p>A concise public signal, not a confidence score.</p><Link className="button primary" href="/login">Unlock your personal feed</Link></aside>
      </div>
    </article>
  );
}
