export default function Loading() {
  return (
    <div className="loading-state" role="status">
      <div className="skeleton skeleton-heading" />
      <div className="skeleton skeleton-line" />
      <div className="skeleton skeleton-card" />
      <div className="skeleton skeleton-card" />
      <span className="sr-only">Loading your news…</span>
    </div>
  );
}
