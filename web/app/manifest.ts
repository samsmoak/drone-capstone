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
    name: "CropWatcher",
    short_name: "CropWatcher",
    description:
      "Autonomous indoor crop-health monitoring with a Crazyflie 2.1 — flight, " +
      "position-tagged telemetry, and zone-level health estimates.",
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
      {
        // Vector, so it is crisp at every size the OS asks for and there is no
        // binary blob in the repo. Chrome has accepted SVG manifest icons for
        // installability since 108.
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
      {
        src: "/apple-icon",
        sizes: "180x180",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
