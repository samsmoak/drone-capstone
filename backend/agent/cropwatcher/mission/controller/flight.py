"""The part of the manual flight system the mission controller may use.

A Protocol, so the controller is written against exactly this and nothing
else, and its tests can drive either the real ManualController (with a fake
commander — tests/fakes.py) or a stand-in. tests/mission/ checks that
ManualController satisfies it, so the two cannot drift apart.

Deliberately MISSING: arm(), start(), stop(), emergency_stop(), heartbeat().
The session owns arming and stopping. The heartbeat stays with the desktop app
on purpose: if the operator's window goes quiet the drone lands, mission or
not — that is the dead-man, and a mission must never defeat it.
"""

from __future__ import annotations

from typing import Protocol

from cropwatcher.flight.manual import ControlState, Fix


class MissionFlight(Protocol):
    @property
    def state(self) -> ControlState: ...
    @property
    def assisted(self) -> bool: ...
    @property
    def target(self) -> Fix | None: ...
    @property
    def target_height(self) -> float: ...
    @property
    def drift_m(self) -> float: ...
    @property
    def goal_active(self) -> bool: ...
    @property
    def operator_override(self) -> bool: ...

    def hold_at(self, height_m: float) -> None: ...
    def fly_to(self, x: float, y: float, height_m: float,
               speed_m_s: float | None = None) -> None: ...
    def land(self) -> None: ...
