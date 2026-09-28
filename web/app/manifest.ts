import type { MetadataRoute } from "next";

/**
 * The web manifest.
 *
 * `app/layout.tsx` has declared `manifest: "/manifest.webmanifest"` since the
 * metadata was written, but no manifest existed — so every page asked the
 * browser for a file that 404'd. This is the file it was promising.
 *
 * Generated rather than static (`app/manifest.ts`, the Next 16 file convention)
 * so the colours stay in one place with the rest of the metadata instead of
 * being re-typed as literals in a .json nobody edits.
 *
 * The colours are the design tokens' own values, copied deliberately: a
 * manifest is read by the operating system before any CSS exists, so it cannot
 * reference `var(--background)`. If the tokens in `globals.css` change, these
 * two change with them.
 *   --background (light) #fcfcfb   --primary #1c5cab
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DroneDeck",
    short_name: "DroneDeck",
    description:
      "An autonomous indoor drone inspection system on a Crazyflie 2.1 — flight, " +
      "position-tagged sensor data and images, and the findings on one dashboard.",
    // The operator area, not the marketing home page: someone who installs this
    // is here to read flight data.
    start_url: "/app",
    scope: "/",
    display: "standalone",
    background_color: "#fcfcfb",
    theme_color: "#1c5cab",
    orientation: "any",
    categories: ["productivity", "utilities"],
    icons: [
      // The drone on its rounded tile (public/brand/, generated from the one
      // stock photograph in public/brand/CREDITS.txt).
      { src: "/brand/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      // Full-bleed with a safe margin: the OS draws its own mask over this one.
      { src: "/brand/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
