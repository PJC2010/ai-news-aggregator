import Link from "next/link";
export default function NotFound() {
  return (
    <div className="standalone-state">
      <span className="eyebrow">404 · NOT FOUND</span>
      <h1>This event isn’t here.</h1>
      <p>The link may be incorrect, or the event may no longer be available.</p>
      <Link className="button primary" href="/">
        Back to overview
      </Link>
    </div>
  );
}
