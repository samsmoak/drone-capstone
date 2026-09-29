"""The data pipeline: a recorded flight → a verdict for every inspection point.

    load ─▶ clean ─▶ enhance ─▶ classify ─▶ interpret ─▶ save
             (4.2)    (4.3)     (4.4, 4.6)    (4.6)

    contracts.py   the types and interfaces every stage builds against — THE
                   agreement (docs/handoffs/sprint-1/done/dpp-contract.txt)
    sources.py     where a flight comes from   (a port; LocalFlightSource)
    sinks.py       where a result goes         (a port; LocalResultSink)
    compose.py     which implementation each stage uses — the one line a
                   stage owner changes to plug in
    runner.py      runs the stages, one inspection point at a time
    stages/        clean (Kevin), enhance (Kevin), classify (Reagan),
                   interpret (Samuel) — each a stub until its owner lands

Ports and adapters: the core never knows whether a flight came off this
laptop's disk or a cloud bucket. A cloud worker later is a new source and a
new sink, not a rewrite.

NOTHING HERE IMPORTS THE FLIGHT CODE (tests/pipeline holds that line): the
pipeline must run with no radio, and in a process of its own beside a flight.
"""

#: Bumped whenever the shape of a result changes. Recorded in every result.
PIPELINE_VERSION = "1"
