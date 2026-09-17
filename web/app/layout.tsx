import type { Metadata, Viewport } from "next";
import { Fraunces, Geist_Mono, Inter } from "next/font/google";
import "./globals.css";

// Inter for reading, Fraunces for titles — the portfolio's pairing, shared with
// the desktop app so the two read as one product.
const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: {
    default: "CropWatcher",
    template: "%s · CropWatcher",
  },
  description:
    "Autonomous indoor crop-health monitoring with a Crazyflie 2.1 — flight, " +
    "position-tagged telemetry, and zone-level health estimates.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "CropWatcher" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fcfcfb" },
    { media: "(prefers-color-scheme: dark)", color: "#1a1a19" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${fraunces.variable} ${geistMono.variable} antialiased`}>
        {/* Keyboard users land here first — WCAG 2.2 AA. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-[var(--primary)] focus:px-4 focus:py-2 focus:text-[var(--on-primary)]"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
