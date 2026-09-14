import Link from "next/link";
import {
  ArrowRight,
  ArrowLeft,
  Search,
  SlidersHorizontal,
  Sparkles,
  ArrowUpRight,
  CircleHelp,
} from "lucide-react";
import { getFeed, getProfile } from "@/lib/api";
import {
  dateLabel,
  EVENT_TYPES,
  feedHref,
  label,
  parseFilters,
} from "@/lib/format";
import { EventCard } from "@/components/event-card";

export default async function Overview({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = parseFilters(await searchParams);
  const profile = await getProfile();
  if (!profile.available_topics.some((topic) => topic.id === filters.topic))
    filters.topic = "";
  const feed = await getFeed(filters);
  const pages = Math.max(1, Math.ceil(feed.total / feed.limit));
  return (
    <>
      <div className="page-intro">
        <div>
          <div className="eyebrow">
            <span className="tiny-rule" />
            YOUR DAILY PERSPECTIVE{" "}
            <span className="intro-date">
              {dateLabel(feed.as_of).toUpperCase()} · UTC
            </span>
          </div>
          <h1>
            {filters.following
              ? "Your interests. In focus."
              : "What matters in AI."}
          </h1>
          <p>The stories, context, and source material worth your attention.</p>
        </div>
        <Link href="/settings" className="button secondary">
          <SlidersHorizontal size={16} />
          Tune your feed
        </Link>
      </div>
      <div className="feed-layout">
        <section aria-label="News feed" className="feed-column">
          <div className="feed-tabs">
            <Link
              className={!filters.following ? "active" : ""}
              aria-current={!filters.following ? "page" : undefined}
              href={feedHref(filters, { following: false, page: 1 })}
            >
              All stories<span>{!filters.following ? feed.total : ""}</span>
            </Link>
            <Link
              className={filters.following ? "active" : ""}
              aria-current={filters.following ? "page" : undefined}
              href={feedHref(filters, { following: true, page: 1 })}
            >
              <Sparkles size={15} />
              Following
            </Link>
          </div>
          <form className="feed-filters" method="get" action="/">
            {filters.following && (
              <input type="hidden" name="following" value="true" />
            )}
            {filters.topic && (
              <input type="hidden" name="topic" value={filters.topic} />
            )}
            <div className="input-wrap search">
              <Search size={17} />
              <input
                aria-label="Search stories"
                name="q"
                defaultValue={filters.q}
                placeholder="Search stories, ideas, and breakthroughs…"
                maxLength={200}
              />
            </div>
            <div className="filter-row">
              <label>
                <span>Period</span>
                <select name="window" defaultValue={filters.window}>
                  <option value="week">Past 7 days</option>
                  <option value="today">Today (UTC)</option>
                  <option value="all">All time</option>
                </select>
              </label>
              <label>
                <span>Type</span>
                <select name="event_type" defaultValue={filters.event_type}>
                  <option value="">All event types</option>
                  {EVENT_TYPES.map((type) => (
                    <option value={type} key={type}>
                      {label(type)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Sort</span>
                <select name="sort" defaultValue={filters.sort}>
                  <option value="ranked">Top ranked</option>
                  <option value="latest">Latest first</option>
                </select>
              </label>
              <button className="button small secondary" type="submit">
                Apply
              </button>
            </div>
          </form>
          {filters.topic && (
            <div className="active-filter">
              Topic:{" "}
              {
                profile.available_topics.find(
                  (topic) => topic.id === filters.topic,
                )?.label
              }
              <Link href={feedHref(filters, { topic: "", page: 1 })}>
                Clear ×
              </Link>
            </div>
          )}
          <div className="feed-result-meta">
            <span>
              {feed.total === 0
                ? "No matching stories"
                : `${feed.offset + 1 > feed.total ? 0 : feed.offset + 1}–${Math.min(feed.offset + feed.items.length, feed.total)} of ${feed.total} stories`}
            </span>
            <span>
              {filters.sort === "ranked"
                ? "Ranked for relevance & recency"
                : "Ordered by latest coverage"}
            </span>
          </div>
          <div className="event-list">
            {feed.items.map((event, index) => (
              <EventCard
                key={event.id}
                event={event}
                now={feed.as_of}
                featured={
                  index === 0 && filters.page === 1 && filters.sort === "ranked"
                }
              />
            ))}
          </div>
          {feed.items.length === 0 && (
            <div className="empty-state">
              <Search size={30} />
              <h2>
                {filters.following && profile.topics.length === 0
                  ? "Choose your first topics"
                  : "Nothing in this view yet"}
              </h2>
              <p>
                {filters.following && profile.topics.length === 0
                  ? "Follow the areas you care about to create a more focused reading list."
                  : "Try a broader search or time period. New stories will appear after the next ingestion run."}
              </p>
              <Link
                className="button primary"
                href={
                  filters.following && profile.topics.length === 0
                    ? "/settings"
                    : "/?window=all"
                }
              >
                {filters.following && profile.topics.length === 0
                  ? "Choose topics"
                  : "Browse all stories"}
                <ArrowRight size={16} />
              </Link>
            </div>
          )}
          {(pages > 1 || filters.page > 1) && (
            <nav className="pagination" aria-label="Feed pagination">
              {filters.page > 1 ? (
                <Link
                  className="button small secondary"
                  href={feedHref(filters, { page: filters.page - 1 })}
                >
                  <ArrowLeft size={15} />
                  Previous
                </Link>
              ) : (
                <span />
              )}
              <span>
                Page {filters.page} of {pages}
              </span>
              {filters.page < pages ? (
                <Link
                  className="button small secondary"
                  href={feedHref(filters, { page: filters.page + 1 })}
                >
                  Next
                  <ArrowRight size={15} />
                </Link>
              ) : (
                <span />
              )}
            </nav>
          )}
        </section>
        <aside className="reading-rail">
          <div className="lens-card">
            <span className="eyebrow">YOUR LENS</span>
            <h2>Make it relevant.</h2>
            <p>
              Follow your interests.
              <br />
              Keep the wider picture.
            </p>
            <div className="lens-topics">
              {profile.topics.length === 0 ? (
                <p className="muted">No topics selected yet.</p>
              ) : (
                profile.topics.map((id) => (
                  <Link
                    key={id}
                    href={feedHref(filters, {
                      topic: id,
                      following: false,
                      page: 1,
                    })}
                  >
                    <span className="status-dot" />
                    {
                      profile.available_topics.find((topic) => topic.id === id)
                        ?.label
                    }
                    <ArrowUpRight size={14} />
                  </Link>
                ))
              )}
            </div>
            <Link href="/settings" className="text-link">
              Manage topics
              <ArrowRight size={15} />
            </Link>
            <div className="lens-art" aria-hidden="true">
              <i />
              <i />
              <i />
              <span>FOCUS ON THE SIGNAL</span>
            </div>
          </div>
          <div className="explainer">
            <CircleHelp size={20} />
            <h3>One story, more context.</h3>
            <p>
              Related coverage is grouped into events. Shared analysis helps
              explain the significance, with sources for your own review.
            </p>
            <small>
              AI analysis can be incomplete. Significance is an editorial
              assessment, not a measure of certainty.
            </small>
          </div>
        </aside>
      </div>
    </>
  );
}
