import Link from "next/link";
import { ArrowUpRight, ArrowRight, Layers3 } from "lucide-react";
import type { NewsEvent } from "@/lib/types";
import { label, publisher, relativeTime, safeUrl } from "@/lib/format";

export function SourceLink({
  url,
  children,
  className,
}: {
  url: string;
  children: React.ReactNode;
  className?: string;
}) {
  const href = safeUrl(url);
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
    >
      {children}
      <ArrowUpRight size={14} aria-hidden="true" />
    </a>
  ) : (
    <span className={className}>{children}</span>
  );
}
export function EventCard({
  event,
  now,
  featured = false,
}: {
  event: NewsEvent;
  now: string;
  featured?: boolean;
}) {
  const score = event.significance_score;
  return (
    <article className={`event-card ${featured ? "featured" : ""}`}>
      <div className="card-body">
        <div className="card-meta">
          <span className={`tag tag-${event.event_type || "pending"}`}>
            {label(event.event_type)}
          </span>
          <span>{relativeTime(event.latest_published_at, now)}</span>
          {featured && <span className="lead-label">LEADING THIS VIEW</span>}
        </div>
        <h2>
          <Link href={`/events/${event.id}`}>
            {event.primary_article.title}
          </Link>
        </h2>
        <p className="card-summary">
          {event.summary ||
            "The source material is available. A shared summary has not been generated yet."}
        </p>
        <div className="card-footer">
          <SourceLink url={event.primary_article.url}>
            {publisher(event.primary_article.url)}
          </SourceLink>
          <span>
            <Layers3 size={14} />
            {event.cluster_size}{" "}
            {event.cluster_size === 1 ? "article" : "articles"}
          </span>
          <Link className="read-analysis" href={`/events/${event.id}`}>
            {event.analysis ? "Read analysis" : "View event"}
            <ArrowRight size={15} />
          </Link>
        </div>
      </div>
      <div
        className="significance"
        title="AI-assessed technical significance; not a confidence score"
      >
        <span>{score ?? "—"}</span>
        <small>{score !== null ? "/ 10" : "PENDING"}</small>
        <div className="score-bars" aria-hidden="true">
          {Array.from({ length: 10 }, (_, index) => (
            <i
              key={index}
              className={score !== null && index < score ? "filled" : ""}
            />
          ))}
        </div>
        <label>Significance</label>
      </div>
    </article>
  );
}
