import Link from "next/link";
import { ArrowRight, Layers3, ScanLine, Telescope } from "lucide-react";
import { Brand } from "@/components/shell";
import { LoginForm } from "@/components/forms";
import { authConfigured } from "@/lib/supabase/server";
import { isDemo } from "@/lib/api";

export const dynamic = "force-dynamic";
export default async function Login({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const configured = authConfigured();
  return (
    <main className="login-page">
      <section className="login-story">
        <Brand />
        <div>
          <span className="eyebrow">A CLEARER VIEW OF AI</span>
          <h1>
            Stay curious.
            <br />
            Stay in focus.
          </h1>
          <p>
            Understand what changed, why it matters, and where to look next.
          </p>
          <ul>
            <li>
              <Layers3 size={20} />
              One event, connected coverage
            </li>
            <li>
              <ScanLine size={20} />
              Technical context that goes deeper
            </li>
            <li>
              <Telescope size={20} />A reading lens built around you
            </li>
          </ul>
        </div>
        <span className="login-footer">AI News Aggregator · Signal</span>
      </section>
      <section className="login-content">
        <div>
          <span className="eyebrow">YOUR READING WORKSPACE</span>
          <h2>Welcome to Signal.</h2>
          <p>
            Sign in or create an account with your email. No password to
            remember.
          </p>
          {isDemo() ? (
            <div className="demo-login">
              <p>
                This is a sample workspace with illustrative stories. No account
                is needed.
              </p>
              <Link href="/" className="button primary">
                Explore the demo
                <ArrowRight size={17} />
              </Link>
            </div>
          ) : (
            <>
              {!configured && (
                <div className="notice" role="status">
                  Sign-in is not available yet. This workspace needs its
                  authentication connection configured.
                </div>
              )}
              {params.error && (
                <p className="form-error" role="alert">
                  That link could not be verified. Request a new link and open
                  it in the same browser.
                </p>
              )}
              {params.expired && (
                <p className="notice">
                  Your session has expired. Sign in again to continue.
                </p>
              )}
              <LoginForm configured={configured} />
            </>
          )}
          <p className="login-fineprint">
            Your interests shape your feed. Source articles and analysis are
            shared across readers.
          </p>
        </div>
      </section>
    </main>
  );
}
