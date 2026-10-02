import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PamatiAI | Student support research",
  description: "A consent-first research platform for sentiment and affect tracking with human oversight."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:bg-white focus:p-4">Skip to content</a>{children}</body></html>;
}
