"""Shared by every script here: the camera's frame size, where the data lives,
and image I/O that survives macOS screenshot names (cv2.imread cannot open a
path with the narrow no-break space macOS puts before "PM")."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# The AI deck's camera (dpp-enhance.txt, THE JOB). Every frame the stage sees is this size.
FRAME_W, FRAME_H = 324, 244

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"  # gitignored: photos, prepared sets, downloaded models, run output
MODELS = DATA / "models"
SETS = DATA / "sets"
RUNS = DATA / "runs"
MANIFESTS = HERE / "manifests"  # committed: what each set was made from

# The viewer's crosshair, burnt into the camera-frame screenshots: a centred box,
# as fractions of the frame, left out of every metric. Measured on the 15 frames
# of 2026-10-06 — arms ±11 px and up to 6 px off centre at 324×244.
CROSSHAIR_BOX = (0.444, 0.426, 0.556, 0.574)  # x0, y0, x1, y1


def read_gray(path: Path) -> np.ndarray:
    """8-bit grayscale; colour and alpha are dropped the way the camera would see it."""
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"not an image: {path}")
    return img


def write_png(path: Path, img: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError(f"could not encode {path}")
    buf.tofile(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shrink(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Area averaging: what a smaller sensor sees, without aliasing."""
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def crop_to_frame_aspect(img: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """The largest centred crop with the camera's 324:244 aspect, and its box."""
    h, w = img.shape
    cw, ch = w, round(w * FRAME_H / FRAME_W)
    if ch > h:
        cw, ch = round(h * FRAME_W / FRAME_H), h
    x, y = (w - cw) // 2, (h - ch) // 2
    return img[y : y + ch, x : x + cw], (x, y, cw, ch)


@dataclass(frozen=True)
class Item:
    """One prepared image of a set: its grayscale, aspect-cropped pixels on disk."""

    id: str
    file: str
    protocol: str  # "reference" | "self" — see prepare.py
    mask: str  # "" | "crosshair"
    path: Path

    def image(self) -> np.ndarray:
        return read_gray(self.path)


def load_set(name: str) -> list[Item]:
    manifest = MANIFESTS / f"{name}.csv"
    if not manifest.exists():
        raise SystemExit(f"no set {name!r} — run prepare.py first ({manifest} is missing)")
    with manifest.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    items = [
        Item(r["id"], r["file"], r["protocol"], r["mask"], SETS / name / f"{r['id']}.png")
        for r in rows
    ]
    missing = [i.file for i in items if not i.path.exists()]
    if missing:
        raise SystemExit(
            f"set {name!r} is not prepared on this machine "
            f"({len(missing)} missing) — run prepare.py"
        )
    return items


def metric_mask(shape: tuple[int, ...], mask: str, border: int) -> np.ndarray:
    """True where a pixel counts. The border is shaved as SR papers do — the
    edges have no neighbours to reconstruct from — and the crosshair is cut out."""
    h, w = shape[:2]
    keep = np.zeros((h, w), bool)
    keep[border : h - border, border : w - border] = True
    if mask == "crosshair":
        x0, y0, x1, y1 = CROSSHAIR_BOX
        keep[int(y0 * h) : int(np.ceil(y1 * h)), int(x0 * w) : int(np.ceil(x1 * w))] = False
    return keep
