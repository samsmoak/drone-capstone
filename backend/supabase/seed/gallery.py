"""Fill the public gallery with albums: the kit, the team, videos and placeholders.

    SUPABASE_API=https://<ref>.supabase.co SUPABASE_SERVICE=<secret key> \\
    python backend/supabase/seed/gallery.py

Needs migrations 0007 (images bucket) and 0008 (gallery tables), and the team
seed (portfolio.py) for Samuel's photo. Uses the SECRET key — developer machine
only, never commit the key.

Idempotent: albums upsert on slug and their items are replaced, so re-running
refreshes the albums it owns and leaves every other album alone.

What is real and what is a placeholder:
  - "The kit": the actual hardware photos from web/public/hardware/.
  - "Flight videos": real Crazyflie videos from Bitcraze's official channel,
    credited to Bitcraze.
  - Team, drones-in-flight and greenhouse photos: stock photos from Unsplash
    (free to use under the Unsplash License), captioned as placeholders until
    the team's own photos replace them in /admin.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
BUCKET = "portfolio-images"
PLACEHOLDER = "Placeholder photo · Unsplash"


def unsplash(photo: str) -> str:
    return f"https://images.unsplash.com/{photo}?w=1600&q=80&fm=jpg&fit=max"


KIT = [
    ("01-crazyflie-2.1-mainboard-top-angled.jpeg", "Crazyflie 2.1 mainboard, from above"),
    ("02-crazyflie-2.1-mainboard-top-flat.jpeg", "The mainboard, flat"),
    ("03-ai-deck-1.1-mounted-underside-a.jpeg", "AI deck mounted underneath"),
    ("04-ai-deck-1.1-mounted-underside-b.jpeg", "AI deck, second angle"),
    ("05-crazyradio-pa-usb-dongle.jpeg", "Crazyradio PA — the only link to the drone"),
    ("06-lipo-batteries-x2-and-usb-charger.jpeg", "Two LiPo batteries and the USB charger"),
    ("07-cf-battery-holder-and-pin-headers.jpeg", "Battery holder and pin headers"),
    ("08-spare-motor-mounts-x2.jpeg", "Spare motor mounts"),
    ("09-spare-coreless-motor-a.jpeg", "A spare coreless motor"),
    ("10-spare-coreless-motor-b.jpeg", "Another spare motor"),
]

ALBUMS: list[dict[str, Any]] = [
    {
        "slug": "the-kit",
        "title": "The kit",
        "summary": "Everything CropWatcher is built from — the Crazyflie 2.1, its decks, the "
                   "radio, batteries and spares — photographed on the bench.",
        "category": "Hardware",
        "date_label": "2026",
        "items": [{"kind": "image", "local": REPO / "web/public/hardware" / name,
                   "caption": caption, "credit": "CropWatcher team"} for name, caption in KIT],
    },
    {
        "slug": "flight-videos",
        "title": "Flight videos",
        "summary": "Crazyflie 2.1 drones flying on Lighthouse positioning — the same system "
                   "CropWatcher navigates by.",
        "category": "Videos",
        "date_label": "2019 – 2020",
        "items": [
            {"kind": "video", "url": "https://www.youtube.com/watch?v=BggnSDj3baE",
             "caption": "A synchronised swarm of nine Crazyflie 2.1 on Lighthouse positioning",
             "credit": "Bitcraze"},
            {"kind": "video", "url": "https://www.youtube.com/watch?v=NHdlHIq_ce0",
             "caption": "Two Crazyflie 2.1 taking off with Lighthouse yaw measurement",
             "credit": "Bitcraze"},
            {"kind": "video", "url": "https://www.youtube.com/watch?v=NuSIBYFfm9Y",
             "caption": "An experimental Crazyflie Bolt flight on Lighthouse 2",
             "credit": "Bitcraze"},
        ],
    },
    {
        "slug": "the-team",
        "title": "The team",
        "summary": "The people behind CropWatcher at work. Placeholder photos stand in until "
                   "the team's own are added.",
        "category": "Team",
        "date_label": "2026",
        "items": [
            {"kind": "image", "storage": "team/samuel-enam-zih.png", "caption": "Samuel Enam Zih",
             "credit": "CropWatcher team"},
            *({"kind": "image", "url": unsplash(p), "caption": c, "credit": PLACEHOLDER} for p, c in [
                ("photo-1581092160607-ee22621dd758", "Working through a build in the lab"),
                ("photo-1581094488379-6a10d04c0f04", "Reviewing a design on paper"),
                ("photo-1581091226033-d5c48150dbaa", "Testing hardware together"),
                ("photo-1581091212911-f4efc3f71c48", "A quick check at the bench"),
                ("photo-1622675363311-3e1904dc1885", "Team review"),
                ("photo-1581087724694-14c17b0c17fc", "Watching a test from the console"),
            ]),
        ],
    },
    {
        "slug": "drones-in-flight",
        "title": "Drones in flight",
        "summary": "Quadcopters in the air. Placeholder photos until the team's own flight "
                   "photos are added.",
        "category": "Flights",
        "date_label": "2026",
        "items": [{"kind": "image", "url": unsplash(p), "caption": c, "credit": PLACEHOLDER} for p, c in [
            ("photo-1473968512647-3e447244af8f", "Over the trees"),
            ("photo-1527977966376-1c8408f9f108", "Mid-turn"),
            ("photo-1487219116710-23ffcb172b2b", "Holding a hover"),
            ("photo-1532989029401-439615f3d4b4", "In the forest"),
            ("photo-1588495077262-e41593eb23c8", "Above the hills"),
            ("photo-1514598800938-f7125ea1aa1c", "Against the sky"),
            ("photo-1488462104523-514bea5f99b3", "A steady climb"),
            ("photo-1456615913800-c33540eac399", "Heavy-lift quadcopter"),
        ]],
    },
    {
        "slug": "in-the-greenhouse",
        "title": "In the greenhouse",
        "summary": "Where CropWatcher is meant to fly: rows of crops under glass. Placeholder "
                   "photos until the team's own are added.",
        "category": "Greenhouse",
        "date_label": "2026",
        "items": [{"kind": "image", "url": unsplash(p), "caption": c, "credit": PLACEHOLDER} for p, c in [
            ("photo-1623136299195-570a06bdae6b", "Rows under glass"),
            ("photo-1708796705570-33fd29ef67d0", "A long tunnel of greens"),
            ("photo-1591754060004-f91c95f5cf05", "Crops under a steel frame"),
            ("photo-1506277450472-30e3f3f55129", "Lush growth"),
            ("photo-1615671524827-c1fe3973b648", "Seedlings in trays"),
            ("photo-1637987327476-5c77df3cb16d", "Beds in a polytunnel"),
            ("photo-1565980102051-97fa602b66f4", "Flowers in bloom"),
        ]],
    },
]


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a JPEG or PNG, read from its header — no imaging library."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + length
    return None


class Api:
    def __init__(self, base: str, key: str) -> None:
        self.base, self.key = base.rstrip("/"), key

    def request(self, method: str, path: str, body: Any = None, *,
                headers: dict[str, str] | None = None, raw: bytes | None = None) -> Any:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("apikey", self.key)
        req.add_header("Authorization", f"Bearer {self.key}")
        if raw is None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req) as resp:
                payload = resp.read()
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path} failed: {e.code} {e.read().decode()[:300]}")

    def public_url(self, object_path: str) -> str:
        return f"{self.base}/storage/v1/object/public/{BUCKET}/{object_path}"

    def upload(self, object_path: str, data: bytes, content_type: str) -> str:
        self.request("POST", f"/storage/v1/object/{BUCKET}/{object_path}", raw=data,
                     headers={"Content-Type": content_type, "x-upsert": "true"})
        return self.public_url(object_path)


def download(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cropwatcher-seed"})) as r:
        return r.read()


def resolve(api: Api, slug: str, index: int, item: dict[str, Any]) -> dict[str, Any]:
    """Put an image in storage and return the row to insert."""
    row: dict[str, Any] = {"kind": item["kind"], "caption": item["caption"],
                           "credit": item["credit"], "display_order": index}
    if item["kind"] == "video":
        row["url"] = item["url"]
        return row
    if "storage" in item:
        data = download(api.public_url(item["storage"]))
        row["url"] = api.public_url(item["storage"])
    else:
        data = item["local"].read_bytes() if "local" in item else download(item["url"])
        ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
        content_type = "image/png" if ext == ".png" else "image/jpeg"
        row["url"] = api.upload(f"gallery/{slug}/{index:02d}{ext}", data, content_type)
    size = image_size(data)
    if size:
        row["width"], row["height"] = size
    return row


def main() -> None:
    base, key = os.environ.get("SUPABASE_API"), os.environ.get("SUPABASE_SERVICE")
    if not base or not key:
        sys.exit("Set SUPABASE_API and SUPABASE_SERVICE (the secret key) in the environment.")
    api = Api(base, key)

    for order, album in enumerate(ALBUMS, start=1):
        items = [resolve(api, album["slug"], i, item) for i, item in enumerate(album["items"])]
        cover = next((it["url"] for it in items if it["kind"] == "image"), None)
        if cover is None:           # a video-only album uses its first video's poster
            vid = album["items"][0]["url"].rsplit("v=", 1)[-1]
            cover = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        fields = {k: album[k] for k in ("slug", "title", "summary", "category", "date_label")}
        saved = api.request(
            "POST", "/rest/v1/gallery_albums?on_conflict=slug",
            {**fields, "status": "published", "display_order": order, "cover_image_url": cover},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        album_id = saved[0]["id"]
        api.request("DELETE", f"/rest/v1/gallery_items?album_id=eq.{album_id}")
        api.request("POST", "/rest/v1/gallery_items", [{**it, "album_id": album_id} for it in items])
        print(f"  album  {album['slug']:<20} {len(items)} items")


if __name__ == "__main__":
    main()
