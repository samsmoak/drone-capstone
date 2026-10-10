"""Check manifests/images.csv against data/raw/ and report the dataset's shape.

    python ml/image-classifier/validate_manifest.py

Exits non-zero if the manifest is malformed or points at missing files.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifests" / "images.csv"
RAW = HERE / "data" / "raw"
COLUMNS = ["file", "label", "defect_type", "angle", "session", "date"]
LABELS = {"normal", "faulty"}


def main() -> int:
    with MANIFEST.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            print(f"columns must be exactly {COLUMNS}, got {reader.fieldnames}")
            return 1
        rows = list(reader)

    problems: list[str] = []
    seen: set[str] = set()
    for n, r in enumerate(rows, start=2):
        f = r["file"].strip()
        if f in seen:
            problems.append(f"line {n}: {f} listed twice")
        seen.add(f)
        if not (RAW / f).is_file():
            problems.append(f"line {n}: {f} not found under data/raw/")
        if r["label"] not in LABELS:
            problems.append(f"line {n}: label {r['label']!r} must be one of {sorted(LABELS)}")
        if r["label"] == "faulty" and not r["defect_type"].strip():
            problems.append(f"line {n}: a faulty photo needs a defect_type")
        if r["label"] == "normal" and r["defect_type"].strip():
            problems.append(f"line {n}: a normal photo should have no defect_type")
        for col in ("angle", "session", "date"):
            if not r[col].strip():
                problems.append(f"line {n}: {col} is empty")

    on_disk = {p.relative_to(RAW).as_posix() for p in RAW.rglob("*")
               if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}}
    for f in sorted(on_disk - seen):
        problems.append(f"{f} is in data/raw/ but not in the manifest")

    print(f"{len(rows)} photos")
    print("  by label:  ", dict(Counter(r["label"] for r in rows)))
    print("  by session:", dict(Counter(r["session"] for r in rows)))
    print("  by defect: ", dict(Counter(r["defect_type"] for r in rows if r["defect_type"])))
    print("  by angle:  ", dict(Counter(r["angle"] for r in rows)))
    if len({r["session"] for r in rows}) < 2 and rows:
        print("  note: one session only — nothing to hold out yet")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
