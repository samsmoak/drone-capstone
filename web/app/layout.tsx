import type { Metadata, Viewport } from "next";
import { Fraunces, Geist_Mono, Inter, Space_Grotesk } from "next/font/google";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";
import "./globals.css";

// Inter for reading, Fraunces for titles — the portfolio's pairing, shared with
// the desktop app so the two read as one product. Space Grotesk is the
// DroneDeck wordmark's face and is used for nothing else.
const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const spaceGrotesk = Space_Grotesk({ variable: "--font-space-grotesk", subsets: ["latin"], weight: ["500", "700"] });

export const metadata: Metadata = {
  title: {
    default: "DroneDeck",
    template: "%s · DroneDeck",
  },
  description:
    "DroneDeck — an autonomous indoor drone inspection system on a Crazyflie 2.1: a desktop " +
    "app that flies it, and a dashboard that shows what it found.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "DroneDeck" },
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
      <head>
        {/* Applies the saved light/dark choice before the first paint, so a
            page never flashes the other theme. See lib/theme.ts. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className={`${inter.variable} ${fraunces.variable} ${geistMono.variable} ${spaceGrotesk.variable} antialiased`}>
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
