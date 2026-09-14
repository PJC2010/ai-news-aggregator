"use client";

import { RefreshCw } from "lucide-react";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="empty-state error-state">
      <RefreshCw size={30} />
      <h1>We couldn’t load this view.</h1>
      <p>
        The news service may be temporarily unavailable. Your preferences have
        not been changed.
      </p>
      <button className="button primary" onClick={reset}>
        Try again
        <RefreshCw size={16} />
      </button>
    </div>
  );
}
