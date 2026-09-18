import Link from "next/link";
import { ArrowRight, Layers3 } from "lucide-react";
import type { PublicEvent } from "@/lib/types";
import { dateLabel, label } from "@/lib/format";

export function PublicEventCard({ event }: { event: PublicEvent }) {
  return (
    <article className="public-event-card">
      <div className="card-meta"><span className={`tag tag-${event.event_type || "pending"}`}>{label(event.event_type)}</span><span>{dateLabel(event.published_at)}</span></div>
      <h2><Link href={`/events/${event.id}`}>{event.title}</Link></h2>
      <p>{event.summary || "Read the original source while this event summary is prepared."}</p>
      <div className="public-card-footer"><span><Layers3 size={14} /> {event.source_count} {event.source_count === 1 ? "source" : "sources"}</span><Link href={`/events/${event.id}`}>View event <ArrowRight size={15} /></Link></div>
    </article>
  );
}
