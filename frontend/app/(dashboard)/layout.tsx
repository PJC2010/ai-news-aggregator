import { accessToken } from "@/lib/api";
import { Shell } from "@/components/shell";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await accessToken();
  return <Shell>{children}</Shell>;
}
