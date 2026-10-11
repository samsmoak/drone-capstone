"""Turn a folder of images into an evaluation set, and write its manifest.

    python prepare.py --src data/originals --name camera-frames --protocol self --mask crosshair
    python prepare.py --src data/photos    --name photos        --protocol reference

Each image becomes one grayscale, centre-cropped (324:244) PNG under
data/sets/<name>/, named by the first 12 hex digits of its sha256 so the
manifest never publishes anything but a file name and a hash.

THE PROTOCOL says what the reference is — score.py reads it from the manifest:

  reference   The image holds MORE detail than the camera (the story 4.1 photos).
              Input: shrunk to 324×244, as the camera would see it.
              Truth: the same image at 324·s × 244·s, for a method of scale s.
              The ticket's protocol. A method whose output is bigger than the
              photo has no truth to be scored against, and is not scored.

  self        The image is a camera frame — no more detail than 324×244 exists.
              Truth: the frame at 324×244.
              Input: the frame shrunk by the method's scale (162×122 for ×2).
              Scores how well a method restores a real frame, on the camera's
              own noise and blur; the standard protocol when no truth is bigger.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from common import (
    FRAME_H,
    FRAME_W,
    MANIFESTS,
    SETS,
    crop_to_frame_aspect,
    read_gray,
    sha256,
    write_png,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--src", type=Path, required=True, help="folder of images")
    ap.add_argument("--name", required=True, help="the set's name, e.g. camera-frames")
    ap.add_argument("--protocol", choices=["reference", "self"], required=True)
    ap.add_argument(
        "--mask",
        choices=["", "crosshair"],
        default="",
        help="leave the viewer's crosshair out of every metric",
    )
    args = ap.parse_args()

    files = sorted(p for p in args.src.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not files:
        raise SystemExit(f"no images in {args.src}")

    out = SETS / args.name
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.png"):
        stale.unlink()

    rows = []
    for f in files:
        img = read_gray(f)
        crop, (x, y, w, h) = crop_to_frame_aspect(img)
        if w < FRAME_W or h < FRAME_H:
            print(f"skipped, smaller than a camera frame: {f.name} ({w}×{h})")
            continue
        digest = sha256(f)
        write_png(out / f"{digest[:12]}.png", crop)
        rows.append(
            {
                "id": digest[:12],
                "file": f.name,
                "sha256": digest,
                "protocol": args.protocol,
                "mask": args.mask,
                "width": img.shape[1],
                "height": img.shape[0],
                "crop_x": x,
                "crop_y": y,
                "crop_w": w,
                "crop_h": h,
                # the largest integer scale this image can be truth for
                "max_scale": min(w // FRAME_W, h // FRAME_H)
                if args.protocol == "reference"
                else "",
            }
        )

    MANIFESTS.mkdir(exist_ok=True)
    manifest = MANIFESTS / f"{args.name}.csv"
    with manifest.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} images → {out}  manifest → {manifest}")
    if args.protocol == "reference":
        scales = sorted({r["max_scale"] for r in rows})
        print(f"truth available up to ×{max(scales)} (per image: {scales})")


if __name__ == "__main__":
    main()
