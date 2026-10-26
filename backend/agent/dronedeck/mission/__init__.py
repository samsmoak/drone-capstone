"""Autonomous missions: what to fly, and how it is flown.

    plan/         WHAT to fly. Pure data and checks — never imports the flight
                  code, so a mission can be drawn, saved and validated with no
                  drone in the room.
        shapes.py       the 2-D geometry every check is built on
        geofence.py     the room's closed boundary
        obstacles.py    lines, rectangles and circles inside it
        floorplan.py    Room: a geofence, its obstacles, its coverage
        mission.py      Mission and InspectionPoint
        validate.py     every check a mission passes before it can fly
        store.py        rooms/ and missions/ as JSON on this laptop

    controller/   HOW a saved mission is flown. The mission controller gives
                  goals to the manual flight system (flight/manual.py) — the
                  tuned 50 Hz loop — and never commands the drone itself.
        events.py              states and events
        flight.py              the part of the manual flight system it may use
        mission_controller.py  the controller

The session (session.py) is what starts a mission: it runs the checks, arms the
manual flight system, and hands it to the mission controller.
"""
