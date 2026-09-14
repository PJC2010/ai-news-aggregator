import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Signal — AI intelligence", template: "%s · Signal" },
  description:
    "The AI stories, technical context, and source material worth your attention.",
  robots: { index: false, follow: false },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
