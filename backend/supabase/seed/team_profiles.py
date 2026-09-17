"""Give every team member a page: /team/<slug>.

Run against a project that has migration 0010, after portfolio.py has created
the people:

    SUPABASE_API=https://<ref>.supabase.co SUPABASE_SERVICE=<secret key> \\
    python backend/supabase/seed/team_profiles.py

Uses the SECRET key — a developer's machine only, never committed, never
shipped. Idempotent: members are matched by name and the fields below are
overwritten, so re-running refreshes the starter content and touches nobody
else.

WHAT IS REAL AND WHAT IS DUMMY CONTENT

**Everything below is placeholder writing, to be replaced by each person at
/admin/team.** It exists so the pages can be built, reviewed and shown before
five people have written their own, and it is written to read like a finished
page rather than like lorem ipsum.

What is true is the description of each part of CropWatcher — mission planning,
sensing, safety, data, the apps — because those come from this repository's own
docs. Who is assigned to which part, and every hobby, is placeholder: swap the
roles around in the admin so they match who actually did what. Deliberately NOT
invented, because they would be
claims about a real person that outlive this seed: employers, schools,
qualifications, locations, email addresses, and links to accounts that might
belong to a stranger. Samuel's website is the one real link, because he gave it.

Photos are stock images from Unsplash (free under the Unsplash Licence),
captioned as placeholders exactly as the gallery seed does it, and copied into
the portfolio-images bucket rather than hot-linked — the site then keeps one
image host (next.config.ts allows that one) and a page cannot break because
somebody else's CDN changed.

`--only <name>` seeds one person, for trying a change before it goes to five.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BUCKET = "portfolio-images"


def unsplash(photo: str) -> str:
    return f"https://images.unsplash.com/{photo}?w=1200&q=80&fm=jpg&fit=max"


PLACEHOLDER = "Placeholder photo · Unsplash"

#: Photos every profile can draw on, uploaded once and shared. Keyed so a page
#: can pick the ones that suit it rather than everyone showing the same two.
STOCK: dict[str, str] = {
    "bench": unsplash("photo-1581092160607-ee22621dd758"),
    "soldering": unsplash("photo-1581091226033-d5c48150dbaa"),
    "notebook": unsplash("photo-1517842645767-c639042777db"),
    "whiteboard": unsplash("photo-1454165804606-c3d57bc86b40"),
    "code": unsplash("photo-1461749280684-dccba630e2f6"),
    "greenhouse": unsplash("photo-1623136299195-570a06bdae6b"),
    "drone": unsplash("photo-1487219116710-23ffcb172b2b"),
    "running": unsplash("photo-1476480862126-209bfaa8edc8"),
    "camera": unsplash("photo-1502136969935-8d8eef54d77b"),
    "books": unsplash("photo-1516414447565-b14be0adf13e"),
    "cooking": unsplash("photo-1556909212-d5b604d0c90d"),
    "guitar": unsplash("photo-1510915361894-db8b60106cb1"),
    "football": unsplash("photo-1431324155629-1a6deb1dec8d"),
    "chess": unsplash("photo-1529699211952-734e80c4d42b"),
    "hiking": unsplash("photo-1551632811-561732d1e306"),
    "garden": unsplash("photo-1466692476868-aef1dfb1e735"),
}

#: The whole team. Dummy content, written to be replaced: the shape of a real
#: page, so the site can be shown and reviewed before anybody writes their own.
#: The roles are a guess and are meant to be swapped in the admin. No invented
#: employer, school, qualification, email, or link to an account that might
#: belong to a stranger — those outlive a seed.
PEOPLE: list[dict[str, Any]] = [
    {
        "full_name": "Yordanos",
        "role": "Mission planning",
        "headline": "Turns a greenhouse floor plan into a route the drone can actually fly.",
        "current_work": "Trimming the lawnmower scan so a full pass fits inside one battery, "
                        "and making the planner refuse a route that clips the geofence instead "
                        "of discovering it mid-flight.",
        "about": "Yordanos works on the part of CropWatcher that decides where the drone goes: "
                 "zones, waypoints, and the checks that run before a motor spins. Most of the "
                 "work is arithmetic about batteries — a scan that cannot finish is a scan "
                 "nobody trusts.\n\n"
                 "She came to the project from coursework in control systems and stayed for the "
                 "part where a plan on a screen makes a real thing move across a room.",
        "hobbies": [
            ("Long-distance running", "Five mornings a week, before the lab opens. It is the "
             "only hour of the day with nothing to debug in it.", "running"),
            ("Chess", "Playing since school and still losing to the same opening. Good practice "
             "for thinking three moves past the obvious one.", "chess"),
        ],
        "photos": [("bench", "At the bench during bring-up week"),
                   ("whiteboard", "Working a scan pattern out on the whiteboard")],
    },
    {
        "full_name": "Hannah",
        "role": "Sensing and calibration",
        "headline": "Makes the numbers the drone reports mean something.",
        "current_work": "The temperature correction: separating the heat the electronics make "
                        "from the heat of the room, so a reading taken over a warm board still "
                        "describes the greenhouse.",
        "about": "Hannah works on the sensing end of CropWatcher — the barometer, the "
                 "temperature model, and the calibration that turns a raw voltage into a "
                 "reading worth writing down. The board heats itself, which is the whole "
                 "difficulty: the correction is validated to 0.12 °F against a reference.\n\n"
                 "She likes the parts of engineering where being nearly right is still wrong, "
                 "and where the fix is measurement rather than opinion.",
        "hobbies": [
            ("Photography", "Film, mostly, because you have to decide before you press the "
             "button. Thirty-six frames is a useful constraint.", "camera"),
            ("Baking", "Weekend sourdough, with a notebook of hydration ratios that looks a lot "
             "like a lab book.", "cooking"),
        ],
        "photos": [("soldering", "Reworking a deck header"),
                   ("notebook", "The calibration log, kept by hand")],
    },
    {
        "full_name": "Kevin",
        "role": "Safety and testing",
        "headline": "Spends his time on the flights that should not happen.",
        "current_work": "Widening the pre-flight checks so the drone refuses a takeoff for a "
                        "reason the operator can read, instead of arming and finding out.",
        "about": "Kevin owns the checks and the guards: battery, positioning, propellers, the "
                 "geofence, and everything that ends a flight early. The rule he works to is "
                 "that a refusal has to explain itself — a check that just says \"failed\" gets "
                 "ignored, and an ignored check is worse than none.\n\n"
                 "He tests by trying to break things on purpose, which is why the drone still "
                 "has all four propellers.",
        "hobbies": [
            ("Five-a-side football", "Tuesdays, whatever the weather. Defends better than he "
             "shoots, which he says is also his approach to flight software.", "football"),
            ("Hiking", "Long walks with a map and no plan to speak of — the opposite of a "
             "mission plan, deliberately.", "hiking"),
        ],
        "photos": [("drone", "Test flight, before the geofence had teeth"),
                   ("bench", "Pre-flight checks on the bench")],
    },
    {
        "full_name": "Reagan",
        "role": "Data and the dashboard",
        "headline": "Gets a flight off the laptop and into something a grower can read.",
        "current_work": "Zone-level health: turning thousands of position-tagged readings into "
                        "a map of a greenhouse that says which rows need attention this week.",
        "about": "Reagan works on everything that happens after a flight lands — the upload, "
                 "the tables behind it, and the dashboard pages that read them. A flight is "
                 "written to the laptop first and uploaded afterwards, because a local write "
                 "cannot fail and a flight cannot be re-run.\n\n"
                 "He is happiest when a page answers a question in one screen without anybody "
                 "exporting a spreadsheet.",
        "hobbies": [
            ("Guitar", "Badly, loudly, and mostly in the evenings after a long day of "
             "queries.", "guitar"),
            ("Growing things", "A balcony of chillies and tomatoes — a much smaller greenhouse "
             "than the one this project is aimed at.", "garden"),
        ],
        "photos": [("code", "Working through the upload path"),
                   ("greenhouse", "The kind of room CropWatcher is built for")],
    },
    {
        "full_name": "Samuel Enam Zih",
        "role": "Flight agent and apps",
        "headline": "Builds the flight agent, the desktop app and this website.",
        "current_work": "Keeping the drone steady in manual flight — eased climbs, a height "
                        "hold that does not bounce, and a 10 Hz trace of every flight so the "
                        "next problem can be read rather than guessed at.",
        "about": "Samuel works on the software between the person and the drone: the agent that "
                 "owns the radio, the desktop app that flies it, and the site you are reading. "
                 "The constraint the whole system is shaped around is that the Crazyradio is a "
                 "USB dongle — only the laptop it is plugged into can command the drone, so no "
                 "cloud service ever touches it.\n\n"
                 "Most of the interesting work has been the unglamorous kind: a zero-thrust "
                 "setpoint that has to be sent before the motors will obey, a barometer "
                 "estimate too noisy to differentiate, and a lot of CSV files.",
        "links": [{"label": "Website", "url": "https://samuelzih.savorar.com/"}],
        "hobbies": [
            ("Reading", "Non-fiction, a chapter at a time, usually about how something was "
             "built and what went wrong first.", "books"),
            ("Photography", "Documenting the build — most of the hardware photos in the gallery "
             "are from these sessions.", "camera"),
        ],
        "photos": [("code", "Writing the manual control loop"),
                   ("drone", "The drone holding a hover")],
    },
]

CURRENT_WORK = (
    "Write what you are in the middle of here — the part of CropWatcher you are working on now, "
    "or what you are building next."
)


def slugify(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in name.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:60]


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


def upload(api: Api, name: str, source: str) -> str:
    """Copy a placeholder into the bucket, once, and return its public URL."""
    object_path = f"team/placeholders/{name}.jpg"
    public = f"{api.base}/storage/v1/object/public/{BUCKET}/{object_path}"
    request = urllib.request.Request(source, headers={"User-Agent": "cropwatcher-seed"})
    with urllib.request.urlopen(request) as response:
        data = response.read()
    api.request("POST", f"/storage/v1/object/{BUCKET}/{object_path}", raw=data,
                headers={"Content-Type": "image/jpeg", "x-upsert": "true"})
    return public


def profile_for(person: dict[str, Any], images: dict[str, str]) -> dict[str, Any]:
    return {
        "slug": slugify(person["full_name"]),
        "role": person["role"],
        "headline": person["headline"],
        "about": person["about"],
        "current_work": person.get("current_work", CURRENT_WORK),
        "hobbies": [
            {"title": title, "body": body, "image_url": images[key]}
            for title, body, key in person["hobbies"]
        ],
        "links": person.get("links", []),
        "photos": [
            {"url": images[key], "caption": f"{caption} · {PLACEHOLDER}"}
            for key, caption in person["photos"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Seed one person, by name.")
    args = parser.parse_args()

    base, key = os.environ.get("SUPABASE_API"), os.environ.get("SUPABASE_SERVICE")
    if not base or not key:
        sys.exit("Set SUPABASE_API and SUPABASE_SERVICE (the secret key) in the environment.")
    api = Api(base, key)

    people = [p for p in PEOPLE if not args.only or p["full_name"].lower() == args.only.lower()]
    if not people:
        sys.exit(f"No seeded person called {args.only!r}.")

    # Uploaded once and shared by every profile that uses them: five copies of
    # the same stock photo would be five copies to delete later. Only the ones
    # the selected people actually reference are fetched.
    wanted = sorted({key for p in people
                     for key in [k for _, _, k in p["hobbies"]] + [k for k, _ in p["photos"]]})
    images = {key: upload(api, key, STOCK[key]) for key in wanted}
    print(f"  images   {len(images)} stock photos in {BUCKET}")

    for person in people:
        name = urllib.parse.quote(person["full_name"])
        found = api.request("GET", f"/rest/v1/team_members?full_name=eq.{name}&select=id,slug")
        if not found:
            print(f"  skipped  {person['full_name']} — not on the team yet (run portfolio.py first)")
            continue
        profile = profile_for(person, images)
        # An edited slug is somebody's live URL. Never move it.
        if found[0].get("slug"):
            profile.pop("slug")
        api.request("PATCH", f"/rest/v1/team_members?id=eq.{found[0]['id']}", profile)
        print(f"  profile  {person['full_name']:<20} /team/{found[0].get('slug') or profile['slug']}")


if __name__ == "__main__":
    main()
