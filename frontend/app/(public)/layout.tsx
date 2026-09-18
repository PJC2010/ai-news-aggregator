import Link from "next/link";
import { Brand } from "@/components/shell";

export const dynamic = "force-dynamic";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="public-shell">
      <header className="public-header">
        <Brand href="/" />
        <nav aria-label="Public navigation">
          <Link href="/feed">News feed</Link>
          <Link href="/login">Sign in</Link>
          <Link className="button primary" href="/dashboard">Your dashboard</Link>
        </nav>
      </header>
      <main>{children}</main>
      <footer className="public-footer">Signal · Public AI news, grounded in sources.</footer>
    </div>
  );
}
