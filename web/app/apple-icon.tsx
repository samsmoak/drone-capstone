import { ImageResponse } from "next/og";

/**
 * The iOS home-screen icon.
 *
 * iOS does not accept an SVG for `apple-touch-icon`, so this one is generated
 * as a PNG rather than shipped as a file — same mark as `icon.svg` and the
 * desktop app's sidebar, no binary blob in the repo.
 *
 * It is drawn edge to edge with no rounding: iOS applies its own mask, and a
 * pre-rounded icon ends up with a second, smaller radius inside the first.
 */
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          // The --primary token's own value. A generated image is rasterised
          // with no stylesheet in scope, so it cannot read the variable.
          background: "#1c5cab",
          color: "#ffffff",
          fontSize: 118,
          fontWeight: 700,
          // Nudged up: the cap-height of a "C" sits low in its own line box,
          // and centring the box is not centring the letter.
          lineHeight: 1,
          paddingBottom: 10,
        }}
      >
        C
      </div>
    ),
    size,
  );
}
