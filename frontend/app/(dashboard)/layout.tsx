import { accessToken } from "@/lib/api";
import { Shell } from "@/components/shell";

export const dynamic = "force-dynamic";
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await accessToken();
  return <Shell>{children}</Shell>;
}
