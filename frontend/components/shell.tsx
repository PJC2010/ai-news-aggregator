import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  Compass,
  SlidersHorizontal,
  Sparkles,
  Radio,
  LogOut,
} from "lucide-react";
import { isDemo } from "@/lib/api";
import { signOut } from "@/app/actions";

export function Brand() {
  return (
    <Link href="/" className="brand">
      <span className="brand-icon">
        <Radio size={22} strokeWidth={2.3} />
      </span>
      signal<span className="brand-period">.</span>
    </Link>
  );
}
export function Shell({ children }: { children: React.ReactNode }) {
  const demo = isDemo();
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Brand />
        <div className="workspace-label">AI INTELLIGENCE</div>
        <nav aria-label="Main navigation">
          <Link href="/">
            <Compass size={19} />
            Overview
            <ArrowUpRight size={14} className="nav-arrow" />
          </Link>
          <Link href="/?following=true">
            <Sparkles size={19} />
            Following
          </Link>
          <Link href="/settings">
            <SlidersHorizontal size={19} />
            My topics
          </Link>
        </nav>
        <div className="sidebar-note">
          <span className="tiny-rule" />
          <h3>
            Less noise.
            <br />
            More perspective.
          </h3>
          <p>One event. The context behind it. The sources to go deeper.</p>
        </div>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          {demo ? "Sample workspace" : "Personal workspace"}
          <small>AI News Aggregator</small>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="mobile-brand">
            <Brand />
          </div>
          <span className="breadcrumb">
            Workspace <span>/</span> AI intelligence
          </span>
          <div className="topbar-actions">
            <span className="mode-pill">
              <Activity size={13} />
              {demo ? "DEMO" : "YOUR FEED"}
            </span>
            {!demo && (
              <form action={signOut}>
                <button className="button small secondary">
                  <LogOut size={14} />
                  Sign out
                </button>
              </form>
            )}
          </div>
        </header>
        {demo && (
          <div className="demo-banner">
            <span className="status-dot" />
            <strong>Demo workspace</strong>
            <span>
              Illustrative stories and analysis. No live news or paid API calls.
            </span>
          </div>
        )}
        <main id="main">{children}</main>
        <footer className="page-footer">
          <span>Signal · A clearer view of AI</span>
          <span>Read the evidence. Form your own view.</span>
        </footer>
      </div>
    </div>
  );
}
