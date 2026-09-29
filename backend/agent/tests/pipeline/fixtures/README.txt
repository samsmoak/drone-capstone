PIPELINE FIXTURE — what is real here, and what was made up
=========================================================

data/ is laid out exactly like the agent's data folder, so LocalFlightSource
reads it with no special case.

  REAL      flights/2026-09-24/flight_372bbdc4_…csv — the first 400 rows (about
            40 s at 10 Hz) of flight 372bbdc4, flown by hand in the lab on
            2026-09-24. Real temperature, pressure, position and battery.

  ADDED     a point_id column: "P1" on rows 100–159, "P2" on rows 250–309,
            empty elsewhere. That flight was manual and had no inspection
            points; the tags are what the mission controller writes while
            HOLDING, placed so the pipeline's grouping can be tested.

  MADE UP   sessions/<id>/meta.json — a trimmed session naming that flight.
            sessions/<id>/frames/ — seven generated 324×244 grayscale PNGs
            (a gradient), not camera images. frames.csv places them: 1 before
            the flight, 2–3 at P1, 4 in transit, 5–6 at P2, 7 after it.
            sessions/<id>/missions/<flight>.json — a three-point plan; P3 was
            never reached, so it has no readings and no frames.
            fixture.json — which flight and session this is.

What the fixture proves: a flight's frames are the session's frames INSIDE its
time window (1 and 7 are not); readings and frames group by point; transit
readings belong to no point; a point never reached is insufficient_data.

`cropwatcher process --fixture` runs the whole pipeline on it and writes to
fixtures/results/, which git ignores.
