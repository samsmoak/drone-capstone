"""The placeholder cleaner: flags nothing, so every reading is usable.

Honest by construction — it claims no fault it did not look for. Replaced by
the agent's cleaner (robust@1; docs/handoffs/sprint-1/done/dpp-clean.txt) with a one-line change in
pipeline/compose.py.
"""

from __future__ import annotations

from cropwatcher.pipeline.contracts import CleanResult, FlightContext, PointData


class StubCleaner:
    name = "stub"
    version = "0"

    def clean(self, data: PointData, ctx: FlightContext) -> CleanResult:
        return CleanResult(readings=data.readings, flags=())
