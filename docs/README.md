# Docs router

One line per doc. Read this first, then open only what your work touches.

## Platform — technical rules that cut across features

| Doc | What it covers |
|---|---|
| [platform/architecture.md](platform/architecture.md) | Why the agent owns the radio, and the two control paths |
| [platform/flight-safety.md](platform/flight-safety.md) | Preflight gates, arming, abort and auto-land rules |
| [platform/temperature-correction.md](platform/temperature-correction.md) | The correction engine and its tuned constants |
| [platform/data-model.md](platform/data-model.md) | Tables, RLS, the CSV-first rule |

## Features — product capabilities

| Doc | What it covers |
|---|---|
| _(none yet)_ | Added as features ship |

## Hardware

[hardware/](hardware/) — photos of the actual kit, plus the previous team's capstone
report and owner's manual as reference PDFs. The photos are the only record of what the
kit contains; `01`–`02` are the mainboard, `03`–`04` the AI deck, `05` the Crazyradio,
`06`–`10` power and spares.

Note the Lighthouse deck appears in **none** of the photos but **is** fitted — confirmed
by querying `deck.bcLighthouse4` on the drone. Trust the drone, not the photos.
