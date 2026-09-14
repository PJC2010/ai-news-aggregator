import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Layers3,
  ScanLine,
  Telescope,
} from "lucide-react";
import { getEvent } from "@/lib/api";
import { dateLabel, label, publisher } from "@/lib/format";
import { SourceLink } from "@/components/event-card";

export const metadata: Metadata = { title: "Event analysis" };
export default async function EventDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const event = await getEvent((await params).id);
  if (!event) notFound();
  const analysis = event.analysis;
  const coverage = event.coverage || [];
  return (
    <div className="detail-page">
      <Link href="/" className="back-link">
        <ArrowLeft size={16} />
        Back to overview
      </Link>
      <div className="detail-heading">
        <div className="card-meta">
          <span className={`tag tag-${event.event_type || "pending"}`}>
            {label(event.event_type)}
          </span>
          <span>{dateLabel(event.latest_published_at)} · UTC</span>
          <span>
            <Layers3 size={14} />
            {event.cluster_size}{" "}
            {event.cluster_size === 1 ? "article" : "articles"}
          </span>
        </div>
        <h1>{event.primary_article.title}</h1>
        <SourceLink url={event.primary_article.url} className="text-link">
          Read the original at {publisher(event.primary_article.url)}
        </SourceLink>
      </div>
      <div className="detail-layout">
        <div>
          <section className="summary-panel">
            <div className="eyebrow">
              <BookOpen size={16} />
              THE BRIEF
            </div>
            <p>
              {event.summary ||
                "A summary is not available for this event yet. You can still read the original source and related coverage below."}
            </p>
          </section>
          {analysis ? (
            <>
              <section className="analysis-section">
                <span className="section-icon">
                  <ScanLine size={21} />
                </span>
                <div>
                  <h2>Why it matters</h2>
                  <p>{analysis.why_it_matters}</p>
                </div>
              </section>
              <section className="analysis-section">
                <span className="section-icon">
                  <Telescope size={21} />
                </span>
                <div>
                  <h2>What to watch</h2>
                  <p>{analysis.what_to_watch}</p>
                </div>
              </section>
              <div className="audience-panel">
                <span className="eyebrow">WHO SHOULD CARE</span>
                <div>
                  {analysis.who_should_care.map((audience, index) => (
                    <span className="audience-tag" key={`${audience}-${index}`}>
                      {audience}
                    </span>
                  ))}
                </div>
              </div>
              {analysis.code_paper_links.length > 0 && (
                <section className="resources">
                  <h2>Go deeper</h2>
                  {analysis.code_paper_links.map((url, index) => (
                    <SourceLink
                      key={`${url}-${index}`}
                      url={url}
                      className="resource-link"
                    >
                      <BookOpen size={17} />
                      {publisher(url)}
                      <span>Reference {index + 1}</span>
                    </SourceLink>
                  ))}
                </section>
              )}
            </>
          ) : (
            <section className="analysis-unavailable">
              <h2>Analysis is not ready yet</h2>
              <p>
                {event.analysis_status === "insufficient_evidence"
                  ? "There is not enough source text to support a useful analysis. Read the available coverage for context."
                  : "This event is available to read, but its structured analysis has not been completed. Browsing this page does not run a paid model request."}
              </p>
            </section>
          )}
          <section className="coverage">
            <div className="section-heading">
              <h2>Source coverage</h2>
              <span className="count-pill">
                {coverage.length}{" "}
                {coverage.length === 1 ? "source record" : "source records"}
              </span>
            </div>
            <p className="muted">
              Related reporting grouped into this event. Source records may
              refer to the same article.
            </p>
            {coverage.length ? (
              coverage.map((source, index) => (
                <div
                  className="coverage-row"
                  key={`${source.article_id}-${index}`}
                >
                  <span className="source-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <span className="source-name">
                      {source.source}
                      <span>{label(source.source_category)}</span>
                    </span>
                    <SourceLink url={source.url}>{source.title}</SourceLink>
                  </div>
                  <ArrowUpRight size={18} />
                </div>
              ))
            ) : (
              <p className="muted">
                No additional source records are available. Use the original
                article above.
              </p>
            )}
          </section>
        </div>
        <aside className="detail-rail">
          <div className="insight-card">
            <span className="eyebrow">TECHNICAL SIGNIFICANCE</span>
            <div className="big-score">
              {event.significance_score ?? "—"}
              <span>/ 10</span>
            </div>
            <p>
              {event.significance_score === null
                ? "Not yet assessed"
                : "AI-assessed significance"}
            </p>
            <div className="insight-divider" />
            <span className="eyebrow">HYPE CHECK</span>
            <strong className="hype-value">
              {analysis
                ? analysis.hype_check === "accurate"
                  ? "In line with the evidence"
                  : label(analysis.hype_check)
                : "Not yet assessed"}
            </strong>
            <small>
              An AI interpretation of the supplied sources. It may be wrong or
              incomplete.
            </small>
          </div>
          <details className="ranking-details">
            <summary>How this event ranks</summary>
            <p>
              The editorial score combines significance, source diversity,
              engagement, and recency.
            </p>
            <dl>
              <div>
                <dt>Rank score</dt>
                <dd>{event.rank_score.toFixed(1)}</dd>
              </div>
              <div>
                <dt>Significance</dt>
                <dd>
                  {event.rank_components.technical_significance?.available
                    ? `${event.significance_score}/10`
                    : "Neutral fallback"}
                </dd>
              </div>
              <div>
                <dt>Method</dt>
                <dd>{event.rank_version}</dd>
              </div>
            </dl>
            <small>Scores are heuristics, not probabilities.</small>
          </details>
        </aside>
      </div>
    </div>
  );
}
